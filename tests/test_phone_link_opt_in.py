"""The phone link is opt-in: PHONE_LINK_ENABLED, off by default.

Off: /remote/connect is not served and send_to_phone is not registered, so
the planner never sees it. On: today's behaviour, and the boot warning names
the phone link when the bind address reaches the network.

The OFF state runs in a fresh process: the flag decides registration at
import time, and conftest turns it ON for the rest of the suite.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

_PROBE = r"""
import json, logging
logging.disable(logging.WARNING)
from fastapi.testclient import TestClient
import backend.server.main as sm
from backend.core.tools.registry import REGISTRY
from backend.core.caps.registry import capability_registry
from backend.server.config import settings
capability_registry.discover()
close = None
try:
    with TestClient(sm.app).websocket_connect("/remote/connect/probe"):
        close = "accepted"
except Exception as e:
    close = getattr(e, "code", type(e).__name__)
print(json.dumps({"flag": settings.phone_link_enabled,
                  "tool": "send_to_phone" in REGISTRY,
                  "capability": any(c.name == "send_to_phone" for c in capability_registry.all()),
                  "remote_ws_close": close}))
"""


def _probe(flag: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "PHONE_LINK_ENABLED"}
    if flag is not None:
        env["PHONE_LINK_ENABLED"] = flag
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_off_by_default_nothing_phone_is_served_or_offered():
    r = _probe(None)
    assert r["flag"] is False
    assert r["tool"] is False and r["capability"] is False
    assert r["remote_ws_close"] == 1000   # no such route (a served one refuses with 1008)


def test_on_serves_the_route_and_offers_the_tool():
    r = _probe("true")
    assert r["tool"] is True and r["capability"] is True
    assert r["remote_ws_close"] == 1008   # served, and a non-private peer is refused


def test_the_boot_warning_names_the_phone_link_when_exposed():
    from backend.daemon.main import warn_if_exposed

    msg = warn_if_exposed("0.0.0.0", allow_lan_hud=False, phone_link=True)
    assert "PHONE_LINK_ENABLED is on" in msg and "no password" in msg
    assert "PHONE_LINK_ENABLED" not in warn_if_exposed("0.0.0.0", allow_lan_hud=False)


def test_loopback_with_the_link_on_says_a_phone_cannot_reach_it(caplog):
    import logging

    from backend.daemon.main import warn_if_exposed

    with caplog.at_level(logging.INFO, logger="backend.daemon.main"):
        assert warn_if_exposed("127.0.0.1", allow_lan_hud=False, phone_link=True) is None
    assert "a phone cannot reach" in caplog.text
