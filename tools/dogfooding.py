"""Dogfooding CLI — manual bug logging + status snapshot.

Usage:
    python tools/dogfooding.py status
    python tools/dogfooding.py bug p0 "volume slider didn't move on Windows 11"
    python tools/dogfooding.py bug P1 "second wake word gets ignored after follow-up"

Counter state lives in backend/database/dogfooding.json (shared with the daemon).
"""
import argparse
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.dogfooding import ledger as dg
from backend.core.dogfooding import _LEDGER_PATH  # noqa: E402


def _fmt_pct(v):
    return f"{v}%" if v is not None else "n/a"


def cmd_status(_args) -> int:
    s = dg.snapshot()
    r = s["rates"]
    print(f"Ledger: {_LEDGER_PATH}")
    print(f"  session_id:               {s.get('session_id')}")
    print(f"  started_at:               {s.get('started_at')}")
    print(f"  first_command_at:         {s.get('first_command_at')}")
    print(f"  last_command_at:          {s.get('last_command_at')}")
    print()
    print(f"  wake_attempts / successes:{s.get('wake_attempts', 0):>6} / {s.get('wake_successes', 0):<6}  -> wake_success: {_fmt_pct(r['wake_success_pct'])}")
    print(f"  command_total / success:  {s.get('command_total', 0):>6} / {s.get('command_success', 0):<6}  -> command_success: {_fmt_pct(r['command_success_pct'])}")
    print(f"  tools_total / success:    {s.get('tools_total', 0):>6} / {s.get('tools_success', 0):<6}  -> tool_success: {_fmt_pct(r['tool_success_pct'])}")
    print(f"  crashes:                  {s.get('crashes', 0):>6}                    -> crash_rate: {_fmt_pct(r['crash_rate_pct'])}")
    avg = r['avg_command_latency_ms']
    avg_str = f"{avg}ms" if avg is not None else "n/a"
    print(f"  avg command latency:      {avg_str}")
    print()
    print(f"  P0 bugs: {s.get('p0_bugs', 0)}   P1 bugs: {s.get('p1_bugs', 0)}")
    bugs = s.get("bugs") or []
    if bugs:
        print(f"  recent bugs (latest 5 of {len(bugs)}):")
        for b in bugs[-5:]:
            print(f"    [{b['priority']}] {b['ts']}  {b['description']}")
    return 0


def cmd_bug(args) -> int:
    if not args.description:
        print("error: bug description required", file=sys.stderr)
        return 2
    entry = dg.record_bug(args.priority, args.description)
    print(f"logged [{entry['priority']}] @ {entry['ts']}: {entry['description']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="SG_CUBE dogfooding ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="print current counters and rates").set_defaults(func=cmd_status)

    bp = sub.add_parser("bug", help="log a P0/P1 bug")
    bp.add_argument("priority", choices=["p0", "p1", "P0", "P1"], help="bug priority")
    bp.add_argument("description", help="short description of the bug")
    bp.set_defaults(func=cmd_bug)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
