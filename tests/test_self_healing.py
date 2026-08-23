

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
    """Guards the seam: healing.py matches on text verifier.py produces."""
    import inspect
    from backend.core.agent import verifier
    src = inspect.getsource(verifier)
    assert "Missing required argument" in src, (
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
