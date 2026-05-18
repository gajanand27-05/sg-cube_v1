"""Communications tools (Phase 11c) — clipboard + WhatsApp + email."""
import re
import subprocess
from urllib.parse import quote_plus

import pyperclip

from backend.core.tools.registry import tool


@tool
def clipboard_copy(text: str) -> dict:
    """Set the system clipboard to `text`. Use for "copy this", "save to clipboard"."""
    pyperclip.copy(text)
    return {"status": "success", "message": f"copied {len(text)} characters to clipboard"}


@tool
def clipboard_get() -> dict:
    """Read the current system clipboard contents (text only)."""
    try:
        text = pyperclip.paste() or ""
    except Exception as e:
        return {"status": "error", "reason": f"clipboard read failed: {e}"}
    preview = text if len(text) <= 100 else text[:97] + "..."
    return {
        "status": "success",
        "message": f"clipboard has {len(text)} chars: {preview}",
        "args": {"text": text},
    }


@tool
def send_whatsapp(contact: str, message: str) -> dict:
    """Open WhatsApp with a pre-filled message to `contact`.
    `contact` must be a phone number with country code (e.g. "+919876543210"
    or "919876543210"). Use for "send X a whatsapp"."""
    if not message.strip():
        return {"status": "blocked", "reason": "empty message"}
    phone = re.sub(r"[^\d]", "", contact)
    if not phone or len(phone) < 7:
        return {
            "status": "blocked",
            "reason": "contact must be a phone number with country code (digits only after country prefix)",
        }
    url = f"https://wa.me/{phone}?text={quote_plus(message)}"
    subprocess.Popen(f'start "" "{url}"', shell=True)
    return {"status": "success", "message": f"opened WhatsApp chat with +{phone}"}


@tool
def send_email(to: str, subject: str = "", body: str = "") -> dict:
    """Open the default mail client with a draft email pre-filled.
    `to` must be an email address. `subject` and `body` are optional."""
    if "@" not in to or " " in to.strip():
        return {"status": "blocked", "reason": "to must be a valid email address"}
    parts = []
    if subject.strip():
        parts.append(f"subject={quote_plus(subject)}")
    if body.strip():
        parts.append(f"body={quote_plus(body)}")
    url = f"mailto:{to.strip()}"
    if parts:
        url += "?" + "&".join(parts)
    subprocess.Popen(f'start "" "{url}"', shell=True)
    return {"status": "success", "message": f"opened email composer for {to}"}
