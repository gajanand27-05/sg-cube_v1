import argparse

from backend.daemon.trigger import handle_wake
from backend.daemon.wake_word import WakeWordListener


def main():
    ap = argparse.ArgumentParser(description="SG_CUBE always-on wake-word daemon")
    ap.add_argument("--wake-phrase", default="sg cube",
                    help='Wake phrase Vosk listens for (default: "sg cube")')
    ap.add_argument("--device", type=int, default=None,
                    help="Input device index (omit for default mic)")
    ap.add_argument("--capture-seconds", type=int, default=5,
                    help="Seconds of audio to grab after wake (default 5)")
    args = ap.parse_args()

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


if __name__ == "__main__":
    main()
