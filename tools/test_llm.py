"""Phase 4 verification: send a phrase to Ollama, print parsed Intent.

Usage:
    python tools/test_llm.py "open notepad"
    python tools/test_llm.py "what time is it"
    python tools/test_llm.py "close chrome"

Requires Ollama running at http://localhost:11434 with the configured model
pulled (`ollama pull phi3` for default).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.core.orchestrator.llm_layer import LLMResolveError, resolve  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)

    phrase = " ".join(sys.argv[1:])
    print(f"Input: {phrase!r}")
    t0 = time.perf_counter()
    try:
        intent = resolve(phrase)
    except LLMResolveError as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    print(f"Latency: {elapsed_ms} ms")
    print("Intent:")
    print(json.dumps(intent.model_dump(), indent=2))


if __name__ == "__main__":
    main()
