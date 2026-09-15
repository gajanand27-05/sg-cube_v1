"""Drive every demo command through the real pipeline, without a microphone.

    .venv\\Scripts\\python.exe tools\\sweep_commands.py
    .venv\\Scripts\\python.exe tools\\sweep_commands.py --only volume brightness

Posts each phrase to /orchestrate/process, which is the POST-STT path: rule
tier -> planner -> Guardian -> Operator -> tools -> spoken text. Everything a
spoken command does except the microphone, the wake word and STT.

Use it to decide what belongs in a demo script. A command that fails here will
certainly fail out loud; one that passes here still has to survive the mic.

Read-only and reversible commands only. Nothing here shuts down the machine,
deletes a file, sends a message or locks the screen — a sweep that fires
destructive tools is a sweep you run once.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "http://127.0.0.1:8001"

# (group, phrase). Grouped so --only can pick a slice for a rehearsal.
COMMANDS: list[tuple[str, str]] = [
    ("instant",    "what time is it"),
    ("instant",    "stop"),

    ("system",     "battery status"),
    ("system",     "system status"),
    ("system",     "list open windows"),
    ("system",     "what monitors do i have"),

    ("volume",     "what's the volume"),
    ("volume",     "set volume to seventy"),
    ("volume",     "volume up"),
    ("volume",     "volume down"),

    ("brightness", "what's the brightness"),
    ("brightness", "set brightness to forty"),
    ("brightness", "brightness up"),

    ("info",       "what is 15 times 12"),
    ("info",       "define serendipity"),
    ("info",       "translate hello to spanish"),
    ("info",       "what's the weather"),
    ("info",       "what's the news"),

    ("memory",     "take a note buy milk"),
    ("memory",     "read my notes"),
    ("memory",     "remember that my favourite colour is blue"),
    ("memory",     "list my reminders"),
    ("memory",     "set a timer for 5 minutes"),

    ("screen",     "read my screen"),
    ("screen",     "take a screenshot"),

    ("fun",        "tell me a joke"),
    ("fun",        "roll a dice"),
    ("fun",        "flip a coin"),
    ("fun",        "generate a password"),

    ("contacts",   "list my contacts"),
    ("files",      "find file report.pdf"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="only these groups")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--json", type=str, help="write full results to this path")
    ap.add_argument("--execute", action="store_true",
                    help="also RUN each resolved intent. Changes the machine: "
                         "sets volume to 70 and brightness to 40. Routing-only "
                         "by default.")
    args = ap.parse_args()

    items = [(g, p) for g, p in COMMANDS
             if not args.only or g in args.only]

    try:
        httpx.get(f"{BASE}/health", timeout=5).raise_for_status()
    except Exception as e:
        print(f"backend not reachable at {BASE} — start it first ({type(e).__name__})")
        return 1

    print(f"{len(items)} commands through /orchestrate/process"
          f"{' + /execute' if args.execute else ' (routing only)'}\n")
    print(f"{'group':11} {'said':34} {'ms':>6}  {'tier':7} {'action':22}")
    print("-" * 100)

    results = []
    slow = fails = 0
    with httpx.Client(timeout=args.timeout) as c:
        for group, phrase in items:
            t0 = time.monotonic()
            layer = action = "?"
            try:
                r = c.post(f"{BASE}/orchestrate/process", json={"text": phrase})
                dt = (time.monotonic() - t0) * 1000
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                layer = body.get("source_layer", "?")
                action = (body.get("intent") or {}).get("action", "?")
                ok = r.status_code == 200 and body.get("status") == "success"
            except Exception as e:
                dt = (time.monotonic() - t0) * 1000
                action = f"{type(e).__name__}: {str(e)[:30]}"
                ok = False
                body = {}

            # Optionally EXECUTE, because routing to a tool is not proof the
            # tool works. Off by default: this list includes set_volume and
            # set_brightness, which change the machine.
            ran = ""
            if ok and args.execute and action not in ("agent_complete", "?"):
                try:
                    intent = body["intent"]
                    er = c.post(f"{BASE}/execute", json={
                        "action": intent["action"],
                        "target": intent.get("target", ""),
                        "args": intent.get("args", {}) or {},
                    })
                    eb = er.json() if er.status_code == 200 else {}
                    msg = (eb.get("message") or eb.get("reason") or "")
                    ran = f" -> {str(msg)[:40]}" if msg else f" -> HTTP {er.status_code}"
                    if er.status_code != 200:
                        ok = False
                except Exception as e:
                    ran = f" -> {type(e).__name__}"
                    ok = False

            # The planner tier is where the seconds go; the rule tier is free.
            mark = ("FAIL" if not ok
                    else "SLOW" if dt > 6000
                    else "ok  ")
            fails += mark == "FAIL"
            slow += mark == "SLOW"

            print(f"{group:11} {phrase[:34]:34} {dt:6.0f}  {layer:7} {action[:22]:22} [{mark}]{ran}")
            results.append({"group": group, "said": phrase, "ms": round(dt),
                            "layer": layer, "action": action,
                            "status": mark.strip(), "raw": body})

    n = len(results)
    clean = sum(1 for r in results if r["status"] == "ok")
    print("\n" + "=" * 100)
    print(f"{clean}/{n} clean   {slow} slow(>6s)   {fails} failed")

    # Group by the tier the router ACTUALLY reported. Note that a second run
    # reports `cache` where the first reported `rule` — the cache is warmed by
    # the first pass. Both are sub-20ms and neither touches the LLM, but a
    # demo rehearsed on cached phrasings is not measuring a cold start.
    by_layer: dict[str, list] = {}
    for r in results:
        by_layer.setdefault(r["layer"], []).append(r)
    for layer in sorted(by_layer, key=lambda k: -len(by_layer[k])):
        rows = by_layer[layer]
        t = sorted(r["ms"] for r in rows)
        note = "  <- no LLM, instant" if layer in ("rule", "cache") else "  <- LLM round trip"
        print(f"  {layer:8} n={len(rows):3}  p50={t[len(t)//2]:6.0f}ms  "
              f"max={t[-1]:7.0f}ms{note}")

    agent = [r for r in results if r["layer"] not in ("rule", "cache")]
    if agent:
        worst = sorted(agent, key=lambda r: -r["ms"])[:4]
        print("\n  slowest, keep these OUT of a timed demo:")
        for r in worst:
            print(f"    {r['ms']:7.0f}ms  {r['said']}")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
