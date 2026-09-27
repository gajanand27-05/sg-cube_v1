"""What personal text may reach sg_cube.log and the console.

Transcripts of what the user said, Onyx's replies, and tool arguments that
carry personal text (message bodies, file paths, contact names, URLs, search
queries, window titles) are logged in full only with LOG_TRANSCRIPTS=true.
Otherwise a line keeps its metadata and the text becomes its length, so a
log attached to a bug report doesn't carry the user's words.
"""
from __future__ import annotations

from typing import Any


def said(text: Any) -> str:
    """The text as repr() with LOG_TRANSCRIPTS on; otherwise "<N chars>"."""
    from backend.server.config import settings

    if text is None:
        return "None"
    s = text if isinstance(text, str) else str(text)
    return repr(s) if settings.log_transcripts else f"<{len(s)} chars>"
