import argparse
import logging
import os
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# Force UTF-8 stdout/stderr before importing anything that prints unicode.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

log = logging.getLogger(__name__)


# ── Service health tracking ─────────────────────────────────────────────
# One entry per service. State is:
#   - "started"  — start() returned without raising
#   - "disabled" — ENABLE_* flag was false; never attempted
#   - "failed"   — start() raised; error text captured
# This is the canonical health surface — the /system/services endpoint
# reads from it. Populated by start_services, cleared on next boot.
SERVICE_STATUS: dict[str, dict] = {}


def get_service_status() -> dict:
    """Snapshot of per-service startup status. Safe for JSON serialization."""
    return {name: dict(entry) for name, entry in SERVICE_STATUS.items()}


def _record(name: str, status: str, error: str | None = None) -> None:
    SERVICE_STATUS[name] = {
        "status": status,
        "error": error,
        "started_at": datetime.now(timezone.utc).isoformat() if status == "started" else None,
    }


def _start_one(name: str, enabled: bool, starter: Callable[[], None]) -> None:
    """Boot one service with error isolation.

    A failed start is logged at ERROR level with the traceback and recorded
    to SERVICE_STATUS. Never re-raises — the caller keeps going with the
    other services. A disabled service reports "disabled", never "failed".
    """
    if not enabled:
        _record(name, "disabled")
        return
    try:
        starter()
        _record(name, "started")
        log.info("Service %s started", name)
    except Exception as e:
        # log.exception writes the traceback at ERROR level.
        log.exception("Service %s failed to start", name)
        _record(name, "failed", error=str(e))


def start_services(settings) -> dict:
    """Boot the background daemon services according to feature flags.

    Called from server/main.py's lifespan so `uvicorn backend.server.main:app`
    launches the full stack. Also called from the daemon CLI wrapper below.

    Each service starts in its own try/except so one bad service (missing
    model, no mic, permission denied) does not prevent the others from
    booting or crash the whole server. Per-service outcomes are queryable
    via GET /system/services.

    Returns an opaque handle for stop_services().
    """
    # Deferred imports so this module stays cheap to import from server startup.
    from backend.daemon.trigger import handle_wake, on_wake_detected, on_barge_in
    from backend.daemon.wake_word import WakeWordListener
    from backend.daemon.clipboard_watcher import watcher as cb_watcher
    from backend.daemon.vision_loop import vision_loop
    from backend.daemon.telemetry import telemetry_loop
    from backend.daemon import preload
    from backend.ai_modules.speech import stt_groq
    from backend.core.agents.watcher import watcher as watcher_agent

    SERVICE_STATUS.clear()
    handle: dict = {"listener": None, "listener_thread": None}

    # Warm phi3 + nomic on a background thread. First spoken command after a
    # boot used to pay phi3's 6408ms cold load (vs 861ms warm), and the first
    # command is usually the one being demonstrated.
    _start_one("preload", settings.enable_model_preload, preload.start)

    # Re-embed memory into the active local embedder's collections, from the
    # stored text, on a background thread. Resumable; sources untouched.
    from backend.core.memory import migration as memory_migration
    _start_one("memory-migration", True, memory_migration.start_background)

    _start_one("clipboard", settings.enable_clipboard, cb_watcher.start)
    _start_one("vision",    settings.enable_vision,    vision_loop.start)
    _start_one("watcher",   settings.enable_watcher,   watcher_agent.start)
    _start_one("telemetry", settings.enable_telemetry, telemetry_loop.start)
    # Cheap TCP probe, no API call and no quota. Sets the offline memo BEFORE
    # a command needs it, so the first utterance of an outage does not
    # discover the problem by waiting out a connect timeout.
    _start_one("stt-connectivity", True, stt_groq.start_connectivity_monitor)

    # Phase 2 browser: LAZY. We don't launch Chromium here — we just
    # record the availability so /system/services can report "ready"
    # (registered but not launched) vs "disabled" (feature flag off).
    # The actual launch happens on first browser tool call. Shutdown
    # hook lives in stop_services below.
    if settings.enable_browser:
        _record("browser", "started", error="lazy: launches on first browser tool call")
    else:
        _record("browser", "disabled")

    # Wake word is a different shape (spawns a thread we need to track for
    # stop_services) so it doesn't fit the plain _start_one() lambda pattern.
    # Same try/except semantics though — record success/failure, never crash.
    if not settings.enable_wake_word:
        _record("wake_word", "disabled")
    else:
        try:
            listener = WakeWordListener(
                on_wake=handle_wake,
                on_wake_detected=lambda: on_wake_detected(emit=None),
                on_barge_in=lambda rms: on_barge_in(rms, emit=None),
                wake_phrase=settings.wake_phrase,
                capture_seconds=settings.wake_capture_seconds,
                device=settings.wake_device,
            )
            t = threading.Thread(target=listener.listen, name="wake-listener", daemon=True)
            t.start()
            handle["listener"] = listener
            handle["listener_thread"] = t
            _record("wake_word", "started")
            log.info("Service wake_word started")
        except Exception as e:
            log.exception("Service wake_word failed to start")
            _record("wake_word", "failed", error=str(e))

    return handle


def stop_services(handle: dict) -> None:
    """Stop everything start_services booted. Safe to call with a partial handle."""
    import asyncio
    from backend.daemon.clipboard_watcher import watcher as cb_watcher
    from backend.daemon.vision_loop import vision_loop
    from backend.daemon.telemetry import telemetry_loop
    from backend.core.agents.watcher import watcher as watcher_agent

    listener = handle.get("listener")
    listener_thread = handle.get("listener_thread")
    if listener is not None:
        try:
            listener.stop()
        except Exception as e:
            log.debug("Wake-word listener stop failed: %s", e)
    if listener_thread is not None:
        listener_thread.join(timeout=2.0)

    # Guard each stop the same way so shutdown never crashes either.
    for name, stopper in (
        ("telemetry", telemetry_loop.stop),
        ("watcher",   watcher_agent.stop),
        ("vision",    vision_loop.stop),
        ("clipboard", cb_watcher.stop),
    ):
        try:
            stopper()
        except Exception as e:
            log.debug("Service %s stop failed: %s", name, e)

    # Phase 2: browser close is async (Playwright). Only fires if the
    # browser was actually launched during runtime — lazy-start means
    # most sessions don't need this. Best-effort: if a loop is running
    # (server lifespan on shutdown), schedule and don't wait. Otherwise
    # run a fresh loop synchronously so a CLI-driven shutdown still cleans up.
    try:
        from backend.core.browser.manager import browser_manager
        if browser_manager.is_launched:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(browser_manager.close())
                else:
                    loop.run_until_complete(browser_manager.close())
            except RuntimeError:
                # No running loop and get_event_loop() refused — make a fresh one.
                new_loop = asyncio.new_event_loop()
                try:
                    new_loop.run_until_complete(browser_manager.close())
                finally:
                    new_loop.close()
    except Exception as e:
        log.debug("Browser close failed: %s", e)


class RedactingFormatter(logging.Formatter):
    """Scrub secrets from every line. uvicorn logs each WebSocket handshake
    with its full query string, and the HUD's session token rides there
    (/ws/ui?token=...) — so the log file held a live credential."""

    _SECRET = re.compile(r"(token=)[^&\s\"']+")

    def format(self, record: logging.LogRecord) -> str:
        return self._SECRET.sub(r"\1<redacted>", super().format(record))


def configure_logging() -> Path:
    """Root logger → console + a rotating file in the data dir.

    Without this the app's own INFO lines went nowhere (uvicorn configures only
    its own loggers), and an installed copy has no console at all — so a user's
    bug report had no log to attach. Called from the entry point, never at
    import, so the test suite does not write to the real log.
    """
    from logging.handlers import RotatingFileHandler
    from backend.core import paths

    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = paths.LOG_DIR / "sg_cube.log"
    fmt = RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=3,
                                       encoding="utf-8")
    file_handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    if sys.stderr is not None:  # None under pythonw — no console to write to
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
    return log_file


# ── single instance ──────────────────────────────────────────────────────
# One backend per data folder. The mutex stops a second one however it was
# started (shortcut, sg_cube.bat, a terminal); the PID file tells the
# launcher which process to open or stop — checked against the process's
# start time and argv, never by matching text in a command line (a shell or
# an editor showing "backend.daemon.main" must never be taken for it).
_instance_mutex = None


def pid_file() -> Path:
    from backend.core import paths
    return paths.DATA_DIR / "sg_cube.pid"


def _mutex_name() -> str:
    import hashlib
    from backend.core import paths
    tag = hashlib.sha256(str(paths.DATA_DIR.resolve()).lower().encode()).hexdigest()[:16]
    return f"Local\\SG-CUBE-{tag}"


def claim_single_instance(port: int) -> bool:
    """Take this data folder's instance mutex and write the PID file.
    False = another SG-CUBE backend already holds it."""
    global _instance_mutex
    import atexit
    import json
    import psutil
    import win32api
    import win32event
    import winerror

    handle = win32event.CreateMutex(None, False, _mutex_name())
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.CloseHandle(handle)
        return False
    _instance_mutex = handle  # held for the life of the process
    me = psutil.Process()
    pf = pid_file()
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(json.dumps({"pid": me.pid, "create_time": me.create_time(), "port": port}),
                  encoding="utf-8")

    def _remove():
        try:
            if json.loads(pf.read_text(encoding="utf-8")).get("pid") == me.pid:
                pf.unlink()
        except (OSError, ValueError):
            pass
    atexit.register(_remove)
    return True


def warn_if_exposed(host: str, allow_lan_hud: bool) -> str | None:
    """Warn when the server listens beyond this machine. Returns the warning.

    /ws/ui accepts confirmation answers ("yes, delete that file"). Measured
    with a LAN peer against a 0.0.0.0 bind: /api/session 403, /ws/ui 4403,
    command routes 401 — refused, but only because ALLOW_LAN_HUD is off; the
    port itself (e.g. /health) answers the whole network either way."""
    import ipaddress

    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if loopback:
        return None
    if allow_lan_hud:
        msg = (f"Listening on {host}: reachable from the network, and ALLOW_LAN_HUD=true, so "
               "any device on your LAN that obtains the session token can answer confirmation "
               "prompts (/ws/ui). Bind to 127.0.0.1 unless you need the HUD on another device.")
    else:
        msg = (f"Listening on {host}: reachable from the network. The confirmation endpoint "
               "(/ws/ui) and /api/session still refuse non-local peers (ALLOW_LAN_HUD is off), "
               "but the port is exposed. Set APP_HOST=127.0.0.1 unless you need LAN access.")
    log.warning(msg)
    return msg


def main() -> None:
    """Thin CLI wrapper: bridge legacy args → env vars, then run uvicorn.

    All service startup now happens inside server/main.py's lifespan, so
    `uvicorn backend.server.main:app` and `python -m backend.daemon.main`
    boot the exact same stack.
    """
    ap = argparse.ArgumentParser(
        description="SG_CUBE daemon — thin CLI around uvicorn. "
        "Prefer setting env vars in .env and running `uvicorn backend.server.main:app` directly."
    )
    ap.add_argument("--wake-phrase", default=None)
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--capture-seconds", type=float, default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None, help="Web server port (default: from .env or 8001)")
    ap.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload for development")
    args = ap.parse_args()

    # Bridge CLI args → env vars BEFORE settings loads, so pydantic picks them up.
    if args.wake_phrase is not None:
        os.environ["WAKE_PHRASE"] = args.wake_phrase
    if args.device is not None:
        os.environ["WAKE_DEVICE"] = str(args.device)
    if args.capture_seconds is not None:
        os.environ["WAKE_CAPTURE_SECONDS"] = str(args.capture_seconds)

    import uvicorn
    from backend.core import paths
    from backend.server.config import settings

    log_file = configure_logging()
    host = args.host or settings.app_host
    port = args.port or settings.app_port
    if not claim_single_instance(port):
        log.error("SG-CUBE is already running for this data folder (%s); not starting a "
                  "second backend", paths.DATA_DIR)
        sys.exit(3)
    log.info("Starting SG_CUBE web server on http://%s:%s", host, port)
    warn_if_exposed(host, settings.allow_lan_hud)
    log.info("Data dir %s, log file %s", paths.DATA_DIR, log_file)

    uvicorn.run(
        "backend.server.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
        # Keep uvicorn from replacing the root handlers configured above.
        log_config=None,
    )


if __name__ == "__main__":
    main()
