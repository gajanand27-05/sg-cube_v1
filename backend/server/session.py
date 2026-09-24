"""Who may open the HUD's WebSocket.

/ws/ui streams every transcript, clipboard change and memory hit, and it now
also ACCEPTS answers to confirmation prompts — so "yes, delete that file" can
arrive on it. A loopback peer check alone does not stop a web page in the
user's own browser: any site can open ws://127.0.0.1:<port>, and the socket
would come from 127.0.0.1. Two checks close that:

  * Origin — browsers always send it on a WebSocket handshake, and a page
    cannot forge it. It must be this app (loopback, or a private LAN address
    when ALLOW_LAN_HUD is on) on the server's own port or the Vite dev port.
    Non-browser clients send none; they still need the token.
  * a session token, minted per process and handed out by GET /api/session.
    Other origins cannot read that response (no CORS grant), and the Host
    check below stops DNS rebinding — a hostile domain re-pointed at
    127.0.0.1, which would otherwise make the fetch same-origin.
"""
from __future__ import annotations

import ipaddress
import secrets
from urllib.parse import urlsplit

# Regenerated every start: a token from a previous run is worthless.
TOKEN = secrets.token_urlsafe(32)

DEV_PORT = 5173
_LOOPBACK_NAMES = {"localhost"}


def token_ok(candidate: str | None) -> bool:
    return bool(candidate) and secrets.compare_digest(candidate, TOKEN)


def _split_host(hostport: str) -> tuple[str, int | None]:
    parts = urlsplit(f"//{hostport}")
    return (parts.hostname or "").lower(), parts.port


def host_allowed(host: str, allow_lan: bool) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False  # any other NAME is exactly what a rebinding attack uses
    return addr.is_loopback or (allow_lan and addr.is_private)


def host_header_ok(host_header: str | None, allow_lan: bool) -> bool:
    if not host_header:
        return False
    host, _port = _split_host(host_header)
    return host_allowed(host, allow_lan)


def origin_ok(origin: str | None, host_header: str | None, allow_lan: bool) -> bool:
    """None (a non-browser client) passes here; the token still applies."""
    if origin is None:
        return True
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    if not host_allowed(parts.hostname.lower(), allow_lan):
        return False
    _h, server_port = _split_host(host_header or "")
    origin_port = parts.port or (443 if parts.scheme == "https" else 80)
    return origin_port in {server_port, DEV_PORT}
