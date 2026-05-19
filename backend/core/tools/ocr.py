"""OCR tool (Phase 11e) — extract text from the screen.

Requires the Tesseract binary on PATH (separate Windows installer:
https://github.com/UB-Mannheim/tesseract/wiki). If it's missing we return a
helpful error rather than crashing the agent loop.
"""
import pyautogui

from backend.core.tools.registry import tool

MAX_CHARS = 4000


@tool
def ocr_screen() -> dict:
    """Read text visible anywhere on the screen using OCR. Takes a screenshot
    of the full desktop and runs Tesseract on it. Useful for "read the error
    on screen", "what does this say", "OCR this image"."""
    try:
        import pytesseract
    except ImportError:
        return {
            "status": "error",
            "reason": "pytesseract not installed (pip install pytesseract)",
        }

    try:
        image = pyautogui.screenshot()
    except Exception as e:
        return {"status": "error", "reason": f"screenshot failed: {e}"}

    try:
        text = pytesseract.image_to_string(image) or ""
    except pytesseract.TesseractNotFoundError:
        return {
            "status": "error",
            "reason": "Tesseract binary not found on PATH. Install it from https://github.com/UB-Mannheim/tesseract/wiki",
        }
    except Exception as e:
        return {"status": "error", "reason": f"OCR failed: {e}"}

    text = text.strip()
    if not text:
        return {"status": "blocked", "reason": "no text detected on screen"}

    truncated = text[:MAX_CHARS]
    preview = truncated[:200].replace("\n", " ")
    return {
        "status": "success",
        "message": f"Screen text: {preview}{'...' if len(truncated) > 200 else ''}",
        "args": {"text": truncated, "chars": len(truncated)},
    }
