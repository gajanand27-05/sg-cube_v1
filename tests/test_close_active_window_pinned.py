"""close_active_window closes the window that was checked, and says whether
it actually went.

It pressed Alt+F4, which lands on whatever has focus when it runs — after a
HUD "yes" that can be the HUD — and it said "closed" even when a "Save
changes?" prompt kept the window open. Every window here is fake (the
conftest fake foreground window plus faked Win32 calls); nothing is closed.
"""
import pytest

from backend.core.agent import tool_policy
from backend.core.tools import files
from backend.core.tools import windowing as w
from backend.core.tools.registry import REGISTRY

NOTEPAD = {"hwnd": 4242, "pid": 77, "title": "*notes.txt - Notepad", "process": "notepad.exe",
           "class": "Notepad"}
HUD = {"hwnd": 9999, "pid": 88, "title": "SG-CUBE", "process": "chrome.exe", "class": "Chrome"}


@pytest.fixture
def desktop(monkeypatch):
    state = {"alive": {4242: True, 9999: True}, "closes_on_request": True, "popup": False,
             "posted": [], "pid": {4242: 77, 9999: 88}}

    def post(hwnd):
        state["posted"].append(hwnd)
        if state["closes_on_request"]:
            state["alive"][hwnd] = False
        return True

    monkeypatch.setattr(w, "_window_alive", lambda h: state["alive"].get(h, False))
    monkeypatch.setattr(w, "_window_pid", lambda h: state["pid"].get(h, 0))
    monkeypatch.setattr(w, "_post_close", post)
    monkeypatch.setattr(w, "_has_modal_popup", lambda h: state["popup"])
    monkeypatch.setattr(w, "_CLOSE_WAIT_S", 0.3)
    return state


def _close(**args):
    return REGISTRY["close_active_window"].func(**args)


def test_confirmation_pins_the_window_the_guard_saw(monkeypatch):
    monkeypatch.setattr(files, "foreground_window", lambda: NOTEPAD)
    prep = tool_policy.prepare_confirmation("close_active_window", {})
    assert prep.args["expect_hwnd"] == 4242 and prep.args["expect_process"] == "notepad.exe"
    assert prep.details == ["Closes: *notes.txt - Notepad (notepad.exe)"]


def test_after_a_hud_yes_the_pinned_window_closes_not_the_hud(desktop, monkeypatch):
    monkeypatch.setattr(files, "foreground_window", lambda: HUD)  # focus moved to the HUD
    res = _close(expect_hwnd=4242, expect_pid=77, expect_title="*notes.txt - Notepad",
                 expect_process="notepad.exe")
    assert res.status == "success"
    assert desktop["posted"] == [4242]
    assert desktop["alive"][9999] is True


def test_without_confirmation_it_closes_the_foreground_window(desktop, monkeypatch):
    monkeypatch.setattr(files, "foreground_window", lambda: NOTEPAD)
    assert _close().status == "success"
    assert desktop["posted"] == [4242]


def test_a_save_prompt_is_reported_not_closed(desktop, monkeypatch):
    monkeypatch.setattr(files, "foreground_window", lambda: NOTEPAD)
    desktop["closes_on_request"], desktop["popup"] = False, True
    res = _close()
    assert res.status == "blocked" and "save prompt is open" in res.reason


def test_a_window_that_ignores_the_request_is_an_error(desktop, monkeypatch):
    monkeypatch.setattr(files, "foreground_window", lambda: NOTEPAD)
    desktop["closes_on_request"] = False
    res = _close()
    assert res.status == "error" and "didn't close" in res.reason


def test_a_window_gone_or_replaced_since_the_check_is_left_alone(desktop):
    desktop["pid"][4242] = 12345    # the handle now belongs to another process
    res = _close(expect_hwnd=4242, expect_pid=77, expect_title="*notes.txt - Notepad")
    assert res.status == "blocked"
    assert desktop["posted"] == []
