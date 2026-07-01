"""Communications tools (Phase 11c) — clipboard + WhatsApp + email."""
import re
import subprocess
from urllib.parse import quote_plus

import pyperclip

from backend.core.tools.registry import SecurityLevel, ToolResult, tool
from backend.core.events import get_bus
from backend.daemon.ui_events import HandoverEvent


@tool
def clipboard_copy(text: str) -> ToolResult:
    """Set the system clipboard to `text`. Use for "copy this", "save to clipboard"."""
    pyperclip.copy(text)
    return ToolResult.success(f"copied {len(text)} characters to clipboard")


@tool
def clipboard_get() -> ToolResult:
    """Read the current system clipboard contents (text only)."""
    try:
        text = pyperclip.paste() or ""
    except Exception as e:
        return ToolResult.error(f"clipboard read failed: {e}")
    preview = text if len(text) <= 100 else text[:97] + "..."
    return ToolResult.success(
        message=f"clipboard has {len(text)} chars: {preview}",
        data={"text": text}
    )


@tool
def send_to_phone(content: str, is_url: bool = False) -> ToolResult:
    """Send a link or a text snippet directly to the connected Android device.
    Useful for "send this to my phone", "open this link on my mobile"."""
    event = HandoverEvent(
        url=content if is_url else None,
        text=content if not is_url else None,
        htype="link" if is_url else "text"
    )
    get_bus().publish(event)
    return ToolResult.success(f"Sent {'link' if is_url else 'text'} to mobile device")


@tool(security=SecurityLevel.CAUTION)
def send_whatsapp(contact: str, message: str) -> ToolResult:
    """Open WhatsApp with a pre-filled message to `contact`.
    `contact` must be a phone number with country code (e.g. "+919876543210"
    or "919876543210"). Use for "send X a whatsapp"."""
    if not message.strip():
        return ToolResult.blocked("empty message")
    phone = re.sub(r"[^\d]", "", contact)
    if not phone or len(phone) < 7:
        return ToolResult.blocked("contact must be a phone number with country code (digits only after country prefix)")

    url = f"https://wa.me/{phone}?text={quote_plus(message)}"
    subprocess.Popen(f'start "" "{url}"', shell=True)
    return ToolResult.success(f"opened WhatsApp chat with +{phone}")


@tool(security=SecurityLevel.CAUTION)
def send_email(to: str, subject: str = "", body: str = "") -> ToolResult:
    """Open the default mail client with a draft email pre-filled.
    `to` must be an email address. `subject` and `body` are optional."""
    if "@" not in to or " " in to.strip():
        return ToolResult.blocked("to must be a valid email address")
    parts = []
    if subject.strip():
        parts.append(f"subject={quote_plus(subject)}")
    if body.strip():
        parts.append(f"body={quote_plus(body)}")
    url = f"mailto:{to.strip()}"
    if parts:
        url += "?" + "&".join(parts)
    subprocess.Popen(f'start "" "{url}"', shell=True)
    return ToolResult.success(f"opened email composer for {to}")
