import asyncio
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import sounddevice as sd

from backend.ai_modules.speech.stt_whisper import transcribe
from backend.ai_modules.speech.tts_piper import speak
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

EmitFn = Callable[[Any], None]

# TODO replace with a service-account UUID after a daemon-auth design exists.
# For now: reuse the Phase 2 test user so command_logs writes still satisfy the FK.
DAEMON_USER_ID = "21c19bf1-b73f-4001-80de-789b93c8d703"

SAMPLE_RATE = 16000
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"


def _play_chime() -> None:
    """Play assets/chime.wav if present; fall back to a generated sine tone
    routed through the user's default audio output (winsound.Beep is
    unreliable on Windows 11)."""
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


def _save_wav(audio_bytes: bytes) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    path = Path(tmp.name)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(audio_bytes)
    return path


def _spoken_response(intent: Intent, result: ExecutionResult) -> str:
    status = result.status
    action = intent.action
    target = intent.target
    # Phase 11a: agent already wrote the spoken response.
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
    # Interrupt any current reasoning/execution
    commander.interrupt()
    
    state_manager.transition_to(AssistantState.LISTENING)
    event = WakeHeard(peak=0)
    bus.publish(event)
    _emit(emit, event)
    threading.Thread(target=_play_chime, daemon=True).start()


async def _speak_selective(text: str, device_id: Optional[str] = None):
    """Speak locally or push audio to a remote device."""
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


async def _handle_wake_async(audio_bytes: bytes, emit: EmitFn | None = None, device_id: Optional[str] = None) -> bool:
    """Main daemon orchestration via async events."""
    state_manager.transition_to(AssistantState.THINKING)
    arr = np.frombuffer(audio_bytes, dtype=np.int16)
    peak = int(np.max(np.abs(arr))) if arr.size else 0
    rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2))) if arr.size else 0

    # Safety check: if the captured audio is exceptionally quiet, it was
    # likely a false trigger or background noise Vosk misidentified.
    # rms < 200 is effectively a silent room.
    if rms < 200:
        print(f"[trigger] skipping whisper: capture too quiet (rms={rms:.0f})")
        state_manager.transition_to(AssistantState.IDLE)
        return False
    
    wav_path = _save_wav(audio_bytes)
    try:
        stt = transcribe(str(wav_path))
        command = (stt.get("text") or "").strip()
        print(f"[command] {command!r}")
        
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
            
            state_manager.transition_to(AssistantState.SPEAKING)
            await _speak_selective(reply, device_id)
            spoken_event = SpokenResponse(text=reply)
            bus.publish(spoken_event)
            _emit(emit, spoken_event)
            state_manager.transition_to(AssistantState.IDLE)
            return False

        intent_event = IntentResolved(
            action=routed.intent.action,
            target=routed.intent.target,
            source_layer=routed.source_layer,
        )
        bus.publish(intent_event)
        _emit(emit, intent_event)

        state_manager.transition_to(AssistantState.EXECUTING)
        result = await do_execute(routed.intent)
        
        exec_event = Executed(
            command=command,
            status=result.status,
            message=result.message,
            reason=result.reason,
            latency_ms=result.latency_ms,
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
    except Exception as e:
        state_manager.transition_to(AssistantState.ERROR)
        log.exception(f"trigger crash: {e}")
        state_manager.transition_to(AssistantState.IDLE)
        return False
    finally:
        wav_path.unlink(missing_ok=True)
