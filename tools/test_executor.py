"""Phase 6 verification: call SafeExecutor.execute() directly with assorted Intents.

Side effect: opens Notepad. Close it manually after the test.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.orchestrator.llm_layer import Intent  # noqa: E402
from backend.core.safe_executor.executor import execute  # noqa: E402

CASES: list[tuple[str, Intent]] = [
    ("allowlisted open_app/notepad",        Intent(action="open_app", target="notepad")),
    ("non-allowlisted open_app/firefox",    Intent(action="open_app", target="firefox")),
    ("dangerous target (system32)",         Intent(action="open_app", target="system32")),
    ("dangerous target (..\\Windows)",      Intent(action="open_app", target="..\\Windows")),
    ("empty target open_app",               Intent(action="open_app", target="")),
    ("unrecognized action",                 Intent(action="delete_system32", target="")),
    ("intent action='unknown'",             Intent(action="unknown", target="")),
    ("get_time",                            Intent(action="get_time", target="")),
]


def main():
    print(f"{'case':<38} {'status':<8} {'lat':>5}  detail")
    print("-" * 80)
    for label, intent in CASES:
        r = execute(intent)
        detail = r.message or r.reason or ""
        print(f"{label:<38} {r.status:<8} {r.latency_ms:>4}ms  {detail}")


if __name__ == "__main__":
    main()
