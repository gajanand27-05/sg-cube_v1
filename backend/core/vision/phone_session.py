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
        # Phone clock minus server clock, in ms. None until the handshake
        # completes — frame age is unmeasurable until then, and reporting an
        # unmeasured age as 0 would claim every frame is perfectly fresh.
        self.clock_offset_ms: float | None = None
        self.pending_capture_ms: float | None = None
        # Starlette does not serialize concurrent sends; the health tick and a
        # pushed command are separate tasks on the same loop, so they can
        # interleave without this.
        self._send_lock = asyncio.Lock()
        self._ack = asyncio.Event()

    async def send(self, payload: dict) -> None:
        import json
        async with self._send_lock:
            await self.ws.send_text(json.dumps(payload))

    def note_time_sync(self, sent_ms: float, phone_ms: float, now_ms: float) -> None:
        """Estimate the phone's clock offset from one round trip.

        The phone reports capture time on its own clock, which can be minutes
        off the server's. Without this correction, frame "age" measures clock
        skew rather than latency, and the staleness gate would drop every frame
        or none. Standard NTP-style estimate: assume the reply's one-way delay
        is half the round trip.
        """
        rtt = max(0.0, now_ms - sent_ms)
        self.clock_offset_ms = phone_ms - (sent_ms + rtt / 2.0)
        log.info("Phone clock offset %.0fms (rtt %.0fms)", self.clock_offset_ms, rtt)

    def frame_age_ms(self, capture_ms: float | None, now_ms: float) -> float | None:
        """How old the frame is, on the server's clock. None if unmeasurable.

        Deliberately NOT clamped at zero. A small negative age is ordinary
        round-trip jitter, but a persistently negative one means the offset
        estimate has the wrong sign — and clamping would report that as 0.0,
        i.e. as a perfectly fresh frame. That is the one failure this module
        could not otherwise detect, and reporting it as absence-of-problem
        breaks the same "never fake a measurement" rule the rest of the
        vision-health path follows.
        """
        if capture_ms is None or self.clock_offset_ms is None:
            return None
        return now_ms - (capture_ms - self.clock_offset_ms)

    def note_status(self, streaming: bool, error: str | None = None) -> None:
        """Called when the phone reports back what it actually did."""
        self.streaming = streaming
        self.last_error = error
        self._ack.set()

    async def notify(self, payload: dict) -> None:
        """Fire-and-forget push. Used for haptics, where waiting on an ack
        would add latency to the one signal that has to be immediate."""
        await self.send(payload)

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
        # Public-space mode: alerts go to the phone's vibrator only, never the
        # speaker. Deliberately NOT a vision mode — it is orthogonal to
        # navigate/scan/read, and folding it into that enum would mean losing
        # the mode when silence is toggled.
        self.silent: bool = False

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

    async def push(self, payload: dict) -> int:
        """Fire-and-forget fan-out — no ack, no waiting. For haptics, where a
        6s ack round-trip would defeat the purpose of the alert."""
        sessions = self.snapshot()
        sent = 0
        for s in sessions:
            try:
                await s.notify(payload)
                sent += 1
            except Exception as e:
                log.warning("Phone push failed: %s", e)
                self.remove(s)
        return sent

    def push_soon(self, payload: dict) -> None:
        """Schedule a push from any context without awaiting it.

        Haptics fire from the detection path, which must not stall on a socket
        write; and the caller may not be on the loop owning the sockets.
        """
        if not self._sessions or self._loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._loop.create_task(self.push(payload))
        else:
            asyncio.run_coroutine_threadsafe(self.push(payload), self._loop)


registry = PhoneSessionRegistry()
