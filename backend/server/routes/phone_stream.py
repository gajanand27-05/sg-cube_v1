"""Phone camera streaming — VisionClaw Phase 1.

Three surfaces:
  WS   /ws/phone_stream    — phone sends binary JPEG frames + JSON control
  GET  /phone              — self-contained capture page for the phone browser
  GET  /vision/phone_frame — latest accepted frame as image/jpeg (HUD polls this)

Wire protocol on the WS.

phone -> server:
  binary          : one JPEG frame
  {"type": "frame_ts", "t": <phone epoch ms>}      immediately before its frame
  {"type": "mode_change", "mode": navigate|scan|read|idle}
  {"type": "time_sync_reply", "server_ms":…, "phone_ms":…}
  {"type": "status", "streaming": bool, "error": str|null, "mode":…}
server -> phone:
  {"type": "time_sync", "server_ms":…}             once, on connect
  {"type": "health", ...}                          every HEALTH_INTERVAL_S
  {"type": "command", "action": start|stop|mode|vibrate, ...}

The command channel is what makes "connect phone camera" work by voice: the
page holds this socket open whenever it is open at all, streaming or not.

Frame pixels never ride the event bus: PhoneFrameEvent carries metadata only
and the HUD fetches the image over HTTP.

Access: private/loopback peers only (the phone is on the LAN; no JWT flow on
a phone browser). Same posture as routes/remote.py.
"""
import asyncio
import io
import json
import logging
import socket
import sys
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response

from backend.core.events import get_bus
from backend.core.vision.frame_ingest import frame_ingestor
from backend.core.vision.obstacle_detector import detection_runner
from backend.core.vision.phone_session import VALID_MODES, PhoneSession, registry
from backend.core.vision.vision_health import STALE_FRAME_MS, vision_health
from backend.daemon.ui_events import ModeChangeEvent, OcrReadEvent, VisionHealthEvent
from backend.server.routes.remote import _is_private_host

log = logging.getLogger(__name__)
router = APIRouter(prefix="/ws", tags=["phone_stream"])
page_router = APIRouter(tags=["phone_stream"])

HEALTH_INTERVAL_S = 5.0


def _peer_allowed(host: str | None) -> bool:
    # "testclient" is what FastAPI's TestClient reports; a real uvicorn peer is
    # always an IP, so this can't open anything in production.
    if host is None or host == "testclient":
        return True
    return _is_private_host(host)


@router.websocket("/phone_stream")
async def phone_stream_ws_endpoint(ws: WebSocket):
    if not _peer_allowed(ws.client.host if ws.client else None):
        await ws.close(code=4403)
        return
    await ws.accept()
    log.info("Phone stream client connected: %s", ws.client.host if ws.client else "?")

    # The page opens this socket on load, before the camera starts, so that
    # "connect phone camera" has something to talk to. Registration is
    # therefore about the page being open — not about frames flowing.
    session = PhoneSession(ws)
    registry.add(session)

    frames_seen = 0
    last_health = time.monotonic()
    # One round trip to learn the phone's clock offset. Until the reply lands,
    # frame age is None (unmeasurable) rather than a fabricated zero.
    sync_sent_ms = time.time() * 1000.0
    await ws.send_text(json.dumps({"type": "time_sync", "server_ms": sync_sent_ms}))

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            if msg.get("bytes") is not None:
                frames_seen += 1
                session.streaming = True
                age_ms = session.frame_age_ms(session.pending_capture_ms,
                                              time.time() * 1000.0)
                session.pending_capture_ms = None
                too_old = age_ms is not None and age_ms > STALE_FRAME_MS
                # Counted before the drop decision: a stale frame is still a
                # frame received, or the drop rate is unmeasurable.
                vision_health.note_frame_received(age_ms=age_ms, dropped_stale=too_old)
                if too_old:
                    # Guiding someone using a 2s-old view of the street is
                    # worse than saying nothing.
                    log.debug("dropping stale frame: %.0fms old", age_ms)
                    continue
                meta = frame_ingestor.ingest_frame(msg["bytes"], mode=session.mode)
                if meta is not None:
                    # Phase 2: YOLO on accepted frames. submit() returns
                    # immediately if a detection is already in flight.
                    asyncio.create_task(detection_runner.submit(msg["bytes"], session.mode))

            elif msg.get("text") is not None:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    log.warning("Invalid JSON from phone: %.200s", msg["text"])
                    continue
                kind = data.get("type")
                if kind == "mode_change" and data.get("mode") in VALID_MODES:
                    previous, session.mode = session.mode, data["mode"]
                    get_bus().publish(ModeChangeEvent(mode=session.mode))
                    log.info("Phone vision mode -> %s", session.mode)
                    if session.mode == "scan" and previous != "scan":
                        # Scan is once-triggered by definition: entering the
                        # mode IS the trigger. Off the receive loop so a ~150ms
                        # inference cannot stall incoming frames.
                        asyncio.create_task(detection_runner.scan_once())
                    if session.mode == "read" and previous != "read":
                        # Clear OCR dedup so the first frame speaks everything.
                        detection_runner._last_read_spoken.clear()
                elif kind == "time_sync_reply":
                    try:
                        session.note_time_sync(
                            sent_ms=float(data["server_ms"]),
                            phone_ms=float(data["phone_ms"]),
                            now_ms=time.time() * 1000.0,
                        )
                    except (KeyError, TypeError, ValueError) as e:
                        log.warning("Bad time_sync_reply from phone: %s", e)
                elif kind == "frame_ts":
                    # Sent immediately before its binary frame. WS preserves
                    # per-connection order, so pairing is deterministic and
                    # needs no id.
                    try:
                        session.pending_capture_ms = float(data["t"])
                    except (KeyError, TypeError, ValueError):
                        session.pending_capture_ms = None
                elif kind == "status":
                    # The phone's answer to a pushed command. Load-bearing: it
                    # is the only thing that distinguishes "command delivered"
                    # from "camera actually running", and the tool reports the
                    # latter to the user.
                    session.note_status(
                        streaming=bool(data.get("streaming")),
                        error=data.get("error"),
                    )
                    if data.get("mode") in VALID_MODES:
                        session.mode = data["mode"]
                    log.info("Phone status: streaming=%s error=%s",
                             session.streaming, data.get("error"))
                else:
                    log.warning("Unknown phone control message: %.100s", msg["text"])

            now = time.monotonic()
            if now - last_health >= HEALTH_INTERVAL_S:
                last_health = now
                snap = vision_health.snapshot(mode=session.mode)
                stats = frame_ingestor.stats
                get_bus().publish(VisionHealthEvent(**snap.event_fields()))
                await ws.send_text(json.dumps({
                    "type": "health",
                    "frames_accepted": stats["frames_processed"],
                    "frames_dropped": stats["frames_dropped"],
                    "fps_received": snap.fps_received,
                }))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.error("Phone stream error: %s", e)
    finally:
        registry.remove(session)
        # Drop the last frame and the detector's confirmation state. Without
        # this, /vision/phone_frame keeps serving a minutes-old image with HTTP
        # 200 after the phone drops off Wi-Fi, so the HUD shows a frozen picture
        # that reads as a live feed — the worst failure mode for a navigation
        # aid — and the next session's first frame can satisfy 2-frame
        # confirmation against the previous session's detections.
        frame_ingestor.reset()
        detection_runner.reset()
        vision_health.reset()
        log.info("Phone stream session ended: %d frames received", frames_seen)


def _lan_ip() -> str | None:
    """This machine's LAN IPv4 — the address a phone on the same Wi-Fi uses.
    UDP connect() picks the interface with the default route; no packet is sent."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def _phone_url() -> str | None:
    """HTTPS when the TLS listener is enabled (camera works after the phone
    accepts the one-time cert warning), plain HTTP otherwise."""
    from backend.server.config import settings
    ip = _lan_ip()
    if ip is None:
        return None
    if settings.enable_phone_tls:
        return f"https://{ip}:{settings.phone_tls_port}/phone"
    return f"http://{ip}:{settings.app_port}/phone"


@page_router.get("/vision/phone_connect")
async def phone_connect_info():
    """The concrete URL the phone should open — the HUD shows this (and the QR
    below) instead of a placeholder the user would have to transcribe."""
    url = _phone_url()
    from backend.server.config import settings
    return {
        "url": url,
        "reachable_from_lan": settings.app_host not in ("127.0.0.1", "localhost"),
    }


@page_router.get("/vision/phone_connect_qr.png")
async def phone_connect_qr():
    """QR of the phone URL — scan with the phone camera, no typing."""
    url = _phone_url()
    if url is None:
        return Response(status_code=404)
    try:
        import qrcode  # deferred: cold import builds tables
    except ImportError:
        # The daemon may run on a different interpreter than the one that
        # pip-installed qrcode (this repo has a system-vs-venv split). The HUD
        # treats 404 as "no QR, URL text only" — never a 500 traceback.
        log.warning("qrcode not installed for %s — run: pip install qrcode", sys.executable)
        return Response(status_code=404)

    img = qrcode.make(url, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@page_router.get("/vision/phone_frame")
async def get_phone_frame():
    """Latest accepted phone frame. The HUD polls this on each PhoneFrameEvent."""
    frame, meta = frame_ingestor.latest_frame()
    if frame is None:
        return Response(status_code=404)
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store",
            "X-Frame-Id": str(meta.frame_id),
            "X-Frame-Mode": meta.mode,
        },
    )


@page_router.get("/phone")
async def phone_capture_page():
    """Phone-side capture page — scan the QR in the HUD's Vision panel."""
    from backend.server.config import settings
    return HTMLResponse(content=_PHONE_PAGE.replace("{{TLS_PORT}}", str(settings.phone_tls_port)))


# Self-contained on purpose: the phone loads exactly one document, nothing else.
_PHONE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>Onyx Phone Cam</title>
<style>
  body { margin:0; background:#040814; color:#e0f2fe; font-family:monospace;
         display:flex; flex-direction:column; align-items:center; gap:12px; padding:16px; }
  h1 { font-size:14px; letter-spacing:.2em; color:#67e8f9; text-transform:uppercase; }
  video { width:100%; max-width:480px; border:1px solid rgba(34,211,238,.35); border-radius:4px; background:#000; }
  button { background:#0a1226; color:#e0f2fe; border:1px solid rgba(34,211,238,.35);
           border-radius:4px; padding:10px 16px; font-family:monospace; font-size:14px; }
  button.active { border-color:#22c55e; color:#22c55e; }
  #modes { display:flex; gap:8px; }
  #status { font-size:12px; color:#7ea3b8; text-align:center; white-space:pre-line; }
  #err { font-size:12px; color:#ef4444; max-width:480px; white-space:pre-line; }
</style>
</head>
<body>
<h1>Onyx Phone Cam</h1>
<video id="v" autoplay playsinline muted></video>
<button id="toggle">Start Streaming</button>
<div id="modes">
  <button data-mode="idle" class="active">Idle</button>
  <button data-mode="navigate">Navigate</button>
  <button data-mode="scan">Scan</button>
  <button data-mode="read">Read</button>
</div>
<div id="status">not connected</div>
<div id="err"></div>
<canvas id="c" hidden></canvas>
<script>
"use strict";
const FPS = 2, MAX_W = 800, QUALITY = 0.6;
const v = document.getElementById("v"), c = document.getElementById("c");
const st = document.getElementById("status"), err = document.getElementById("err");
let ws = null, timer = null, sent = 0, running = false, mode = "idle";

function wsUrl() {
  return (location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws/phone_stream";
}

function setStatus() {
  st.textContent = (ws && ws.readyState === 1 ? "connected" : "disconnected")
    + (running ? " | streaming" : " | camera idle") + " | frames sent: " + sent;
}

// Tell the server what actually happened. The assistant reports this back to
// the user, so a command that was delivered but failed on the device must not
// look like success.
function report(error) {
  if (ws && ws.readyState === 1)
    ws.send(JSON.stringify({ type: "status", streaming: running, mode: mode,
                             error: error || null }));
}

// The control socket is open whenever this page is open, streaming or not —
// that is what lets "connect phone camera" reach the phone without a QR scan.
// It always reconnects, because the page being backgrounded must not
// permanently deafen the phone.
function connect() {
  ws = new WebSocket(wsUrl());
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { setStatus(); report(null); };
  ws.onclose = () => { setStatus(); setTimeout(connect, 2000); };
  ws.onmessage = async (m) => {
    let d; try { d = JSON.parse(m.data); } catch { return; }
    if (d.type === "time_sync") {
      // Reply immediately — the server halves the round trip to estimate our
      // clock offset. Any delay here inflates its estimate.
      ws.send(JSON.stringify({ type: "time_sync_reply",
                               server_ms: d.server_ms, phone_ms: Date.now() }));
    } else if (d.type === "health") {
      st.textContent = "connected | sent: " + sent + " | server accepted: "
        + d.frames_accepted + " (dropped " + d.frames_dropped + ")";
    } else if (d.type === "command") {
      if (d.action === "vibrate") { buzz(d.pulses || 1); return; }  // no ack: latency is the point
      if (d.mode) setMode(d.mode);
      if (d.action === "start") { if (!running) await start(); else report(null); }
      else if (d.action === "stop") { stop(); }
      else report(null);
    }
  };
}

// One long buzz = critical (stop), two short = warning. Distinguishable
// through a pocket, which a single pattern is not. navigator.vibrate is
// unsupported on iOS Safari, hence the guard — the spoken alert still fires.
function buzz(pulses) {
  if (!navigator.vibrate) return;
  navigator.vibrate(pulses === 1 ? [400] : [120, 80, 120]);
}

function setMode(m) {
  mode = m;
  document.querySelectorAll("#modes button").forEach(x =>
    x.classList.toggle("active", x.dataset.mode === m));
  if (ws && ws.readyState === 1)
    ws.send(JSON.stringify({ type: "mode_change", mode: m }));
}

async function start() {
  err.textContent = "";
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    const msg = "Camera API unavailable — phone browsers only allow the camera on HTTPS.\\n"
      + (location.protocol === "https:"
        ? "Unexpected: this page IS https. Try reloading, or a different browser."
        : "Open the HTTPS version instead: https://" + location.hostname + ":{{TLS_PORT}}/phone\\n"
          + "(accept the one-time security warning: Advanced \\u2192 Proceed). "
          + "Rescanning the QR on the HUD also takes you there.");
    err.textContent = msg;
    report("camera API unavailable (needs HTTPS)");
    return false;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false,
    });
    v.srcObject = stream;
  } catch (e) {
    err.textContent = "Camera permission failed: " + e;
    // Browsers only grant the camera without a tap once permission is already
    // remembered for this origin, so this is the expected first-run answer.
    report("camera permission denied — tap Start Streaming on the phone once");
    return false;
  }
  running = true;
  timer = setInterval(() => {
    if (!ws || ws.readyState !== 1 || v.videoWidth === 0) return;
    const scale = Math.min(1, MAX_W / v.videoWidth);
    c.width = Math.round(v.videoWidth * scale);
    c.height = Math.round(v.videoHeight * scale);
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    // Stamp at draw time, not at send time: JPEG encoding is async and its
    // duration is part of the frame's age.
    const capturedAt = Date.now();
    c.toBlob((b) => {
      if (b && ws && ws.readyState === 1) {
        // Ordered pair — WS preserves per-connection order, so the server
        // attributes this timestamp to the very next binary message.
        ws.send(JSON.stringify({ type: "frame_ts", t: capturedAt }));
        ws.send(b); sent++; setStatus();
      }
    }, "image/jpeg", QUALITY);
  }, 1000 / FPS);
  document.getElementById("toggle").textContent = "Stop Streaming";
  if (mode === "idle") setMode("navigate");
  setStatus();
  report(null);
  return true;
}

function stop() {
  running = false;
  clearInterval(timer); timer = null;
  if (v.srcObject) { v.srcObject.getTracks().forEach(t => t.stop()); v.srcObject = null; }
  // The control socket deliberately stays open, so the assistant can start the
  // camera again later without the phone being touched.
  document.getElementById("toggle").textContent = "Start Streaming";
  setStatus();
  report(null);
}

document.getElementById("toggle").onclick = () => (running ? stop() : start());
document.querySelectorAll("#modes button").forEach(b => {
  b.onclick = () => setMode(b.dataset.mode);
});
connect();
</script>
</body>
</html>"""
