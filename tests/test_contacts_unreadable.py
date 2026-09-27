"""An unreadable contacts file is an error, never an empty book.

It used to load as empty, and the next add_contact saved a one-entry book
over every saved number while saying "Saved X". Now reads and writes refuse
(after one retry), nothing is written, and each save keeps the previous file
as contacts.json.bak.
"""
import json

import pytest

from backend.core import contacts as store
from backend.core.tools.registry import REGISTRY

GOOD = {"contacts": [{"name": "Sharath", "number": "919876543210"},
                     {"name": "Asha", "number": "919812345678"}]}


def _book(tmp_path, content):
    path = tmp_path / "contacts.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    return store.ContactBook(path), path


@pytest.mark.parametrize("content", ['{"contacts": [{"name": "Shar', "not json", "[1, 2]",
                                     '{"contacts": "oops"}'])
def test_a_corrupt_file_refuses_to_save_and_is_left_untouched(tmp_path, content):
    book, path = _book(tmp_path, content)
    with pytest.raises(store.ContactsUnreadable):
        book.add("Ravi", "+919900112233")
    with pytest.raises(store.ContactsUnreadable):
        book.delete("Sharath")
    with pytest.raises(store.ContactsUnreadable):
        book.resolve("Sharath")
    assert path.read_text(encoding="utf-8") == content


def test_a_missing_file_is_an_empty_book(tmp_path):
    book, path = _book(tmp_path, None)
    assert book.all() == []
    book.add("Ravi", "+919900112233")
    assert json.loads(path.read_text())["contacts"] == [{"name": "Ravi", "number": "919900112233"}]


def test_a_briefly_unreadable_file_is_retried(tmp_path, monkeypatch):
    book, path = _book(tmp_path, json.dumps(GOOD))
    real = type(path).read_text
    calls = {"n": 0}

    def flaky(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("locked by antivirus")
        return real(self, *a, **k)
    monkeypatch.setattr(type(path), "read_text", flaky)
    book._load()  # first read fails
    assert book.resolve("Sharath").number == "919876543210"  # the retry succeeds


def test_save_keeps_one_backup_of_the_previous_file(tmp_path):
    book, path = _book(tmp_path, json.dumps(GOOD))
    book.add("Ravi", "+919900112233")
    assert json.loads(path.with_suffix(".json.bak").read_text()) == GOOD
    book.add("Meena", "+919911223344")
    backup = json.loads(path.with_suffix(".json.bak").read_text())
    assert [c["name"] for c in backup["contacts"]] == ["Sharath", "Asha", "Ravi"]
    assert not path.with_suffix(".json.tmp").exists()


def test_the_tools_say_so_instead_of_saved(tmp_path, monkeypatch):
    book, path = _book(tmp_path, "not json")
    monkeypatch.setattr(store, "book", book)
    for name, args in [("add_contact", ("Ravi", "+919900112233")), ("delete_contact", ("Asha",)),
                       ("list_contacts", ()), ("find_contact", ("Asha",)),
                       ("send_whatsapp", ("Asha", "hi"))]:
        res = REGISTRY[name].func(*args)
        assert res.status == "error", (name, res)
        assert "could not be read" in res.reason
    assert path.read_text() == "not json"
