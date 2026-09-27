"""media_control looks at what is playing before pressing a toggle.

It pressed the play/pause key and said "Toggled playback." whatever happened;
the key is a TOGGLE, so "pause" with nothing playing started something. Now
Windows' audio sessions decide "nothing is playing" / "already playing", and
anything else is worded as a key sent, not an outcome. The key press and the
audio sessions are faked: no media key is pressed here.
"""
import pytest

from backend.core.tools import media


@pytest.fixture
def keys(monkeypatch):
    pressed = []
    monkeypatch.setattr(media, "_press", pressed.append)
    monkeypatch.setattr(media.sys, "platform", "win32")
    return pressed


def _playing(monkeypatch, apps):
    monkeypatch.setattr(media, "_playing", lambda: apps)


def test_pause_with_nothing_playing_presses_nothing(keys, monkeypatch):
    _playing(monkeypatch, [])
    res = media.media_control("pause")
    assert res.status == "blocked" and res.reason == "nothing is playing"
    assert keys == []


def test_play_while_already_playing_presses_nothing(keys, monkeypatch):
    _playing(monkeypatch, ["chrome.exe"])
    res = media.media_control("play")
    assert res.status == "success" and "already playing (chrome.exe)" in res.message
    assert keys == []


def test_pause_while_playing_sends_the_key(keys, monkeypatch):
    _playing(monkeypatch, ["Spotify.exe"])
    res = media.media_control("pause")
    assert res.message == "Sent pause."
    assert keys == [media._VK["playpause"]]


def test_unknown_state_still_sends_but_says_only_sent(keys, monkeypatch):
    def broken():
        raise OSError("audio service unavailable")
    monkeypatch.setattr(media, "_playing", broken)
    res = media.media_control("pause")
    assert res.status == "success" and res.message == "Sent pause."


@pytest.mark.parametrize("action,said", [("next", "Sent next track."), ("previous", "Sent previous track."),
                                         ("toggle", "Sent play/pause.")])
def test_other_actions_say_sent(keys, monkeypatch, action, said):
    _playing(monkeypatch, [])   # a paused player can still skip
    assert media.media_control(action).message == said
