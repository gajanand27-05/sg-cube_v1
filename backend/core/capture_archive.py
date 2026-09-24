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
import threading
import time
import wave
from pathlib import Path
from backend.core import paths

import numpy as np

log = logging.getLogger(__name__)

_ARCHIVE_DIR = paths.DB_DIR / "captures"
SAMPLE_RATE = 16000

# Oldest files are deleted past this. Roughly 2s of 16-bit 16kHz audio is
# ~64KB, so 500 captures is well under 100MB.
_MAX_CAPTURES = 500

# Captures the speech gate threw away get their OWN budget, and a `drop-`
# filename prefix so selecting them is a glob rather than 500 JSON reads.
#
# Separate budgets because they are not interchangeable. Roughly a fifth of
# wakes are gated, and false wakes cluster — one noisy afternoon produced ~30.
# On a single shared 500-file FIFO that noise evicts the real commands, which
# are the whole reason the archive exists. Capped by BOTH age and count, the
# tighter of the two winning, because an audio log of someone's living room
# should expire on its own even if the count never fills up.
_MAX_DROPPED = 500
_DROPPED_MAX_AGE_S = 7 * 24 * 3600
_DROPPED_PREFIX = "drop-"

# High-volume buckets, each with its OWN budget so one cannot starve another
# or the real captures. `bucket` in archive()'s `extra` selects one.
#   speech_gate  - captures the gate threw away
#   wake_trigger - the pre-roll that fired the wake word, recorded so a
#                  false-fire rate can be measured instead of guessed
_BUCKET_PREFIX = {
    "speech_gate": _DROPPED_PREFIX,
    "wake_trigger": "wake-",
}


def enabled() -> bool:
    from backend.server.config import settings
    return bool(getattr(settings, "stt_archive_captures", False))


# ── what the listener measured, carried to the archive call ────────────
#
# The number the follow-up gate compares (`_FOLLOWUP_MIN_RMS`) is known in
# wake_word at trigger time; the transcript and the audio are only known in
# trigger.py after STT. This carries the first to the second.
#
# THREAD-LOCAL, not a module global, and not threaded through on_wake.
#
#   * A module global races. Turn bodies are serialized only up to
#     _TURN_HANDOVER_TIMEOUT_S, and past it two turns run on two threads.
#     `state_manager._voice_trigger_source` is exactly this shape and was
#     already found being reset by one turn while another read it, silently
#     mislabelling records — see the note in wake_word._start_turn.
#   * on_wake(audio) is called with one positional argument from a dozen
#     test sites and from tools/, and _start_turn wraps the call in
#     `except Exception`. Widening the signature would turn every stale
#     caller into a swallowed TypeError logged as "on_wake handler raised",
#     i.e. a production break that the tests would not show.
#
# handle_wake runs asyncio.run on the turn's OWN thread, so a thread-local
# set at the top of the turn reaches the archive call and nothing else.
_local = threading.local()


def set_trigger_context(**meta) -> None:
    """Record what fired this turn, for the archive call that follows."""
    _local.meta = dict(meta)


def take_trigger_context() -> dict:
    """Pop it. Empty dict when there was no listener behind this turn — the
    text and proactive paths have none, and must still archive."""
    meta = getattr(_local, "meta", None) or {}
    _local.meta = None
    return dict(meta)


# ── rejected triggers, counts only ─────────────────────────────────────
GATE_REJECTIONS_FILE = "gate_rejections.json"
_REJECTION_BIN = 100
_rejection_lock = threading.Lock()


def record_gate_rejection(rms: float, *, floor: float) -> None:
    """Count one follow-up trigger the RMS floor turned away.

    Counts only, no audio. The passing triggers alone can show what RAISING
    the floor would cost; they say nothing about how much real speech the
    current floor already drops, which is the other half of the calibration.
    Keeping audio for these would mean archiving every quiet frame of every
    follow-up window, which is exactly the volume the bucket budgets exist to
    avoid.

    Never raises: this runs inside the listen loop, and losing a statistic is
    worth strictly less than continuing to listen.
    """
    if not enabled():
        return
    try:
        with _rejection_lock:
            path = _ARCHIVE_DIR / GATE_REJECTIONS_FILE
            try:
                hist = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                hist = {"floor": floor, "bin_width": _REJECTION_BIN,
                        "bins": {}, "total": 0}
            # The floor is stored, not assumed: it is the censoring point of
            # the whole archived sample, and a record that does not name it
            # reads as the full population of follow-up attempts.
            hist["floor"] = floor
            key = str(int(rms // _REJECTION_BIN) * _REJECTION_BIN)
            hist["bins"][key] = hist["bins"].get(key, 0) + 1
            hist["total"] = hist.get("total", 0) + 1
            hist["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(hist, indent=2), encoding="utf-8")
    except Exception as e:
        log.debug("could not count a gate rejection: %s", e)


def _delete(wav: Path) -> None:
    wav.unlink(missing_ok=True)
    wav.with_suffix(".json").unlink(missing_ok=True)


def _prune(directory: Path) -> None:
    """Independent budgets per bucket, so noise cannot evict real captures.

    Real captures are the only reason the archive exists; gated audio and wake
    triggers are both high-volume (a fifth of wakes are gated, and every wake
    including the false ones records a trigger). On one shared FIFO the volume
    buckets would steadily push the real commands out.
    """
    everything = sorted(directory.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    prefixes = tuple(_BUCKET_PREFIX.values())

    real = [p for p in everything if not p.name.startswith(prefixes)]
    for stale in real[:-_MAX_CAPTURES]:
        _delete(stale)

    cutoff = time.time() - _DROPPED_MAX_AGE_S
    for prefix in prefixes:
        bucket = [p for p in everything if p.name.startswith(prefix)]
        # Count first, then age. BOTH apply, so the stricter one decides — an
        # audio log of someone's living room should expire on its own even if
        # the count never fills up.
        for stale in bucket[:-_MAX_DROPPED]:
            _delete(stale)
        for p in bucket[-_MAX_DROPPED:]:
            try:
                if p.stat().st_mtime < cutoff:
                    _delete(p)
            except OSError:
                continue


def archive(audio: np.ndarray | bytes, transcript: str, *,
            trigger: str = "", dispatched: bool = True,
            extra: dict | None = None) -> Path | None:
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
        # The prefix is what lets _prune give these their own budget without
        # opening every sidecar. `drop-*.wav` still matches `*.wav`, so every
        # existing replay tool picks them up unchanged.
        prefix = _BUCKET_PREFIX.get((extra or {}).get("bucket", ""), "")
        wav_path = _ARCHIVE_DIR / f"{prefix}{stamp}.wav"

        with wave.open(str(wav_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())

        wav_path.with_suffix(".json").write_text(json.dumps({
            "transcript": transcript,
            "trigger": trigger,
            # Named here so one record carries rms, transcript AND its audio:
            # calibration means sorting by rms and listening in order, and
            # `dispatched` is not a label for "addressed to Onyx" — every turn
            # in the 2026-09-22 log dispatched and none of them were.
            "audio": wav_path.name,
            # Whether this reached the router. An empty or gated transcript is
            # exactly the case worth reviewing, so it is archived too and
            # flagged rather than skipped.
            "dispatched": dispatched,
            "seconds": round(pcm.size / SAMPLE_RATE, 2),
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            # Whatever the caller needs to explain THIS capture — e.g. the
            # speech gate's score for one it dropped. A dropped capture never
            # gets a transcript, so without the score and the audio side by
            # side there is no way to audit later whether the gate ate a real
            # command.
            **(extra or {}),
        }, indent=2), encoding="utf-8")

        _prune(_ARCHIVE_DIR)
        return wav_path
    except Exception as e:
        log.warning("could not archive capture: %s", e)
        return None
