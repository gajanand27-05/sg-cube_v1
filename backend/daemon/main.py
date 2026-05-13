import argparse
import threading

from backend.daemon.trigger import handle_wake
from backend.daemon.tray import TrayController
from backend.daemon.wake_word import WakeWordListener


def main() -> None:
    ap = argparse.ArgumentParser(description="SG_CUBE always-on wake-word daemon")
    ap.add_argument("--wake-phrase", default="sg cube",
                    help='Wake phrase Vosk listens for (default: "sg cube")')
    ap.add_argument("--device", type=int, default=None,
                    help="Input device index (omit for default mic)")
    ap.add_argument("--capture-seconds", type=int, default=5,
                    help="Seconds of audio to grab after wake (default 5)")
    ap.add_argument("--no-tray", action="store_true",
                    help="Run as a foreground console process without a tray icon (Phase 9a behavior)")
    args = ap.parse_args()

    listener = WakeWordListener(
        on_wake=handle_wake,
        wake_phrase=args.wake_phrase,
        capture_seconds=args.capture_seconds,
        device=args.device,
    )

    if args.no_tray:
        try:
            listener.listen()
        except KeyboardInterrupt:
            print("\n[daemon] stopping...")
            listener.stop()
        return

    # Tray mode: pystray must own the main thread on Windows.
    tray = TrayController(on_quit=listener.stop)
    listener_thread = threading.Thread(target=listener.listen, name="wake-listener", daemon=True)
    listener_thread.start()
    try:
        tray.run()
    finally:
        listener.stop()
        listener_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()
