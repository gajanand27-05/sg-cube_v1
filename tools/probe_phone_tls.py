"""Live probe: does the phone's HTTPS/WSS listener actually serve?

iOS Safari refuses getUserMedia on plain HTTP, so the phone-camera feature on
an iPhone depends entirely on the second uvicorn listener that main.py's
lifespan starts on `phone_tls_port` with a self-signed cert. Everything about
that is enabled by default (`enable_phone_tls: bool = True`).

tests/test_phone_tls.py covers the CERT — generation, reuse, rotation, repair.
It cannot cover whether the listener binds and serves, which is the half that
actually decides whether a phone can connect, and is exactly the shape this
repo keeps shipping broken (wiring present, activation absent).

Runs a real backend on dedicated ports, hits it over real TLS, opens a real
WSS frame socket, then shuts it down and PROVES the ports are free again —
orphaned probe backends squatting :8001 have bitten this project twice.

    .venv/Scripts/python.exe tools/probe_phone_tls.py
"""
from __future__ import annotations

import os
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTTP_PORT = 8002        # deliberately NOT 8001 — never squat the real one
TLS_PORT = 8444         # deliberately NOT 8443
BOOT_TIMEOUT_S = 90

PASS, FAIL = "[PASS]", "[FAIL]"
_results: list[tuple[str, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    _results.append((PASS if ok else FAIL, f"{name}{' — ' + detail if detail else ''}"))
    print(f"  {PASS if ok else FAIL} {name}" + (f" — {detail}" if detail else ""))
    return ok


def port_open(port: int, timeout: float = 0.4) -> bool:
    with socket.socket() as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_port(port: int, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if port_open(port):
            return True
        time.sleep(0.5)
    return False


def start_backend() -> subprocess.Popen:
    env = os.environ | {
        "APP_HOST": "127.0.0.1",
        "APP_PORT": str(HTTP_PORT),
        "PHONE_TLS_PORT": str(TLS_PORT),
        "ENABLE_PHONE_TLS": "true",
        # Telemetry-only backend: the cheap liveness rig. Nothing here needs a
        # mic, a camera or a browser, and starting them makes boot slow and
        # noisy.
        "ENABLE_WAKE_WORD": "false",
        "ENABLE_VISION": "false",
        "ENABLE_CLIPBOARD": "false",
        "ENABLE_WATCHER": "false",
        "ENABLE_BROWSER": "false",
        "ENABLE_TELEMETRY": "false",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.server.main:app",
         "--host", "127.0.0.1", "--port", str(HTTP_PORT), "--log-level", "warning"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def probe_https() -> None:
    import httpx
    # verify=False is correct here and only here: the cert is self-signed by
    # design, which is also why the phone shows a warning the user must accept.
    with httpx.Client(verify=False, timeout=15) as c:
        r = c.get(f"https://127.0.0.1:{TLS_PORT}/phone")
        check("GET /phone over HTTPS", r.status_code == 200, f"status {r.status_code}")
        body = r.text.lower()
        check("capture page is the real one", "getusermedia" in body or "camera" in body,
              f"{len(body)} bytes")


def probe_wss() -> None:
    import asyncio

    import websockets

    async def _run() -> tuple[bool, str]:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        uri = f"wss://127.0.0.1:{TLS_PORT}/ws/phone_stream"
        try:
            async with websockets.connect(uri, ssl=ctx, open_timeout=15) as ws:
                await ws.send('{"type": "mode_change", "mode": "read"}')
                await ws.send(b"\xff\xd8\xff\xe0" + b"not-a-real-jpeg" * 4)
                await asyncio.sleep(0.5)
                return True, "connected, sent mode + frame"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    ok, detail = asyncio.run(_run())
    check("WSS /ws/phone_stream over TLS", ok, detail)


def main() -> int:
    print(f"Probing phone TLS on :{TLS_PORT} (http :{HTTP_PORT})\n")
    proc = start_backend()
    try:
        deadline = time.monotonic() + BOOT_TIMEOUT_S
        if not check("backend booted", wait_for_port(HTTP_PORT, deadline)):
            out = proc.stdout.read() if proc.stdout else ""
            print("\n--- backend output ---\n" + out[-3000:])
            return 1
        if not check("TLS listener bound", wait_for_port(TLS_PORT, deadline)):
            out = proc.stdout.read() if proc.stdout else ""
            print("\n--- backend output ---\n" + out[-3000:])
            return 1
        probe_https()
        probe_wss()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        time.sleep(1.0)
        # Prove it, don't assert it: "backend stopped, port free" has been
        # claimed here before while the process was still listening.
        for port in (HTTP_PORT, TLS_PORT):
            check(f"port {port} released", not port_open(port))

    failed = [m for s, m in _results if s == FAIL]
    print(f"\n{len(_results) - len(failed)}/{len(_results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
