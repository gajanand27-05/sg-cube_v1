"""The file tools may only touch the user's own folders.

No quote/shell-metacharacter rule: no file tool hands a path to a shell
(open_folder / open_notes_today use argument lists / ShellExecute), and the
rule refused legal names like "Mom's notes.txt".

The verifier's shell-injection check stopped looking at paths (9ad8a13: its
backslash rule made every Windows path "malicious"), which also removed the
only thing refusing UNC and device paths — by accident. check_user_path is
the real path policy, shared by write_file / edit_file / insert_lines /
read_file / delete_file.
"""
import subprocess

import pytest

import backend.core.tools  # noqa: F401
from backend.core.tools import files
from backend.core.tools.files import PathRefused, check_user_path
from backend.core.tools.registry import REGISTRY


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "Documents"
    r.mkdir()
    monkeypatch.setattr(files, "SEARCH_ROOTS", [r])
    return r


def test_a_plain_path_inside_the_user_folders_is_accepted(root):
    assert check_user_path(str(root / "notes.txt")) == (root / "notes.txt").resolve()


def test_nested_dotdot_that_stays_inside_is_accepted(root):
    (root / "a").mkdir()
    assert check_user_path(str(root / "a" / ".." / "b.txt")) == (root / "b.txt").resolve()


@pytest.mark.parametrize("make, why", [
    (lambda r: str(r / ".." / ".." / "evil.bat"), "outside your user folders"),       # .. traversal
    (lambda r: r"C:\Windows\System32\drivers\etc\hosts", "outside your user folders"),
    (lambda r: r"\\fileserver\share\report.docx", "UNC"),                             # UNC
    (lambda r: "//fileserver/share/report.docx", "UNC"),
    (lambda r: "\\\\?\\" + str(r / "notes.txt"), "UNC"),                              # \\?\ device path
    (lambda r: "\\\\.\\PhysicalDrive0", "UNC"),                                       # \\.\ device
    (lambda r: str(r / "notes.txt:hidden"), "stream"),                                # ADS
    (lambda r: str(r / "a") + "\x00b.txt", "control characters"),
    (lambda r: str(r / "CON.txt"), "reserved"),                                       # device name
])
def test_refused(root, make, why):
    with pytest.raises(PathRefused, match=why):
        check_user_path(make(root))


def test_a_junction_pointing_outside_is_refused(root, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "escape"), str(outside)],
                   check=True, capture_output=True)
    with pytest.raises(PathRefused, match="outside"):
        check_user_path(str(root / "escape" / "payload.txt"))


@pytest.mark.parametrize("tool,args", [
    ("write_file", {"path": r"\\fileserver\share\x.txt", "content": "x"}),
    ("edit_file", {"path": r"C:\Windows\win.ini", "old_text": "a", "new_text": "b"}),
    ("insert_lines", {"path": "\\\\?\\C:\\x.txt", "line_number": 0, "text": "x"}),
    ("read_file", {"path": r"C:\Users\Public\..\..\Windows\win.ini"}),
    ("delete_file", {"file": r"C:\Windows\win.ini"}),
])
def test_every_file_tool_enforces_it(root, tool, args):
    r = REGISTRY[tool].func(**args)
    status = r.status if hasattr(r, "status") else r["status"]
    assert status == "blocked", r


def test_writes_inside_still_work(root):
    r = REGISTRY["write_file"].func(path=str(root / "ok.txt"), content="fine")
    assert r.status == "success" and (root / "ok.txt").read_text() == "fine"


@pytest.mark.parametrize("name", ["Mom's notes.txt", "a & b.txt", "50% off.pdf",
                                  "report (final) [v2].docx", "cost $5; paid.txt"])
def test_legal_names_with_quotes_and_symbols_work(root, name):
    """Windows allows these; refusing them was a shell rule with no shell."""
    r = REGISTRY["write_file"].func(path=str(root / name), content="ok")
    assert r.status == "success", r
    assert (root / name).read_text() == "ok"


# ── EXTRA_ALLOWED_ROOTS ─────────────────────────────────────────────────

def test_extra_roots_default_to_empty():
    from backend.server.config import Settings
    assert Settings(_env_file=None).extra_allowed_roots == ""


def test_an_extra_root_is_allowed(root, tmp_path, monkeypatch):
    from backend.server.config import settings
    extra = tmp_path / "Projects"
    extra.mkdir()
    with pytest.raises(PathRefused):
        check_user_path(str(extra / "a.txt"))
    monkeypatch.setattr(settings, "extra_allowed_roots", f"{extra};")
    assert check_user_path(str(extra / "a.txt")) == (extra / "a.txt").resolve()


@pytest.mark.parametrize("entry", [r"\\fileserver\share", "\\\\?\\C:\\", r"relative\dir"])
def test_network_device_and_relative_extra_roots_are_ignored(root, monkeypatch, entry, caplog):
    from backend.server.config import settings
    monkeypatch.setattr(settings, "extra_allowed_roots", entry)
    assert files.allowed_roots() == files.SEARCH_ROOTS
    assert "ignored" in caplog.text


def test_no_tool_can_change_the_allowed_roots():
    """Config / HUD only, never voice: no registered tool takes a parameter
    that could write the setting."""
    offenders = [n for n, t in REGISTRY.items()
                 if "extra_allowed_roots" in str(t.schema).lower() or "allowed_root" in n]
    assert offenders == []


# ── checks that approval does not skip ──────────────────────────────────

def test_path_guard_runs_on_an_approved_call(root):
    import asyncio
    r = asyncio.run(files_registry_call("write_file",
                                        {"path": r"C:\Windows\evil.txt", "content": "x"}))
    assert r.status == "blocked" and "outside your user folders" in r.reason


def test_injection_check_runs_on_an_approved_call():
    """Harmless payload on purpose: if this check ever breaks, what runs is
    two echoes."""
    import asyncio
    r = asyncio.run(files_registry_call("run_command", {"command": "echo hi & echo there"}))
    assert r.status == "blocked" and "injection" in r.reason.lower()


async def files_registry_call(name, args):
    from backend.core.tools import registry
    return await registry.call(name, args, approved=True)


# ── no file tool reaches a shell ────────────────────────────────────────

def test_open_folder_uses_an_argument_list_without_a_shell(root, monkeypatch):
    seen = {}
    monkeypatch.setattr(files.subprocess, "Popen",
                        lambda args, shell=False, **k: seen.update(args=args, shell=shell))
    (root / "Mom's stuff").mkdir()
    r = REGISTRY["open_folder"].func(str(root / "Mom's stuff"))
    assert r["status"] == "success"
    assert seen == {"args": ["explorer", str(root / "Mom's stuff")], "shell": False}


def test_open_notes_today_uses_shellexecute_not_cmd(monkeypatch, tmp_path):
    from backend.core.tools import notes
    opened = []
    monkeypatch.setattr(notes, "NOTES_DIR", tmp_path)
    monkeypatch.setattr(notes.os, "startfile", opened.append, raising=False)
    assert REGISTRY["open_notes_today"].func()["status"] == "success"
    assert len(opened) == 1 and opened[0].endswith(".md")
