"""What read mode does when the OCR engine is not there.

This is the branch that matters most and is hardest to exercise by hand,
because on this machine Tesseract IS installed — so it only runs on someone
else's machine, in the field, which is the worst place to discover it is wrong.

Two behaviours, and both were shipped untested when OCRUnavailable was
introduced:

  * Read mode must SAY the engine is unavailable, not report "no readable text
    in view". The second is a claim about the world, told to someone who asked
    precisely because they cannot see the sign in front of them.
  * It must say it ONCE per session. Frames arrive at 2fps, so announcing on
    every one would talk over the obstacle alerts that still work — and those
    are the ones that stop you walking into a car.
"""
import asyncio
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.vision import obstacle_detector as od
from backend.core.vision.ocr_reader import OCRUnavailable

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 64


@pytest.fixture()
def runner_without_engine(monkeypatch):
    """A runner whose OCR always reports the engine missing."""
    def _boom(_jpeg):
        raise OCRUnavailable("Tesseract is not installed or could not be found.")

    monkeypatch.setattr("backend.core.vision.ocr_reader.ocr_frame", _boom)

    spoken: list[str] = []
    runner = od.DetectionRunner()
    monkeypatch.setattr(type(runner), "_speak_offloop",
                        lambda self, phrase, direction="straight": spoken.append(phrase))
    monkeypatch.setattr(od.registry, "silent", False)
    return runner, spoken


def test_it_says_the_engine_is_unavailable_not_that_there_is_no_text(runner_without_engine):
    runner, spoken = runner_without_engine
    asyncio.run(runner.submit(JPEG, "read"))

    assert spoken, "a missing engine was not announced at all"
    said = " ".join(spoken).lower()
    assert "unavailable" in said, said
    assert "no readable text" not in said, (
        f"said {said!r} — that describes the SCENE, and the scene is exactly "
        "what the user cannot check"
    )


def test_it_says_so_only_once_per_session(runner_without_engine):
    runner, spoken = runner_without_engine
    for _ in range(6):          # three seconds of frames at 2fps
        asyncio.run(runner.submit(JPEG, "read"))

    assert len(spoken) == 1, (
        f"announced {len(spoken)} times — at 2fps this talks over the obstacle "
        f"alerts that still work: {spoken}"
    )


def test_a_new_session_announces_again(runner_without_engine):
    """reset() runs on phone disconnect. The next session is a new walk,
    possibly a different phone — it must not inherit the last one's silence."""
    runner, spoken = runner_without_engine
    asyncio.run(runner.submit(JPEG, "read"))
    assert len(spoken) == 1

    runner.reset()
    asyncio.run(runner.submit(JPEG, "read"))
    assert len(spoken) == 2, "a fresh session stayed silent about a broken engine"


def test_silent_mode_still_suppresses_the_announcement(runner_without_engine, monkeypatch):
    """Public-space silent mode means no speech. The haptic path is unaffected
    by OCR, so nothing is lost by staying quiet here."""
    runner, spoken = runner_without_engine
    monkeypatch.setattr(od.registry, "silent", True)
    asyncio.run(runner.submit(JPEG, "read"))
    assert spoken == []


def test_the_runner_is_not_left_busy_after_the_failure(runner_without_engine):
    """The early `return` inside the except sits above the `finally` that
    clears _busy. If that ever inverted, read mode would wedge after one
    failure and every later frame would be skipped in silence."""
    runner, _ = runner_without_engine
    asyncio.run(runner.submit(JPEG, "read"))
    assert runner._busy is False
