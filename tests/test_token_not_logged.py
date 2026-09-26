"""The HUD's session token must never reach a log file.

It rides in the WebSocket query string (/ws/ui?token=...), and uvicorn logs
every handshake with its full path — before the RedactingFormatter, a live
token sat in sg_cube.log. This boots the REAL server in its own process, uses
the token over a real socket, stops it, and greps everything it wrote.
"""
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import websockets

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_session_token_never_reaches_any_log(tmp_path):
    port = _free_port()
    env = {**os.environ, "SG_CUBE_HOME": str(tmp_path), "APP_HOST": "127.0.0.1",
           "ENABLE_WAKE_WORD": "false", "ENABLE_VISION": "false",
           "ENABLE_MODEL_PRELOAD": "false", "ENABLE_CLIPBOARD": "false",
           "ENABLE_WATCHER": "false", "ENABLE_TELEMETRY": "false"}
    out = tmp_path / "stdout.log"
    proc = subprocess.Popen([sys.executable, "-m", "backend.daemon.main", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=out.open("wb"), stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.5)
        else:
            raise AssertionError("server never came up:\n" + out.read_text(errors="replace")[-2000:])

        token = httpx.get(f"{base}/api/session").json()["token"]

        async def use_it():
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws/ui?token={token}",
                                          additional_headers={"Origin": base}):
                pass
            try:  # and a rejected attempt, which logs a warning
                async with websockets.connect(f"ws://127.0.0.1:{port}/ws/ui?token={token}x",
                                              additional_headers={"Origin": base}) as ws:
                    await ws.recv()
            except websockets.exceptions.ConnectionClosed:
                pass

        asyncio.run(use_it())
        time.sleep(0.5)
    finally:
        proc.terminate()
        proc.wait(timeout=20)

    logs = [p for p in tmp_path.rglob("*") if p.is_file() and (".log" in p.name)]
    assert any(p.name == "sg_cube.log" for p in logs), f"no log file was written: {logs}"
    handshake_lines = 0
    for p in logs:
        text = p.read_text(encoding="utf-8", errors="replace")
        assert token not in text, f"session token found in {p}"
        handshake_lines += text.count("/ws/ui?token=<redacted>")
    assert handshake_lines >= 2, "the handshakes were not logged at all — this test proves nothing"
