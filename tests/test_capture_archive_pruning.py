"""Gate-dropped captures must not evict the real ones.

Roughly a fifth of wakes are gated and false wakes cluster — one noisy
afternoon produced ~30. On a single shared FIFO that noise pushes out the real
commands, which are the only reason the archive exists.
"""
import sys
import time
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core import capture_archive as ca


def _make(directory: Path, name: str, age_s: float = 0.0) -> Path:
    wav = directory / f"{name}.wav"
    wav.write_bytes(b"RIFF")
    wav.with_suffix(".json").write_text("{}", encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        for p in (wav, wav.with_suffix(".json")):
            import os
            os.utime(p, (old, old))
    return wav


def test_dropped_captures_do_not_evict_real_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_MAX_CAPTURES", 3)
    monkeypatch.setattr(ca, "_MAX_DROPPED", 3)

    real = [_make(tmp_path, f"2026{i:04d}", age_s=100 - i) for i in range(3)]
    for i in range(10):                       # a flood of gated noise
        _make(tmp_path, f"{ca._DROPPED_PREFIX}2026{i:04d}", age_s=50 - i)

    ca._prune(tmp_path)

    for p in real:
        assert p.exists(), f"a real capture was evicted by gated noise: {p.name}"
    assert len(list(tmp_path.glob(f"{ca._DROPPED_PREFIX}*.wav"))) == 3


def test_dropped_captures_expire_by_age_even_under_the_count_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_MAX_DROPPED", 500)
    monkeypatch.setattr(ca, "_DROPPED_MAX_AGE_S", 7 * 24 * 3600)

    fresh = _make(tmp_path, f"{ca._DROPPED_PREFIX}fresh", age_s=60)
    stale = _make(tmp_path, f"{ca._DROPPED_PREFIX}stale", age_s=8 * 24 * 3600)

    ca._prune(tmp_path)

    assert fresh.exists()
    assert not stale.exists(), "age cap must apply even when the count cap is not reached"
    assert not stale.with_suffix(".json").exists(), "sidecar must go with the wav"


def test_real_captures_are_not_aged_out(tmp_path, monkeypatch):
    """Only the gated ones expire on a clock. A real command from last month
    is still the most interesting file in the directory."""
    monkeypatch.setattr(ca, "_MAX_CAPTURES", 500)
    old_real = _make(tmp_path, "20260101-000000-000", age_s=90 * 24 * 3600)

    ca._prune(tmp_path)

    assert old_real.exists()


def test_archive_prefixes_only_dropped_captures(tmp_path, monkeypatch):
    import numpy as np

    monkeypatch.setattr(ca, "_ARCHIVE_DIR", tmp_path)
    monkeypatch.setattr(ca, "enabled", lambda: True)
    audio = np.zeros(1600, dtype=np.int16)

    kept = ca.archive(audio, "open notepad", trigger="wake")
    gated = ca.archive(audio, "", trigger="wake", dispatched=False,
                       extra={"bucket": "speech_gate", "speech_seconds": 0.0})

    assert kept is not None and not kept.name.startswith(ca._DROPPED_PREFIX)
    assert gated is not None and gated.name.startswith(ca._DROPPED_PREFIX)

    import json
    sidecar = json.loads(gated.with_suffix(".json").read_text(encoding="utf-8"))
    assert sidecar["bucket"] == "speech_gate"
    assert sidecar["speech_seconds"] == 0.0
    assert sidecar["dispatched"] is False
