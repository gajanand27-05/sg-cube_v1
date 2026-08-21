"""Name -> phone number resolution, and its refusal to guess.

"Open whatsapp and send hi to sherat" was transcribed perfectly and still
failed: send_whatsapp requires a phone number with country code and nothing
in the system maps a name to one, so the assistant asked for the number.
Correct behaviour, useless outcome.

The whole risk of fixing it lives in one decision — what to do when the name
is not an exact match. Speech recognition mangles names constantly ("sherat"
for "Sharat"), so exact-only matching would make this useless; but messaging
the WRONG person is irreversible, and an assistant that silently picks the
closest name will eventually send something private to the wrong contact.

So the rule is: resolve only when there is exactly ONE plausible candidate,
at the most precise tier that matches. Any ambiguity returns the candidates
instead of a winner, so the caller can ask. Refusing is cheap; a message sent
to the wrong person cannot be recalled.
"""
import json
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from backend.core import contacts as contacts_mod


@pytest.fixture
def book(tmp_path, monkeypatch):
    """A ContactBook on a throwaway file — never the user's real one."""
    path = tmp_path / "contacts.json"
    b = contacts_mod.ContactBook(path)
    monkeypatch.setattr(contacts_mod, "book", b)
    return b


# ── storing ──────────────────────────────────────────────────────────────

def test_add_then_resolve_exactly(book):
    book.add("Sharat", "+919876543210")
    assert book.resolve("Sharat").number == "919876543210"


def test_name_matching_ignores_case_and_spacing(book):
    book.add("Sharat Kumar", "+919876543210")
    for spoken in ("sharat kumar", "SHARAT KUMAR", "  Sharat   Kumar "):
        assert book.resolve(spoken).number == "919876543210", spoken


def test_a_number_must_look_like_a_number(book):
    """send_whatsapp builds a wa.me URL from this; garbage in means a dead
    link and a confusing failure two layers away."""
    with pytest.raises(ValueError):
        book.add("Nobody", "not-a-phone")
    with pytest.raises(ValueError):
        book.add("Nobody", "12345")          # too short to be a real number


def test_adding_the_same_name_twice_updates_it(book):
    book.add("Sharat", "+919876543210")
    book.add("Sharat", "+919999999999")
    assert book.resolve("Sharat").number == "919999999999"
    assert len(book.all()) == 1


def test_contacts_survive_a_reload(book, tmp_path):
    book.add("Sharat", "+919876543210")
    reopened = contacts_mod.ContactBook(tmp_path / "contacts.json")
    assert reopened.resolve("Sharat").number == "919876543210"


def test_delete_removes_it(book):
    book.add("Sharat", "+919876543210")
    assert book.delete("sharat") is True
    assert book.resolve("Sharat") is None
    assert book.delete("sharat") is False


# ── resolving: the part that must not guess ──────────────────────────────

def test_a_unique_first_name_resolves(book):
    """Nobody says the surname out loud."""
    book.add("Sharat Kumar", "+919876543210")
    assert book.resolve("Sharat").number == "919876543210"


def test_an_ambiguous_first_name_refuses_and_names_the_candidates(book):
    """Two Sharats. Picking either is a coin flip with an irreversible
    outcome, so it must return neither."""
    book.add("Sharat Kumar", "+919876543210")
    book.add("Sharat Iyer", "+919111111111")

    result = book.resolve("Sharat")
    assert result is None
    assert sorted(book.candidates("Sharat")) == ["Sharat Iyer", "Sharat Kumar"]


def test_a_mangled_name_still_resolves_when_unambiguous(book):
    """The reported case: STT heard "sherat" for "Sharat"."""
    book.add("Sharat", "+919876543210")
    assert book.resolve("sherat").number == "919876543210"


def test_a_mangled_name_refuses_when_two_contacts_are_close(book):
    """Fuzzy matching is what makes this usable and what makes it dangerous.
    With two similar names the transcript cannot distinguish them, so it must
    not choose."""
    book.add("Sharat", "+919876543210")
    book.add("Sherat", "+919111111111")
    assert book.resolve("sherath") is None


def test_an_exact_match_beats_a_fuzzy_one(book):
    """With both present, the exact name must win outright rather than being
    treated as two candidates."""
    book.add("Sharat", "+919876543210")
    book.add("Sharath", "+919111111111")
    assert book.resolve("Sharat").number == "919876543210"
    assert book.resolve("Sharath").number == "919111111111"


def test_an_unrelated_name_does_not_resolve_to_anyone(book):
    """The failure that matters most: a name with no contact must return
    nothing, not the least-bad match."""
    book.add("Sharat", "+919876543210")
    assert book.resolve("Priya") is None
    assert book.resolve("") is None


def test_a_raw_number_passes_straight_through(book):
    """Saying the digits must keep working with an empty contact book."""
    assert book.resolve("+91 98765 43210").number == "919876543210"


def test_an_empty_book_resolves_nothing(book):
    assert book.resolve("Sharat") is None
    assert book.all() == []


def test_the_file_is_valid_json_a_human_can_edit(book, tmp_path):
    """Same reasoning as the dogfooding ledger: eyeball-able beats clever."""
    book.add("Sharat", "+919876543210")
    data = json.loads((tmp_path / "contacts.json").read_text(encoding="utf-8"))
    assert data["contacts"][0]["name"] == "Sharat"


def test_a_corrupt_file_does_not_crash_startup(tmp_path):
    """A half-written file must degrade to an empty book, not take down every
    turn that touches contacts."""
    path = tmp_path / "contacts.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert contacts_mod.ContactBook(path).all() == []


def test_the_tool_layer_uses_the_isolated_book_not_the_real_file():
    """Guards the conftest isolation, which is what keeps the suite out of the
    user's real phone numbers.

    `from backend.core.contacts import book` at module scope would bind the
    production singleton at import time and ignore the fixture entirely — the
    tools would then add and delete real contacts during a test run. Asserting
    the tool writes where the fixture points is the only way to notice.
    """
    from backend.core import contacts as contacts_mod
    from backend.core.tools import contact_book as tools

    real_path = contacts_mod._CONTACTS_PATH
    tools.add_contact("Isolation Probe", "+919876500000")
    try:
        assert contacts_mod.book._path != real_path, (
            "the tool layer is pointed at the production contacts file")
        assert any(c.name == "Isolation Probe" for c in contacts_mod.book.all())
        assert not real_path.exists() or "Isolation Probe" not in \
            real_path.read_text(encoding="utf-8"), \
            "a test wrote into the user's real contacts file"
    finally:
        tools.delete_contact("Isolation Probe")
