import argparse
import logging
import os
import sys
import threading
from datetime import datetime, timezone
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
    from backend.daemon.trigger import handle_wake, on_wake_detected
    from backend.daemon.wake_word import WakeWordListener
    from backend.daemon.clipboard_watcher import watcher as cb_watcher
    from backend.daemon.vision_loop import vision_loop
    from backend.daemon.telemetry import telemetry_loop
    from backend.core.agents.watcher import watcher as watcher_agent

    SERVICE_STATUS.clear()
    handle: dict = {"listener": None, "listener_thread": None}

    _start_one("clipboard", settings.enable_clipboard, cb_watcher.start)
    _start_one("vision",    settings.enable_vision,    vision_loop.start)
    _start_one("watcher",   settings.enable_watcher,   watcher_agent.start)
    _start_one("telemetry", settings.enable_telemetry, telemetry_loop.start)

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
    from backend.server.config import settings

    host = args.host or settings.app_host
    port = args.port or settings.app_port
    log.info(f"Starting SG_CUBE web server on http://{host}:{port}")

    uvicorn.run(
        "backend.server.main:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
