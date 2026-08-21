"""Saved contacts — the name->number map send_whatsapp resolves against.

Named contact_book.py rather than contacts.py so the tool module and
backend/core/contacts.py (the store) stay distinguishable in tracebacks and
imports; a shadowed name has silently killed publishers in this codebase
before.

Tiering follows the reversibility rule: adding is a write you can undo by
deleting, deleting loses data you would have to re-enter, and listing changes
nothing.
"""
# The MODULE, not `book` itself. `from ... import book` binds the singleton at
# import time, so anything that swaps the module attribute — notably the
# conftest fixture that keeps the suite out of the user's real contacts file —
# would be ignored here and these tools would write real phone numbers during
# a test run. Same shape as the ledger trap documented in tests/conftest.py.
from backend.core import contacts as _contacts
from backend.core.contacts import looks_like_a_number
from backend.core.tools.registry import CapabilityTier, SecurityLevel, ToolResult, tool


@tool(tier=CapabilityTier.READONLY)  # tier: reads a local file, no side effects
def list_contacts() -> ToolResult:
    """List every saved contact and their phone number. Use for "who do I
    have saved", "list my contacts", or before sending a message when you are
    unsure a name is saved."""
    people = _contacts.book.all()
    if not people:
        return ToolResult.success(
            "No contacts saved yet. Add one with add_contact, for example "
            "add_contact('Sharath', '+919876543210').")
    listing = ", ".join(f"{c.name} (+{c.number})" for c in people)
    return ToolResult.success(f"{len(people)} contact(s): {listing}")


@tool(tier=CapabilityTier.READONLY)  # tier: reads a local file, no side effects
def find_contact(name: str) -> ToolResult:
    """Look up one saved contact by name and return their number. Returns the
    possible matches instead of guessing when the name is ambiguous. Use this
    to check a name before sending a message."""
    match = _contacts.book.resolve(name)
    if match is not None:
        return ToolResult.success(f"{match.name}: +{match.number}")
    options = _contacts.book.candidates(name)
    if options:
        return ToolResult.blocked(
            f"{name!r} matches more than one contact: {', '.join(options)}. "
            f"Which one?")
    return ToolResult.blocked(f"no contact named {name!r}")


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.SYSTEM_WRITE)  # tier: writes a local file, undone by delete_contact
def add_contact(name: str, phone: str) -> ToolResult:
    """Save a phone number under a name so it can be messaged by name later.
    `phone` must include the country code (e.g. "+919876543210"). Saving a
    name that already exists replaces its number."""
    if not looks_like_a_number(phone):
        return ToolResult.blocked(
            f"{phone!r} is not a phone number with a country code — "
            f"say it like plus nine one, then the ten digits")
    existing = any(c.name.lower() == (name or "").strip().lower()
                   for c in _contacts.book.all())
    try:
        saved = _contacts.book.add(name, phone)
    except ValueError as e:
        return ToolResult.blocked(str(e))
    verb = "Updated" if existing else "Saved"
    return ToolResult.success(f"{verb} {saved.name} as +{saved.number}")


@tool(security=SecurityLevel.CAUTION, tier=CapabilityTier.DESTRUCTIVE)  # tier: loses a number the user would have to re-enter
def delete_contact(name: str) -> ToolResult:
    """Remove a saved contact by name. The name must match exactly — this
    does NOT fuzzy-match, so a mis-heard name cannot delete the wrong
    person."""
    if _contacts.book.delete(name):
        return ToolResult.success(f"Deleted contact {name}")
    return ToolResult.blocked(f"no contact named {name!r} to delete")
