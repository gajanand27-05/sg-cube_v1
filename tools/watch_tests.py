"""Test monitor — reruns pytest on every Python change under backend/ and tests/.

Run it with the venv interpreter, not a bare `python`: the runner reuses
sys.executable, and the system Python has no cv2/torch, which fails five vision
tests for reasons that have nothing to do with your edit.

    .venv/Scripts/python.exe tools/watch_tests.py
"""
import sys
import time
import subprocess
from pathlib import Path

from watchfiles import PythonFilter, watch

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
BACKEND = ROOT / "backend"

GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
RESET = "\x1b[0m"
CYAN = "\x1b[36m"


def run_tests() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(TESTS), "-v", "--tb=short", "-q"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )

    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if "passed" in line:
                print(f"\n{GREEN}PASS  {line.strip()}{RESET}")
                break
        return True
    else:
        for line in result.stdout.splitlines():
            if "failed" in line or "error" in line.lower() or "passed" in line:
                print(f"\n{RED}FAIL  {line.strip()}{RESET}")
                break
        return False


def main() -> None:
    print(f"{CYAN}SG Cube Test Monitor{RESET}")
    print(f"{YELLOW}Watching: backend/, tests/{RESET}")
    print(f"{YELLOW}Press Ctrl+C to stop{RESET}\n")

    run_tests()

    # PythonFilter(), not the string "python": watchfiles CALLS watch_filter,
    # so a str raised TypeError on the first save. The watcher printed one
    # pytest run at startup and then died at the first edit — which looks
    # enough like "it works" to have survived unnoticed.
    for changes in watch(str(BACKEND), str(TESTS), watch_filter=PythonFilter()):
        files = {str(Path(c[1]).relative_to(ROOT)) for c in changes}
        print(f"\n{'─' * 50}")
        print(f"{YELLOW}Changes: {len(files)} file(s){RESET}")
        for f in sorted(files):
            print(f"  {f}")

        t0 = time.monotonic()
        passed = run_tests()
        elapsed = time.monotonic() - t0
        tag = f"{GREEN}PASS" if passed else f"{RED}FAIL"
        print(f"{'─' * 50}")
        print(f"  {tag} in {elapsed:.1f}s{RESET}\n")


if __name__ == "__main__":
    main()
