# Tool post-condition verification — design

**Date**: 2026-08-23
**Status**: approved, not yet implemented
**Ticket**: extends `T-sentence-queue-turn-ownership`'s sibling class; new ticket `T-tool-claims-unconfirmed`

## The property we want

Onyx must never claim what it did not verify.

Today a tool reports the outcome it *intended*, not the outcome it *achieved*, and the framework stamps every one of those claims with `confidence: 100.0`.

## Evidence

`backend/core/tools/audio.py:21-25` — the simplest tool in the codebase:

```python
def set_volume(level: int) -> dict:
    level = _clamp(level)
    _endpoint().SetMasterVolumeLevelScalar(level / 100.0, None)
    return {"status": "success", "message": f"volume set to {level}%"}
```

It reports the level it was asked for. It never reads back, though `GetMasterVolumeLevelScalar` is used one function below in `volume_up`. If the Set silently no-ops — another process holding the endpoint in exclusive mode, the default device changing between the two calls — Onyx says *"volume set to 50%"* at full confidence and nothing happened.

`volume_up`, `volume_down` and `mute` share the shape: each reads *current* state, then reports *intended* state, never the *achieved* one. There are 31 `"status": "success"` literals across `backend/core/tools/`, and every one is a claim.

This class has already cost three separate fixes, each applied pointwise:

| incident | layer | mechanism |
|---|---|---|
| `"Done."` announced for turns that ran nothing | brain | hardcoded string (fixed, `c2fdd13`) |
| `chrome_tabs.close_matching` reported success while closing nothing | tool | background tabs' close buttons have a `(0,0,0,0)` rect; the click no-ops (fixed for that tool, `952b475`) |
| `[The OCR result will be provided after the tool runs.]` spoken aloud | planner | model narrated ahead of the data (fixed via `_pending_tool_calls`) |

A fabricated completion is the worst failure available. An error is visible and silence is obvious, but a confident success is indistinguishable from having worked — the user only finds out by going to look.

## Scope

**This spec covers the tool layer only.** The planner-narration layer (gating what reaches TTS on the presence of evidence) is a deliberate follow-up, not part of this work. The tools must be honest first: the model can only be honest about results it was told the truth about, and a tool that lies to the planner corrupts the next iteration regardless of any speech-layer gate.

## Design

### 1. The contract — `@tool(verify=...)`

A declared, framework-run callable on the `@tool` decorator, mirroring the established `confirm_if` idiom (`registry.py:143`).

```python
def _volume_disagrees(args, result):
    want = _clamp(args.get("level"))
    got = int(round(_endpoint().GetMasterVolumeLevelScalar() * 100))
    return None if got == want else f"volume is {got}%, expected {want}%"

@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_volume_disagrees)
def set_volume(level: int) -> dict:
    ...
```

Signature: `verify(args: dict, result: ToolResult) -> Optional[str]`.

| verify | outcome | meaning |
|---|---|---|
| returns `None` | **confirmed** | read the world back, it agrees |
| returns a string | **contradicted** | it disagrees; the string is the human reason |
| raises | **unconfirmed** | the read-back itself could not run |
| not declared | **unconfirmed** | no post-condition exists |

Letting the read-back raise is the honest signal for "couldn't check", and the exception never propagates to the caller. This is a deliberate divergence from `confirm_if`, which must never raise because a broken guard there has to fail closed into asking the user. Here there is no user to ask — the action has already happened — so the honest outcome is to record that we do not know.

`verify` runs **after** the tool returns, and must not itself mutate state.

**Relative actions must declare their expected end-state.** `verify` sees only `args` and `result`, which is enough for `set_volume(50)` but not for `volume_up(10)` or `mute()` — their post-condition depends on pre-state the tool read and did not keep. Three of the four proving-ground tools are in this category, so it is the common case, not an edge one.

The rule: a tool whose outcome is relative puts the state it *expected to reach* into `result.data`, and `verify` compares the world against that.

```python
def mute() -> dict:
    ep = _endpoint()
    was_muted = bool(ep.GetMute())
    ep.SetMute(0 if was_muted else 1, None)
    return {"status": "success",
            "message": "unmuted" if was_muted else "muted",
            "data": {"expect_muted": not was_muted}}
```

This is a small honesty win on its own: it forces each tool to state its intent as a checkable value rather than only as English prose in `message`. Note that `run_tool`'s legacy-dict coercion reads `res.get("args") or res.get("data")` into `ToolResult.data` (`runtime.py:86`), so both spellings already work — `get_volume` uses `"args"` today.

### 2. Where it runs

`runtime.run_tool`, at the result-coercion point (`runtime.py:80-89`) — the single place every tool call already becomes a `ToolResult` and where `confidence` currently receives its unconditional `100.0`. `run_tool` takes `name`, so it can reach `REGISTRY[name].verify`.

Runs only when:

- the result status is `SUCCESS` — there is nothing to verify about a `blocked` or `error`, and
- the tool's tier is not `READONLY` — a read tool's result *is* the observation; verifying it would mean reading twice and believing the second read for no reason.

Verification needs its own short timeout — by the coercion point the tool's `asyncio.wait_for` has already returned, so its budget is spent and cannot cover the check. A read-back is a cheap local call; a couple of seconds is generous. Because `verify` is a plain sync callable in the common case (the audio ones make blocking COM calls), it runs in the executor rather than on the event loop, the same way `run_tool` already dispatches sync tool functions (`runtime.py:62-64`).

A `verify` that hangs or explodes yields **unconfirmed**, never an error: the check failing tells us nothing about whether the action succeeded, and turning "I couldn't look" into "it failed" is its own false claim.

### 3. What it produces

Into fields that already exist and are currently inert (`registry.py:74-75`):

| outcome | status | confidence | confidence_reason |
|---|---|---|---|
| confirmed | `SUCCESS` | 100.0 | what was read back |
| unconfirmed | `SUCCESS` | reduced | why not (`"no post-condition declared"`, or the exception) |
| contradicted | **`ERROR`** | 0.0 | the disagreement, e.g. `"volume is 30%, expected 50%"` |

Contradicted becoming `ERROR` is the load-bearing decision. The world was read and it disagrees; that is not a low-confidence success, it is a failure that happens to have been detected.

Unconfirmed staying `SUCCESS` is equally deliberate. It keeps the 31 existing tools working while the retrofit proceeds, and avoids an invisible fail-closed — the pattern that made an Ollama outage look exactly like bad speech recognition.

The exact reduced-confidence value is an implementation choice, not a contract; only the ordering `confirmed > unconfirmed > contradicted` is specified.

### 4. What changes downstream

Three consumers read tool success today. All three currently treat all successes as equal.

**a. The planner handback** — the highest-leverage one. `operator.py:63` already does `res.model_dump()`, so `confidence` and `confidence_reason` **already reach the planner's `tool_results` JSON** (`commander.py:399`). The pipe exists and transmits a constant. This work puts real information into it; the planner's system prompt must then state that an unconfirmed result may not be narrated as confirmed.

**b. `summarize_outcome`** (`brain.py:33`) — the no-spoken-text fallback. Already prefers each tool's own message. Unconfirmed results get hedged: *"I set volume to 50%, but couldn't confirm it"* rather than *"volume is 50%"*.

**c. `_confirmed_summary`** (`commander.py:98`) — what is spoken after a confirmed action. Same hedging rule. Notable because this is the path the user explicitly authorised, which makes a false success claim here the most costly of the three.

### 5. Naming collision — resolved by naming the new concept, not renaming the old

`_publish_completed("verified", ...)` (`commander.py:391`) already uses "verified" to mean *Guardian approved the plan before execution* — a pre-condition on intent, roughly the opposite of a post-condition on outcome.

The first instinct was to rename that one. **Don't.** That string is a typed union on both sides of the process boundary — `ui_events.py:131` and `frontend/src/lib/uiEvents.ts:36` — so renaming it is a py↔ts event-contract change, and this repo keeps a standing guard on exactly that contract. It would turn a self-contained backend change into a cross-boundary one for a word.

So the **new** concept takes distinct vocabulary instead:

- the decorator kwarg stays `verify=` — it is a tool-declaration API, a different namespace from the event status, and it reads naturally at the call site;
- the **outcomes** are `confirmed` / `unconfirmed` / `contradicted`, and those are the words used in `confidence_reason` strings, log lines and docs.

`AgentCompletedEvent.status == "verified"` keeps its existing pre-execution meaning, untouched. A comment at the outcome definitions records why the two vocabularies differ, so the next reader does not "fix" the inconsistency by reintroducing the collision.

## Scope of the first pass

Contract + chokepoint + **`audio.py`'s four tools as the proving ground**. Not all 31.

They are the cleanest available case (the read-back API is one line away), they are provably wrong today, and retrofitting four real tools validates the contract before it is applied widely. Remaining modules retrofit module-by-module afterwards, each with its own evidence.

Explicitly out of scope for this pass:

- The planner-narration gate (separate layer, separate design).
- A registration-time warning for side-effecting tools that declare no `verify`. Worth doing — it is the same forcing function that makes the tier default fail safe — but it should land after the contract has survived one real retrofit, or it will warn about 27 tools on every boot before anyone can act on it.

## Testing

**Anchor test, written first.** Stub the audio endpoint so `SetMasterVolumeLevelScalar` silently no-ops while `GetMasterVolumeLevelScalar` keeps returning the old value; call `set_volume(50)`; assert the result is not a success claim. This fails against current code, which is the point.

Then:

- Each of the three outcomes at the `run_tool` chokepoint, with a fake tool: verify returns `None` / a string / raises.
- A `verify` that hangs or raises does not fail the turn.
- `READONLY` tools are not checked.
- A non-`SUCCESS` result is not checked.
- The three downstream consumers each hedge an unconfirmed result and none of them speak completion grammar for a contradicted one.
- Retrofit tests for all four audio tools against a stubbed endpoint.

**Live probe before this is called done.** Unit tests on a stubbed endpoint prove the contract, not the pipeline — the same distinction that let `close_matching` pass 12 unit tests while closing nothing. Set the real volume to a known value, run a real turn, confirm what Onyx *says* matches what the endpoint *reads*.

## Adjacent finding, recorded not fixed

`operator.py:60-64` appends result wrappers keyed `"name"`, but `commander.py:114` and `commander.py:251` both read `wrapper.get("tool")`. That lookup always misses. Consequences: the timeline records `"Executed unknown tool: <msg>"` for every confirmed action, and a failed confirmed action with no message says *"I tried to X, but it failed: that"*. Real, small, and a different bug — it should not be bundled into this change.
