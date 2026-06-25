import time
from pathlib import Path

import numpy as np
import sounddevice as sd
from piper import PiperVoice

VOICE_DIR = Path(__file__).parent / "piper_voices"
VOICE_NAME = "en_US-ryan-high"

_voice: PiperVoice | None = None


def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        model_path = VOICE_DIR / f"{VOICE_NAME}.onnx"
        config_path = VOICE_DIR / f"{VOICE_NAME}.onnx.json"
        if not model_path.exists() or not config_path.exists():
            raise RuntimeError(
                f"Piper voice files missing in {VOICE_DIR}. "
                f"Expected {VOICE_NAME}.onnx + .onnx.json"
            )
        _voice = PiperVoice.load(str(model_path), config_path=str(config_path))
    return _voice


def generate_audio(text: str) -> tuple[bytes, int]:
    """Synthesize `text` and return raw PCM bytes (16kHz) and sample rate."""
    voice = _get_voice()
    chunks = list(voice.synthesize(text))
    if not chunks:
        return b"", 0
    rate = chunks[0].sample_rate
    audio = np.concatenate([c.audio_int16_array for c in chunks])
    return audio.tobytes(), rate


# ── Phase C2: Non-blocking TTS with interrupt ──

def speak(text: str) -> dict:
    """Synthesize `text` via Piper and play through the default audio device.

    Non-blocking — returns immediately after dispatching audio playback.
    Call `stop_speech()` to interrupt playback mid-utterance.
    """
    t0 = time.perf_counter()
    voice = _get_voice()

    chunks = list(voice.synthesize(text))
    if not chunks:
        return {
            "status": "spoke",
            "text": text,
            "engine": "piper",
            "voice": VOICE_NAME,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }

    rate = chunks[0].sample_rate
    audio = np.concatenate([c.audio_int16_array for c in chunks])
    # Pad with 250ms of trailing silence to avoid truncation.
    silence = np.zeros(int(0.25 * rate), dtype=np.int16)
    audio = np.concatenate([audio, silence])

    sd.play(audio, samplerate=rate)

    return {
        "status": "spoke",
        "text": text,
        "engine": "piper",
        "voice": VOICE_NAME,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


def speak_stream(text: str) -> dict:
    """Streaming variant — plays each synthesized chunk immediately.

    Piper's `synthesize()` already returns an iterator. We play the first
    chunk while subsequent chunks are still being generated.
    Non-blocking — returns immediately after dispatching the first chunk.
    """
    t0 = time.perf_counter()
    voice = _get_voice()
    iterator = voice.synthesize(text)

    try:
        first = next(iterator)
    except StopIteration:
        return {
            "status": "spoke",
            "text": text,
            "engine": "piper",
            "voice": VOICE_NAME,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        }

    rate = first.sample_rate
    first_audio = first.audio_int16_array
    trailing = np.zeros(int(0.25 * rate), dtype=np.int16)

    remaining: list[np.ndarray] = [first_audio]
    for chunk in iterator:
        remaining.append(chunk.audio_int16_array)
    remaining.append(trailing)

    full_audio = np.concatenate(remaining)
    sd.play(full_audio, samplerate=rate)

    return {
        "status": "spoke",
        "text": text,
        "engine": "piper",
        "voice": VOICE_NAME,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }


def stop_speech() -> None:
    """Immediately stop any in-progress speech playback."""
    sd.stop()
