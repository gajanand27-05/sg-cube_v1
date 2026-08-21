"""Communications tools (Phase 11c) — clipboard + WhatsApp + email."""
import re
import webbrowser
from urllib.parse import quote_plus

import pyperclip

from backend.core.tools.registry import CapabilityTier, SecurityLevel, ToolResult, tool
from backend.core.events import get_bus
from backend.daemon.ui_events import HandoverEvent


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: writes the clipboard, reversible by copying again
def clipboard_copy(text: str) -> ToolResult:
    """Set the system clipboard to `text`. Use for "copy this", "save to clipboard"."""
    pyperclip.copy(text)
    return ToolResult.success(f"copied {len(text)} characters to clipboard")


@tool(tier=CapabilityTier.READONLY)  # tier: reads clipboard, no side effects
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


@tool(tier=CapabilityTier.DESTRUCTIVE)  # tier: external comms — cannot be recalled once sent
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


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.DESTRUCTIVE)  # tier: external comm, irreversible
def send_whatsapp(contact: str, message: str) -> ToolResult:
    """Open WhatsApp with a pre-filled message to `contact`.
    `contact` is a saved contact NAME (e.g. "Sharath") or a phone number with
    country code (e.g. "+919876543210"). Names are resolved against the saved
    contacts; add one with add_contact. Use for "send X a whatsapp"."""
    if not message.strip():
        return ToolResult.blocked("empty message")

    # Names, not just digits. Resolution refuses to guess between two similar
    # contacts, because this opens a real chat with a real person and there is
    # no undo — see backend/core/contacts.py.
    from backend.core.contacts import book

    resolved = book.resolve(contact)
    if resolved is None:
        options = book.candidates(contact)
        if options:
            return ToolResult.blocked(
                f"{contact!r} matches more than one contact: "
                f"{', '.join(options)}. Which one?")
        known = ", ".join(c.name for c in book.all()) or "none saved yet"
        return ToolResult.blocked(
            f"no contact named {contact!r}, and it is not a phone number with "
            f"a country code. Known contacts: {known}")

    phone = resolved.number
    url = f"https://wa.me/{phone}?text={quote_plus(message)}"
    # No shell. `start "" "<url>"` via shell=True let an LLM-supplied url close
    # the quote and append `& <command>`; webbrowser.open hands the string to
    # ShellExecute/xdg-open directly, so there is no command line to break out of.
    webbrowser.open(url)
    # Lead with the NAME. The user hears this sentence, and a read-back number
    # is unverifiable by ear — the name is their last chance to catch a
    # resolution that went to the wrong person.
    who = resolved.name if resolved.name != contact.strip() else f"+{phone}"
    return ToolResult.success(f"opened WhatsApp chat with {who} (+{phone})")


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.DESTRUCTIVE)  # tier: external email, irreversible
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
    webbrowser.open(url)  # no shell — see send_whatsapp
    return ToolResult.success(f"opened email composer for {to}")
