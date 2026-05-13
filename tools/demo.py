"""Phase 8 end-to-end demo:
   record 5s from your mic → POST /voice/process → app runs the command,
   speaks the response, and prints the structured result.

Usage:
    python tools/demo.py                     # records 5s, default user
    python tools/demo.py --duration 8
    python tools/demo.py --device "Rockerz"  # specific input device
"""
import argparse
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.record_clip import record, resolve_device  # noqa: E402

BASE = os.environ.get("SGCUBE_BASE", "http://127.0.0.1:8000")
EMAIL = os.environ.get("TEST_USER_EMAIL", "sgcube.user.1778339955@gmail.com")
PASSWORD = os.environ.get("TEST_USER_PASSWORD", "TestPass123!")


def login(client: httpx.Client) -> str:
    r = client.post(
        f"{BASE}/auth/login",
        json={"email": EMAIL, "password": PASSWORD, "role": "user"},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def process(client: httpx.Client, token: str, clip: Path) -> dict:
    with clip.open("rb") as f:
        r = client.post(
            f"{BASE}/voice/process",
            headers={"Authorization": f"Bearer {token}"},
            files={"audio": (clip.name, f, "audio/wav")},
            timeout=120.0,
        )
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=5)
    ap.add_argument("--device", type=str, default=None,
                    help="Input device index or substring")
    ap.add_argument("--clip", type=Path, default=Path("tools/_recordings/demo.wav"))
    args = ap.parse_args()

    record(args.duration, args.clip, resolve_device(args.device))

    with httpx.Client() as client:
        print("\nLogging in...")
        token = login(client)
        print("Sending to /voice/process (this will speak the reply)...\n")
        result = process(client, token, args.clip)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
