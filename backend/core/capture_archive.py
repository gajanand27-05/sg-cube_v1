"""Keep real captured audio next to what Whisper made of it.

Every accuracy decision so far has been measured on tools/_stt_corpus — clean
push-to-talk audio, read one phrase at a time, scoring CMD 93.3%. Real
sessions are visibly worse:

    said "play mungaru male music on youtube"
    heard 'I am talking to my voice assistant, which is called Onyx.'

    heard 'Next voice is cuo of nvd.'
    heard 'nd the assistant nd the birth ive onigth.'

Those are the failures worth fixing, and every one of them was thrown away
the moment the turn ended. Tuning a model against the clean corpus is tuning
against the wrong distribution — it cannot get worse on audio it never sees,
and it cannot get better either.

This writes each capture to disk with its transcript, so the failures
accumulate into a corpus of things that actually went wrong. tools/stt_bench
can then be pointed at real audio rather than a reading exercise.

OFF by default (STT_ARCHIVE_CAPTURES=true to enable). It records everything
the microphone hears in a room where the user lives, which is not something
to switch on for them — and it is bounded, because an unbounded audio log on
someone's laptop is a liability, not a feature.
"""
from __future__ import annotations

import json
import logging
import time
import wave
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_ARCHIVE_DIR = Path(__file__).resolve().parents[1] / "database" / "captures"
SAMPLE_RATE = 16000

# Oldest files are deleted past this. Roughly 2s of 16-bit 16kHz audio is
# ~64KB, so 500 captures is well under 100MB.
_MAX_CAPTURES = 500


def enabled() -> bool:
    from backend.server.config import settings
    return bool(getattr(settings, "stt_archive_captures", False))


def _prune(directory: Path) -> None:
    wavs = sorted(directory.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    for stale in wavs[:-_MAX_CAPTURES]:
        stale.unlink(missing_ok=True)
        stale.with_suffix(".json").unlink(missing_ok=True)


def archive(audio: np.ndarray | bytes, transcript: str, *,
            trigger: str = "", dispatched: bool = True) -> Path | None:
    """Save one capture and its transcript. Returns the wav path, or None.

    Never raises: this runs inside the voice turn, and losing a recording is
    worth strictly less than completing the command.
    """
    if not enabled():
        return None
    try:
        if isinstance(audio, bytes):
            pcm = np.frombuffer(audio, dtype=np.int16)
        else:
            pcm = np.asarray(audio)
            if pcm.dtype != np.int16:
                # The turn carries float32 in [-1, 1]; store int16 so the
                # files are directly usable by the bench and by any player.
                pcm = np.clip(pcm * 32768.0, -32768, 32767).astype(np.int16)
        if pcm.size == 0:
            return None

        _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
        wav_path = _ARCHIVE_DIR / f"{stamp}.wav"

        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())

        wav_path.with_suffix(".json").write_text(json.dumps({
            "transcript": transcript,
            "trigger": trigger,
            # Whether this reached the router. An empty or gated transcript is
            # exactly the case worth reviewing, so it is archived too and
            # flagged rather than skipped.
            "dispatched": dispatched,
            "seconds": round(pcm.size / SAMPLE_RATE, 2),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }, indent=2), encoding="utf-8")

        _prune(_ARCHIVE_DIR)
        return wav_path
    except Exception as e:
        log.warning("could not archive capture: %s", e)
        return None
