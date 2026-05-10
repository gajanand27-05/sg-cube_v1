"""End-to-end Phase 3 test:
  1. Record 5s from your mic
  2. Login to get a Supabase JWT
  3. POST the WAV to /voice/transcribe
  4. Print the transcribed text + latency

Usage:
    python tools/test_transcribe.py
    python tools/test_transcribe.py --duration 8
    TEST_USER_EMAIL=foo@gmail.com TEST_USER_PASSWORD=... python tools/test_transcribe.py

Requires the server running on http://127.0.0.1:8000.
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
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"Login did not succeed: {body}")
    return body["access_token"]


def transcribe(client: httpx.Client, token: str, clip: Path) -> dict:
    with clip.open("rb") as f:
        r = client.post(
            f"{BASE}/voice/transcribe",
            headers={"Authorization": f"Bearer {token}"},
            files={"audio": (clip.name, f, "audio/wav")},
            timeout=60.0,
        )
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=5)
    ap.add_argument("--clip", type=Path, default=Path("tools/_recordings/clip.wav"))
    ap.add_argument("--device", type=str, default=None,
                    help="Input device index or substring (see record_clip.py --list)")
    args = ap.parse_args()

    record(args.duration, args.clip, resolve_device(args.device))

    with httpx.Client() as client:
        print("Logging in...")
        token = login(client)
        print("Transcribing...")
        result = transcribe(client, token, args.clip)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
