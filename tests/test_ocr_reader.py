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


def test_ocr_frame_real_image():
    """A real photograph with no signage in it.

    Was an unconditional @pytest.mark.skip — permanently off regardless of
    whether Tesseract existed, so installing the engine did not bring it back.
    It also asserted only isinstance(), which an empty list satisfies, while
    its comment claimed "we expect zero lines". Now it is gated on the actual
    resolver and asserts the contract it can honestly make.

    Observed 2026-08-13 with Tesseract 5.4.0: this photo yields one spurious
    line, 'al j' at confidence 0.56 — just over the 50 cutoff. Recorded rather
    than tuned away: raising the threshold on a single sample risks dropping
    genuine low-contrast signage, which is the failure that actually matters.
    """
    from pathlib import Path

    from backend.core.vision.ocr_reader import tesseract_path

    if tesseract_path() is None:
        pytest.skip("Tesseract binary not installed")

    pt = Path(__file__).parents[1] / ".venv/Lib/site-packages/ultralytics/assets/zidane.jpg"
    if not pt.exists():
        pytest.skip("ultralytics assets not installed")

    lines = ocr_frame(pt.read_bytes())
    assert all(isinstance(line, OCRLine) for line in lines)
    assert all(isinstance(line.text, str) and line.text.strip() for line in lines)
    assert all(0.0 < line.confidence <= 1.0 for line in lines), \
        [(line.text, line.confidence) for line in lines]
    # A photo of two footballers must not read as a page of text.
    assert len(lines) <= 3, f"unexpected volume of text from a text-free photo: {lines}"


def test_ocr_direction_center_boundary():
    """Center zone is 1/3 to 2/3 of frame width (inclusive at thirds)."""
    line = OCRLine(text="X", bbox=(213, 0, 214, 10), confidence=0.9)
    assert ocr_direction(line, 640) == "center"


def test_ocr_direction_right_boundary():
    line = OCRLine(text="X", bbox=(430, 0, 431, 10), confidence=0.9)
    assert ocr_direction(line, 640) == "right"
