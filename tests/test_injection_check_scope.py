"""The shell-injection check applied to every argument of every tool, so a
backslash made every Windows path an "injection": write_file / edit_file /
insert_lines / delete_file were refused for any real path (found live
2026-09-25), and JSON content was refused for its braces. It now applies only
to tools whose arguments can be executed."""
import asyncio

import pytest

import backend.core.tools  # noqa: F401
from backend.core.agent import verifier


@pytest.fixture(autouse=True)
def _phi3_passes(monkeypatch):
    async def ok(*a, **k):
        return True
    monkeypatch.setattr(verifier, "_secondary_check", ok)


def _verify(name, args):
    return asyncio.run(verifier.verify("", {"name": name, "args": args, "confidence": 1.0}))


def test_a_windows_path_is_not_an_injection():
    r = _verify("write_file", {"path": r"C:\Users\me\Documents\notes.txt", "content": "hi"})
    assert r.is_valid, r.error


def test_json_content_is_not_an_injection():
    r = _verify("write_file", {"path": "cfg.json", "content": '{"a": [1, 2], "b": "$HOME"}'})
    assert r.is_valid, r.error


@pytest.mark.parametrize("name,args", [
    ("run_command", {"command": "dir & del /q C:\\x"}),
    ("open_app", {"name": "calc & del x"}),
])
def test_tools_that_execute_their_arguments_are_still_checked(name, args):
    r = _verify(name, args)
    assert not r.is_valid
