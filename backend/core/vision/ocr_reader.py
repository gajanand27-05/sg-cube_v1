"""OCR on phone camera frames — Read mode.

Runs Tesseract on a JPEG frame, returns text lines with their bounding boxes
so the caller knows where each piece of text sits on screen. Runs Tesseract on
a worker thread so it never stalls the WS loop.

Reuses pytesseract from requirements.txt — no new dependency.
"""
import logging
import os
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)


class OCRUnavailable(RuntimeError):
    """The OCR engine itself is missing — distinct from 'no text in view'.

    These two must never collapse into the same answer. Read mode exists for a
    user who cannot see the sign, so "no readable text in view" is a statement
    about the WORLD; if the engine is absent it is a statement about the
    software, and the user acts on the wrong one. ocr_frame() returned [] for
    both until 2026-08-13.
    """


# The Windows installer (UB-Mannheim) does not put tesseract.exe on PATH, so
# `shutil.which` alone finds nothing on a perfectly good install. Checked in
# order; TESSERACT_CMD wins so an unusual install can be pointed at directly.
_TESSERACT_HINTS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)


@lru_cache(maxsize=1)
def tesseract_path() -> str | None:
    """Absolute path to the Tesseract binary, or None if it is not installed.

    Cached: this runs per frame in read mode, and a filesystem probe per frame
    at 2fps is pure waste. Call tesseract_path.cache_clear() after installing.
    """
    override = os.environ.get("TESSERACT_CMD", "").strip()
    if override:
        return override if Path(override).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    return next((p for p in _TESSERACT_HINTS if Path(p).is_file()), None)


def _configure_pytesseract(pytesseract) -> None:
    """Point pytesseract at the binary we resolved. Raises if there isn't one."""
    path = tesseract_path()
    if path is None:
        raise OCRUnavailable(
            "Tesseract is not installed or could not be found. Install it "
            "(winget install UB-Mannheim.TesseractOCR) or set TESSERACT_CMD."
        )
    pytesseract.pytesseract.tesseract_cmd = path


@dataclass
class OCRLine:
    """One recognized text region."""
    text: str
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 (pixel coords)
    confidence: float


# Drop single-character fragments, which are mostly edge artefacts and stray
# punctuation — but NEVER a lone alphanumeric. "PLATFORM 4" came back as
# "PLATFORM" under a flat `len(text) < 2` rule, and the digit is the entire
# point of the sign: platform and gate numbers, bus routes, room numbers,
# prices, "Exit 9". Losing the noun is inconvenient; losing the number sends
# someone to the wrong platform.
_MIN_CHARS = 2


def _is_noise(text: str) -> bool:
    """True for fragments not worth speaking."""
    if not text:
        return True
    return len(text) < _MIN_CHARS and not text.isalnum()


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

    _configure_pytesseract(pytesseract)

    # data_and_boxes returns: (text, _, boxes, confidences)
    # hocr mode gives per-word data with boxes
    try:
        data = pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
            config="--psm 6",  # Assume a uniform block of text
        )
    except pytesseract.TesseractNotFoundError as e:
        # Resolved a path but the binary would not run — a broken install, not
        # an empty scene. Same reason this is not `return []`.
        raise OCRUnavailable(f"Tesseract at {tesseract_path()!r} would not run: {e}") from e
    except Exception as e:
        log.warning("OCR failed: %s", e)
        return []

    out: list[OCRLine] = []
    img_h, img_w = img.shape[:2]

    for i, text in enumerate(data.get("text", [])):
        text = text.strip()
        if _is_noise(text):
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
