"""Vision tool — on-demand VLM screen understanding.

Wraps `capture_screen` + `analyze_screenshot` so the planner can invoke live
scene understanding when the user asks about their screen. Independent of the
passive vision loop: captures a fresh screenshot every call.

Distinct from `ocr_screen` (pytesseract, exact text extraction). Prefer this
tool for "what am I doing", "what's on my screen", "describe the layout" —
prefer `ocr_screen` for "read the error message text" or "OCR this image".
"""
from backend.core.tools.registry import CapabilityTier, ToolResult, tool
from backend.core.vision.capture import capture_screen
from backend.core.vision.vlm import analyze_screenshot


@tool(tier=CapabilityTier.READONLY)  # tier: captures screen + VLM description, no state change
async def describe_screen() -> ToolResult:
    """Describe the LAYOUT and ACTIVITY on the user's screen — what app is
    open, what they appear to be doing. SLOW: runs a local vision model and
    takes about 35 seconds.

    Do NOT use this to read text. Any request to read, quote, extract or OCR
    what is on screen — "read my screen", "read the error", "what does this
    say", "what is the text" — must use `ocr_screen`, which returns exact text
    in about 3 seconds. Only use this tool when the question is genuinely about
    the scene rather than its words."""
    img_b64, window_title = capture_screen()
    if not img_b64:
        return ToolResult.error("Screen capture failed")

    observation = await analyze_screenshot(img_b64, window_title)
    if not observation:
        return ToolResult.error("VLM analysis failed (Ollama unreachable or model missing)")

    app = observation.get("app", window_title)
    summary = observation.get("summary", "")
    keywords = observation.get("keywords", [])

    return ToolResult.success(
        message=f"{app}: {summary}",
        data={"app": app, "summary": summary, "keywords": keywords, "window_title": window_title},
        confidence=85.0,
        confidence_reason=[
            "Fresh screenshot captured",
            f"VLM described: {app}",
            f"{len(keywords)} keywords extracted",
        ],
    )
