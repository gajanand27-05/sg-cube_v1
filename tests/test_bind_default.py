"""The server must bind to loopback unless a user deliberately says otherwise.

Several routes can screenshot the desktop, read memory, and run tools, and the
HUD sends no credential — the loopback peer guard is what protects them. A
0.0.0.0 bind puts the whole API on every network the laptop joins (café Wi-Fi
included). The dev machine's own .env sets 0.0.0.0; the shipped defaults must
not follow it.
"""
from pathlib import Path

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
