import argparse
import logging
import os
import sys
import threading

# Force UTF-8 stdout/stderr before importing anything that prints unicode.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

log = logging.getLogger(__name__)


def start_services(settings) -> dict:
    """Boot the background daemon services according to feature flags.

    Called from server/main.py's lifespan so `uvicorn backend.server.main:app`
    launches the full stack. Also called from the daemon CLI wrapper below.

    Returns an opaque handle for stop_services().
    """
    # Deferred imports so this module stays cheap to import from server startup.
    from backend.daemon.trigger import handle_wake, on_wake_detected
    from backend.daemon.wake_word import WakeWordListener
    from backend.daemon.clipboard_watcher import watcher as cb_watcher
    from backend.daemon.vision_loop import vision_loop
    from backend.daemon.telemetry import telemetry_loop
    from backend.core.agents.watcher import watcher as watcher_agent

    handle: dict = {"listener": None, "listener_thread": None}

    if settings.enable_clipboard:
        cb_watcher.start()
    if settings.enable_vision:
        vision_loop.start()
    if settings.enable_watcher:
        watcher_agent.start()
    if settings.enable_telemetry:
        telemetry_loop.start()

    if settings.enable_wake_word:
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
        except Exception as e:
            # ponytail: headless / no-mic machines should not crash the server.
            # Ceiling: silently continues without wake word. Upgrade path: expose
            # the failure via /health so the UI can show a "wake word disabled" pill.
            log.warning("Wake-word listener disabled: %s", e)

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

    telemetry_loop.stop()
    watcher_agent.stop()
    vision_loop.stop()
    cb_watcher.stop()


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
