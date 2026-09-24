"""OCR reader — phone frame text recognition."""
import pytest

from backend.core.vision.ocr_reader import OCRLine, ocr_frame, ocr_text, ocr_direction


# Minimal JPEG SOI + minimal EOI. Tesseract won't parse this, but it
# satisfies cv2.imdecode and lets us test the data flow.
_MINIMAL_JPEG = b"\xff\xd8\xff\xe0" + b"x" * 100


def test_ocr_text_empty():
    text = ocr_text([])
    assert text == "No readable text in view."


def test_ocr_text_single():
    lines = [OCRLine(text="HELLO", bbox=(0, 0, 10, 10), confidence=0.9)]
    assert ocr_text(lines) == "HELLO"


def test_ocr_text_multiple():
    lines = [
        OCRLine(text="STOP", bbox=(0, 0, 10, 10), confidence=0.95),
        OCRLine(text="MAIN ST", bbox=(20, 20, 50, 30), confidence=0.88),
    ]
    assert ocr_text(lines) == "STOP MAIN ST"


def test_ocr_direction_left():
    line = OCRLine(text="X", bbox=(0, 0, 50, 10), confidence=0.9)
    assert ocr_direction(line, 640) == "left"


def test_ocr_direction_center():
    line = OCRLine(text="X", bbox=(200, 0, 400, 10), confidence=0.9)
    assert ocr_direction(line, 640) == "center"


def test_ocr_direction_right():
    line = OCRLine(text="X", bbox=(550, 0, 600, 10), confidence=0.9)
    assert ocr_direction(line, 640) == "right"


def test_ocr_frame_invalid_jpeg():
    """Invalid JPEG returns empty list, no crash."""
    result = ocr_frame(_MINIMAL_JPEG)
    assert result == []


def test_ocr_frame_empty_bytes():
    result = ocr_frame(b"")
    assert result == []


def _text_free_photo(seed: int) -> bytes:
    """A deterministic photo-like JPEG with no text in it: a lighting
    gradient, overlapping solid shapes (hard edges are what Tesseract
    misreads), lens blur and sensor noise."""
    import cv2
    import numpy as np

    rng = np.random.default_rng(seed)
    h, w = 480, 640
    y, x = np.mgrid[0:h, 0:w]
    img = np.dstack([x * 255 / w, y * 255 / h, (x + y) * 255 / (w + h)])
    img = img.astype(np.float32) * 0.6 + 40
    for _ in range(25):
        colour = tuple(int(v) for v in rng.integers(0, 256, 3))
        if rng.random() < 0.5:
            centre = (int(rng.integers(0, w)), int(rng.integers(0, h)))
            cv2.circle(img, centre, int(rng.integers(10, 120)), colour, -1)
        else:
            p = rng.integers(0, [w, h], size=(2, 2))
            cv2.rectangle(img, tuple(int(v) for v in p[0]),
                          tuple(int(v) for v in p[1]), colour, -1)
    img = cv2.GaussianBlur(img, (0, 0), 2.0) + rng.normal(0, 8, img.shape)
    return cv2.imencode(".jpg", np.clip(img, 0, 255).astype(np.uint8))[1].tobytes()


@pytest.mark.parametrize("seed", range(5))
def test_ocr_frame_text_free_image(seed):
    """A photo-like image with no text in it must not read as a page of text.

    Was an unconditional @pytest.mark.skip — permanently off regardless of
    whether Tesseract existed, so installing the engine did not bring it back.
    Then it read zidane.jpg out of the ultralytics package, which was never a
    declared dependency: it skipped on every fresh install, and went for good
    when torch/ultralytics left the venv. Now it generates its own images.

    Observed 2026-09-24 with Tesseract 5.4.0: seeds 0-3 yield nothing, seed 4
    yields one spurious line, 'Jj' at confidence 0.55 — the same behaviour as
    the old photo ('al j' at 0.56). Recorded rather than tuned away: raising
    the threshold on these samples risks dropping genuine low-contrast
    signage, which is the failure that actually matters.
    """
    from backend.core.vision.ocr_reader import tesseract_path

    if tesseract_path() is None:
        pytest.skip("Tesseract binary not installed")

    lines = ocr_frame(_text_free_photo(seed))
    assert all(isinstance(line, OCRLine) for line in lines)
    assert all(isinstance(line.text, str) and line.text.strip() for line in lines)
    assert all(0.0 < line.confidence <= 1.0 for line in lines),         [(line.text, line.confidence) for line in lines]
    assert len(lines) <= 3, f"unexpected volume of text from a text-free image: {lines}"


def test_ocr_direction_center_boundary():
    """Center zone is 1/3 to 2/3 of frame width (inclusive at thirds)."""
    line = OCRLine(text="X", bbox=(213, 0, 214, 10), confidence=0.9)
    assert ocr_direction(line, 640) == "center"


def test_ocr_direction_right_boundary():
    line = OCRLine(text="X", bbox=(430, 0, 431, 10), confidence=0.9)
    assert ocr_direction(line, 640) == "right"
