"""Interactive type-to-chat REPL for the agent.

No mic, no STT, no TTS — just type what you'd say to SG_CUBE and see what
gemma calls and what it would speak back. Conversation context is kept
across turns, so follow-ups work.

Usage:
    python tools/chat.py

Commands inside the REPL:
    /tools    list registered tools
    /history  show conversation context
    /clear    reset conversation context
    /quit     exit
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# UTF-8 console so unicode (Hindi, Spanish, °, etc.) prints cleanly.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from backend.core.agent import agent  # noqa: E402
from backend.core.agent.context import ConversationContext  # noqa: E402
from backend.core.tools.registry import REGISTRY  # noqa: E402


def main() -> None:
    ctx = ConversationContext()
    print(f"SG_CUBE chat REPL — {len(REGISTRY)} tools loaded. Type /help for commands.")
    print()
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue

        if text in ("/quit", "/q", "/exit"):
            break
        if text == "/help":
            print("  /tools    list registered tools")
            print("  /history  show conversation context")
            print("  /clear    reset conversation context")
            print("  /quit     exit")
            continue
        if text == "/tools":
            for name in sorted(REGISTRY):
                desc = REGISTRY[name].description
                print(f"  {name:<28s} {desc}")
            continue
        if text == "/history":
            for t in ctx.turns:
                head = t.text if len(t.text) < 120 else t.text[:117] + "..."
                print(f"  [{t.role}] {head}")
            continue
        if text == "/clear":
            ctx.clear()
            print("  context cleared.")
            continue

        t0 = time.perf_counter()
        try:
            spoken, records = agent.run(text, ctx)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        elapsed_ms = (time.perf_counter() - t0) * 1000

        for r in records:
            status = (r.get("result") or {}).get("status", "?")
            print(f"  · tool: {r['name']}({r.get('args')}) -> {status}")
        print(f"sgcube> {spoken}  [{elapsed_ms:.0f}ms]")


if __name__ == "__main__":
    main()
