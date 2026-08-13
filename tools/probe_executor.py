"""Phase 6 + 10a + 10b + 10c verification: call SafeExecutor.execute() with assorted Intents.

Default run: only side effect is opening Notepad (test 1). Validation/blocked
cases never spawn anything.

  python tools/test_executor.py

UAC run: also fires real Windows UAC prompts for regedit / task manager /
powershell. Click No on each dialog to keep the test non-destructive.

  python tools/test_executor.py --include-uac

Browser run: also opens 4 browser tabs (Google, YouTube search, YouTube watch
via yt-dlp first-result, and a URL). Close them after.

  python tools/test_executor.py --include-browser

  All three:  --include-uac --include-browser
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
    # ── happy path: app launch ────────────────────────────────────────
    ("open_app/notepad — opens notepad",             Intent(action="open_app", target="notepad")),
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

    # ── 10c validation (queries blocked when empty) ───────────────────
    ("search_google empty",                          Intent(action="search_google", target="")),
    ("search_youtube empty",                         Intent(action="search_youtube", target="")),
    ("play_youtube empty",                           Intent(action="play_youtube", target="")),
    ("open_url empty",                               Intent(action="open_url", target="")),
    ("open_url dangerous",                           Intent(action="open_url", target="system32")),

    # ── meta ──────────────────────────────────────────────────────────
    ("get_time",                                     Intent(action="get_time", target="")),
]

UAC_CASES: list[tuple[str, Intent]] = [
    ("open_app/regedit — UAC prompt",                Intent(action="open_app", target="regedit")),
    ("open_app/task manager — UAC prompt",           Intent(action="open_app", target="task manager")),
    ("open_app/powershell — UAC prompt",             Intent(action="open_app", target="powershell")),
]

BROWSER_CASES: list[tuple[str, Intent]] = [
    ("open_url github.com",                          Intent(action="open_url", target="github.com")),
    ("search_google 'python tutorials'",             Intent(action="search_google", target="python tutorials")),
    ("search_youtube 'lo-fi beats'",                 Intent(action="search_youtube", target="lo-fi beats")),
    ("play_youtube 'happy by pharrell' (yt-dlp)",    Intent(action="play_youtube", target="happy by pharrell")),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-uac", action="store_true",
                    help="Run system-app tests that trigger real Windows UAC dialogs.")
    ap.add_argument("--include-browser", action="store_true",
                    help="Run tests that open browser tabs (search/play/url).")
    args = ap.parse_args()

    cases = SAFE_CASES.copy()
    if args.include_uac:
        cases += UAC_CASES
    if args.include_browser:
        cases += BROWSER_CASES

    print(f"{'case':<48} {'status':<8} {'lat':>5}  detail")
    print("-" * 100)
    for label, intent in cases:
        if args.include_uac and intent in (c[1] for c in UAC_CASES):
            print(f"  >>> next test fires UAC for {intent.target!r}. Click No to keep the test clean. <<<")
        r = execute(intent)
        detail = r.message or r.reason or ""
        if len(detail) > 70:
            detail = detail[:67] + "..."
        print(f"{label:<48} {r.status:<8} {r.latency_ms:>5}ms  {detail}")


if __name__ == "__main__":
    main()
