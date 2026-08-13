"""OCR tool (Phase 11e) — extract text from the screen.

Needs the Tesseract BINARY, which pip cannot install. Resolution is shared
with vision/ocr_reader.py via tesseract_path(): the UB-Mannheim Windows
installer does NOT add itself to PATH, so `pytesseract`'s own lookup fails on
a perfectly good install. This tool relied on that lookup and reported
"Tesseract binary not found on PATH" with the engine sitting installed at the
default location — the resolver was added for the phone-camera OCR path on
2026-08-13 and not applied here, so screen OCR stayed broken while phone OCR
worked.
"""
import pyautogui

from backend.core.tools.registry import CapabilityTier, ToolResult, tool

# Cap on OCR text returned to the agent loop — a full-screen Tesseract pass on
# a text-dense display can exceed the planner's useful context budget.
MAX_CHARS = 6000

@tool(tier=CapabilityTier.READONLY)  # tier: captures screen + OCR, no state change
def ocr_screen() -> ToolResult:
    """Read text visible anywhere on the screen using OCR. Takes a screenshot
    of the full desktop and runs Tesseract on it. Useful for "read the error
    on screen", "what does this say", "OCR this image"."""
    try:
        import pytesseract
    except ImportError:
        return ToolResult.error("pytesseract not installed (pip install pytesseract)")

    from backend.core.vision.ocr_reader import tesseract_path

    binary = tesseract_path()
    if binary is None:
        return ToolResult.error(
            "Tesseract is not installed. Install it with "
            "`winget install UB-Mannheim.TesseractOCR`, or set TESSERACT_CMD."
        )
    pytesseract.pytesseract.tesseract_cmd = binary

    try:
        image = pyautogui.screenshot()
    except Exception as e:
        return ToolResult.error(f"screenshot failed: {e}")

    try:
        text = pytesseract.image_to_string(image) or ""
    except pytesseract.TesseractNotFoundError:
        return ToolResult.error(
            f"Tesseract at {binary!r} would not run — the install looks broken."
        )
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
