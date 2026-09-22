"""The Guardian must validate the arguments the Operator will actually run.

Reproduced from the live log:

    [command] "It's not Gajanan 2, it's Gajanan only"
    Guardian rejected: ["Missing required argument 'fact' for tool 'remember'."]

The fact WAS in the utterance. The planner simply named the argument something
else, and `_coerce_args` — which exists precisely to repair that, and which
maps content/text/facts/information onto `fact` — ran at `registry.call()`,
AFTER `guardian.verify_plan` had already rejected the call.

So the repair was unreachable for any alias on a REQUIRED argument, including
_coerce_args' own documented example, open_app({"app_name": ...}).

Two halves, and the second is the one with teeth: the Guardian validating one
dict while the Operator runs a different one is a hole in the security layer
independent of this bug. Validated args and executed args must be the same
object.

Narrowing that comes with it: the last-resort POSITIONAL bind (any single
unplaced argument lands in the first free parameter, which is what rescues
get_news_data(query=...) -> topic) is fine for a one-parameter tool, where
there is only one thing it could have meant. On a multi-parameter DESTRUCTIVE
tool it is a guess about something irreversible — binding a stray key into
send_whatsapp's `message` is not a repair, it is inventing content. Allowed
only for single-parameter tools or tools that are not DESTRUCTIVE.

Coercion is deliberately NOT removed from registry.call(): the rule fast path
(trigger.py) calls the registry directly and never sees a Guardian, so it
still needs the repair. It is idempotent, so running it on already-coerced
args is a no-op — pinned below.
"""
import asyncio
import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import backend.core.tools as _tools  # noqa: F401  (registers the tools)
from backend.core.agent.verifier import verify
from backend.core.tools.registry import (
    REGISTRY, CapabilityTier, ToolResult, _coerce_args, tool,
)


def _verify(name, args):
    return asyncio.run(verify(user_query="remember my name",
                              call={"name": name, "args": args,
                                    "reasoning": "t", "confidence": 1.0}))


# ── the repair is now reachable ────────────────────────────────────────


def test_an_aliased_required_arg_passes_the_guardian():
    """The regression, in the exact shape of the log line."""
    from backend.core.agents.commander import _coerce_call_args

    call = _coerce_call_args({"name": "remember",
                              "args": {"content": "The user's name is Gajanand"}})
    assert "fact" in call["args"], (
        f"args still {sorted(call['args'])} — the Guardian will reject this "
        "for a missing 'fact' that _coerce_args knows how to supply"
    )
    assert _verify("remember", call["args"]).is_valid is True


def test_the_same_call_is_still_rejected_without_coercion():
    """Pins that the fixture above is actually exercising the fix, rather
    than the Guardian having become lenient."""
    assert _verify("remember", {"content": "x"}).is_valid is False


def test_open_app_alias_is_repaired_too():
    """_coerce_args' own documented example, which was equally unreachable."""
    from backend.core.agents.commander import _coerce_call_args

    call = _coerce_call_args({"name": "open_app", "args": {"app_name": "notepad"}})
    assert "name" in call["args"], sorted(call["args"])


# ── the positional bind is narrowed ────────────────────────────────────


def test_a_single_param_tool_still_gets_the_positional_bind():
    """This is what rescues remember(content=...); it must survive."""
    out = _coerce_args("remember", {"information": "something"})
    assert out == {"fact": "something"}


def test_a_destructive_multi_param_tool_rejects_an_unmatched_key():
    """send_whatsapp(contact, message) is irreversible external comms.
    Binding a stray key into `message` invents the content of a real
    message to a real person."""
    out = _coerce_args("send_whatsapp", {"contact": "Sharath", "gibberish": "?"})
    assert "message" not in out, (
        f"a stray key was bound into an irreversible message body: {out!r}"
    )
    assert _verify("send_whatsapp", out).is_valid is False, (
        "the Guardian accepted a send_whatsapp whose message was guessed"
    )


def test_a_non_destructive_multi_param_tool_keeps_the_bind():
    """The narrowing is about irreversibility, not about arity."""
    @tool(tier=CapabilityTier.READONLY)
    def _coerce_probe_readonly(topic: str, limit: int = 5) -> ToolResult:  # pragma: no cover
        return ToolResult.success("ok")

    name = "_coerce_probe_readonly"
    try:
        out = _coerce_args(name, {"query": "weather"})
        assert out == {"topic": "weather"}, out
    finally:
        REGISTRY.pop(name, None)


# ── validated args == executed args ────────────────────────────────────


def test_coercion_is_idempotent():
    """registry.call() still coerces, because the rule fast path reaches it
    without a Guardian. Running it on already-coerced args must change
    nothing, or the Operator would run something the Guardian never saw."""
    once = _coerce_args("remember", {"content": "x"})
    assert _coerce_args("remember", dict(once)) == once


def test_the_operator_runs_exactly_what_was_validated():
    """The security half. Executed args must equal validated args."""
    from backend.core.agents.commander import _coerce_call_args

    call = _coerce_call_args({"name": "remember", "args": {"text": "hello"}})
    validated = dict(call["args"])
    assert _verify("remember", validated).is_valid is True
    # What registry.call would hand the tool function.
    assert _coerce_args("remember", dict(validated)) == validated, (
        "the Operator would re-map arguments the Guardian had already "
        "approved, so the checked dict and the executed dict differ"
    )


def test_commander_coerces_before_verifying():
    """Wiring guard, and order-sensitive: this is the whole bug."""
    import inspect

    from backend.core.agents import commander as cmd

    src = inspect.getsource(type(cmd.commander)._run_loop_stream)
    assert "_coerce_call_args" in src, "Commander never coerces"
    assert src.index("_coerce_call_args") < src.index("verify_plan"), (
        "coercion runs AFTER the Guardian, which is the original defect"
    )


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            print(f"  [SKIP] {_name} (needs pytest)")
