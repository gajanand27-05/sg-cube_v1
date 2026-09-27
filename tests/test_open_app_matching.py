"""open_app resolves a spoken name to an INSTALLED app, or says it can't.

2026-09-26: "open vscode" matched nothing in the Start menu ("Visual Studio
Code"), fell through to `start "" "vscode"`, and reported "opened vscode"
while Windows showed "Windows cannot find 'vscode'". There is no such
fallback any more: Start-menu apps, then App Paths, then "I couldn't find".

Fake app lists and a fake Popen: nothing is launched and no real app list is
read.
"""
import pytest

from backend.core.orchestrator.llm_layer import Intent
from backend.core.safe_executor import command_whitelist as cw

APPS = ["Visual Studio Code", "Notepad", "Google Chrome", "WhatsApp", "Calculator",
        "Barcode Scanner", "Adobe Acrobat (64-bit)", "File Explorer", "Settings"]


@pytest.mark.parametrize("query,expected", [
    ("vscode", "Visual Studio Code"),
    ("vs code", "Visual Studio Code"),
    ("code", "Visual Studio Code"),          # a word of the name, not "Barcode"
    ("notpad", "Notepad"),                   # close spelling
    ("whats app", "WhatsApp"),
    ("calc", "Calculator"),
    ("google chrome browser", "Google Chrome"),
    ("Adobe Acrobat [64-bit]", "Adobe Acrobat (64-bit)"),
    ("adobe acrobat", "Adobe Acrobat (64-bit)"),
])
def test_names_people_actually_say(query, expected):
    assert cw._match_app(query, APPS) == expected


def test_a_bracketed_request_matches_a_plain_start_menu_name():
    assert cw._match_app("Adobe Acrobat [64-bit]", ["Adobe Acrobat", "Acrobat Distiller"]) == "Adobe Acrobat"


@pytest.mark.parametrize("query", ["my models", "zzqx", "a", ""])
def test_no_plausible_match_is_none(query):
    assert cw._match_app(query, APPS) is None


@pytest.fixture
def launches(monkeypatch):
    calls = []

    def fake_popen(args, **kw):
        calls.append((args, kw))
        return None
    monkeypatch.setattr(cw.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(cw, "_apps_cache", [(n, f"id.{i}") for i, n in enumerate(APPS)])
    monkeypatch.setattr(cw, "refresh_apps_cache", lambda: None)
    monkeypatch.setattr(cw, "_app_paths", lambda: {"winword": r"C:\Office\WINWORD.EXE"})
    # By default the launched app shows up as a new process named like it.
    monkeypatch.setattr(cw, "_procs_started_since", lambda since: ["Code.exe", "WINWORD.EXE"])
    monkeypatch.setattr(cw, "_APP_APPEAR_S", 0.3)
    return calls


def _open(name):
    return cw.handle_open_app(Intent(action="open_app", target=name))


def test_a_start_menu_app_opens_through_its_app_id(launches):
    res = _open("vscode")
    assert res == {"status": "success", "message": "opened Visual Studio Code"}
    assert launches == [(["explorer.exe", "shell:AppsFolder\\id.0"], {})]


def test_app_paths_is_the_second_source(launches):
    res = _open("winword")
    assert res["status"] == "success"
    assert launches == [([r"C:\Office\WINWORD.EXE"], {})]


def test_nothing_found_says_so_and_launches_nothing(launches):
    res = _open("my models")
    assert res == {"status": "error", "reason": "I couldn't find my models"}
    assert launches == []


@pytest.mark.parametrize("target", [
    r"C:\Windows\Temp\x.exe", "C:/tools/run.exe", r"\\server\share\app.exe",
    "setup.bat", "payload.ps1", "installer.msi", "notepad.exe",
])
def test_paths_and_file_names_are_refused(launches, target):
    res = _open(target)
    assert res["status"] == "blocked"
    assert launches == []


# ── did the app actually appear? ─────────────────────────────────────────

def test_an_app_that_never_appears_is_reported(launches, monkeypatch):
    monkeypatch.setattr(cw, "_procs_started_since", lambda since: ["svchost.exe"])
    res = _open("notepad")
    assert res == {"status": "error", "reason": "I tried to open Notepad, but it didn't appear"}


def test_an_already_running_app_brought_to_the_front_counts(launches, monkeypatch):
    from backend.core.tools import files
    monkeypatch.setattr(cw, "_procs_started_since", lambda since: [])
    monkeypatch.setattr(files, "foreground_window", lambda: {
        "hwnd": 5, "pid": 5, "title": "notes.txt - Notepad", "process": "notepad.exe", "class": "Notepad"})
    assert _open("notepad")["status"] == "success"


@pytest.mark.parametrize("app,process", [
    ("Microsoft Edge", "msedge.exe"), ("Calculator", "CalculatorApp.exe"),
    ("Settings", "SystemSettings.exe"), ("WhatsApp", "WhatsApp.Root.exe"),
    ("Visual Studio Code", "Code.exe"),
])
def test_process_names_that_differ_from_the_app_name(monkeypatch, app, process):
    monkeypatch.setattr(cw, "_procs_started_since", lambda since: [process])
    assert cw._app_seen(app, 0.0)
