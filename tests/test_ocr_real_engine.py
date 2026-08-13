"""Read mode against the real Tesseract engine.

Tesseract 5.4.0 was installed on 2026-08-13, which unblocked testing this path
for the first time — and the first real image showed "PLATFORM 4" coming back
as "PLATFORM". A flat `len(text) < 2` filter was dropping every single
character, and on signage the digit IS the message: platform and gate numbers,
bus routes, room numbers, prices, "Exit 9".

The other half is that a missing engine must never read as an empty scene.
ocr_frame() returned [] both when there was no text and when Tesseract was
absent, and the caller spoke "no readable text in view" either way — a claim
about the world, made to someone who asked because they cannot see the world.
That is now OCRUnavailable.

Skips rather than fails without the binary, so a fresh clone is not red — but
`test_the_engine_is_actually_installed` records the expectation loudly.
"""
import sys
from pathlib import Path

import pytest

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from backend.core.vision import ocr_reader
from backend.core.vision.ocr_reader import OCRUnavailable, ocr_frame, ocr_text, tesseract_path

pytestmark = pytest.mark.skipif(tesseract_path() is None,
                                reason="Tesseract binary not installed")


def _render(*lines: str) -> bytes:
    import cv2
    import numpy as np
    img = np.full((90 * len(lines) + 60, 760, 3), 255, np.uint8)
    for i, text in enumerate(lines):
        cv2.putText(img, text, (30, 80 + 90 * i), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 4)
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_the_engine_is_actually_installed():
    path = tesseract_path()
    assert path and Path(path).is_file(), f"tesseract_path() returned {path!r}"


def test_reads_plain_signage():
    assert "EXIT" in ocr_text(ocr_frame(_render("EXIT RIGHT")))


@pytest.mark.parametrize("sign, must_contain", [
    ("PLATFORM 4", "4"),      # the exact regression: a lone digit
    ("BUS 7 CITY", "7"),
    ("GATE B 12", "12"),
])
def test_single_characters_and_numbers_survive(sign, must_contain):
    """Losing the noun is inconvenient; losing the number sends someone to the
    wrong platform."""
    read = ocr_text(ocr_frame(_render(sign)))
    assert must_contain in read, f"read {read!r} from {sign!r} — the number was dropped"


def test_a_blank_scene_is_empty_not_an_error():
    """The genuine 'no text here' case still has to be an empty result, or the
    distinction below is meaningless."""
    import cv2
    import numpy as np
    blank = cv2.imencode(".jpg", np.full((200, 400, 3), 255, np.uint8))[1].tobytes()
    assert ocr_frame(blank) == []


def test_missing_engine_raises_instead_of_reporting_an_empty_scene(monkeypatch):
    """The load-bearing distinction. Before this, both answered []."""
    monkeypatch.setattr(ocr_reader, "tesseract_path", lambda: None)
    with pytest.raises(OCRUnavailable):
        ocr_frame(_render("EXIT"))


def test_env_override_points_at_an_explicit_binary(monkeypatch, tmp_path):
    """TESSERACT_CMD is the escape hatch for an install in an unusual place."""
    tesseract_path.cache_clear()
    fake = tmp_path / "tesseract.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("TESSERACT_CMD", str(fake))
    try:
        assert tesseract_path() == str(fake)
        monkeypatch.setenv("TESSERACT_CMD", str(tmp_path / "nope.exe"))
        tesseract_path.cache_clear()
        assert tesseract_path() is None, "a bad override must not silently fall back"
    finally:
        tesseract_path.cache_clear()


def _noisy_sign(w: int, h: int, text: str = "PLATFORM 4") -> bytes:
    """Textured backdrop, not a clean render — a flat white image is far easier
    than anything a phone camera actually produces."""
    import cv2
    import numpy as np
    rng = np.random.default_rng(3)
    img = rng.integers(110, 205, (h, w, 3), dtype=np.uint8)
    cv2.rectangle(img, (int(w * .08), int(h * .28)), (int(w * .92), int(h * .62)), (255, 255, 255), -1)
    s = w / 700
    cv2.putText(img, text, (int(w * .11), int(h * .45)),
                cv2.FONT_HERSHEY_SIMPLEX, 1.5 * s, (0, 0, 0), int(4 * s))
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_oversized_frames_are_capped_for_speed():
    """Read mode runs at 2fps. Measured 2026-08-13: a 1080p frame took a median
    445ms against a 500ms budget — 11% headroom — while 720p took 273ms at
    identical word recall. The cap is what keeps a busy scene from silently
    dropping frames."""
    from backend.core.vision.ocr_reader import _OCR_MAX_HEIGHT
    assert _OCR_MAX_HEIGHT == 720
    assert "PLATFORM" in ocr_text(ocr_frame(_noisy_sign(1920, 1080))).upper()


def test_bboxes_are_reported_in_original_frame_coordinates():
    """The downscale must be invisible to callers. ocr_direction() divides a
    bbox centre by the frame width the CALLER measured, so bboxes left in
    downscaled pixels would report left/right against the wrong frame."""
    big = ocr_frame(_noisy_sign(1920, 1080))[0].bbox
    small = ocr_frame(_noisy_sign(1280, 720))[0].bbox   # native, no downscale
    ratios = [b / s for b, s in zip(big, small)]
    assert all(1.42 < r < 1.58 for r in ratios), (
        f"expected ~1.5x (1080/720); got {[round(r, 3) for r in ratios]} — "
        "bboxes are still in the downscaled coordinate space"
    )


def test_preflight_reports_ocr_available():
    from backend.core.preflight import PreflightStatus, check_ocr
    result = check_ocr()
    assert result.status is PreflightStatus.OK, result.message
    assert result.detail["path"] == tesseract_path()
