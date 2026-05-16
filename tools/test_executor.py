"""Phase 6 + 10a + 10b verification: call SafeExecutor.execute() with assorted Intents.

Default run (no flag): only side effect is opening Notepad. All system-app /
dangerous / unknown cases are rejected before any process spawn.

  python tools/test_executor.py

UAC run (--include-uac): also fires real Windows UAC prompts for regedit,
task manager, powershell. You'll see UAC dialogs pop up — click No on each
to verify the "blocked" path, or Yes if you actually want them to launch.

  python tools/test_executor.py --include-uac
"""
import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.orchestrator.llm_layer import Intent  # noqa: E402
from backend.core.safe_executor.executor import execute  # noqa: E402

SAFE_CASES: list[tuple[str, Intent]] = [
    # ── happy path ────────────────────────────────────────────────────
    ("open_app/notepad — opens notepad",             Intent(action="open_app", target="notepad")),

    # ── any-installed-app launch (no allowlist) ───────────────────────
    ("open_app/firefox — start command attempt",     Intent(action="open_app", target="firefox")),
    ("open_app/spotify — start command attempt",     Intent(action="open_app", target="spotify")),
    ("open_app/fakeappxyz — start launches anyway",  Intent(action="open_app", target="fakeappxyz")),

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

UAC_CASES: list[tuple[str, Intent]] = [
    ("open_app/regedit — UAC prompt",                Intent(action="open_app", target="regedit")),
    ("open_app/task manager — UAC prompt",           Intent(action="open_app", target="task manager")),
    ("open_app/powershell — UAC prompt",             Intent(action="open_app", target="powershell")),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--include-uac",
        action="store_true",
        help="Run system-app tests that trigger real Windows UAC dialogs. "
             "You'll need to click No on each to keep the test non-destructive.",
    )
    args = ap.parse_args()

    cases = SAFE_CASES + (UAC_CASES if args.include_uac else [])

    print(f"{'case':<48} {'status':<8} {'lat':>5}  detail")
    print("-" * 100)
    for label, intent in cases:
        if args.include_uac and intent in (c[1] for c in UAC_CASES):
            print(f"  >>> next test fires UAC for {intent.target!r}. Click No to keep the test clean. <<<")
        r = execute(intent)
        detail = r.message or r.reason or ""
        if len(detail) > 70:
            detail = detail[:67] + "..."
        print(f"{label:<48} {r.status:<8} {r.latency_ms:>4}ms  {detail}")


if __name__ == "__main__":
    main()
