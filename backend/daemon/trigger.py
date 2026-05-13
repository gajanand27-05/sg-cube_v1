import tempfile
import wave
import winsound
from pathlib import Path

import numpy as np
import sounddevice as sd

from backend.ai_modules.speech.stt_whisper import transcribe
from backend.ai_modules.speech.tts_piper import speak
from backend.core.orchestrator.llm_layer import Intent, LLMResolveError
from backend.core.orchestrator.router import process_input
from backend.core.safe_executor.executor import ExecutionResult
from backend.core.safe_executor.executor import execute as do_execute

# TODO replace with a service-account UUID after a daemon-auth design exists.
# For now: reuse the Phase 2 test user so command_logs writes still satisfy the FK.
DAEMON_USER_ID = "21c19bf1-b73f-4001-80de-789b93c8d703"

SAMPLE_RATE = 16000
ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"


def _play_chime() -> None:
    """Play assets/chime.wav if present; fall back to a sine-tone Beep."""
    chime = ASSETS_DIR / "chime.wav"
    if chime.exists():
        try:
            with wave.open(str(chime), "rb") as w:
                rate = w.getframerate()
                frames = w.readframes(w.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16)
            sd.play(audio, samplerate=rate, blocking=True)
            return
        except Exception:
            pass
    winsound.Beep(880, 120)


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
    if status == "success":
        if action == "open_app":
            return f"Opening {target}"
        if action == "close_app":
            return f"Closing {target}"
        if action == "get_time":
            return f"The time is {result.message}"
        return "Done"
    if status == "blocked":
        if action == "unknown":
            return "Sorry, I didn't understand"
        return "Sorry, that command is not allowed"
    return "Something went wrong"


def handle_wake(audio_bytes: bytes) -> None:
    """Called by WakeWordListener with the 5s of audio captured after the wake phrase."""
    _play_chime()

    wav_path = _save_wav(audio_bytes)
    try:
        stt = transcribe(str(wav_path))
        command = (stt.get("text") or "").strip()
        print(f"[command] {command!r}")

        if not command:
            speak("Sorry, I did not catch that")
            return

        try:
            routed = process_input(command, DAEMON_USER_ID)
        except LLMResolveError as e:
            print(f"[trigger] LLM unavailable: {e}")
            speak("Sorry, my reasoning model is unavailable")
            return

        result = do_execute(routed.intent)
        print(
            f"[trigger] {routed.source_layer} -> "
            f"{routed.intent.action}/{routed.intent.target!r} -> {result.status}"
        )

        speak(_spoken_response(routed.intent, result))
    finally:
        wav_path.unlink(missing_ok=True)
