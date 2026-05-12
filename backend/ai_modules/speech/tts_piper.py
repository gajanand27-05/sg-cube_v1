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


def speak(text: str) -> dict:
    """Synthesize `text` via Piper and play through the default audio device. Blocks."""
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

    sd.play(audio, samplerate=rate, blocking=True)

    return {
        "status": "spoke",
        "text": text,
        "engine": "piper",
        "voice": VOICE_NAME,
        "latency_ms": int((time.perf_counter() - t0) * 1000),
    }
