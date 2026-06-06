"""OCR tool (Phase 11e) — extract text from the screen.

Requires the Tesseract binary on PATH (separate Windows installer:
https://github.com/UB-Mannheim/tesseract/wiki). If it's missing we return a
helpful error rather than crashing the agent loop.
"""
import pyautogui

from backend.core.tools.registry import ToolResult, tool

@tool
def ocr_screen() -> ToolResult:
    """Read text visible anywhere on the screen using OCR. Takes a screenshot
    of the full desktop and runs Tesseract on it. Useful for "read the error
    on screen", "what does this say", "OCR this image"."""
    try:
        import pytesseract
    except ImportError:
        return ToolResult.error("pytesseract not installed (pip install pytesseract)")

    try:
        image = pyautogui.screenshot()
    except Exception as e:
        return ToolResult.error(f"screenshot failed: {e}")

    try:
        text = pytesseract.image_to_string(image) or ""
    except pytesseract.TesseractNotFoundError:
        return ToolResult.error("Tesseract binary not found on PATH. Install it from https://github.com/UB-Mannheim/tesseract/wiki")
    except Exception as e:
        return ToolResult.error(f"OCR failed: {e}")

    text = text.strip()
    if not text:
        return ToolResult.blocked("no text detected on screen", confidence=20.0, confidence_reason=["Screenshot captured", "No readable characters found"])

    truncated = text[:MAX_CHARS]
    preview = truncated[:200].replace("\n", " ")
    
    # Calculate confidence based on text quality (simple heuristic)
    confidence = 90.0 if len(text) > 50 else 75.0
    
    return ToolResult.success(
        message=f"Screen text: {preview}{'...' if len(truncated) > 200 else ''}",
        data={"text": truncated, "chars": len(truncated)},
        confidence=confidence,
        confidence_reason=[
            "Full screen screenshot captured",
            f"Detected {len(text)} characters",
            "Tesseract OCR processing complete"
        ]
    )
