

# ── Guardian's missing-argument error must reach the FIX path ─────────

def test_missing_required_argument_is_a_fix_not_a_clarification_request():
    """Live probe, n=9 real turns: 2-3 produced

        Commander: Guardian rejected parts of the plan:
        ["Missing required argument 'level' for tool 'set_volume'."]

    and Onyx then asked "Could you tell me the exact volume level?" for a
    command that already said seventy. The healer classified it ESCALATE and
    handed the planner the default instruction, which literally ends "Ask the
    user for clarification."

    Cause was a substring miss: the rule tested for "missing argument", and
    "missing argument" is NOT a substring of "missing required argument".
    """
    from backend.core.healing import RecoveryPath, healer

    # Built the way the verifier builds it, so a reword there fails this test
    # rather than silently un-fixing the bug.
    req, resolved = "level", "set_volume"
    real_error = f"Missing required argument {req!r} for tool {resolved!r}."

    path = healer.analyze("set_volume", real_error)
    assert path == RecoveryPath.FIX, (
        f"missing-argument error classified {path}; ESCALATE tells the planner "
        "to ask the user for a value the user already gave"
    )

    instruction = healer.get_instruction(path, "set_volume", real_error)
    assert "ask the user" not in instruction.lower(), instruction


def test_the_verifier_still_words_it_that_way():
    """Guards the seam: healing.py matches on text the verifier produces.

    Asserted on the verifier's actual OUTPUT rather than its source: the
    schema check moved into tool_policy.py, and a grep of verifier.py would
    have broken on a move that changed no behaviour — or passed on a comment."""
    import asyncio
    import backend.core.tools  # noqa: F401
    from backend.core.agent import verifier
    res = asyncio.run(verifier.verify("", {"name": "set_volume", "args": {}}))
    assert not res.is_valid
    assert "Missing required argument" in res.error, (
        "verifier reworded its missing-arg error; healing.py matches on it"
    )


def test_fix_instruction_tells_the_planner_to_use_the_original_request():
    """Not just 'correct the parameters' — the value is already in the user's
    words, and the planner's failure mode is asking for it again."""
    from backend.core.healing import RecoveryPath, healer

    instruction = healer.get_instruction(
        RecoveryPath.FIX, "set_volume",
        "Missing required argument 'level' for tool 'set_volume'.",
    )
    low = instruction.lower()
    assert "original request" in low or "user's request" in low, instruction
