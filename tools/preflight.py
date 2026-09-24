"""Demo pre-flight — one command, one green/red board.

Run this before every rehearsal and on the morning of the demo:

    .venv\\Scripts\\python.exe tools\\preflight.py            # full check
    .venv\\Scripts\\python.exe tools\\preflight.py --offline   # airplane mode

Written for the 24 Sep submission. Every check here exists because the thing
it checks actually broke, or was actually found misconfigured, during Phase 0.

Exit code is 0 only when nothing is RED, so this can gate a rehearsal.

── Why the Gemini check goes through GeminiBackend ──────────────────────
The obvious implementation — build a `genai.Client(api_key=k)` and call
`generate_content` — DOES NOT WORK in this environment. The sync path raises
"Cannot send a request, as the client has been closed" and the bare async
path raises an empty AssertionError, for keys that are provably fine. A
pre-flight built that way would report every key dead on demo morning and
send you hunting a quota problem you do not have. Ask the app's own backend
instead; it is also the thing whose behaviour you actually care about.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Quiet the import-time noise so the board is readable.
import logging
logging.disable(logging.WARNING)

GREEN, RED, WARN, DIM, BOLD, OFF = (
    "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[1m", "\033[0m"
)
if os.name == "nt":
    os.system("")  # enable ANSI on cmd.exe

results: list[tuple[str, str, str]] = []  # (state, label, detail)


def record(state: str, label: str, detail: str = "") -> None:
    results.append((state, label, detail))
    colour = {"PASS": GREEN, "FAIL": RED, "WARN": WARN, "SKIP": DIM}[state]
    mark = {"PASS": "OK  ", "FAIL": "FAIL", "WARN": "WARN", "SKIP": "skip"}[state]
    print(f"  {colour}{mark}{OFF}  {label:<38} {DIM}{detail}{OFF}")


def section(title: str) -> None:
    print(f"\n{BOLD}{title}{OFF}")


# ── 1. Config ────────────────────────────────────────────────────────────
def check_config() -> None:
    section("Config")
    from backend.server.config import settings

    # Neither backend is "correct" — they trade different things, and which one
    # is right was a deliberate decision (see .env). Report the consequences of
    # whichever is set rather than pretending there is one right answer.
    if settings.stt_backend == "groq":
        # The default (stt.py). Was missing here, so the default config FAILed.
        if settings.groq_api_key:
            record("PASS", "STT_BACKEND", "groq — cloud; falls back to Gemini, and to "
                                          "local CPU whisper when the network is down")
        else:
            record("WARN", "STT_BACKEND", "groq selected but GROQ_API_KEY is empty — every "
                                          "utterance falls through to the fallbacks")
    elif settings.stt_backend == "gemini":
        record("PASS", "STT_BACKEND", "gemini — off the GPU, but NO offline path: "
                                      "no network means no voice at all, and each turn "
                                      "costs 2 requests against the key pool")
    elif settings.stt_backend == "whisper":
        record("PASS", "STT_BACKEND", f"whisper — on-device, works offline; "
                                      f"costs ~2091 MiB VRAM at {settings.whisper_model_gpu}")
        if settings.stt_profile != "accurate":
            record("WARN", "STT_PROFILE", f"{settings.stt_profile!r} — 'accurate' stops the "
                                          "profile dropping to CPU/small on battery")
    else:
        record("FAIL", "STT_BACKEND", f"{settings.stt_backend!r} is not a valid backend "
                                      "(expected 'groq', 'gemini' or 'whisper')")

    if settings.enable_vision:
        record("WARN", "ENABLE_VISION", "true — passive VLM glance is ~35s and drains battery; "
                                        "set false for the demo")
    else:
        record("PASS", "ENABLE_VISION", "false — on-demand describe_screen/ocr_screen still work")

    record("PASS" if settings.enable_wake_word else "WARN",
           "ENABLE_WAKE_WORD", str(settings.enable_wake_word).lower())

    # Dead settings that look set but are ignored (both were live in .env).
    raw = (ROOT / ".env").read_text(encoding="utf-8") if (ROOT / ".env").exists() else ""
    for dead, real in (("OLLAMA_MODEL", "FAST_MODEL"),
                       ("WHISPER_MODEL=", "WHISPER_MODEL_GPU / _CPU")):
        if any(l.strip().startswith(dead) for l in raw.splitlines()):
            record("WARN", f".env has {dead.rstrip('=')}", f"silently ignored — the live setting is {real}")


# ── 2. Ollama ────────────────────────────────────────────────────────────
def check_ollama(offline: bool) -> None:
    section("Ollama (local planner failover, embeddings, OCR-adjacent)")
    import httpx
    from backend.server.config import settings

    needed = {"phi3": "local planner failover + verifier",
              "nomic-embed-text": "ChromaDB memory embeddings"}
    if settings.enable_vision:
        needed["qwen2.5vl"] = "vision loop"

    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=8.0)
        r.raise_for_status()
        have = [m["name"] for m in r.json().get("models", [])]
    except Exception as e:
        record("FAIL", "ollama serve", f"unreachable at {settings.ollama_url} — {type(e).__name__}. "
                                       "Without it: no offline planner, memory recall breaks, and the "
                                       "verifier fails closed (looks exactly like mishearing)")
        for m in needed:
            record("SKIP", f"model {m}", "ollama down")
        return

    record("PASS", "ollama serve", f"{len(have)} models at {settings.ollama_url}")
    _check_vram(settings)
    for m, why in needed.items():
        hit = next((h for h in have if h.split(":")[0] == m.split(":")[0]), None)
        if hit:
            record("PASS", f"model {m}", f"{hit} — {why}")
        else:
            record("FAIL", f"model {m}", f"missing — {why}. Run: ollama pull {m}")


def _check_vram(settings) -> None:
    """VRAM headroom. This box crashed the backend once already.

    The GPU is 6144 MiB. Ollama alone held 4.12 GB (phi3 3.80 + nomic 0.32) —
    well over the ~2.5 GB config.py budgets for it — and Whisper medium adds
    ~1.5 GB, leaving roughly half a gigabyte. Loading anything else on the GPU
    (the test suite, a bench, the audit tool) pushed it over and the backend
    died with NO Python traceback, because a CUDA abort is a native crash.
    From the outside the assistant simply stopped existing mid-session.
    """
    import subprocess

    # Measured on this box: small 739, medium 2091, large-v3 4019 MiB.
    # Zero when STT is in the cloud — that is the whole point of that switch.
    WHISPER_MEDIUM_MIB = 2091 if settings.stt_backend == "whisper" else 0
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        used, total = (int(x) for x in out.stdout.strip().split("\n")[0].split(","))
    except Exception:
        record("SKIP", "GPU headroom", "nvidia-smi unavailable")
        return

    # Whisper may or may not be resident yet, so report the worst case.
    free_after_whisper = total - used - WHISPER_MEDIUM_MIB
    detail = f"{used}/{total} MiB used, ~{free_after_whisper} MiB spare once Whisper loads"

    if free_after_whisper < 0:
        record("FAIL", "GPU headroom", detail + " — Whisper cannot fit; free VRAM first")
    elif free_after_whisper < 700:
        record("WARN", "GPU headroom", detail + " — tight. Do NOT run pytest, "
                                                "stt_bench or the audit tool during a rehearsal")
    else:
        record("PASS", "GPU headroom", detail)

    # Name the hogs, so the fix is obvious rather than a guessing game.
    try:
        import httpx
        ps = httpx.get(f"{settings.ollama_url}/api/ps", timeout=6.0).json()
        loaded = [(m["name"], m.get("size_vram", 0) / 1e9) for m in ps.get("models", [])]
        if loaded:
            record("PASS", "ollama VRAM residents",
                   ", ".join(f"{n} {g:.2f}GB" for n, g in loaded))
    except Exception:
        pass


# ── 3. Gemini keys ───────────────────────────────────────────────────────
async def check_gemini(offline: bool) -> None:
    section("Gemini key pool (cloud planner)")
    if offline:
        record("SKIP", "key pool", "--offline")
        return

    from backend.ai_modules.llm import key_pool as kp
    from backend.ai_modules.llm.backends import GeminiBackend
    from backend.server.config import settings

    slots = [settings.gemini_api_key, settings.gemini_api_key_2, settings.gemini_api_key_3]
    configured = [i for i, k in enumerate(slots, 1) if k]
    if not configured:
        record("FAIL", "key pool", "no keys configured — every cloud turn will fail")
        return

    live = 0
    original = tuple(slots)
    try:
        for i in configured:
            # Expose exactly one key so the backend must use THIS slot.
            settings.gemini_api_key = slots[i - 1]
            settings.gemini_api_key_2 = settings.gemini_api_key_3 = ""
            kp.pool.__init__()
            try:
                t = time.monotonic()
                out = await GeminiBackend().generate("Reply with one word: OK", temperature=0.0)
                dt = time.monotonic() - t
                if out.strip():
                    live += 1
                    record("PASS", f"key slot {i}", f"live in {dt:.2f}s  (…{slots[i-1][-6:]})")
                else:
                    record("WARN", f"key slot {i}", f"empty reply in {dt:.2f}s")
            except Exception as e:
                msg = str(e)
                hint = " — DAILY QUOTA SPENT" if "RESOURCE_EXHAUSTED" in msg or "429" in msg else ""
                record("FAIL", f"key slot {i}", f"{type(e).__name__}{hint}: {msg[:80]}")
    finally:
        settings.gemini_api_key, settings.gemini_api_key_2, settings.gemini_api_key_3 = original
        kp.pool.__init__()

    blank = 3 - len(configured)
    if blank:
        record("WARN", "spare key slots", f"{blank} blank — each free key from a separate Google "
                                          "account multiplies the daily budget")
    if live == 0:
        record("FAIL", "usable cloud budget", "no live keys — only rule-tier and offline commands will work")


# ── 4. Local failover, end to end ────────────────────────────────────────
async def check_failover() -> None:
    section("Local planner failover (the Act I punchline)")
    from backend.ai_modules.llm.backends import OllamaBackend
    from backend.server.config import settings

    if settings.llm_fallback_backend != "ollama_fallback":
        record("WARN", "llm_fallback_backend", f"{settings.llm_fallback_backend!r}")

    try:
        b = OllamaBackend(base_url=settings.ollama_url,
                          default_model=settings.llm_fallback_model)
        t = time.monotonic()
        out = await b.generate("Reply with exactly one word: OK", temperature=0.0)
        dt = time.monotonic() - t
        if out.strip():
            record("PASS", f"{settings.llm_fallback_model} answers locally", f"{dt:.2f}s")
        else:
            record("FAIL", f"{settings.llm_fallback_model} answers locally", "empty reply")
    except Exception as e:
        record("FAIL", "local planner", f"{type(e).__name__}: {str(e)[:90]}")


# ── 5. Voice assets ──────────────────────────────────────────────────────
def check_voice() -> None:
    section("Voice assets")
    import importlib.util as iu

    for mod, why in (("faster_whisper", "STT"), ("vosk", "wake word"),
                     ("piper", "TTS"), ("onnxruntime", "speech gate VAD")):
        record("PASS" if iu.find_spec(mod) else "FAIL", f"import {mod}", why)

    from backend.core import paths

    for name, path in (("vosk wake model", paths.VOSK_DIR),
                       ("piper voice", paths.PIPER_DIR)):
        files = list(path.rglob("*")) if path.exists() else []
        if any(f.is_file() for f in files):
            record("PASS", name, f"{path.name}/ populated")
        else:
            record("FAIL", name, f"{path} is empty — run tools/download_*.py")

    # CUDA via ctranslate2, NOT torch.cuda. torch is no longer a dependency at
    # all; when it was, the venv's CPU-only build (2.13.0+cpu) reported False
    # while CTranslate2 reported a working device — stt_manager.cuda_available() documents exactly this. An earlier
    # draft of this script used torch and cried wolf about a healthy GPU.
    try:
        from backend.ai_modules.speech.stt_manager import cuda_available, select_profile
        profile = select_profile()
        if cuda_available():
            record("PASS", "CUDA (ctranslate2)", f"available — profile {profile}")
        elif profile.device == "cuda":
            record("FAIL", "CUDA (ctranslate2)",
                   f"NOT available but STT_PROFILE forces {profile.device} — "
                   "set STT_PROFILE=auto or fast")
        else:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                # The card is there; only the libraries are missing.
                record("WARN", "CUDA (ctranslate2)",
                       f"NVIDIA GPU found but cuBLAS/cuDNN are not installed — running "
                       f"{profile}. `uv sync --extra gpu` to use it")
            else:
                record("WARN", "CUDA (ctranslate2)", f"unavailable — running {profile}")
    except Exception as e:
        record("WARN", "CUDA (ctranslate2)", f"could not query: {type(e).__name__}: {str(e)[:70]}")

    # Same trap: shutil.which finds nothing on a perfectly good Windows
    # install because the installer does not touch PATH. Use the resolver the
    # OCR path itself uses (ocr_reader._TESSERACT_HINTS).
    try:
        from backend.core.vision.ocr_reader import tesseract_path
        tp = tesseract_path()
        record("PASS" if tp else "WARN", "tesseract (OCR)",
               tp or "not found — 'read my screen' will fail. "
                     "winget install UB-Mannheim.TesseractOCR, or set TESSERACT_CMD")
    except Exception as e:
        record("WARN", "tesseract (OCR)", f"could not query: {type(e).__name__}")


# ── 6. The offline fast-path tools ───────────────────────────────────────
def check_fast_path() -> None:
    section("Offline fast-path tools (no planner, no network)")
    from backend.core.tools import registry  # noqa: F401  (import bootstraps)
    from backend.core.tools.registry import REGISTRY
    from backend.daemon.trigger import _VOICE_FAST_PATH_ACTIONS, _VOICE_FAST_PATH_TOOLS

    missing = sorted(t for t in _VOICE_FAST_PATH_TOOLS if t not in REGISTRY)
    if missing:
        record("FAIL", "fast-path tools registered", f"missing from REGISTRY: {', '.join(missing)}")
    else:
        record("PASS", "fast-path tools registered",
               f"{len(_VOICE_FAST_PATH_TOOLS)} tools + {len(_VOICE_FAST_PATH_ACTIONS)} handlers, "
               f"{len(REGISTRY)} total")

    # The rule tier must actually resolve the demo phrasings — a rule that
    # stops matching turns an instant offline command into a cloud round trip.
    from backend.core.orchestrator import rule_engine
    from backend.core.orchestrator.normalize import normalize_for_rules

    phrases = {
        "what time is it": "get_time",
        "battery status": "get_battery",
        "system status": "get_system_status",
        "set volume to seventy": "set_volume",
        "volume up": "volume_up",
        "set brightness to forty": "set_brightness",
        "stop": "stop",
    }
    bad = []
    for said, expect in phrases.items():
        hit = rule_engine.match(normalize_for_rules(said))
        got = hit.action if hit else None
        if got != expect:
            bad.append(f"{said!r}->{got}")
    if bad:
        record("FAIL", "demo phrasings match their rule", "; ".join(bad))
    else:
        record("PASS", "demo phrasings match their rule", f"{len(phrases)}/{len(phrases)} offline-ready")


# ── main ─────────────────────────────────────────────────────────────────
async def main() -> int:
    ap = argparse.ArgumentParser(description="SG-CUBE demo pre-flight")
    ap.add_argument("--offline", action="store_true",
                    help="skip cloud checks (use when rehearsing in airplane mode)")
    args = ap.parse_args()

    print(f"{BOLD}SG-CUBE pre-flight{OFF}  {DIM}"
          f"{'offline mode' if args.offline else 'full check'}{OFF}")

    check_config()
    check_ollama(args.offline)
    await check_gemini(args.offline)
    await check_failover()
    check_voice()
    check_fast_path()

    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print(f"\n{BOLD}{'─' * 64}{OFF}")
    if fails:
        print(f"{RED}{BOLD}NOT READY{OFF} — {len(fails)} blocking, {len(warns)} warning(s)")
        for _, label, detail in fails:
            print(f"  {RED}·{OFF} {label}: {detail}")
    elif warns:
        print(f"{WARN}{BOLD}READY, with {len(warns)} warning(s){OFF}")
        for _, label, detail in warns:
            print(f"  {WARN}·{OFF} {label}: {detail}")
    else:
        print(f"{GREEN}{BOLD}READY{OFF} — every check green")

    print(f"\n{DIM}Reminders this script cannot check:{OFF}")
    print(f"{DIM}  · Restart the backend after any .env change — the running process predates it.{OFF}")
    print(f"{DIM}  · Use AIRPLANE MODE for the offline act, not weak wifi. A reachable-but-failing{OFF}")
    print(f"{DIM}    cloud costs ~6.3s of retries per command; a dead one fails over in ~1s.{OFF}")
    print(f"{DIM}  · Pre-warm whisper (tools/pre_load_whisper.py): first command is ~2.6s vs ~0.35s.{OFF}")
    print(f"{DIM}  · Do not demo music — it holds the VAD open and every later command hits the 10s cap.{OFF}")
    print(f"{DIM}  · Never run pytest / stt_bench / audit_dropped_segments while the backend is up.{OFF}")
    print(f"{DIM}    They load a SECOND Whisper onto a GPU that is already ~90% full, and the{OFF}")
    print(f"{DIM}    backend dies from a native CUDA abort with no traceback — it just disappears.{OFF}")

    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
