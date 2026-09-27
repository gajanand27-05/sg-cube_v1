"""shutdown / restart / sleep / cancel report what Windows actually did.

They used to Popen shutdown.exe and say "shutting down in 10s" whatever it
answered; sleep went through a `timeout && rundll32` chain that
cancel_shutdown could not stop and that hibernates when hibernation is on;
cancel_shutdown decided by English error text. Everything Windows-facing is
faked here: nothing is shut down, restarted or put to sleep.
"""
import subprocess
import time

import pytest

from backend.core.tools import windowing as w
from backend.core.tools.registry import REGISTRY


def _call(name, **kw):
    return REGISTRY[name].func(**kw)


@pytest.fixture
def windows(monkeypatch):
    state = {"rc": {}, "calls": [], "suspended": 0, "allowed": True, "suspend_ok": True}

    def shutdown_exe(*args):
        state["calls"].append(args)
        rc = state["rc"].get(args[0], 0)
        return subprocess.CompletedProcess(["shutdown", *args], rc, "", "some localized text")

    def suspend():
        state["suspended"] += 1
        return (state["suspend_ok"], 0 if state["suspend_ok"] else 50)

    monkeypatch.setattr(w, "_shutdown_exe", shutdown_exe)
    monkeypatch.setattr(w, "_suspend", suspend)
    monkeypatch.setattr(w, "_sleep_allowed", lambda: state["allowed"])
    monkeypatch.setattr(w, "_sleep_timer", None)
    yield state
    if w._sleep_timer is not None:
        w._sleep_timer.cancel()


# ── shutdown / restart ───────────────────────────────────────────────────

@pytest.mark.parametrize("tool,flag", [("shutdown_pc", "/s"), ("restart_pc", "/r")])
def test_success_only_when_windows_accepts(windows, tool, flag):
    res = _call(tool, seconds=30)
    assert res.status == "success"
    assert windows["calls"] == [(flag, "/t", "30")]


@pytest.mark.parametrize("tool,flag", [("shutdown_pc", "/s"), ("restart_pc", "/r")])
def test_already_scheduled_is_not_success(windows, tool, flag):
    windows["rc"][flag] = 1190
    res = _call(tool)
    assert res.status == "blocked" and "already scheduled" in res.reason


@pytest.mark.parametrize("tool,flag", [("shutdown_pc", "/s"), ("restart_pc", "/r")])
def test_access_denied_is_an_error_with_the_code(windows, tool, flag):
    windows["rc"][flag] = 5
    res = _call(tool)
    assert res.status == "error" and "code 5" in res.reason


# ── cancel, by exit code not text ────────────────────────────────────────

def test_cancel_success(windows):
    assert _call("cancel_shutdown").status == "success"


def test_cancel_with_nothing_scheduled_is_decided_by_the_code(windows):
    windows["rc"]["/a"] = 1116          # the stderr text is not English here
    res = _call("cancel_shutdown")
    assert res.status == "blocked" and "nothing was scheduled" in res.reason


def test_cancel_failure_is_not_reported_as_cancelled(windows):
    windows["rc"]["/a"] = 5
    res = _call("cancel_shutdown")
    assert res.status == "error" and "code 5" in res.reason


# ── sleep ────────────────────────────────────────────────────────────────

def test_sleep_countdown_can_be_cancelled(windows):
    windows["rc"]["/a"] = 1116          # no shutdown pending, only the sleep
    assert _call("sleep_pc", seconds=1).status == "success"
    res = _call("cancel_shutdown")
    assert res.status == "success" and "sleep cancelled" in res.message
    time.sleep(1.3)
    assert windows["suspended"] == 0


def test_sleep_countdown_fires_the_real_sleep_call(windows, monkeypatch):
    monkeypatch.setattr(w.threading, "Timer", _instant_timer)
    assert _call("sleep_pc", seconds=3).status == "success"
    assert windows["suspended"] == 1


def test_sleep_refused_by_windows_is_an_error(windows):
    windows["suspend_ok"] = False
    res = _call("sleep_pc", seconds=0)
    assert res.status == "error" and "refused to sleep" in res.reason


def test_sleep_not_allowed_on_this_pc_is_blocked(windows):
    windows["allowed"] = False
    res = _call("sleep_pc", seconds=0)
    assert res.status == "blocked"
    assert windows["suspended"] == 0


def test_second_sleep_while_one_is_pending_is_refused(windows):
    assert _call("sleep_pc", seconds=30).status == "success"
    assert _call("sleep_pc", seconds=30).status == "blocked"


def test_sleep_asks_windows_not_to_hibernate(monkeypatch):
    """SetSuspendState(Hibernate=FALSE, ...) directly, not rundll32's junk args."""
    seen = []

    class _PowrProf:
        def SetSuspendState(self, hibernate, force, wake_disabled):
            seen.append((hibernate, force, wake_disabled))
            return 1

    import ctypes
    monkeypatch.setattr(ctypes.windll, "powrprof", _PowrProf(), raising=False)
    assert w._suspend() == (True, 0)
    assert seen == [(False, True, False)]


class _instant_timer:
    def __init__(self, _seconds, fn):
        self.fn, self.daemon = fn, True

    def start(self):
        self.fn()

    def cancel(self):
        pass
