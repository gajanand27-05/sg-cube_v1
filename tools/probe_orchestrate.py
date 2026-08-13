"""Phase 5 verification: send phrases through /orchestrate/process and print
which layer answered each one + latency.

Usage:  python tools/test_orchestrate.py
"""
import os

import httpx

BASE = os.environ.get("SGCUBE_BASE", "http://127.0.0.1:8000")
EMAIL = os.environ.get("TEST_USER_EMAIL", "sgcube.user.1778339955@gmail.com")
PASSWORD = os.environ.get("TEST_USER_PASSWORD", "TestPass123!")

PHRASES = [
    "open notepad",          # rule
    "open notepad",          # cache (exact repeat)
    "open notepad.",         # cache (normalization strips period)
    "Open  NOTEPAD",         # cache (normalization lowercases, collapses ws)
    "launch chrome",         # rule
    "close calculator",      # rule (alias: calculator -> calc)
    "what time is it",       # rule
    "play some music",       # llm fallback -> unknown
    "play some music",       # cache (repeat)
]


def main():
    with httpx.Client(timeout=120.0) as client:
        r = client.post(
            f"{BASE}/auth/login",
            json={"email": EMAIL, "password": PASSWORD, "role": "user"},
        )
        r.raise_for_status()
        token = r.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        print(f"{'layer':<7} {'latency':>9}   input  ->  intent")
        print("-" * 70)
        for phrase in PHRASES:
            r = client.post(
                f"{BASE}/orchestrate/process",
                json={"text": phrase},
                headers=headers,
            )
            r.raise_for_status()
            body = r.json()
            i = body["intent"]
            print(
                f"{body['source_layer']:<7} "
                f"{body['latency_ms']:>6} ms   "
                f"{phrase!r:30}  ->  {i['action']}/{i['target']!r}"
            )


if __name__ == "__main__":
    main()
