"""lock_screen asks LockWorkStation directly and reports Windows' answer.

It ran `rundll32 user32.dll,LockWorkStation`, which hides the result, so a
lock refused by policy still said "screen locked". LockWorkStation is faked:
the screen is never locked here.
"""
import ctypes

import pytest

from backend.core.tools.registry import REGISTRY


class _User32:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def LockWorkStation(self):
        self.calls += 1
        return self.result


@pytest.fixture
def user32(monkeypatch):
    def install(result):
        fake = _User32(result)
        monkeypatch.setattr(ctypes.windll, "user32", fake, raising=False)
        monkeypatch.setattr(ctypes, "GetLastError", lambda: 5)
        return fake
    return install


def test_locked_when_windows_accepts(user32):
    fake = user32(1)
    res = REGISTRY["lock_screen"].func()
    assert res.status == "success" and fake.calls == 1


def test_refused_lock_is_an_error_not_locked(user32):
    user32(0)
    res = REGISTRY["lock_screen"].func()
    assert res.status == "error"
    assert "refused to lock" in res.reason and "error 5" in res.reason
