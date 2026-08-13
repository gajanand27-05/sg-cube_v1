"""Find coroutine calls that are never awaited.

Motivated by three real production-dead bugs found on 2026-08-13: POST /execute
and POST /voice/process called async functions from a sync context (voice twice
over), so the first attribute access landed on a coroutine object and the routes
500'd on every request. Nothing raises at import; the coroutine is simply never
run. Neither route had a test.

Static, AST-based, no imports of the code under test (importing the daemon has
side effects). Precision matters more than recall here — a checker that cries
wolf gets muted — so it narrows on two axes:

RESOLUTION. Only calls whose callee resolves to an `async def` in this repo:
  A. `foo(...)` where foo was imported into this module from a backend module.
  B. `self.foo(...)` where foo is an async method of a class in the same module.
So `Path(...).resolve()`, `cursor.execute()` and `f.close()` can never be
confused with this repo's own `resolve`/`execute`/`close` coroutines. Async
GENERATORS are excluded — they are consumed by `async for`, never awaited.

CONTEXT. Only the three shapes where a dropped coroutine is a genuine bug:
  * discarded as a bare statement     `do_execute(intent)`
  * assigned to a name                `result = process_input(text)`
  * used as a receiver                `do_execute(intent).model_dump()`
A coroutine passed as an ARGUMENT is deliberately not flagged: `_run(verify(x))`,
`asyncio.create_task(f())` and `gather(*[f(i) for i in xs])` all hand it to
something that will run it, and no wrapper-tracing heuristic is worth the false
positives. `await f()`, `async for x in f()` and `async with f()` fall out
automatically — their parent node is not one of the three.

Run:  .venv/Scripts/python.exe tools/check_unawaited.py
Also enforced by tests/test_no_unawaited_coroutines.py.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Trees to walk. `tests` is included because a test that drops a coroutine
# passes while asserting nothing about code that never ran — the same blind
# spot as the production bug, one level up.
SCAN_DIRS = ("backend", "tests")
# Import prefix used to resolve a call back to its definition. Stays "backend"
# for both trees: a test importing `from backend.x import y` must still resolve.
PACKAGE = "backend"


def _is_async_generator(node: ast.AsyncFunctionDef) -> bool:
    """`async def` containing a yield: consumed by `async for`, not awaited."""
    return any(isinstance(c, (ast.Yield, ast.YieldFrom)) for c in ast.walk(node))


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def collect_coroutines(trees: dict[Path, ast.AST]) -> tuple[set[str], dict[Path, set[str]]]:
    """Module-level `async def` names as "module.func", plus per-file the async
    method names defined on classes in that file."""
    module_level: set[str] = set()
    methods: dict[Path, set[str]] = {}
    for path, tree in trees.items():
        mod = _module_name(path)
        own: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and not _is_async_generator(node):
                module_level.add(f"{mod}.{node.name}")
            elif isinstance(node, ast.ClassDef):
                own |= {s.name for s in node.body
                        if isinstance(s, ast.AsyncFunctionDef) and not _is_async_generator(s)}
        methods[path] = own
    return module_level, methods


def _imported_coroutines(tree: ast.AST, module_level: set[str]) -> dict[str, str]:
    """local name -> "module.func", honouring `import x as y`."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith(PACKAGE):
            for alias in node.names:
                qualified = f"{node.module}.{alias.name}"
                if qualified in module_level:
                    out[alias.asname or alias.name] = qualified
    return out


def _dropped_call_ids(tree: ast.AST) -> set[int]:
    """Calls appearing in one of the three shapes where a coroutine result is
    dropped rather than handed on. See the CONTEXT note in the module docstring."""
    suspect: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            suspect.add(id(node.value))          # bare statement — result discarded
        elif isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Call):
            suspect.add(id(node.value))          # bound to a name
        elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.value, ast.Call):
            suspect.add(id(node.value))          # `f(...).attr` — the /execute shape
    return suspect


def scan() -> list[tuple[str, int, str]]:
    trees: dict[Path, ast.AST] = {}
    for p in (f for d in SCAN_DIRS for f in (ROOT / d).rglob("*.py")):
        try:
            trees[p] = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue

    module_level, methods = collect_coroutines(trees)

    out: list[tuple[str, int, str]] = []
    for path, tree in trees.items():
        dropped = _dropped_call_ids(tree)
        imported = _imported_coroutines(tree, module_level)
        own_methods = methods[path]

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or id(node) not in dropped:
                continue
            func = node.func
            if isinstance(func, ast.Name) and func.id in imported:
                target = imported[func.id]
            elif (isinstance(func, ast.Attribute)
                  and isinstance(func.value, ast.Name) and func.value.id == "self"
                  and func.attr in own_methods):
                target = f"self.{func.attr}"
            else:
                continue
            out.append((str(path.relative_to(ROOT)), node.lineno, target))
    return sorted(out)


if __name__ == "__main__":
    hits = scan()
    for path, lineno, name in hits:
        print(f"{path}:{lineno}: {name}() is a coroutine function; its result is never awaited")
    print(f"\n{len(hits)} suspect call(s)")
    sys.exit(1 if hits else 0)
