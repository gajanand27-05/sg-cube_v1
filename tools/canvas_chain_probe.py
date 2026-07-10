"""Canvas-chain probe — classify T-planner-canvas-chain.

The question: when the user says "Show me AAPL and the news", does the live
Planner (DeepSeek V3 base via OpenRouter) emit multiple tool_calls in one
response, or does it emit only one?

Why it matters (from reading Commander at commander.py:157):
  - Multi-tool response: batch executes both, feeds results back to Planner,
    next iteration emits render_canvas. Canvas-chain works.
  - Single-tool response with success + message: Commander SHORT-CIRCUITS at
    len(batch_results) == 1. Loop returns. Second tool never fires. No canvas.

So the classification:
  - Multi-entry tool_calls emitted -> prompt tune is enough (strengthen the
    "call BOTH data tools in one turn" language).
  - Single-entry tool_calls emitted -> planner-loop / pipeline gap. Options
    become: (a) remove the len==1 short-circuit for tools that don't render,
    (b) inject an implicit "render on canvas" hint that forces render_canvas
    into every canvas-request response, (c) actually re-invoke Planner after
    a single fetch tool.

This probe runs the Planner alone — no Guardian, no Operator, no execution.
Just: what does V3 emit as raw JSON? Repeats each query 3x so we know if
behavior is deterministic.
"""
from __future__ import annotations

import asyncio
import json
import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force-import the tool module so the registry + capability_registry populate.
import backend.core.tools  # noqa: F401


PROBE_QUERIES = [
    "Show me AAPL and the news",
    "Show me AAPL on the canvas and the top news headlines",
    "Put Apple stock and world news on the canvas",
]

REPEATS = 3


async def _run_planner(query: str, history: list[dict], context) -> tuple[str, object]:
    from backend.core.agents.planner import PlannerAgent
    planner = PlannerAgent()
    full_content = ""
    parsed_final = None
    async for chunk in planner.generate_plan_stream(query, history, context):
        if chunk["type"] == "token":
            full_content += chunk["content"]
        elif chunk["type"] == "final":
            parsed_final = chunk["content"]
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", full_content, re.DOTALL)
    clean = m.group(1).strip() if m else full_content.strip()
    return clean, parsed_final


def _fake_tool_results(names: list[str]) -> list[dict]:
    """Simulate the shape Operator returns to Commander. Just enough for V3
    to know the data is there — we don't need real values."""
    out = []
    for n in names:
        if n == "get_stock":
            out.append({
                "name": "get_stock",
                "args": {"symbol": "AAPL"},
                "result": {
                    "status": "success",
                    "message": "AAPL: 234.56 USD (+1.23%)",
                    "data": {
                        "source": "yahoo-finance",
                        "fetched_at": "2026-07-10T00:00:00Z",
                        "as_of": "2026-07-10T00:00:00Z",
                        "stale": False,
                        "payload": {"symbol": "AAPL", "price": 234.56, "change_pct": 1.23,
                                    "currency": "USD"},
                    },
                },
            })
        elif n == "get_news_data":
            out.append({
                "name": "get_news_data",
                "args": {"topic": "world", "limit": 5},
                "result": {
                    "status": "success",
                    "message": "5 headlines fetched",
                    "data": {
                        "source": "bbc-rss",
                        "fetched_at": "2026-07-10T00:00:00Z",
                        "as_of": None,
                        "stale": False,
                        "is_external_data": True,
                        "payload": {"items": [
                            {"title": "Headline one", "summary": "..."},
                            {"title": "Headline two", "summary": "..."},
                            {"title": "Headline three", "summary": "..."},
                        ]},
                    },
                },
            })
    return out


async def probe_one(query: str, run_idx: int) -> dict:
    from backend.core.context.builder import context_builder
    from backend.core.context.types import RequestContext

    request = RequestContext(
        user_intent=query,
        user_id="probe",
        session_id="canvas-chain-probe",
        request_id=f"probe-{run_idx}",
        input_mode="text",
    )
    context = await context_builder.collect(request)

    # ── Turn 1: fresh user query ──────────────────────────────────────
    raw1, parsed1 = await _run_planner(query, [], context)
    tool_calls_1 = parsed1 if isinstance(parsed1, list) else []
    final_response_1 = parsed1.get("final_response") if isinstance(parsed1, dict) else None
    names_1 = [c.get("name") for c in tool_calls_1]

    # ── Turn 2: simulate Commander's follow-up ────────────────────────
    # Only meaningful if turn 1 emitted tool calls that Commander would run.
    turn2 = None
    if tool_calls_1:
        fake_results = _fake_tool_results(names_1)
        history = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": json.dumps({"tool_calls": tool_calls_1})},
            {
                "role": "user",
                "content": json.dumps({
                    "tool_results": fake_results,
                    "instruction": "Summarize results for the user.",
                }),
            },
        ]
        raw2, parsed2 = await _run_planner(query, history, context)
        tool_calls_2 = parsed2 if isinstance(parsed2, list) else []
        final_response_2 = parsed2.get("final_response") if isinstance(parsed2, dict) else None
        names_2 = [c.get("name") for c in tool_calls_2]
        turn2 = {
            "raw": raw2,
            "tool_call_count": len(tool_calls_2),
            "tool_names": names_2,
            "final_response": final_response_2,
            "emitted_render_canvas": "render_canvas" in names_2,
        }

    return {
        "query": query,
        "run": run_idx,
        "turn1": {
            "raw": raw1,
            "tool_call_count": len(tool_calls_1),
            "tool_names": names_1,
            "final_response": final_response_1,
        },
        "turn2": turn2,
    }


async def main():
    print("=" * 70)
    print("CANVAS-CHAIN PROBE — DeepSeek V3 base (deepseek/deepseek-chat)")
    print("=" * 70)

    all_runs: list[dict] = []
    for q in PROBE_QUERIES:
        for i in range(REPEATS):
            print(f"\n--- Query: {q!r}   run {i + 1}/{REPEATS} ---")
            try:
                result = await probe_one(q, i + 1)
            except Exception as e:
                print(f"  [FAILED] {type(e).__name__}: {e}")
                continue
            all_runs.append(result)
            t1 = result["turn1"]
            print(f"  TURN 1  tool_call_count = {t1['tool_call_count']}, names = {t1['tool_names']}")
            if t1["final_response"]:
                print(f"          final_response = {t1['final_response']!r}")
            t2 = result["turn2"]
            if t2:
                print(f"  TURN 2  tool_call_count = {t2['tool_call_count']}, names = {t2['tool_names']}")
                print(f"          emitted_render_canvas = {t2['emitted_render_canvas']}")
                if t2["final_response"]:
                    print(f"          final_response = {t2['final_response']!r}")
            else:
                print(f"  TURN 2  (skipped — turn 1 had no tool_calls)")

    print("\n" + "=" * 70)
    print("CLASSIFICATION")
    print("=" * 70)
    total = len(all_runs)
    if not total:
        print("No successful runs.")
        return
    t1_multi = sum(1 for r in all_runs if r["turn1"]["tool_call_count"] >= 2)
    t1_single = sum(1 for r in all_runs if r["turn1"]["tool_call_count"] == 1)
    t1_final = sum(1 for r in all_runs if r["turn1"]["final_response"])
    t2_render = sum(1 for r in all_runs if r["turn2"] and r["turn2"]["emitted_render_canvas"])
    t2_final = sum(1 for r in all_runs if r["turn2"] and r["turn2"]["final_response"])
    t2_other_tools = sum(
        1 for r in all_runs
        if r["turn2"] and r["turn2"]["tool_call_count"] > 0 and not r["turn2"]["emitted_render_canvas"]
    )

    print(f"Runs: {total}")
    print(f"Turn 1:")
    print(f"  emitted 2+ tool_calls: {t1_multi}")
    print(f"  emitted 1 tool_call:   {t1_single}")
    print(f"  emitted final_response only: {t1_final}")
    print(f"Turn 2 (after simulated tool results):")
    print(f"  emitted render_canvas: {t2_render}")
    print(f"  emitted other tool_calls (no canvas): {t2_other_tools}")
    print(f"  emitted final_response only: {t2_final}")

    print("\nVERDICT:")
    if t1_multi >= total * 0.66 and t2_render >= total * 0.66:
        print("  Both hops work. V3 chains data-fetch in turn 1, renders canvas in turn 2.")
        print("  T-planner-canvas-chain should already work end-to-end. Live-run to confirm.")
    elif t1_multi >= total * 0.66 and t2_render < total * 0.33:
        print("  Turn 1 chains fine (V3 emits both fetch tools).")
        print("  Turn 2 FAILS to emit render_canvas even with tool_results in history.")
        print("  Root cause is Commander's iteration-2 instruction 'Summarize results")
        print("  for the user.' — that cues V3 toward a spoken summary, not a canvas")
        print("  render. Fix: Commander should detect canvas-intent queries and inject")
        print("  a 'now call render_canvas' instruction instead / in addition.")
    elif t1_single >= total * 0.66:
        print("  Planner-loop gap. V3 emits 1 tool at a time.")
    else:
        print("  Mixed. Need larger sample or re-check the prompt.")

    with open("tools/canvas_chain_probe_output.json", "w", encoding="utf-8") as f:
        json.dump(all_runs, f, indent=2, ensure_ascii=False)
    print("\nRaw output saved to tools/canvas_chain_probe_output.json")


if __name__ == "__main__":
    asyncio.run(main())
