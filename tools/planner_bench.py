"""Planner accuracy bench — same planner production uses, scored against
tools/planner_cases.json.

Planner quality on real tasks has never been measured in this repo. The
migration note said so outright ("only synthetic JSON probes so far"), and the
move from Ollama Cloud to Gemini was not a quality decision at all — the Ollama
key got commented out and routing.py::_cloud_or fell through. This exists so
the next provider choice is made on numbers.

    .venv/Scripts/python.exe tools/planner_bench.py --provider gemini
    .venv/Scripts/python.exe tools/planner_bench.py --provider ollama_cloud
    .venv/Scripts/python.exe tools/planner_bench.py --provider ollama_cloud --only siblings
    .venv/Scripts/python.exe tools/planner_bench.py --check-access

The Ollama Cloud leg needs OLLAMA_API_KEY. Pass it for THIS PROCESS ONLY rather
than uncommenting it in .env — uncommenting flips production routing for
planning/coding/chat/general globally, which is a decision, not a side effect:

    OLLAMA_API_KEY=... .venv/Scripts/python.exe tools/planner_bench.py --provider ollama_cloud
"""
import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CASES_FILE = Path(__file__).with_name("planner_cases.json")


# ── scoring ──────────────────────────────────────────────────────────────

def _matches(expected, actual) -> bool:
    """Substring match, case-insensitive, for strings; == otherwise.

    'tokyo' must match 'Tokyo, Japan' — the model is not wrong for being more
    specific than the fixture.
    """
    if expected is None:
        return True
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.lower() in actual.lower()
    if isinstance(expected, (int, float)) and isinstance(actual, str):
        return str(expected) in actual
    return expected == actual


def score_case(case: dict, calls: list[dict], schemas: dict, coerce=None) -> dict:
    """Grade one planner response. Every field is independently interesting.

    `argnames_ok` grades what the model LITERALLY said. `effective_ok` grades
    what production actually executes, because registry.call() runs
    _coerce_args() before dispatch and repairs a single misnamed argument
    (`file` -> `path`, `text` -> `fact`). Without both numbers the bench
    overstates the problem: three of gemma4's "failures" are repaired before
    any tool sees them. The gap between the two columns IS the finding — and
    coercion gives up entirely once TWO names are wrong, so raw accuracy still
    buys the margin that keeps calls off that cliff.
    """
    out = {
        "id": case["id"],
        "group": case.get("group", "?"),
        "tool_ok": False,
        "argnames_ok": False,
        "argvals_ok": False,
        "effective_ok": False,
        "got": None,
        "why": "",
    }

    if case["expect"] == "none":
        out["got"] = [c.get("name") for c in calls] or None
        ok = not calls
        out["tool_ok"] = out["argnames_ok"] = out["argvals_ok"] = out["effective_ok"] = ok
        if not ok:
            out["why"] = f"expected no tool, got {out['got']}"
        return out

    if not calls:
        out["why"] = "expected a tool call, got none"
        return out

    names = [c.get("name") for c in calls]
    out["got"] = names
    # The ARGS, not just the names. Without these a failed run can only be
    # diagnosed by re-running it — which is how a fixture bug (demanding `path`
    # from delete_file, whose parameter is `file`) survived a whole analysis.
    out["args"] = [c.get("args") or {} for c in calls]
    first = calls[0]
    name = first.get("name")

    min_calls = case.get("min_calls", 1)
    if len(calls) < min_calls:
        out["why"] = f"expected >={min_calls} calls, got {len(calls)}"
        return out

    # For compound cases every call must be an accepted tool; for single cases
    # only the first matters (a trailing extra call is a different defect and
    # shows up as a min_calls/args mismatch, not a wrong-tool one).
    accept = case["accept"]
    if min_calls > 1:
        out["tool_ok"] = all(n in accept for n in names[:min_calls])
    else:
        out["tool_ok"] = name in accept
    if not out["tool_ok"]:
        out["why"] = f"tool {names} not in {accept}"
        return out

    # Hallucinated ARG NAMES — the historic planner failure. Checked against
    # the real registry schema, so it covers every case for free.
    schema = schemas.get(name, {})
    known = set((schema.get("parameters", {}).get("properties") or {}).keys())
    got_args = first.get("args") or {}
    unknown = set(got_args) - known
    out["argnames_ok"] = not unknown
    if unknown:
        out["why"] = f"unknown arg names for {name}: {sorted(unknown)}"

    # Sibling tools sometimes name the same concept differently (get_news takes
    # `category`, get_news_data takes `topic`). A single `args` map then grades
    # the model against the OTHER tool's vocabulary and marks a correct call
    # wrong — which is exactly what happened on the first run.
    required = (case.get("args_by_tool") or {}).get(name)
    if required is None:
        required = case.get("args") or {}
    missing = [k for k in required if k not in got_args]
    wrong = [k for k in required if k in got_args and not _matches(required[k], got_args[k])]
    out["argvals_ok"] = not missing and not wrong
    if missing or wrong:
        detail = []
        if missing:
            detail.append(f"missing {missing}")
        if wrong:
            detail.append(f"wrong {{{', '.join(f'{k}={got_args[k]!r}' for k in wrong)}}}")
        out["why"] = (out["why"] + "; " if out["why"] else "") + " ".join(detail)

    # What production would actually execute. registry.call() coerces before
    # dispatch, so a single misnamed arg never reaches the tool. Two misnamed
    # args do — coercion bails and the call TypeErrors.
    if coerce is not None:
        try:
            fixed = coerce(name, dict(got_args))
        except Exception:
            fixed = got_args
        still_unknown = set(fixed) - known
        eff_missing = [k for k in required if k not in fixed]
        eff_wrong = [k for k in required
                     if k in fixed and not _matches(required[k], fixed[k])]
        out["effective_ok"] = not still_unknown and not eff_missing and not eff_wrong
        if out["effective_ok"] and not (out["argnames_ok"] and out["argvals_ok"]):
            out["why"] = (out["why"] or "") + "  [repaired by _coerce_args]"
    else:
        out["effective_ok"] = out["argnames_ok"] and out["argvals_ok"]

    return out


# ── running ──────────────────────────────────────────────────────────────

async def _build_context():
    """The real AgentContext production sends — 109 capabilities and all.

    discover() is NOT optional and its absence is silent. ContextBuilder reads
    capability_registry, which is populated by server/main.py's lifespan — so a
    harness that skips the lifespan hands the planner an EMPTY tool list, and
    the planner then invents tool names (`open_chrome`, `fetch_url`) or falls
    through to final_response. The first run of this bench scored 23.3% for
    exactly that reason and it looked like a bad model. server/main.py already
    carries a comment about this same bug biting production once.
    """
    from backend.core.caps.registry import capability_registry
    from backend.core.context.builder import context_builder
    from backend.core.context.types import RequestContext

    capability_registry.discover()
    if not capability_registry.all():
        raise SystemExit("capability registry is empty — the planner would see no tools")

    return await context_builder.collect(RequestContext(
        user_intent="", user_id="bench", session_id="bench",
        request_id="bench", input_mode="text",
    ))


async def run_case(planner, case: dict, context) -> tuple[list[dict], float, float]:
    """Returns (calls, ttft_ms, total_ms). A final_response yields no calls."""
    t0 = time.perf_counter()
    ttft = None
    calls: list[dict] = []

    async for chunk in planner.generate_plan_stream(case["utterance"], [], context):
        if chunk["type"] in ("token", "prose") and ttft is None:
            ttft = (time.perf_counter() - t0) * 1000
        elif chunk["type"] == "final":
            content = chunk["content"]
            if isinstance(content, dict):
                calls = content.get("tool_calls") or content.get("toolCalls") or []
            elif isinstance(content, list):
                calls = content
            break

    total = (time.perf_counter() - t0) * 1000
    return [c for c in calls if isinstance(c, dict)], (ttft or total), total


def _select_provider(name: str, model: str | None = None) -> str:
    """Pin PLANNING to one backend, bypassing _cloud_or's key-presence logic.

    The bench must test the backend it was ASKED for, not the one the current
    .env happens to select — otherwise a run silently benches Gemini and
    reports it as Ollama.
    """
    from backend.ai_modules.llm import create_llm_provider
    from backend.ai_modules.llm.provider import get_llm
    from backend.ai_modules.llm.routing import TaskType
    from backend.server.config import settings

    # Backends read their default model from settings AT CONSTRUCTION, so this
    # has to land before create_llm_provider() or the run silently benches
    # whatever .env names while reporting the model that was asked for.
    if model:
        if name == "ollama_cloud":
            settings.ollama_cloud_model = model
        elif name == "gemini":
            settings.gemini_model = model
        else:
            settings.fast_model = model

    create_llm_provider()
    llm = get_llm()
    if name not in llm._backends:
        raise SystemExit(
            f"Backend {name!r} is not registered. Registered: {sorted(llm._backends)}.\n"
            f"For ollama_cloud, pass OLLAMA_API_KEY=... in the environment."
        )
    llm.policy.override(TaskType.PLANNING, name)
    backend = llm._backends[name]
    return backend.active_model_name() or name


async def check_access(model: str | None = None) -> None:
    """One real POST. ollama.com/api/tags is public and lists models the
    account cannot call, so entitlement is only ever proven by a chat call.
    """
    from backend.ai_modules.llm.backends import OllamaCloudBackend
    from backend.server.config import settings

    if not settings.ollama_api_key:
        raise SystemExit("OLLAMA_API_KEY not set in this process.")
    backend = OllamaCloudBackend()
    target = model or settings.ollama_cloud_model
    t0 = time.perf_counter()
    try:
        reply = await backend.generate(
            "Reply with the single word: ok", model=target,
        )
        dt = (time.perf_counter() - t0) * 1000
        print(f"ACCESS OK   {target}  {dt:.0f}ms  reply={str(reply)[:60]!r}")
    except Exception as e:
        print(f"ACCESS FAIL {target}  {type(e).__name__}: {e}")


async def main_async(args) -> int:
    import backend.core.tools  # noqa: F401  — populates REGISTRY
    from backend.core.tools.registry import REGISTRY, _coerce_args

    if args.check_access:
        await check_access(args.model)
        return 0

    data = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    cases = data["cases"]
    if args.only:
        cases = [c for c in cases if c.get("group") == args.only]
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    if not cases:
        raise SystemExit("no cases selected")

    model = _select_provider(args.provider, args.model)
    schemas = {n: t.schema for n, t in REGISTRY.items() if hasattr(t, "schema")}

    from backend.core.agents.planner import PlannerAgent
    planner = PlannerAgent()
    context = await _build_context()

    print(f"provider={args.provider}  model={model}  cases={len(cases)}\n")

    results, ttfts, totals = [], [], []
    for i, case in enumerate(cases, 1):
        try:
            calls, ttft, total = await run_case(planner, case, context)
            r = score_case(case, calls, schemas, coerce=_coerce_args)
        except Exception as e:
            r = {"id": case["id"], "group": case.get("group", "?"), "tool_ok": False,
                 "argnames_ok": False, "argvals_ok": False, "effective_ok": False,
                 "got": None, "why": f"{type(e).__name__}: {e}"}
            ttft = total = float("nan")
        else:
            ttfts.append(ttft)
            totals.append(total)

        # NaN on the exception path; round() would raise converting it to int.
        r["ttft_ms"] = round(ttft) if ttft == ttft else None
        r["total_ms"] = round(total) if total == total else None
        results.append(r)
        mark = ("PASS" if (r["tool_ok"] and r["argnames_ok"] and r["argvals_ok"])
                else ("RPRD" if r.get("effective_ok") else "FAIL"))
        print(f"[{i:2}/{len(cases)}] {mark}  {r['id']:26} {total:7.0f}ms  {r['why']}")

    n = len(results)
    print(f"\n── {args.provider} ({model}) ──")
    for label, key in (("tool choice", "tool_ok"), ("arg names", "argnames_ok"),
                       ("arg values", "argvals_ok"), ("EFFECTIVE", "effective_ok")):
        hits = sum(1 for r in results if r[key])
        print(f"{label:12} {hits}/{n}  {hits / n * 100:5.1f}%")
    full = sum(1 for r in results if r["tool_ok"] and r["argnames_ok"] and r["argvals_ok"])
    print(f"{'all three':12} {full}/{n}  {full / n * 100:5.1f}%")
    if ttfts:
        print(f"\nTTFT  median {statistics.median(ttfts):.0f}ms   "
              f"total median {statistics.median(totals):.0f}ms  (n={len(ttfts)})")

    by_group: dict[str, list] = {}
    for r in results:
        by_group.setdefault(r["group"], []).append(r)
    print("\nby group:")
    for g, rs in by_group.items():
        ok = sum(1 for r in rs if r.get("effective_ok"))
        print(f"  {g:12} {ok}/{len(rs)}  (effective)")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"provider": args.provider, "model": model, "results": results},
            indent=2), encoding="utf-8")
        print(f"\nwrote {args.json_out}")

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--provider", default="gemini",
                   help="backend name to pin PLANNING to (gemini, ollama_cloud, ollama)")
    p.add_argument("--only", help="run one group only (baseline, siblings, multistep, compound, argnames, destructive, no_action)")
    p.add_argument("--case", help="run a single case id")
    p.add_argument("--model", help="pin a specific model (e.g. gpt-oss:20b, gemma4:31b)")
    p.add_argument("--check-access", action="store_true",
                   help="one real POST to prove entitlement, then exit")
    p.add_argument("--json-out", help="write per-case results to this path")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
