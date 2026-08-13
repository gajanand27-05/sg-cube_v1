"""OCR on phone camera frames — Read mode.

Runs Tesseract on a JPEG frame, returns text lines with their bounding boxes
so the caller knows where each piece of text sits on screen. Runs Tesseract on
a worker thread so it never stalls the WS loop.

Reuses pytesseract from requirements.txt — no new dependency.
"""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class OCRLine:
    """One recognized text region."""
    text: str
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 (pixel coords)
    confidence: float


# Short text that is too common to be useful — screen UI chrome, time stamps
# that aren't signs, etc.
_MIN_CHARS = 2


def ocr_frame(jpeg: bytes) -> list[OCRLine]:
    """Run Tesseract on one JPEG frame. Blocking — call off-loop.

    Returns recognized lines with bounding boxes. Filters single characters and
    whitespace-only runs.
    """
    if not jpeg:
        return []
    import cv2
    import numpy as np
    import pytesseract

    img = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return []

    # data_and_boxes returns: (text, _, boxes, confidences)
    # hocr mode gives per-word data with boxes
    try:
        data = pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
            config="--psm 6",  # Assume a uniform block of text
        )
    except pytesseract.TesseractNotFoundError:
        log.error("Tesseract binary not found on PATH")
        return []
    except Exception as e:
        log.warning("OCR failed: %s", e)
        return []

    out: list[OCRLine] = []
    img_h, img_w = img.shape[:2]

    for i, text in enumerate(data.get("text", [])):
        text = text.strip()
        if len(text) < _MIN_CHARS:
            continue

        conf = data.get("conf", [0])[i] if "conf" in data else 0
        if conf < 50:
            continue

        x = data.get("left", [0])[i]
        y = data.get("top", [0])[i]
        w = data.get("width", [0])[i]
        h = data.get("height", [0])[i]

        out.append(OCRLine(
            text=text,
            bbox=(x, y, x + w, y + h),
            confidence=round(conf / 100.0, 2),
        ))

    # Merge adjacent lines belonging to the same horizontal band (same sign).
    # Two lines share a band when their y-coordinates overlap by >40%.
    merged: list[OCRLine] = []
    for line in out:
        merged_any = False
        for m in merged:
            m_y1, m_y2 = m.bbox[1], m.bbox[3]
            l_y1, l_y2 = line.bbox[1], line.bbox[3]
            overlap = max(0, min(m_y2, l_y2) - max(m_y1, l_y1))
            min_h = min(m_y2 - m_y1, l_y2 - l_y1, 1)
            if overlap / min_h > 0.4:
                m.text += " " + line.text
                m.bbox = (
                    min(m.bbox[0], line.bbox[0]),
                    min(m.bbox[1], line.bbox[1]),
                    max(m.bbox[2], line.bbox[2]),
                    max(m.bbox[3], line.bbox[3]),
                )
                merged_any = True
                break
        if not merged_any:
            merged.append(line)

    return merged


def ocr_text(ocr_lines: list[OCRLine]) -> str:
    """One spoken sentence from recognized text."""
    if not ocr_lines:
        return "No readable text in view."
    texts = [line.text for line in ocr_lines if line.text]
    return " ".join(texts)


def ocr_direction(line: OCRLine, frame_w: int) -> str:
    """Where on screen the text sits."""
    cx = (line.bbox[0] + line.bbox[2]) / 2
    return "left" if cx < frame_w / 3 else "right" if cx > 2 * frame_w / 3 else "center"
