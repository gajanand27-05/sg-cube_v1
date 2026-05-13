"""Launch the SG_CUBE always-on wake-word daemon.

Says "sg cube" to wake it, then your command in the next 5 seconds.
Example: "sg cube" ... beep ... "open notepad"

Usage:
    python tools/run_daemon.py
    python tools/run_daemon.py --device 22         # bluetooth headset (see record_clip.py --list)
    python tools/run_daemon.py --wake-phrase "hey cube"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.daemon.main import main  # noqa: E402

if __name__ == "__main__":
    main()
