"""Demo-readiness check for the voice path.

Answers one question: if you say "open notepad" tomorrow, will it work?

Checks the things that fail SILENTLY or that look like a speech problem when
they are not one. In particular the verifier's secondary check is fail-closed
(verifier.py returns False on any exception), and it routes to LOCAL Ollama —
so an unreachable Ollama, or a missing `phi3`, rejects the tool while Whisper
transcribed the words perfectly. From the outside that is indistinguishable
from "it didn't understand me".

Models are exercised, not listed: /api/tags reports models the daemon knows
about and does not prove one will actually answer.

    .venv/Scripts/python.exe tools/probe_voice_ready.py
"""
from __future__ import annotations

import io
import json
import sys
import time
import urllib.error
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from backend.server.config import settings  # noqa: E402

OK, WARN, BAD = "[ OK ]", "[WARN]", "[FAIL]"
results: list[tuple[str, str]] = []


def check(mark: str, name: str, detail: str = "") -> None:
    results.append((mark, name))
    print(f"  {mark} {name}" + (f" — {detail}" if detail else ""))


def _post(path: str, payload: dict, timeout: float) -> dict | None:
    req = urllib.request.Request(
        settings.ollama_url.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main() -> int:
    print(f"Voice-path readiness — Ollama at {settings.ollama_url}\n")

    # 1. Is it up at all?
    try:
        with urllib.request.urlopen(settings.ollama_url.rstrip("/") + "/api/tags", timeout=5) as r:
            tags = json.loads(r.read())
        installed = sorted(m["name"] for m in tags.get("models", []))
        check(OK, "Ollama reachable", f"{len(installed)} models installed")
    except Exception as e:
        check(BAD, "Ollama reachable", f"{type(e).__name__} — start it, then re-run")
        print("\nNothing else can be checked until Ollama is running.")
        return 1

    # 2. The models the voice path actually needs, exercised not listed.
    def _has(name: str) -> bool:
        base = name.split(":")[0]
        return any(m == name or m.split(":")[0] == base for m in installed)

    fast = settings.fast_model
    if not _has(fast):
        check(BAD, f"verifier model {fast!r} installed",
              f"missing — every deep-checked tool will be REJECTED. `ollama pull {fast}`")
    else:
        try:
            t0 = time.perf_counter()
            res = _post("/api/chat", {
                "model": fast,
                "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
                "stream": False,
            }, timeout=120)
            dt = (time.perf_counter() - t0) * 1000
            reply = (res.get("message") or {}).get("content", "").strip()[:40]
            mark = OK if dt < 8000 else WARN
            check(mark, f"verifier model {fast!r} answers", f"{dt:.0f}ms, said {reply!r}")
        except Exception as e:
            check(BAD, f"verifier model {fast!r} answers", f"{type(e).__name__}: {e}")

    emb = settings.embedding_model
    if not _has(emb):
        check(BAD, f"embedding model {emb!r} installed",
              f"missing — memory search stays empty. `ollama pull {emb}`")
    else:
        try:
            t0 = time.perf_counter()
            res = _post("/api/embeddings", {"model": emb, "prompt": "hello"}, timeout=60)
            dt = (time.perf_counter() - t0) * 1000
            dim = len(res.get("embedding") or [])
            check(OK if dim == 768 else BAD, f"embedding model {emb!r} answers",
                  f"{dt:.0f}ms, {dim} dims")
        except Exception as e:
            check(BAD, f"embedding model {emb!r} answers", f"{type(e).__name__}: {e}")

    # 3. Cloud planner — the thing that actually writes the plan.
    if settings.ollama_api_key:
        check(OK, "cloud planner key present", settings.ollama_cloud_model)
    else:
        check(WARN, "cloud planner key absent",
              "planning falls back to local Ollama, which is much slower")

    print()
    bad = [n for m, n in results if m == BAD]
    warn = [n for m, n in results if m == WARN]
    if bad:
        print(f"{len(bad)} blocking issue(s): {', '.join(bad)}")
    elif warn:
        print(f"ready, with {len(warn)} caveat(s): {', '.join(warn)}")
    else:
        print("voice path is ready.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
