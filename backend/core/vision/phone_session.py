"""Live phone-camera sessions and the server -> phone control channel.

Phase 1 only ever pushed health frames at the phone; the camera itself could
only be started by tapping the button on the phone. This module keeps a
registry of connected capture pages so the assistant can drive them — that is
what makes "connect phone camera" work as a spoken command instead of a QR
scan.

Why this lives in core/ and not in routes/phone_stream.py: the tool layer
(backend/core/tools/vision_phone.py) needs to reach it, and tools importing a
FastAPI route module would invert the dependency.

Loop ownership is the whole difficulty here. Sessions are created on the
uvicorn loop, but a spoken turn runs its tools on the daemon's per-capture
`asyncio.run` loop (see trigger.handle_wake). Touching a WebSocket from a
foreign loop is exactly the class of bug T-tts-loop-globals documents, so the
registry records the loop that owns its sessions and `command()` hops back onto
it when called from anywhere else.
"""
import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

# How long to wait for the phone to confirm it actually started the camera.
# getUserMedia has to resolve on the phone, so this is not instant; 6s is long
# enough for a cold camera and short enough not to stall a spoken turn.
ACK_TIMEOUT_S = 6.0

VALID_MODES = {"navigate", "scan", "read", "idle"}


class PhoneSession:
    """One connected capture page."""

    def __init__(self, ws: Any):
        self.ws = ws
        self.mode = "idle"
        self.streaming = False
        self.last_error: str | None = None
        # Starlette does not serialize concurrent sends; the health tick and a
        # pushed command are separate tasks on the same loop, so they can
        # interleave without this.
        self._send_lock = asyncio.Lock()
        self._ack = asyncio.Event()

    async def send(self, payload: dict) -> None:
        import json
        async with self._send_lock:
            await self.ws.send_text(json.dumps(payload))

    def note_status(self, streaming: bool, error: str | None = None) -> None:
        """Called when the phone reports back what it actually did."""
        self.streaming = streaming
        self.last_error = error
        self._ack.set()

    async def request(self, payload: dict, expect_streaming: bool) -> bool:
        """Send a command and wait for the phone to report what it actually did.

        Success is the phone's state matching `expect_streaming`, not mere
        delivery: a start that failed on the device (permission denied, no
        camera) must never be reported to the user as a working camera.
        """
        self._ack.clear()
        await self.send(payload)
        try:
            await asyncio.wait_for(self._ack.wait(), timeout=ACK_TIMEOUT_S)
        except asyncio.TimeoutError:
            self.last_error = "phone did not respond"
            return False
        return self.streaming == expect_streaming


class PhoneSessionRegistry:
    def __init__(self) -> None:
        self._sessions: set[PhoneSession] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def add(self, session: PhoneSession) -> None:
        # Captured per-connect rather than at import: at import time there is
        # no running loop, and under the test client the loop differs per case.
        self._loop = asyncio.get_running_loop()
        self._sessions.add(session)

    def remove(self, session: PhoneSession) -> None:
        self._sessions.discard(session)

    @property
    def count(self) -> int:
        return len(self._sessions)

    def snapshot(self) -> list[PhoneSession]:
        return list(self._sessions)

    async def _fanout(self, payload: dict, expect_streaming: bool) -> tuple[int, str | None]:
        """Push to every session on the owning loop. Returns (ok_count, error)."""
        sessions = self.snapshot()
        if not sessions:
            return 0, "no phone connected"
        ok = 0
        err: str | None = None
        for s in sessions:
            try:
                if await s.request(payload, expect_streaming):
                    ok += 1
                else:
                    err = s.last_error or "phone did not apply the command"
            except Exception as e:  # a dead socket must not kill the others
                log.warning("Phone command failed for a session: %s", e)
                err = str(e)
                self.remove(s)
        return ok, err

    async def command(self, action: str, mode: str | None = None) -> tuple[int, str | None]:
        """Drive the connected phone(s). Safe to call from any loop.

        Returns (phones that confirmed, first error) — callers report the
        confirmation, never the send.
        """
        payload: dict = {"type": "command", "action": action}
        if mode is not None:
            payload["mode"] = mode
        expect_streaming = action == "start"

        if not self._sessions or self._loop is None:
            return 0, "no phone connected"

        running = asyncio.get_running_loop()
        if running is self._loop:
            return await self._fanout(payload, expect_streaming)

        # Foreign loop (the daemon's per-turn asyncio.run). Hop to the loop
        # that owns the sockets and block a worker thread, not this loop.
        fut = asyncio.run_coroutine_threadsafe(
            self._fanout(payload, expect_streaming), self._loop)
        return await asyncio.to_thread(fut.result, ACK_TIMEOUT_S + 2.0)


registry = PhoneSessionRegistry()
