import asyncio
import logging
import tempfile
import threading
import uuid
import wave
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import sounddevice as sd

from backend.ai_modules.speech.stt_whisper import transcribe_array
from backend.ai_modules.speech.tts_piper import speak, stop_speech
from backend.core.agents.commander import commander
from backend.core.orchestrator.llm_layer import Intent, LLMResolveError
from backend.core.orchestrator.router import process_input
from backend.core.safe_executor.executor import ExecutionResult
from backend.core.safe_executor.executor import execute as do_execute
from backend.core.events import bus
from backend.core.state import AssistantState, manager as state_manager
from backend.daemon.ui_events import (
    CommandTranscribed,
    Executed,
    IntentResolved,
    SpokenResponse,
    TriggerError,
    WakeHeard,
)

log = logging.getLogger(__name__)

EmitFn = Callable[[Any], None]

DAEMON_USER_ID = "21c19bf1-b73f-4001-80de-789b93c8d703"

SAMPLE_RATE = 16000
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"


def _play_chime() -> None:
    """Play assets/chime.wav if present; fall back to a generated sine tone."""
    chime = ASSETS_DIR / "chime.wav"
    if chime.exists():
        try:
            with wave.open(str(chime), "rb") as w:
                rate = w.getframerate()
                frames = w.readframes(w.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16)
            sd.play(audio, samplerate=rate, blocking=True)
            sd.wait()
            return
        except Exception:
            pass
    rate = 44100
    duration = 0.15
    freq = 880
    t = np.linspace(0, duration, int(rate * duration), endpoint=False)
    tone = np.sin(2 * np.pi * freq * t) * 0.30
    fade = int(rate * 0.01)
    tone[:fade] *= np.linspace(0, 1, fade)
    tone[-fade:] *= np.linspace(1, 0, fade)
    tone_i16 = (tone * 32767).astype(np.int16)
    sd.play(tone_i16, samplerate=rate, blocking=True)
    sd.wait()


def _spoken_response(intent: Intent, result: ExecutionResult) -> str:
    status = result.status
    action = intent.action
    target = intent.target
    if action == "agent_complete":
        return (intent.args or {}).get("spoken") or result.message or "Done."
    if status == "success":
        if action == "open_app":
            return f"Opening {target}"
        if action == "close_app":
            return f"Closing {target}"
        if action == "get_time":
            return f"The time is {result.message}"
        if action == "play_youtube":
            return result.message or f"Playing {target}"
        if action == "search_google":
            return f"Searching Google for {target}"
        if action == "search_youtube":
            return f"Searching YouTube for {target}"
        if action == "open_url":
            return f"Opening {target}"
        if action == "set_volume":
            return f"Setting volume to {intent.args.get('level', '')}"
        if action == "volume_up":
            return "Volume up"
        if action == "volume_down":
            return "Volume down"
        if action == "mute":
            return "Muted"
        if action == "unmute":
            return "Unmuted"
        if action in ("shutdown_pc", "restart_pc", "sleep_pc"):
            return result.message or "Done"
        if action == "lock_screen":
            return "Locking screen"
        if action == "take_note":
            return "Note saved"
        if action == "set_reminder":
            return "Reminder set"
        return "Done"
    if status == "blocked":
        if action == "unknown":
            return "Sorry, I didn't understand"
        return result.reason or "Sorry, that command is not allowed"
    return "Something went wrong"


def _emit(emit: EmitFn | None, event: Any) -> None:
    if emit is None:
        return
    try:
        emit(event)
    except Exception as e:
        print(f"[ui] emit raised: {e}")


def on_wake_detected(emit: EmitFn | None = None) -> None:
    """Fires the instant the wake phrase is recognised."""
    # Phase C2: Interrupt any in-progress speech immediately
    stop_speech()
    commander.interrupt()

    state_manager.transition_to(AssistantState.LISTENING)
    event = WakeHeard(peak=0)
    bus.publish(event)
    _emit(emit, event)
    threading.Thread(target=_play_chime, daemon=True).start()


async def _speak_selective(text: str, device_id: Optional[str] = None):
    """Speak locally (non-blocking) or push audio to a remote device."""
    if device_id:
        from backend.ai_modules.speech.tts_piper import generate_audio
        from backend.server.routes.remote import manager as remote_manager

        audio_bytes, rate = generate_audio(text)
        if audio_bytes:
            await remote_manager.broadcast_bytes_to_device(device_id, audio_bytes)
    else:
        speak(text)


def handle_wake(audio_bytes: bytes, emit: EmitFn | None = None, device_id: Optional[str] = None) -> bool:
    """Synchronous entry point for the wake word listener."""
    return asyncio.run(_handle_wake_async(audio_bytes, emit, device_id))


async def _process_and_execute(command: str, peak: int, t0: float, emit: EmitFn | None = None, device_id: Optional[str] = None) -> bool:
    request_id = str(uuid.uuid4())[:8]
    event = CommandTranscribed(text=command, peak=peak)
    bus.publish(event)
    _emit(emit, event)

    if not command:
        state_manager.transition_to(AssistantState.IDLE)
        return False

    try:
        routed = await process_input(command, DAEMON_USER_ID)
    except LLMResolveError as e:
        state_manager.transition_to(AssistantState.ERROR)
        err_event = TriggerError(detail=f"LLM unavailable: {e}")
        bus.publish(err_event)
        _emit(emit, err_event)
        reply = "Sorry, my reasoning model is unavailable"
        print(f"[ai] LLM unavailable: {e}")
        print(f"[ai] → {reply}")

        state_manager.transition_to(AssistantState.SPEAKING)
        await _speak_selective(reply, device_id)
        spoken_event = SpokenResponse(text=reply)
        bus.publish(spoken_event)
        _emit(emit, spoken_event)
        state_manager.transition_to(AssistantState.IDLE)
        return False

    print(f"[ai] intent: {routed.intent.action} → {routed.intent.target} ({routed.source_layer})")
    intent_event = IntentResolved(
        action=routed.intent.action,
        target=routed.intent.target,
        source_layer=routed.source_layer,
    )
    bus.publish(intent_event)
    _emit(emit, intent_event)

    state_manager.transition_to(AssistantState.EXECUTING)
    result = await do_execute(routed.intent)

    from backend.core.observability import engine as obs_engine
    total_latency = int((asyncio.get_event_loop().time() - t0) * 1000)
    obs_engine.report_tool_quality(request_id, result.confidence, result.status)
    obs_engine.report_latency(request_id, total_latency)

    print(f"[ai] result: {result.status} — {result.message or result.reason or 'ok'}")
    exec_event = Executed(
        command=command,
        status=result.status,
        message=result.message,
        reason=result.reason,
        latency_ms=result.latency_ms,
        confidence=result.confidence,
        confidence_reason=result.confidence_reason
    )
    bus.publish(exec_event)
    _emit(emit, exec_event)

    reply = _spoken_response(routed.intent, result)

    state_manager.transition_to(AssistantState.SPEAKING)
    await _speak_selective(reply, device_id)

    spoken_event = SpokenResponse(text=reply)
    bus.publish(spoken_event)
    _emit(emit, spoken_event)

    state_manager.transition_to(AssistantState.IDLE)
    return True


async def _handle_wake_async(audio_bytes: bytes, emit: EmitFn | None = None, device_id: Optional[str] = None) -> bool:
    """Main daemon orchestration via async events.

    Phase C1: Uses `transcribe_array` instead of saving audio to a temp WAV file.
    Phase C2: TTS is non-blocking — returns to IDLE immediately after dispatching speech.
    """
    t0 = asyncio.get_event_loop().time()

    state_manager.transition_to(AssistantState.THINKING)
    arr = np.frombuffer(audio_bytes, dtype=np.int16)
    peak = int(np.max(np.abs(arr))) if arr.size else 0
    rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) if arr.size else 0

    if rms < 200:
        print(f"[trigger] skipping whisper: capture too quiet (rms={rms:.0f})")
        state_manager.transition_to(AssistantState.IDLE)
        return False

    # Normalize int16 → float32 for Whisper
    audio_float = arr.astype(np.float32) / 32768.0

    try:
        stt = transcribe_array(audio_float, SAMPLE_RATE)
        command = (stt.get("text") or "").strip()
        print(f"[command] {command!r}")

        return await _process_and_execute(command, peak, t0, emit, device_id)
    except Exception as e:
        state_manager.transition_to(AssistantState.ERROR)
        log.exception(f"trigger crash: {e}")
        state_manager.transition_to(AssistantState.IDLE)
        return False


from backend.daemon.ui_events import ProactiveEvent
import time

def on_proactive_event(event: ProactiveEvent):
    """Handle events fired by the Watcher Agent in the background."""
    def _run():
        while state_manager.current_state != AssistantState.IDLE:
            time.sleep(1)

        try:
            asyncio.run(_handle_proactive_async(event.query))
        except Exception as e:
            log.error(f"Proactive trigger failed: {e}")

    threading.Thread(target=_run, daemon=True, name="proactive-trigger").start()


async def _handle_proactive_async(query: str):
    t0 = asyncio.get_event_loop().time()
    state_manager.transition_to(AssistantState.THINKING)
    print(f"[proactive] {query!r}")

    command = f"[Proactive] {query}"
    await _process_and_execute(command, peak=0, t0=t0, emit=None, device_id=None)

bus.subscribe(ProactiveEvent, on_proactive_event)
