import asyncio
import json
import logging
import re
import time
import uuid
from typing import List, Optional, Tuple, AsyncGenerator, Any

from backend.core.agent.context import ConversationContext
from backend.core.agents.guardian import GuardianAgent
from backend.core.agents.operator import OperatorAgent
from backend.core.agents.pending_confirmation import (
    Pending,
    classify_reply,
    store as pending_store,
)
from backend.core.agents.planner import PlannerAgent
from backend.core.context.builder import context_builder
from backend.core.context.types import RequestContext
from backend.core.events import get_bus
from backend.core.healing import healer as self_healer
from backend.core.memory.episodic import summarizer as episodic_summarizer
from backend.core.memory.timeline import timeline
from backend.daemon.ui_events import AgentCompletedEvent, SelfHealingEvent

log = logging.getLogger(__name__)

MAX_ITER = 5

# T-planner-canvas-chain: "Summarize results for the user." cues the planner
# toward a spoken summary, and some fraction of the time it fabricates a
# render claim instead of calling render_canvas. Canvas-intent queries get
# an explicit render instruction on the iteration-2 handback.
_CANVAS_INTENT_RE = re.compile(r"\bcanvas\b|\bshow\s+me\b|\bdisplay\b|\brender\b", re.IGNORECASE)


# Which arguments a confirmation must read back, per tool.
#
# Naming only the tool ("permission to send whatsapp") is unanswerable for
# anything outbound: it cannot catch a false wake putting words into a message
# the user never dictated, nor a misheard recipient. Both are observed live.
#
# Scoped to outbound content on purpose. Reading back every argument of every
# confirmation would make the prompt long enough that the user stops listening
# to it, which is the failure this is trying to avoid, not cause.
#
# tests/test_confirmation_reads_back_content.py fails if a DESTRUCTIVE tool is
# added to tools/comms.py without an entry here, so this cannot rot quietly.
_READBACK_FIELDS: dict[str, tuple[str, ...]] = {
    "send_whatsapp": ("contact", "message"),
    "send_email": ("to", "subject"),
    "send_to_phone": ("content",),
}

# Spoken aloud, so it has a budget. Long enough for a normal message, short
# enough that a pasted paragraph does not become a recital.
_READBACK_MAX_CHARS = 160


from backend.core.agents.pending_clarification import (  # noqa: E402
    Clarification as _Clarification,
    context_for as _clarification_context,
    parse_missing_arg as _parse_missing_arg,
    store as _clarification_store,
)


def _coerce_call_args(call: dict) -> dict:
    """Repair a planner call's argument NAMES before validation.

    Same repair registry.call() applies at execution time — run here so the
    Guardian validates what the Operator will actually receive. It stays in
    registry.call() as well, because the rule fast path reaches the registry
    directly and never sees a Guardian; _coerce_args is idempotent, so the
    second pass is a no-op on an already-repaired dict.

    Never raises: a malformed call must reach the Guardian and be rejected
    there, with its own error message, rather than dying here.
    """
    if not isinstance(call, dict):
        return call
    name, args = call.get("name"), call.get("args")
    if not isinstance(name, str) or not isinstance(args, dict):
        return call
    try:
        from backend.core.tools.registry import REGISTRY, _coerce_args

        if name not in REGISTRY:
            return call
        repaired = _coerce_args(name, args)
    except Exception:
        return call
    if repaired == args:
        return call
    log.info("arg repair before verification: %s %s -> %s",
             name, sorted(args), sorted(repaired))
    out = dict(call)
    out["args"] = repaired
    return out


def _readback_args(call: dict) -> str:
    """What this call will actually send, phrased for speech.

    Returns "" when there is nothing worth reading back — a non-messaging
    tool, or a call whose arguments have not been filled in yet (which is the
    normal state on the clarification path, so it must not raise).
    """
    fields = _READBACK_FIELDS.get((call or {}).get("name", ""))
    if not fields:
        return ""
    args = (call or {}).get("args") or {}
    if not isinstance(args, dict):
        return ""

    parts = []
    for field in fields:
        value = args.get(field)
        if value is None or not str(value).strip():
            continue
        text = " ".join(str(value).split())
        if len(text) > _READBACK_MAX_CHARS:
            text = text[:_READBACK_MAX_CHARS].rstrip() + "..."
        parts.append(f"{field} {text}")
    return ", ".join(parts)


def _fan_out_summary(calls: list, limit: int = 4) -> str:
    """"open Notepad, open Chrome, open Firefox and 3 more" — spoken aloud.

    Prefers the argument over the tool name: "open app, open app, open app"
    tells the user nothing about what is going to happen to their desktop.
    """
    labels: list[str] = []
    for call in calls:
        name = str(call.get("name") or "action").replace("_", " ")
        args = call.get("args") or {}
        target = ""
        if isinstance(args, dict):
            for key in ("name", "target", "query", "app", "text", "url"):
                value = args.get(key)
                if isinstance(value, str) and value.strip():
                    target = value.strip()
                    break
        labels.append(f"{name} {target}".strip() if target else name)

    if len(labels) <= limit:
        if len(labels) == 1:
            return labels[0]
        return ", ".join(labels[:-1]) + f" and {labels[-1]}"
    return ", ".join(labels[:limit]) + f" and {len(labels) - limit} more"


def _pending_tool_calls(content) -> list:
    """Tool calls carried in a planner 'final' envelope, or [].

    Models routinely emit final_response AND tool_calls together, where the
    prose narrates what the tool is ABOUT to return — sometimes with a literal
    placeholder. Observed live reading a Notepad window:

        I've read the text from the Notepad window. Here's what it says:
        [The OCR result will be provided after the tool runs.]

    Commander used to test for "final_response" first, speak it and return, so
    ocr_screen never ran. That is worse than an error: an error is visible,
    while this is a fluent confident sentence with no data behind it.

    When both are present the tool calls win; the answer is produced on the
    next iteration with real results in history. Tolerant of malformed input
    on purpose — it parses model output, so it must never be what crashes a
    turn.
    """
    if isinstance(content, list):
        return content
    if not isinstance(content, dict):
        return []
    # planner.py accepts both spellings; knowing only one would let the other
    # through as a spoken placeholder.
    calls = content.get("tool_calls") or content.get("toolCalls") or []
    return calls if isinstance(calls, list) else []


def _iteration_instruction(user_query: str) -> str:
    """The instruction handed back to the planner with tool results.

    Kept as one function so the canvas-chain probe can validate the real
    path instead of its own copy of the string."""
    if _CANVAS_INTENT_RE.search(user_query):
        return (
            "Now call render_canvas with widgets built from these tool_results. "
            "Do NOT emit final_response until render_canvas has actually been called."
        )
    return "Summarize results for the user."


def _plan_confidence(calls: list[dict]) -> float:
    """Weakest-link confidence of a tool plan, on AgentCompletedEvent's 0-100 scale.

    The planner declares per-call confidence on a 0.0-1.0 scale (see the
    system prompt in planner.py), while AgentCompletedEvent.confidence is
    0-100. Skipping this conversion renders every response as "1%" behind a
    danger-red bar — plausible enough to survive review, which is exactly why
    it is done in one place instead of at each call site.
    """
    confs = [
        c.get("confidence")
        for c in calls
        if isinstance(c.get("confidence"), (int, float))
    ]
    if not confs:
        return 100.0
    return max(0.0, min(100.0, min(confs) * 100))


def _confirmed_summary(batch_results: list[dict], tool_name: str) -> str:
    """What to say after an authorised action ran.

    Prefers the tool's own message — "Playing Lo-fi beats" beats "Done" — and
    reports failure honestly rather than claiming success, which is the whole
    reason the user was asked in the first place.
    """
    messages, failed = [], []
    for wrapper in batch_results:
        res = wrapper.get("result")
        status = getattr(res, "status", res.get("status") if isinstance(res, dict) else "error")
        msg = getattr(res, "message", res.get("message") if isinstance(res, dict) else None)
        if status == "success":
            if msg:
                from backend.core.brain import _hedge
                messages.append(_hedge(str(msg), res))
        else:
            # A contradicted post-condition builds its ToolResult with `reason`
            # and no `message` — "volume is 30%, expected 50%" is the single
            # most informative sentence this feature can produce, and reading
            # only `message` dropped it. The wrapper key is "name" (see
            # operator.execute_batch), never "tool", so the old fallback always
            # missed and the user heard "...but it failed: that".
            reason = getattr(res, "reason", res.get("reason") if isinstance(res, dict) else None)
            failed.append(
                str(msg) if msg
                else str(reason) if reason
                else wrapper.get("name", "that")
            )
    if failed:
        return f"I tried to {tool_name}, but it failed: {failed[0]}"
    if messages:
        return messages[0]
    return f"Done — {tool_name}."


def _publish_completed(
    status: str, confidence: float, t0: float, summary: str | None
) -> None:
    """Announce the Commander's turn outcome. Never raises — telemetry must
    not break the response path."""
    try:
        get_bus().publish(
            AgentCompletedEvent(
                agent_name="Commander",
                status=status,
                confidence=confidence,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                summary=summary,
            )
        )
    except Exception as e:
        log.warning("AgentCompletedEvent publish failed: %s", e)


class CommanderChunk:
    """Streaming chunk from Commander."""
    def __init__(self, type: str, content: Any = None, metadata: dict = None):
        self.type = type
        self.content = content
        self.metadata = metadata or {}


# Sentinel closing the pump queue. A private object rather than None, which is
# a legitimate CommanderChunk payload.
_PUMP_DONE = object()

# Chunk type meaning "the user interrupted this turn". Consumers must end the
# turn WITHOUT speaking: there is no answer to give, and the fallback text is
# an accusation of mishearing. Exported so brain.py and tests name the same
# thing rather than matching on a string literal in two places.
INTERRUPTED = "interrupted"


class CommanderAgent:
    """The central orchestrator of the specialized internal agents."""

    def __init__(self):
        self.planner = PlannerAgent()
        self.guardian = GuardianAgent()
        self.operator = OperatorAgent()
        # The task running THIS commander's reasoning loop, and the loop it
        # belongs to. Never the caller's task — see run_stream.
        self._current_task: Optional[asyncio.Task] = None
        self._current_loop: Optional[asyncio.AbstractEventLoop] = None

    def interrupt(self):
        """Abort the in-flight reasoning/execution loop.

        Called from the WAKE-WORD LISTENER THREAD (on_wake_detected and
        on_barge_in both call it), so it must not touch the task directly:
        Task.cancel() reaches into the owning loop's callback queue and is not
        thread-safe. It appeared to work because the loop was usually running,
        which is what a race looks like right up until it isn't.

        A closed loop means the turn it belonged to is already over, so a
        RuntimeError here is the no-op it should be.
        """
        task = self._current_task
        loop = self._current_loop
        if task is None or loop is None or task.done():
            return
        try:
            loop.call_soon_threadsafe(task.cancel)
        except RuntimeError:
            return
        log.info("Commander: Interrupted by user.")

    async def run(self, text: str, context: ConversationContext, user_id: str | None = None) -> Tuple[str, List[dict]]:
        """Non-streaming entry point — collects all chunks and returns final result."""
        spoken = ""
        tool_records = []
        async for chunk in self.run_stream(text, context, user_id):
            if chunk.type == "final_response":
                spoken = chunk.content
            elif chunk.type == "tool_end":
                tool_records.append(chunk.content)
        return spoken, tool_records

    async def run_stream(self, text: str, context: ConversationContext, user_id: str | None = None) -> AsyncGenerator[CommanderChunk, None]:
        """Streaming entry point — yields chunks as they're ready.

        The reasoning loop runs in its OWN task, feeding a queue this generator
        drains. That indirection is the whole point: `interrupt()` cancels
        `_current_task`, and this used to be `asyncio.current_task()` — which
        on the voice path is the main task of `asyncio.run(_handle_wake_async)`,
        i.e. the entire turn. Cancelling it aborted whatever the turn happened
        to be doing, and live that was TTS playback:

            File "backend/daemon/trigger.py", line 449, in _process_and_execute
                await _speak_selective(reply, device_id)
              File "backend/ai_modules/speech/tts_piper.py", line 410, in speak_stream
                await session.player
            asyncio.exceptions.CancelledError

        CancelledError is a BaseException, so trigger's and wake_word's
        `except Exception` guards both missed it: the wake-turn thread died and
        the state machine stayed in SPEAKING.

        The `except asyncio.CancelledError` that used to sit here only covered
        the case where the cancel landed WHILE the loop was running. It could
        not cover the one that actually bit — a consumer that stops iterating
        early (brain.run() returns the moment it sees a `final` chunk) leaves
        this generator suspended at a `yield` with `_current_task` still set,
        so the next wake word cancelled a turn that had moved on to speaking.
        A task that only ever runs `_run_loop_stream` cannot have that problem
        regardless of when the cancel arrives.

        The queue is unbounded and fed with put_nowait so neither side can
        deadlock the other; run-ahead is bounded by MAX_ITER anyway.
        """
        queue: asyncio.Queue = asyncio.Queue()

        async def _pump() -> None:
            try:
                async for chunk in self._run_loop_stream(text, context, user_id):
                    queue.put_nowait(chunk)
            finally:
                # Always closes the queue, including on cancellation, so the
                # drain below can never park on a producer that is gone.
                queue.put_nowait(_PUMP_DONE)

        pump = asyncio.create_task(_pump())
        self._current_task = pump
        self._current_loop = asyncio.get_running_loop()
        try:
            while True:
                item = await queue.get()
                if item is _PUMP_DONE:
                    break
                yield item
            # _PUMP_DONE came from the pump's own finally, so it is finishing;
            # wait so cancelled()/exception() below are meaningful. wait() does
            # not re-raise, which is what we want — the outcome is inspected.
            await asyncio.wait({pump})
        finally:
            if not pump.done():
                pump.cancel()
            # Only clear if still ours: an overlapping turn may already have
            # taken the slot, and nulling shared state we no longer own is the
            # bug pattern T-tts-loop-globals documents.
            if self._current_task is pump:
                self._current_task = None
                self._current_loop = None

        if pump.cancelled():
            # Its own chunk type, not "error". Brain has no branch for chunks
            # it does not know, so an interrupted turn used to fall out of the
            # loop and answer with summarize_outcome([]) — "I'm not sure what
            # to do with that — could you say it again?". The user cut us off
            # and got told they were misheard.
            yield CommanderChunk(INTERRUPTED, "Interrupted")
            return
        exc = pump.exception()
        if exc is not None:
            raise exc

    async def _run_loop_stream(self, text: str, context: ConversationContext, user_id: str | None) -> AsyncGenerator[CommanderChunk, None]:
        t0 = time.perf_counter()
        # 1. Build unified context via ContextBuilder
        request = RequestContext(
            user_intent=text,
            user_id=user_id,
            session_id=context.session_id,
            request_id=str(uuid.uuid4())[:8],
            input_mode="voice",
        )
        agent_context = await context_builder.collect(request)

        # 2. Setup Request
        request_id = agent_context.request_id

        # ORDER IS LOAD-BEARING: the current turn must be added BEFORE the
        # snapshot. This used to snapshot first, so `history` excluded the
        # question being asked — and because the Planner only appended
        # user_query when history was empty, every turn after the first
        # answered the PREVIOUS question. Turn 1 worked, which is why
        # single-shot tests never caught it.
        #
        # history must also *contain* the current turn rather than have the
        # Planner append it, because the loop below appends corrections and
        # tool results to `history`; a question appended after those would
        # land out of order.
        context.add_user(text)
        agent_context.recent_conversation = context.render()
        history = agent_context.recent_conversation
        
        # Record user query in timeline
        timeline.record_event(content=f"User asked: \"{text}\"", source="user_query")

        tool_records: list[dict] = []
        # Set when the Guardian rejects a call for a missing argument, so that
        # if this turn ends by ASKING for it we can hold the partial call.
        unfilled: tuple[str, dict, str] | None = None

        # A question this assistant asked on an earlier turn, possibly in an
        # earlier chain. Taken (not peeked) so it is consumed whatever the
        # planner decides — an ignored question must not stay answerable later.
        #
        # Passed as CONTEXT, never auto-applied: the planner decides whether
        # this utterance answers it. Stuffing it in here would mean "Onyx,
        # what's the weather" sends the weather to Sharath.
        _clar = _clarification_store.take(context.session_id)
        if _clar is not None:
            log.info("Clarification pending for %r (missing %r); offering it "
                     "to the planner as context", _clar.tool, _clar.missing)
            history.insert(max(len(history) - 1, 0),
                           {"role": "user", "content": _clarification_context(_clar)})

        # ── Answer to a pending "should I proceed?" ──────────────────────
        # take() POPS unconditionally: whatever this turn says, the previous
        # prompt is now closed. An unanswered prompt must not survive to be
        # accidentally authorised by a later "sure" meant for something else.
        pending = pending_store.take(context.session_id)
        if pending is not None:
            reply = classify_reply(text)
            if reply == "no":
                spoken = f"Okay, I won't {pending.tool_name}."
                context.add_assistant(spoken)
                yield CommanderChunk("final_response", spoken)
                _publish_completed("completed", 100.0, t0, spoken)
                return
            if reply == "yes":
                log.info(
                    "Confirmation granted for %r (critical=%s)",
                    pending.tool_name, pending.is_critical,
                )
                # Execute what was already verified. These calls passed every
                # check including the LLM secondary check — confirmation was
                # the only thing outstanding, so re-verifying would just ask
                # the same question again.
                batch_results = await self.operator.execute_batch(
                    pending.calls, request_id
                )
                tool_records.extend(batch_results)
                for res_wrapper in batch_results:
                    res = res_wrapper.get("result")
                    status = getattr(res, "status", res.get("status") if isinstance(res, dict) else "error")
                    if status == "success":
                        # "name", not "tool": operator.execute_batch keys its
                        # wrappers "name".
                        name = res_wrapper.get("name", "unknown tool").replace("_", " ")
                        msg = getattr(res, "message", res.get("message") if isinstance(res, dict) else "success")
                        timeline.record_event(
                            content=f"Executed {name}: {msg}", source="execution"
                        )
                for res in batch_results:
                    yield CommanderChunk("tool_end", res)
                spoken = _confirmed_summary(batch_results, pending.tool_name)
                context.add_assistant(spoken)
                yield CommanderChunk("final_response", spoken)
                _publish_completed("completed", 100.0, t0, spoken)
                return
            # Anything else is a new request. The pending is already discarded
            # above; fall through and plan this turn normally.
            log.info(
                "Pending confirmation for %r dropped — user said something else",
                pending.tool_name,
            )

        for _iter in range(MAX_ITER):
            # A. Planner Stage (receives full AgentContext) - streaming
            async for chunk in self.planner.generate_plan_stream(text, history, agent_context):
                if chunk["type"] == "token":
                    yield CommanderChunk("token", chunk["content"], {"request_id": request_id})
                elif chunk["type"] == "prose":
                    # Speakable text only — see agents/prose_stream.py. Kept
                    # distinct from "token" so TTS never sees the JSON envelope
                    # while the UI ticker and latency marks still get raw tokens.
                    yield CommanderChunk("prose", chunk["content"], {"request_id": request_id})
                elif chunk["type"] == "final":
                    content = chunk["content"]
                    queued_calls = _pending_tool_calls(content)
                    if (isinstance(content, dict) and "final_response" in content
                            and not queued_calls):
                        # A question, not an answer: the planner gave up on a
                        # call the Guardian rejected for a missing argument and
                        # asked the user for it. Hold the half-built call so the
                        # reply completes it — even after this chain dies and
                        # the user says the wake word again, which is exactly
                        # how the live WhatsApp turn was lost.
                        if unfilled is not None:
                            tool_name, known_args, missing = unfilled
                            _clarification_store.remember(
                                context.session_id,
                                _Clarification(
                                    tool=tool_name, args=known_args,
                                    missing=missing,
                                    question=str(content["final_response"]),
                                ),
                            )
                        yield CommanderChunk("final_response", content["final_response"])
                        context.add_assistant(content["final_response"])
                        asyncio.create_task(episodic_summarizer.summarize_and_store(text, tool_records))
                        _publish_completed(
                            "completed", 100.0, t0, content["final_response"]
                        )
                        return
                    # tool_calls
                    if isinstance(content, dict) and "final_response" in content and queued_calls:
                        log.warning(
                            "Planner answered AND asked for tools in one envelope; "
                            "running the tools and discarding the premature answer: %r",
                            str(content.get("final_response"))[:120],
                        )
                    calls = queued_calls or (
                        content if isinstance(content, list) else [content])
                    # Repair argument NAMES before the Guardian sees them, not
                    # after. _coerce_args used to run at registry.call(), so a
                    # planner alias on a REQUIRED argument was rejected before
                    # the repair could reach it:
                    #
                    #   Guardian rejected: ["Missing required argument 'fact'
                    #                        for tool 'remember'."]
                    #
                    # while _coerce_args maps content/text/facts onto `fact`
                    # perfectly well. Coercing here also closes a hole that is
                    # not about this bug at all: the Guardian was validating
                    # one dict while the Operator executed another.
                    calls = [_coerce_call_args(c) for c in calls]
                    # B. Guardian Stage (Verification)
                    # verify_plan signature is (user_query, calls, request_id, agent_context) — the
                    # fourth arg carries metadata (trigger_source) that the verifier's tier gate uses
                    # to require confirmation on non-explicit-wake turns.
                    valid_calls, pending_calls, errors = await self.guardian.verify_plan(text, calls, request_id, agent_context)

                    if errors:
                        log.warning(f"Commander: Guardian rejected parts of the plan: {errors}")
                        last_error = errors[-1]
                        # Remember WHAT was half-built, in case this retry ends
                        # with the planner asking the user instead of filling
                        # it in. Recorded here rather than at the question
                        # because by then `calls` is gone. See the write at the
                        # final_response branch.
                        _missing = _parse_missing_arg(last_error)
                        if _missing and calls and isinstance(calls[0], dict):
                            unfilled = (_missing[1], dict(calls[0].get("args") or {}),
                                        _missing[0])
                        # Guardian can reject a plan whose calls list is empty or
                        # malformed — don't let the recovery path itself crash.
                        failed_tool = calls[0].get("name", "unknown") if calls and isinstance(calls[0], dict) else "unknown"
                        path = self_healer.analyze(failed_tool, last_error)
                        instruction = self_healer.get_instruction(path, failed_tool, last_error)
                        get_bus().publish(SelfHealingEvent(
                            tool_name=failed_tool, error=last_error, path=path.value,
                        ))
                        # The healer silently rewrites the turn — it retries, pivots
                        # or aborts and the user sees only a delay. SelfHealingEvent
                        # existed for this, with ws_ui and remote.py already carrying
                        # it, but nothing had ever constructed one, so the whole
                        # recovery path was invisible to every observer.

                        history.append({"role": "assistant", "content": json.dumps({"tool_calls": calls})})
                        history.append({"role": "user", "content": f"Correction needed: {instruction}"})
                        continue

                    if pending_calls:
                        first_pending = pending_calls[0]
                        tool_name = first_pending.get("name", "action").replace("_", " ")
                        is_critical = first_pending.get("is_critical", False)

                        # Read back the content for anything outbound, on EVERY
                        # branch. It was added to the plain branch first and
                        # that was backwards: send_whatsapp is classified
                        # critical, so the most dangerous tool got the least
                        # informative prompt. Caught by driving the real loop
                        # in test_pending_clarification_end_to_end.
                        detail = _readback_args(pending_calls[0]) if pending_calls else ""

                        if is_critical:
                            spoken = (f"⚠️ CRITICAL ACTION: I need your explicit "
                                      f"permission to {tool_name}")
                            if detail:
                                spoken += f" — {detail}"
                            spoken += ". This is a high-risk operation. Should I proceed?"
                        elif any(c.get("fan_out") for c in pending_calls):
                            # Naming only the first of six app launches would
                            # ask "permission to open app" and hide the scale,
                            # which is the whole reason this prompt exists.
                            spoken = (
                                f"That's {len(pending_calls)} actions from one "
                                f"request — {_fan_out_summary(pending_calls)}. "
                                f"Should I do all of them?"
                            )
                        else:
                            # "Yes" to a bare "permission to send whatsapp"
                            # authorises an unknown message to an unknown
                            # person — exactly what a false wake or a misheard
                            # dictation produces. Empty for every other tool.
                            if detail:
                                spoken = (f"I need your permission to {tool_name} "
                                          f"— {detail}. Should I proceed?")
                            else:
                                spoken = f"I need your permission to {tool_name}. Should I proceed?"

                        # Remember what we are asking about. Without this the
                        # question was unanswerable: the prompt was spoken and
                        # `first_pending` died with the frame, so "yes" arrived
                        # as an unrelated new turn and the action never ran.
                        pending_store.remember(
                            context.session_id,
                            Pending(
                                calls=pending_calls,
                                user_query=text,
                                tool_name=tool_name,
                                is_critical=is_critical,
                            ),
                        )
                        context.add_assistant(spoken)
                        yield CommanderChunk("final_response", spoken)
                        # Completed its turn — asking for permission is a
                        # finished outcome, not a failure.
                        _publish_completed("completed", 100.0, t0, spoken)
                        return

                    # C. Operator Stage (Execution)
                    batch_results = await self.operator.execute_batch(valid_calls, request_id)
                    tool_records.extend(batch_results)

                    # Record successful tool executions in timeline
                    for res_wrapper in batch_results:
                        res = res_wrapper.get("result")
                        status = getattr(res, "status", res.get("status") if isinstance(res, dict) else "error")
                        if status == "success":
                            tool_name = res_wrapper.get("name", "unknown tool").replace("_", " ")
                            msg = getattr(res, "message", res.get("message") if isinstance(res, dict) else "success")
                            timeline.record_event(
                                content=f"Executed {tool_name}: {msg}",
                                source="execution"
                            )

                    # Yield tool results
                    for res in batch_results:
                        yield CommanderChunk("tool_end", res)

                    # D. Assessment Stage
                    if len(batch_results) == 1:
                        res = batch_results[0]["result"]
                        status = getattr(res, "status", res.get("status") if isinstance(res, dict) else "error")
                        msg = getattr(res, "message", res.get("message") if isinstance(res, dict) else None)
                        
                        if status == "success" and msg:
                            # The dominant spoken path. Without the hedge every
                            # tool with no declared post-condition spoke its
                            # claim verbatim, which is exactly the flattening
                            # this branch exists to prevent. Imported inside the
                            # function: brain imports commander, so a top-level
                            # import is circular.
                            from backend.core.brain import _hedge
                            spoken = _hedge(str(msg), res)
                            context.add_assistant(spoken)
                            asyncio.create_task(episodic_summarizer.summarize_and_store(text, tool_records))
                            yield CommanderChunk("final_response", spoken)
                            # Guardian verified the plan and Operator executed it.
                            _publish_completed(
                                "verified", _plan_confidence(valid_calls), t0, spoken
                            )
                            return

                    # Multi-tool summary request
                    history.append({"role": "assistant", "content": json.dumps({"tool_calls": valid_calls})})
                    history.append({
                        "role": "user", 
                        "content": json.dumps({"tool_results": batch_results, "instruction": _iteration_instruction(text)})
                    })

        exhausted = "I tried a few steps but couldn't finish that."
        yield CommanderChunk("final_response", exhausted)
        _publish_completed("failed", 0.0, t0, exhausted)


# Global instance
commander = CommanderAgent()
