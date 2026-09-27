"""send_whatsapp and send_email open DRAFTS, and only say so when they did.

Both ignored webbrowser.open's result, and send_email claimed "opened email
composer" on a PC with no mail app for mailto: — Windows shows a "pick an
app" box instead (this laptop has none, measured 2026-09-27). Nothing is
opened here: webbrowser.open and the mailto lookup are faked.
"""
import pytest

from backend.core import contacts as store
from backend.core.tools import comms
from backend.core.tools.registry import REGISTRY


@pytest.fixture
def opened(monkeypatch, tmp_path):
    urls = []
    monkeypatch.setattr(comms.webbrowser, "open", lambda u: urls.append(u) or True)
    monkeypatch.setattr(comms, "_mailto_handler", lambda: True)
    book = store.ContactBook(tmp_path / "contacts.json")
    book.add("Asha", "+919812345678")
    monkeypatch.setattr(store, "book", book)
    return urls


def test_whatsapp_says_draft_not_sent(opened):
    res = REGISTRY["send_whatsapp"].func("Asha", "hi")
    assert res.status == "success"
    assert "draft" in res.message and "isn't sent" in res.message
    assert "sent to" not in res.message.lower()


def test_whatsapp_link_not_taken_is_an_error(opened, monkeypatch):
    monkeypatch.setattr(comms.webbrowser, "open", lambda u: False)
    assert REGISTRY["send_whatsapp"].func("Asha", "hi").status == "error"


def test_email_says_draft_not_sent(opened):
    res = REGISTRY["send_email"].func("a@example.com", "Hi", "Body")
    assert res.status == "success"
    assert "email draft" in res.message and "isn't sent" in res.message
    assert opened == ["mailto:a@example.com?subject=Hi&body=Body"]


def test_email_with_no_mail_app_says_so_and_opens_nothing(opened, monkeypatch):
    monkeypatch.setattr(comms, "_mailto_handler", lambda: False)
    res = REGISTRY["send_email"].func("a@example.com", "Hi")
    assert res.status == "blocked" and "no email app" in res.reason
    assert opened == []


def test_email_link_not_taken_is_an_error(opened, monkeypatch):
    monkeypatch.setattr(comms.webbrowser, "open", lambda u: False)
    assert REGISTRY["send_email"].func("a@example.com").status == "error"
