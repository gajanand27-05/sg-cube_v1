"""Phase 6 + 10a verification: call SafeExecutor.execute() with assorted Intents.

Side effects:
  - Test 1 opens Notepad (close it manually after).
  - All other cases are non-destructive (system app / dangerous / unknown
    targets are rejected before any process spawn).
"""
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.orchestrator.llm_layer import Intent  # noqa: E402
from backend.core.safe_executor.executor import execute  # noqa: E402

CASES: list[tuple[str, Intent]] = [
    # ── happy path ────────────────────────────────────────────────────
    ("open_app/notepad — opens notepad",             Intent(action="open_app", target="notepad")),

    # ── any-installed-app launch (no allowlist) ───────────────────────
    ("open_app/firefox — start command attempt",     Intent(action="open_app", target="firefox")),
    ("open_app/spotify — start command attempt",     Intent(action="open_app", target="spotify")),
    ("open_app/fakeappxyz — start launches anyway",  Intent(action="open_app", target="fakeappxyz")),

    # ── system-app gate (10a blocks; 10b will UAC) ────────────────────
    ("open_app/regedit — system app, blocked",       Intent(action="open_app", target="regedit")),
    ("open_app/task manager — system app, blocked",  Intent(action="open_app", target="task manager")),
    ("open_app/powershell — system app, blocked",    Intent(action="open_app", target="powershell")),

    # ── dangerous-target filter ───────────────────────────────────────
    ("dangerous: system32",                          Intent(action="open_app", target="system32")),
    ("dangerous: path traversal",                    Intent(action="open_app", target="..\\Windows")),

    # ── input validation ──────────────────────────────────────────────
    ("empty target",                                 Intent(action="open_app", target="")),
    ("unknown action",                               Intent(action="delete_system32", target="")),
    ("intent action='unknown'",                      Intent(action="unknown", target="")),

    # ── meta ──────────────────────────────────────────────────────────
    ("get_time",                                     Intent(action="get_time", target="")),
]


def main():
    print(f"{'case':<48} {'status':<8} {'lat':>5}  detail")
    print("-" * 100)
    for label, intent in CASES:
        r = execute(intent)
        detail = r.message or r.reason or ""
        if len(detail) > 70:
            detail = detail[:67] + "..."
        print(f"{label:<48} {r.status:<8} {r.latency_ms:>4}ms  {detail}")


if __name__ == "__main__":
    main()
