"""The server must bind to loopback unless a user deliberately says otherwise.

Several routes can screenshot the desktop, read memory, and run tools, and the
HUD sends no credential — the loopback peer guard is what protects them. A
0.0.0.0 bind puts the whole API on every network the laptop joins (café Wi-Fi
included). The dev machine's own .env sets 0.0.0.0; the shipped defaults must
not follow it.
"""
import logging
from pathlib import Path

import pytest

from backend.daemon.main import warn_if_exposed
from backend.server.config import Settings

_ROOT = Path(__file__).resolve().parents[1]


def test_code_default_is_loopback(monkeypatch):
    monkeypatch.delenv("APP_HOST", raising=False)
    assert Settings(_env_file=None).app_host == "127.0.0.1"


def test_shipped_env_example_is_loopback():
    lines = (_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    hosts = [ln.split("=", 1)[1].strip() for ln in lines
             if ln.strip().startswith("APP_HOST=")]
    assert hosts in ([], ["127.0.0.1"]), hosts



@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_bind_is_quiet(host, caplog):
    with caplog.at_level(logging.WARNING):
        assert warn_if_exposed(host, allow_lan_hud=False) is None
    assert not caplog.records


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "::", "my-laptop.local"])
def test_any_other_bind_warns_at_boot(host, caplog):
    with caplog.at_level(logging.WARNING):
        msg = warn_if_exposed(host, allow_lan_hud=False)
    assert msg and "reachable from the network" in msg and "/ws/ui" in msg
    assert caplog.records[-1].levelno == logging.WARNING


def test_lan_hud_plus_open_bind_says_prompts_are_answerable(caplog):
    msg = warn_if_exposed("0.0.0.0", allow_lan_hud=True)
    assert "can answer confirmation prompts" in msg


def test_lan_hud_is_off_by_default(monkeypatch):
    """ALLOW_LAN_HUD is what lets a LAN peer reach /api/session and answer
    confirmations on /ws/ui; it must be opt-in."""
    monkeypatch.delenv("ALLOW_LAN_HUD", raising=False)
    assert Settings(_env_file=None).allow_lan_hud is False
