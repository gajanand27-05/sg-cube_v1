"""Read-aloud tool (Phase 11e).

Reads whatever is on the clipboard out loud via Piper TTS. The user copies
text (Ctrl+C in any app), then says "read this" / "read it out loud".
"""
import threading

import pyperclip

from backend.core.tools.registry import CapabilityTier, tool

MAX_CHARS = 4000  # cap clipboard size piped into TTS


def _speak_async(text: str) -> None:
    def _go() -> None:
        from backend.ai_modules.speech.tts_piper import speak
        speak(text)
    threading.Thread(target=_go, daemon=True).start()


@tool(tier=CapabilityTier.READONLY)  # tier: TTS output only, no persistent state change
def read_aloud() -> dict:
    """Read the current clipboard contents out loud. Copy text in any app
    first (Ctrl+C), then say "read this" or "read it out loud"."""
    try:
        text = pyperclip.paste() or ""
    except Exception as e:
        return {"status": "error", "reason": f"clipboard error: {e}"}

    text = text.strip()
    if not text:
        return {"status": "blocked", "reason": "clipboard is empty"}

    truncated = text[:MAX_CHARS]
    _speak_async(truncated)

    return {
        "status": "success",
        "message": f"reading {len(truncated)} characters from the clipboard",
        "args": {"chars": len(truncated), "truncated": len(text) > MAX_CHARS},
    }
