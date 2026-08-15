"""Vision loop change detection: does the skip that guards a 35s VLM run
actually fire?

The old byte-hash never did. It was written as an "Efficiency Improvement"
but, measured against real screen captures, skipped 0 of 9 consecutive
frames and could not skip a single changed pixel — so an idle machine paid
the full VLM every 300s at ~96% GPU. These tests pin the replacement to the
numbers that motivated it, and drive VisionLoop._step directly so the saving
is proven where it happens rather than only in the hash function.
"""
import base64
import sys
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core.vision.change_detect import HASH_BITS, dhash, distance


# ── fixtures: synthetic "screens" ──────────────────────────────────────

def _encode(arr: np.ndarray) -> str:
    buf = BytesIO()
    Image.fromarray(arr).save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode()


def _screen(seed: int = 0, w: int = 1024, h: int = 576) -> np.ndarray:
    """Something with structure — a flat colour hashes to all-zeros and
    would make every comparison trivially equal."""
    rng = np.random.default_rng(seed)
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    for _ in range(40):  # windows/panels
        y, x = rng.integers(0, h - 60), rng.integers(0, w - 120)
        arr[y:y + 60, x:x + 120] = rng.integers(30, 220, 3)
    return arr


def _old_naive_hash(img_b64: str) -> str:
    """The implementation this replaced, kept so the tests can show the
    difference rather than assert it."""
    return f"{len(img_b64)}-{img_b64[:100]}-{img_b64[-100:]}"


# ── the hash itself ────────────────────────────────────────────────────

def test_identical_screen_scores_zero():
    b64 = _encode(_screen())
    assert distance(dhash(b64), dhash(b64)) == 0


def test_single_changed_pixel_is_not_a_change():
    """The case the old hash got wrong."""
    base = _screen()
    mutated = base.copy()
    mutated[288, 512] = (255, 0, 255)
    a, b = _encode(base), _encode(mutated)
    assert _old_naive_hash(a) != _old_naive_hash(b), (
        "fixture is wrong: the old hash is supposed to fail this"
    )
    assert distance(dhash(a), dhash(b)) == 0


def test_clock_sized_region_is_not_a_change():
    """A taskbar clock ticking over is why an idle screen never skipped."""
    base = _screen()
    mutated = base.copy()
    mutated[560:572, 980:1020] = 255
    assert distance(dhash(_encode(base)), dhash(_encode(mutated))) <= 6


def test_switching_windows_is_a_change():
    """Must stay well clear of the threshold in the other direction — an
    over-eager skip means Onyx silently stops seeing the screen."""
    a, b = _encode(_screen(seed=1)), _encode(_screen(seed=2))
    assert distance(dhash(a), dhash(b)) > 20


def test_half_the_screen_is_a_large_change():
    base = _screen()
    mutated = base.copy()
    mutated[: base.shape[0] // 2, :] = 0
    assert distance(dhash(_encode(base)), dhash(_encode(mutated))) > 20


def test_global_brightness_shift_is_not_a_change():
    """dhash compares neighbours, not levels, so a theme dimming or a
    backlight change must not burn a VLM run."""
    base = _screen()
    dimmed = (base.astype(np.int16) * 0.8).clip(0, 255).astype(np.uint8)
    assert distance(dhash(_encode(base)), dhash(_encode(dimmed))) <= 6


def test_undecodable_frame_is_maximally_different():
    """Fail toward looking. Not looking is the expensive mistake."""
    assert dhash("not base64 at all") is None
    assert distance(None, dhash(_encode(_screen()))) == HASH_BITS
    assert distance(dhash(_encode(_screen())), None) == HASH_BITS


def test_threshold_sits_in_a_real_gap():
    """The configured threshold has to separate the two clusters, not just
    happen to work on one fixture."""
    from backend.server.config import settings
    base = _screen()
    noise = base.copy()
    noise[560:572, 980:1020] = 255          # clock
    noise[288, 512] = (255, 0, 255)         # cursor
    unchanged_dist = distance(dhash(_encode(base)), dhash(_encode(noise)))
    changed_dist = distance(dhash(_encode(_screen(1))), dhash(_encode(_screen(2))))
    assert unchanged_dist <= settings.vision_change_threshold < changed_dist, (
        f"threshold {settings.vision_change_threshold} does not separate "
        f"noise={unchanged_dist} from change={changed_dist}"
    )


# ── the loop step, where the GPU is actually spent ─────────────────────

class _VLMSpy:
    def __init__(self):
        self.calls = 0

    def __call__(self, img_b64, title):
        self.calls += 1
        return {"app": title, "summary": "spied", "keywords": [], "objects": [], "ocr": []}


def _run_steps(frames, titles=None):
    """Drive VisionLoop._step over a list of (already-encoded) frames.
    Returns how many of them reached the VLM."""
    from backend.daemon.vision_loop import VisionLoop
    titles = titles or ["Same Window"] * len(frames)
    spy = _VLMSpy()
    loop = VisionLoop()
    seq = list(zip(frames, titles))
    with patch("backend.daemon.vision_loop.capture_screen", side_effect=seq), \
         patch("backend.daemon.vision_loop.analyze_screenshot_sync", spy), \
         patch("backend.daemon.vision_loop.screen_memory"), \
         patch("backend.daemon.vision_loop.timeline"), \
         patch("backend.daemon.vision_loop.get_bus"):
        for _ in seq:
            loop._step()
    return spy.calls


def test_idle_screen_costs_one_vlm_run_not_ten():
    """The battery finding, restated as a test. Ten glances at a screen
    where only a clock is moving used to be ten 35s VLM runs."""
    base = _screen()
    frames = []
    for i in range(10):
        f = base.copy()
        f[560:572, 980:1020] = (i * 25) % 256  # the clock, ticking
        frames.append(_encode(f))
    assert _run_steps(frames) == 1


def test_the_old_hash_would_have_run_all_ten():
    """Non-vacuity: those ten frames really are byte-distinct, so the
    saving above is the gate working, not a fixture of identical images."""
    base = _screen()
    frames = []
    for i in range(10):
        f = base.copy()
        f[560:572, 980:1020] = (i * 25) % 256
        frames.append(_encode(f))
    assert len({_old_naive_hash(f) for f in frames}) == 10


def test_real_activity_still_reaches_the_vlm():
    frames = [_encode(_screen(seed=i)) for i in range(5)]
    assert _run_steps(frames) == 5


def test_title_change_forces_a_look_even_if_pixels_match():
    """Alt-tab between two visually similar windows is a context switch the
    VLM needs to see, and the window title is free evidence of it."""
    b64 = _encode(_screen())
    assert _run_steps([b64, b64], titles=["Notepad", "Notepad"]) == 1
    assert _run_steps([b64, b64], titles=["Notepad", "Terminal"]) == 2


def test_drift_is_measured_from_the_last_analysed_frame():
    """Comparing against the last CAPTURED frame would let a screen creep
    arbitrarily far from what Onyx last understood, one sub-threshold step
    at a time, and never trigger a look."""
    base = _screen()
    frames = []
    for i in range(1, 30):  # a widening band — each step tiny, the sum large
        f = base.copy()
        f[: i * 18, :] = 0
        frames.append(_encode(f))
    assert _run_steps(frames) > 1


if __name__ == "__main__":
    for name, fn in sorted(list(globals().items())):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  [PASS] {name}")
