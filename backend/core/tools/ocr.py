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

# Tokens the assistant SPEAKS have to be words. A full-screen pass reads every
# toolbar icon as text, and since the spoken line is the head of the OCR
# output, and the head of a screen is browser chrome, the user heard
# "¥ @o @xs OH Oa Ot so QP fir The kein to |Me QQ»" while the actual document
# text sat further down and was never reached.
#
# Filtering on Tesseract's confidence does NOT fix this — measured on a real
# 1920x1080 screen, junk tokens were 24% at conf>=0 and still 18% at conf>=80.
# Tesseract is confident about its garbage. Word SHAPE is the signal that
# separates them.
#
# This is applied ONLY to the spoken preview. `data["text"]` keeps the full
# unfiltered pass, because the agent legitimately needs the tokens this drops:
# error codes, temperatures, prices, timestamps. Speaking is a different job
# from reading, and only one of them can afford to be lossy.
_PREVIEW_MIN_CONF = 40.0
_PREVIEW_MIN_LETTERS = 2
_PREVIEW_LETTER_RATIO = 0.6
# Punctuation that legitimately appears inside or beside a word. Anything
# else — |, @, ¥, », \, <, ~ — is an icon Tesseract read as a character.
#
# A letter-ratio test alone is not enough: "|Me" and "@tc" are two letters in
# three and sail through it, and both came from the real reported output. The
# stray symbol IS the evidence, so the charset is the test.
_WORD_PUNCT = set("'-.,:;!?()’")
# Line-level thresholds. A row of icon labels is a couple of two-letter
# tokens; a line of prose is several longer ones. Deliberately mild — the goal
# is a readable spoken line, and being aggressive here would start dropping
# short real UI labels ("Ask Gemini", "File Edit View") that the user may well
# have been asking about.
_PREVIEW_MIN_LINE_TOKENS = 2
_PREVIEW_MIN_LINE_LETTERS = 8


def _word_shaped(token: str) -> bool:
    letters = sum(c.isalpha() for c in token)
    if letters < _PREVIEW_MIN_LETTERS:
        return False
    if letters / len(token) < _PREVIEW_LETTER_RATIO:
        return False
    return all(c.isalnum() or c in _WORD_PUNCT for c in token)


def _readable_preview(pytesseract, image, limit: int = 200) -> str:
    """A spoken-quality summary of what is on screen, or "" if unavailable.

    Never raises: this is a nicety on top of a working OCR result, and a
    failure here must not turn a successful read into an error.
    """
    try:
        from pytesseract import Output
        data = pytesseract.image_to_data(image, output_type=Output.DICT)
    except Exception:
        return ""
    # Group by Tesseract's own line numbering. Token-level filtering alone
    # leaves runs like "Qo sc ire he Mie Op ax Br ado ao" — icon labels that
    # are pure letters and pass any charset or ratio test. What separates them
    # from prose is structural, not lexical: an icon row is a couple of very
    # short tokens, a line of text is several longer ones. The line number is
    # already in the payload, so this costs nothing extra.
    lines: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    n = len(data.get("text", []))
    for i in range(n):
        token = (data["text"][i] or "").strip()
        if not token:
            continue
        try:
            if float(data["conf"][i]) < _PREVIEW_MIN_CONF:
                continue
        except (TypeError, ValueError):
            continue
        if not _word_shaped(token):
            continue
        key = (
            data.get("block_num", [0] * n)[i],
            data.get("par_num", [0] * n)[i],
            data.get("line_num", [0] * n)[i],
        )
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(token)

    kept: list[str] = []
    for key in order:
        tokens = lines[key]
        letters = sum(sum(c.isalpha() for c in t) for t in tokens)
        # Two signals, both required: enough words to be a phrase, and enough
        # letters to not be a row of two-character icon labels.
        if len(tokens) >= _PREVIEW_MIN_LINE_TOKENS and letters >= _PREVIEW_MIN_LINE_LETTERS:
            kept.extend(tokens)
    return " ".join(kept)[:limit].strip()

@tool(tier=CapabilityTier.READONLY)  # tier: captures screen + OCR, no state change
def ocr_screen() -> ToolResult:
    """Read the exact text visible anywhere on screen, using OCR. FAST: about
    3 seconds.

    This is the right tool for every request to read, quote, extract or OCR
    what is on screen — "read my screen", "read the error", "what does this
    say", "what is the text on screen". Prefer it over `describe_screen`,
    which is a ~35 second vision model and returns a description rather than
    the words themselves."""
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
        spoken_preview = _readable_preview(pytesseract, image)
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
    # Prefer the word-filtered preview; fall back to the raw head only if
    # image_to_data was unavailable, so a degraded read still says something.
    preview = spoken_preview or truncated[:200].replace("\n", " ")
    
    # Calculate confidence based on text quality (simple heuristic)
    confidence = 90.0 if len(text) > 50 else 75.0
    
    return ToolResult.success(
        message=f"Screen text: {preview}{'...' if len(truncated) > len(preview) else ''}",
        data={"text": truncated, "chars": len(truncated)},
        confidence=confidence,
        confidence_reason=[
            "Full screen screenshot captured",
            f"Detected {len(text)} characters",
            "Tesseract OCR processing complete"
        ]
    )
