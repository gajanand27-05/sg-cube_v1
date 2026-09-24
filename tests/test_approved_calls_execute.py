"""The legacy SecurityLevel sandbox answered every CAUTION tool with "say
'confirm 1234' or click OK" — which nothing in production can answer — even
for calls the Guardian had already approved and the user had said yes to. So
write_file, edit_file, delete_file, add_contact, send_whatsapp, ... never ran.
Measured 2026-09-24 before the fix: a confirmed write_file wrote nothing."""
import asyncio
import types

import pytest

import backend.core.tools  # noqa: F401
from backend.core import chrome_tabs
from backend.core.agents.operator import OperatorAgent
from backend.core.tools import files, registry


def test_a_guardian_approved_caution_tool_actually_runs(tmp_path):
    target = tmp_path / "out.txt"
    res = asyncio.run(OperatorAgent().execute_batch(
        [{"name": "write_file", "args": {"path": str(target), "content": "hello"}}], "t"))
    assert res[0]["result"]["status"] == "success", res
    assert target.read_text() == "hello"


def test_an_unapproved_caller_is_still_gated(tmp_path):
    """Plugins, capabilities and the fast path have no Guardian in front of
    them; for those the sandbox is the only gate and must stay."""
    target = tmp_path / "out.txt"
    r = asyncio.run(registry.call("write_file", {"path": str(target), "content": "x"}))
    assert r.status == "pending_confirmation"
    assert not target.exists()


# ── delete_file ─────────────────────────────────────────────────────────

def test_delete_goes_to_the_recycle_bin_not_os_remove(tmp_path, monkeypatch):
    f = tmp_path / "old.txt"; f.write_text("x")
    binned = []
    monkeypatch.setattr(files, "_to_recycle_bin", lambda p: (binned.append(p), p.unlink()))
    r = registry.REGISTRY["delete_file"].func(str(f))
    assert r.status == "success" and "Recycle Bin" in r.message
    assert binned == [f.resolve()]


def test_an_ambiguous_name_deletes_nothing_and_lists_the_matches(tmp_path, monkeypatch):
    for n in ("report-a.txt", "report-b.txt"):
        (tmp_path / n).write_text("x")
    monkeypatch.setattr(files, "SEARCH_ROOTS", [tmp_path])
    monkeypatch.setattr(files, "_to_recycle_bin",
                        lambda p: pytest.fail("deleted despite an ambiguous name"))
    r = registry.REGISTRY["delete_file"].func("report")
    assert r.status == "blocked"
    assert str(tmp_path / "report-a.txt") in r.reason and str(tmp_path / "report-b.txt") in r.reason


# ── close_chrome_tab bound to the titles the user confirmed ─────────────

def _tabs(monkeypatch, titles):
    monkeypatch.setattr(chrome_tabs, "available", lambda: True)
    monkeypatch.setattr(chrome_tabs, "list_tabs",
                        lambda: [types.SimpleNamespace(title=t) for t in titles])


def test_tabs_changed_since_confirmation_closes_nothing(monkeypatch):
    _tabs(monkeypatch, ["Lofi - YouTube", "Talk - YouTube", "Gmail"])
    monkeypatch.setattr(chrome_tabs, "close_matching",
                        lambda q: pytest.fail("closed tabs the user never saw"))
    r = registry.REGISTRY["close_chrome_tab"].func("youtube", only_if_titles=["Lofi - YouTube"])
    assert r.status == "blocked" and "changed since you confirmed" in r.reason


def test_unchanged_tabs_close(monkeypatch):
    _tabs(monkeypatch, ["Lofi - YouTube", "Gmail"])
    monkeypatch.setattr(chrome_tabs, "close_matching", lambda q: ["Lofi - YouTube"])
    r = registry.REGISTRY["close_chrome_tab"].func("youtube", only_if_titles=["Lofi - YouTube"])
    assert r.status == "success"
