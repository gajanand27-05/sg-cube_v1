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


@pytest.mark.skip(reason="needs Tesseract binary installed")
def test_ocr_frame_real_image():
    """Smoke test against a known image. Skip on CI."""
    from pathlib import Path

    pt = Path(__file__).parents[1] / ".venv/Lib/site-packages/ultralytics/assets/zidane.jpg"
    if not pt.exists():
        return  # assets not installed
    lines = ocr_frame(pt.read_bytes())
    # The asset image has no text, so we expect zero lines.
    assert all(isinstance(l, OCRLine) for l in lines)
    assert all(isinstance(l.text, str) for l in lines)


def test_ocr_direction_center_boundary():
    """Center zone is 1/3 to 2/3 of frame width (inclusive at thirds)."""
    line = OCRLine(text="X", bbox=(213, 0, 214, 10), confidence=0.9)
    assert ocr_direction(line, 640) == "center"


def test_ocr_direction_right_boundary():
    line = OCRLine(text="X", bbox=(430, 0, 431, 10), confidence=0.9)
    assert ocr_direction(line, 640) == "right"
