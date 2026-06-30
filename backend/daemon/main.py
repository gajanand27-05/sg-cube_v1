import argparse
import logging
import sys
import threading

# Force UTF-8 stdout/stderr before importing anything that prints unicode.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import uvicorn

# Bootstrap tool registry — triggers all @tool decorators before any agent runs.
import backend.core.tools  # noqa: F401

# Initialize LLM provider — single interface for all model backends
from backend.ai_modules.llm import create_llm_provider
create_llm_provider()

# Initialize async event bus — must be done on the event loop
from backend.core.events import init_event_bus, get_bus

from backend.daemon.trigger import handle_wake, on_wake_detected
from backend.daemon.wake_word import WakeWordListener
from backend.daemon.clipboard_watcher import watcher as cb_watcher
from backend.daemon.vision_loop import vision_loop
from backend.daemon.telemetry import telemetry_loop
from backend.core.agents.watcher import watcher as watcher_agent
from backend.server.config import settings

log = logging.getLogger(__name__)


def _run_headless(args) -> None:
    # Start background services
    cb_watcher.start()
    vision_loop.start()
    watcher_agent.start()
    telemetry_loop.start()

    listener = WakeWordListener(
        on_wake=handle_wake,
        on_wake_detected=lambda: on_wake_detected(emit=None),
        wake_phrase=args.wake_phrase,
        capture_seconds=args.capture_seconds,
        device=args.device,
    )
    listener_thread = threading.Thread(
        target=listener.listen, name="wake-listener", daemon=True
    )
    listener_thread.start()

    # Start the FastAPI web server (uvicorn creates the event loop)
    host = args.host or settings.app_host
    port = args.port or settings.app_port
    log.info(f"Starting SG_CUBE web server on http://{host}:{port}")

    try:
        uvicorn.run(
            "backend.server.main:app",
            host=host,
            port=port,
            reload=args.reload,
            log_level="info",
        )
    except KeyboardInterrupt:
        print("\n[daemon] stopping...")
    finally:
        telemetry_loop.stop()
        watcher_agent.stop()
        vision_loop.stop()
        cb_watcher.stop()
        listener.stop()
        listener_thread.join(timeout=2.0)


def main() -> None:
    ap = argparse.ArgumentParser(description="SG_CUBE daemon — web server + background services")
    ap.add_argument("--wake-phrase", default="onyx")
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--capture-seconds", type=float, default=2.5)
    ap.add_argument("--host", default=None, help="Web server host (default: from .env or 127.0.0.1)")
    ap.add_argument("--port", type=int, default=None, help="Web server port (default: from .env or 8000)")
    ap.add_argument("--reload", action="store_true", help="Enable uvicorn auto-reload for development")
    args = ap.parse_args()

    _run_headless(args)


if __name__ == "__main__":
    main()
