"""minimize_all never toggles windows back, and counts what it minimized.

It pressed Win+D, a toggle: with the desktop already showing, every window
came back and it still said "showed desktop". Windows are faked here —
nothing is minimized.
"""
import pytest

from backend.core.tools import windowing as w
from backend.core.tools.registry import REGISTRY

NOTEPAD = {"hwnd": 1, "title": "notes - Notepad", "app": "notepad.exe", "minimized": False}
CODE = {"hwnd": 2, "title": "x.py - Visual Studio Code", "app": "Code.exe", "minimized": False}


@pytest.fixture
def desktop(monkeypatch):
    state = {"frames": [], "minimize_calls": 0}

    def windows():
        return state["frames"].pop(0) if len(state["frames"]) > 1 else state["frames"][0]

    def minimize():
        state["minimize_calls"] += 1

    monkeypatch.setattr(w, "_open_app_windows", windows)
    monkeypatch.setattr(w, "_minimize_all_windows", minimize)
    return state


def _run():
    return REGISTRY["minimize_all"].func()


def test_desktop_already_showing_does_nothing(desktop):
    desktop["frames"] = [[]]
    res = _run()
    assert res.status == "success" and "already showing" in res.message
    assert desktop["minimize_calls"] == 0


def test_everything_minimized_is_counted(desktop):
    desktop["frames"] = [[NOTEPAD, CODE], []]
    res = _run()
    assert res.message == "minimized 2 window(s)" and desktop["minimize_calls"] == 1


def test_a_window_that_stays_open_is_named(desktop):
    desktop["frames"] = [[NOTEPAD, CODE], [CODE]]
    res = _run()
    assert res.status == "success" and "still open: Code.exe" in res.message


def test_nothing_minimized_is_an_error(desktop):
    desktop["frames"] = [[NOTEPAD, CODE], [NOTEPAD, CODE]]
    assert _run().status == "error"
