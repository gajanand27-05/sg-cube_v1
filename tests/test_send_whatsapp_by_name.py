"""send_whatsapp must accept a NAME, and must refuse an ambiguous one.

The reported failure: "Open whatsapp and send hi to sharath" transcribed
perfectly, then asked for a phone number, because `contact` had to be digits.

What matters more than making names work is what happens when the name is
unclear. This tool is DESTRUCTIVE tier and opens a real chat with a real
person; resolving "sharath" to whichever of two contacts sorts first would be
a silent, irreversible mistake. Every refusal below asserts that no browser
was opened — a blocked ToolResult that still launched the chat would be the
worst of both worlds.
"""
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core import contacts as contacts_mod
from backend.core.tools import comms


@pytest.fixture
def opened(tmp_path, monkeypatch):
    """Isolated contact book + a recording stand-in for webbrowser.open."""
    book = contacts_mod.ContactBook(tmp_path / "contacts.json")
    monkeypatch.setattr(contacts_mod, "book", book)
    urls: list[str] = []
    monkeypatch.setattr(comms.webbrowser, "open", lambda u: urls.append(u))
    return book, urls


def test_a_raw_number_still_works(opened):
    """The pre-existing contract. Names are additive, not a replacement."""
    _, urls = opened
    res = comms.send_whatsapp("+919876543210", "hi")
    assert res.status == "success"
    assert "wa.me/919876543210" in urls[0]


def test_a_known_name_resolves_and_sends(opened):
    book, urls = opened
    book.add("Sharath", "+919876543210")

    res = comms.send_whatsapp("sharath", "hi")
    assert res.status == "success"
    assert "wa.me/919876543210" in urls[0]
    assert "hi" in urls[0]


def test_the_result_names_who_it_went_to(opened):
    """The user hears this sentence. "opened WhatsApp chat with +9198..." is
    unverifiable by ear — the NAME is what tells them it went to the right
    person, and it is their last chance to catch a bad resolution."""
    book, _ = opened
    book.add("Sharath Kumar", "+919876543210")
    res = comms.send_whatsapp("sharath", "hi")
    assert "Sharath Kumar" in res.message


def test_a_mangled_name_still_reaches_the_right_person(opened):
    """STT heard "sherat" for "Sharath"; one contact, so no ambiguity."""
    book, urls = opened
    book.add("Sharath", "+919876543210")
    assert comms.send_whatsapp("sherat", "hi").status == "success"
    assert "wa.me/919876543210" in urls[0]


def test_an_ambiguous_name_refuses_and_opens_nothing(opened):
    book, urls = opened
    book.add("Sharath Kumar", "+919876543210")
    book.add("Sharath Iyer", "+919111111111")

    res = comms.send_whatsapp("sharath", "hi")
    assert res.status == "blocked"
    assert urls == [], "an ambiguous name opened a chat anyway"
    # The candidates have to be in the reply, or the user cannot answer.
    assert "Sharath Kumar" in res.reason and "Sharath Iyer" in res.reason


def test_an_unknown_name_refuses_and_opens_nothing(opened):
    book, urls = opened
    book.add("Sharath", "+919876543210")

    res = comms.send_whatsapp("priya", "hi")
    assert res.status == "blocked"
    assert urls == []
    assert "priya" in res.reason.lower()


def test_an_empty_book_does_not_send_to_a_name(opened):
    _, urls = opened
    assert comms.send_whatsapp("sharath", "hi").status == "blocked"
    assert urls == []


def test_an_empty_message_is_still_refused(opened):
    """Pre-existing guard; name resolution must not slip past it."""
    book, urls = opened
    book.add("Sharath", "+919876543210")
    assert comms.send_whatsapp("sharath", "   ").status == "blocked"
    assert urls == []
