import tempfile
import threading
import wave
from pathlib import Path
from typing import Any, Callable

import numpy as np
import sounddevice as sd

from backend.ai_modules.speech.stt_whisper import transcribe
from backend.ai_modules.speech.tts_piper import speak
from backend.core.orchestrator.llm_layer import Intent, LLMResolveError
from backend.core.orchestrator.router import process_input
from backend.core.safe_executor.executor import ExecutionResult
from backend.core.safe_executor.executor import execute as do_execute
from backend.core.events import bus
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
    """Fires the instant the wake phrase is recognised — BEFORE the command
    audio is captured. Purpose: give the user immediate feedback (chime +
    UI flash) so they know to start speaking, rather than waiting 2-3s for
    the legacy fixed capture window to elapse.
    """
    event = WakeHeard(peak=0)
    bus.publish(event)
    _emit(emit, event)
    # Play the chime asynchronously so we don't delay capture start.
    threading.Thread(target=_play_chime, daemon=True).start()


def handle_wake(audio_bytes: bytes, emit: EmitFn | None = None) -> bool:
    """Called by WakeWordListener with audio captured after the wake phrase.

    Returns True if a real command was recognised and processed, False if
    the capture was empty (silence / noise) or the LLM was unavailable.
    The listener uses this signal to decide whether to keep the follow-up
    window open or close it after consecutive empty rounds.
    """
    arr = np.frombuffer(audio_bytes, dtype=np.int16)
    peak = int(np.max(np.abs(arr))) if arr.size else 0
    print(f"[trigger] captured {len(arr)/SAMPLE_RATE:.2f}s, peak={peak}/32767")

    wav_path = _save_wav(audio_bytes)
    try:
        stt = transcribe(str(wav_path))
        command = (stt.get("text") or "").strip()
        print(f"[command] {command!r}")
        
        event = CommandTranscribed(text=command, peak=peak)
        bus.publish(event)
        _emit(emit, event)

        if not command:
            # Silent capture — almost certainly a false-positive wake or
            # follow-up trigger. Skip the "didn't catch that" TTS so we
            # don't feed our own speaker into the open follow-up window.
            return False

        try:
            routed = process_input(command, DAEMON_USER_ID)
        except LLMResolveError as e:
            print(f"[trigger] LLM unavailable: {e}")
            err_event = TriggerError(detail=f"LLM unavailable: {e}")
            bus.publish(err_event)
            _emit(emit, err_event)
            reply = "Sorry, my reasoning model is unavailable"
            speak(reply)
            spoken_event = SpokenResponse(text=reply)
            bus.publish(spoken_event)
            _emit(emit, spoken_event)
            return False

        intent_event = IntentResolved(
            action=routed.intent.action,
            target=routed.intent.target,
            source_layer=routed.source_layer,
        )
        bus.publish(intent_event)
        _emit(emit, intent_event)

        result = do_execute(routed.intent)
        print(
            f"[trigger] {routed.source_layer} -> "
            f"{routed.intent.action}/{routed.intent.target!r} -> {result.status}"
        )
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
        speak(reply)
        
        spoken_event = SpokenResponse(text=reply)
        bus.publish(spoken_event)
        _emit(emit, spoken_event)
        return True
    finally:
        wav_path.unlink(missing_ok=True)
