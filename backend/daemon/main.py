import argparse
import sys
import threading

# Force UTF-8 stdout/stderr before importing anything that prints unicode.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from backend.daemon.trigger import handle_wake
from backend.daemon.wake_word import WakeWordListener


def _run_terminal(args) -> None:
    from backend.daemon.ui import SGCubeApp

    app = SGCubeApp()

    def emit(event):
        try:
            app.call_from_thread(app.handle_daemon_event, event)
        except Exception as e:
            print(f"[main] failed to push UI event: {e}")

    def on_wake(audio: bytes) -> None:
        handle_wake(audio, emit=emit)

    listener = WakeWordListener(
        on_wake=on_wake,
        wake_phrase=args.wake_phrase,
        capture_seconds=args.capture_seconds,
        device=args.device,
    )
    app._listener_stop = listener.stop

    listener_thread = threading.Thread(
        target=listener.listen, name="wake-listener", daemon=True
    )
    listener_thread.start()

    try:
        app.run()
    finally:
        listener.stop()
        listener_thread.join(timeout=2.0)


def _run_tray(args) -> None:
    from backend.daemon.tray import TrayController

    listener = WakeWordListener(
        on_wake=handle_wake,
        wake_phrase=args.wake_phrase,
        capture_seconds=args.capture_seconds,
        device=args.device,
    )
    tray = TrayController(on_quit=listener.stop)
    listener_thread = threading.Thread(
        target=listener.listen, name="wake-listener", daemon=True
    )
    listener_thread.start()
    try:
        tray.run()
    finally:
        listener.stop()
        listener_thread.join(timeout=2.0)


def _run_headless(args) -> None:
    listener = WakeWordListener(
        on_wake=handle_wake,
        wake_phrase=args.wake_phrase,
        capture_seconds=args.capture_seconds,
        device=args.device,
    )
    try:
        listener.listen()
    except KeyboardInterrupt:
        print("\n[daemon] stopping...")
        listener.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="SG_CUBE always-on wake-word daemon")
    ap.add_argument("--wake-phrase", default="sg cube")
    ap.add_argument("--device", type=int, default=None)
    ap.add_argument("--capture-seconds", type=float, default=2.5)
    ap.add_argument(
        "--ui",
        choices=["terminal", "tray", "none"],
        default="terminal",
        help="UI mode: terminal (default, sci-fi Textual), tray (legacy Phase 9b), or none (autostart/headless).",
    )
    ap.add_argument("--no-tray", action="store_true",
                    help="Legacy alias for --ui none.")
    args = ap.parse_args()

    if args.no_tray:
        args.ui = "none"

    if args.ui == "terminal":
        _run_terminal(args)
    elif args.ui == "tray":
        _run_tray(args)
    else:
        _run_headless(args)


if __name__ == "__main__":
    main()
