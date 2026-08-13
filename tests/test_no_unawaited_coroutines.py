"""A coroutine that is built and dropped is silent code death.

Three separate handlers shipped with this bug: POST /execute and /voice/process
both called async functions from a sync context, and /voice/process did it
twice (process_input as well as safe_executor.execute). Nothing raises at
import; the coroutine is simply never run, the attribute access on it fails at
request time, and the route 500s in production while the suite stays green.

This is the standing guard. It exists as a test rather than only as
tools/check_unawaited.py because a script nobody runs is how the last one got
missed — the repo already carries ~40 untracked one-off probes.

The checker's own accuracy is asserted below: a checker that reports nothing
because it resolves nothing would pass this file trivially.
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))

from check_unawaited import collect_coroutines, scan  # noqa: E402


def test_no_coroutine_is_left_unawaited():
    hits = scan()
    assert hits == [], "\n".join(
        f"{p}:{line}: {name}() is never awaited — the call builds a coroutine "
        f"and drops it, so the body never runs" for p, line, name in hits
    )


def test_the_checker_actually_resolves_this_repos_coroutines():
    """Guards the failure mode where the checker silently stops resolving
    anything (a rename, a moved package root) and passes by finding nothing."""
    root = Path(__file__).parents[1]
    trees = {p: ast.parse(p.read_text(encoding="utf-8"))
             for p in (root / "backend").rglob("*.py")}
    module_level, _ = collect_coroutines(trees)
    assert "backend.core.safe_executor.executor.execute" in module_level
    assert "backend.core.orchestrator.router.process_input" in module_level
    # ...and async generators stay out, or every `async for` site is a false hit.
    assert not any(n.endswith(".speak_stream") for n in module_level), (
        "speak_stream is an async generator — including it makes every "
        "`async for chunk in speak_stream(...)` a false positive"
    )


@pytest.mark.parametrize("source, should_flag", [
    # The exact shape that shipped three times.
    ("from backend.core.safe_executor.executor import execute\n"
     "def handler(i):\n"
     "    return execute(i).model_dump()\n", True),
    # Aliased import — how it was actually written in routes/execute.py.
    ("from backend.core.safe_executor.executor import execute as do_execute\n"
     "def handler(i):\n"
     "    result = do_execute(i)\n"
     "    return result.status\n", True),
    # Deliberate blind spot, documented so it isn't mistaken for a miss: a sync
    # function returning a coroutine for its caller to await is a normal
    # delegation pattern, indistinguishable here from a dropped one.
    ("from backend.core.safe_executor.executor import execute\n"
     "def delegate(i):\n"
     "    return execute(i)\n", False),
    ("from backend.core.safe_executor.executor import execute\n"
     "async def handler(i):\n"
     "    return (await execute(i)).model_dump()\n", False),
    # Handing the coroutine to the loop is a correct consumption, not a bug.
    ("import asyncio\n"
     "from backend.core.safe_executor.executor import execute\n"
     "def handler(i):\n"
     "    asyncio.create_task(execute(i))\n", False),
    ("import asyncio\n"
     "from backend.core.safe_executor.executor import execute\n"
     "async def handler(items):\n"
     "    await asyncio.gather(*[execute(i) for i in items])\n", False),
    # Handed to a local runner — tests/test_capability_tiers.py does exactly
    # this with its `_run` helper, and an earlier revision of the checker
    # reported all 12 such call sites as bugs.
    ("import asyncio\n"
     "from backend.core.safe_executor.executor import execute\n"
     "def _run(coro):\n"
     "    return asyncio.run(coro)\n"
     "def test_it():\n"
     "    assert _run(execute('x'))\n", False),
    # Fire-and-forget: nothing runs it, and nothing ever will.
    ("from backend.core.safe_executor.executor import execute\n"
     "def handler(i):\n"
     "    execute(i)\n", True),
])
def test_checker_distinguishes_the_bug_from_correct_usage(tmp_path, source, should_flag, monkeypatch):
    """Runs the real checker over a synthetic backend tree. Without this, a
    checker that never fires reads exactly like a clean codebase."""
    import check_unawaited

    pkg = tmp_path / "backend" / "core" / "safe_executor"
    pkg.mkdir(parents=True)
    for parent in (tmp_path / "backend", tmp_path / "backend" / "core", pkg):
        (parent / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "executor.py").write_text("async def execute(intent):\n    return intent\n", encoding="utf-8")
    (tmp_path / "backend" / "caller.py").write_text(source, encoding="utf-8")

    monkeypatch.setattr(check_unawaited, "ROOT", tmp_path)
    hits = check_unawaited.scan()
    assert bool(hits) is should_flag, hits
