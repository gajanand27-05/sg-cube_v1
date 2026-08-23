import asyncio
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from backend.core.events import get_bus
from backend.core.tools.registry import ToolResult, ToolStatus
from backend.daemon.ui_events import ToolFinishedEvent, ToolStartedEvent

log = logging.getLogger(__name__)

# ── Post-condition outcomes (T-tool-claims-unconfirmed) ──────────────
#
# A side-effecting tool reports the outcome it INTENDED, not the one it
# achieved: set_volume returned "volume set to 50%" without ever reading the
# volume back, stamped confidence 100.0 by this very function. Three outcomes
# now exist instead of one.
#
# Vocabulary is confirmed / unconfirmed / contradicted, NOT "verified" —
# AgentCompletedEvent.status already spends that word on Guardian's
# pre-execution plan approval, and it is a typed union on both sides of the
# py/ts boundary. Two meanings for one word across a process boundary is how
# you get a bug nobody can describe.
_UNCONFIRMED_CONFIDENCE = 60.0
_VERIFY_TIMEOUT_S = 2.0

# A hung verify() must not hang the CURRENT turn. If it ran on the default
# executor, asyncio.run(main()) would wait for that executor to fully drain
# on shutdown (shutdown_default_executor) before returning — so a sync
# verify() that ignores the wait_for timeout would still hold up that
# asyncio.run() call for its full duration even though wait_for itself
# returned on time. This matters most in tests (each one is its own
# asyncio.run()); the daemon's event loop is long-lived, so in production
# shutdown_default_executor only fires once, at real process shutdown.
#
# A dedicated executor avoids that per-asyncio.run() join. It does NOT make a
# hang free: concurrent.futures.thread installs an atexit hook (_python_exit)
# that joins EVERY ThreadPoolExecutor ever created, this one included, at
# final interpreter shutdown — independent of asyncio.run(). A verify() that
# hangs forever still blocks process exit; this executor only moves that
# block from "end of each asyncio.run()" to "interpreter teardown", it does
# not eliminate it. verify callables MUST NOT block indefinitely — the
# _VERIFY_TIMEOUT_S wait_for bounds how long the CALLER waits, but nothing
# can force an uncooperative sync call (e.g. a hung blocking COM call) to
# actually stop running in its worker thread.
_VERIFY_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool-verify")


async def _apply_post_condition(name: str, args: dict, res: ToolResult) -> ToolResult:
    """Check a successful side-effecting tool's claim against the world.

    Never raises and never blocks the loop: verify callables are sync in the
    common case (the audio ones make blocking COM calls), so this dispatches
    to the executor the same way run_tool dispatches sync tools.

    A check that raises or hangs yields UNCONFIRMED, never ERROR. "I could not
    look" is not "it failed", and conflating them is its own false claim.
    """
    from backend.core.tools.registry import REGISTRY, CapabilityTier

    if res.status != ToolStatus.SUCCESS:
        return res

    tool_obj = REGISTRY.get(name)
    if tool_obj is None or tool_obj.tier == CapabilityTier.READONLY:
        # READONLY: the tool's result IS the observation. Reading a second time
        # and believing that one instead buys nothing.
        return res

    if tool_obj.verify is None:
        # min(), not assignment. Several tools already read the world back
        # themselves and declare a MEANINGFUL confidence — open_url 95.0 after
        # comparing the final URL, arrange_windows 65.0 when some placements
        # failed. Overwriting with 60.0 both RAISED the honest 65.0-partial
        # signal's neighbours and destroyed the partial-failure signal itself.
        # The ceiling still applies: no undeclared post-condition means we
        # cannot ratify a tool's own 100.0.
        res.confidence = min(res.confidence, _UNCONFIRMED_CONFIDENCE)
        # A tool that recorded its own reasoning is not silent, so appending
        # "it said nothing" contradicts the line above it. Say what is actually
        # true instead: nobody checked independently.
        if res.confidence_reason:
            res.confidence_reason = list(res.confidence_reason) + [
                "unconfirmed: nothing checked this independently"
            ]
        else:
            res.confidence_reason = ["unconfirmed: no post-condition declared"]
        return res

    try:
        loop = asyncio.get_running_loop()
        disagreement = await asyncio.wait_for(
            loop.run_in_executor(_VERIFY_EXECUTOR, lambda: tool_obj.verify(args, res)),
            timeout=_VERIFY_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        res.confidence = _UNCONFIRMED_CONFIDENCE
        res.confidence_reason = list(res.confidence_reason) + [
            f"unconfirmed: post-condition timed out after {_VERIFY_TIMEOUT_S}s"
        ]
        return res
    except Exception as e:
        res.confidence = _UNCONFIRMED_CONFIDENCE
        res.confidence_reason = list(res.confidence_reason) + [
            f"unconfirmed: post-condition could not run: {e}"
        ]
        return res

    if disagreement:
        log.warning("Tool %r claimed success but the world disagrees: %s", name, disagreement)
        return ToolResult(
            status=ToolStatus.ERROR,
            reason=str(disagreement),
            data=res.data,
            confidence=0.0,
            confidence_reason=[f"contradicted: {disagreement}"],
        )

    res.confidence_reason = list(res.confidence_reason) + ["confirmed: read back and agrees"]
    return res


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskEvent:
    task_id: str
    status: TaskStatus
    message: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)


class Task:
    def __init__(self, task_id: str, name: str, coro: Coroutine):
        self.id = task_id
        self.name = name
        self.coro = coro
        self.status = TaskStatus.PENDING
        self.result: Optional[ToolResult] = None
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None
        self._async_task: Optional[asyncio.Task] = None

    def cancel(self):
        if self._async_task and not self._async_task.done():
            self._async_task.cancel()
            self.status = TaskStatus.CANCELLED
            get_bus().publish(TaskEvent(self.id, self.status, message="Task cancelled by user"))


class Runtime:
    """Async execution runtime for SG_CUBE tools."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}

    async def run_tool(self, name: str, func: Callable, args: dict, timeout: float = 30.0, request_id: Optional[str] = None) -> ToolResult:
        """Run a tool asynchronously with timeout and logging."""
        task_id = str(uuid.uuid4())[:8]
        rid = request_id or task_id
        
        # Wrap sync functions in a thread pool to avoid blocking
        if not asyncio.iscoroutinefunction(func):
            loop = asyncio.get_running_loop()
            coro = loop.run_in_executor(None, lambda: func(**args))
        else:
            coro = func(**args)

        task = Task(task_id, name, coro)
        self._tasks[task_id] = task
        
        task.status = TaskStatus.RUNNING
        task.start_time = time.perf_counter()
        get_bus().publish(TaskEvent(task_id, task.status, message=f"Starting tool {name}"))
        get_bus().publish(ToolStartedEvent(tool_name=name, args=args))

        try:
            # Execute with timeout
            res = await asyncio.wait_for(coro, timeout=timeout)
            
            if isinstance(res, dict):
                # Coerce legacy dicts
                res = ToolResult(
                    status=ToolStatus(res.get("status", "success")),
                    message=res.get("message"),
                    reason=res.get("reason"),
                    data=res.get("args") or res.get("data") or {},
                    confidence=res.get("confidence", 100.0),
                    confidence_reason=res.get("confidence_reason") or [],
                )

            # Between coercion and recording: every tool result, whichever
            # shape it arrived in, gets checked against the world here.
            res = await _apply_post_condition(name, args, res)

            task.result = res
            task.status = TaskStatus.COMPLETED if res.status == ToolStatus.SUCCESS else TaskStatus.FAILED

        except asyncio.TimeoutError:
            log.error(f"Task {name} ({task_id}) timed out after {timeout}s")
            task.status = TaskStatus.FAILED
            task.result = ToolResult.error(f"Execution timed out after {timeout}s", confidence=0.0, confidence_reason=["Timeout reached"])

        except asyncio.CancelledError:
            log.info(f"Task {name} ({task_id}) was cancelled")
            task.status = TaskStatus.CANCELLED
            task.result = ToolResult.blocked("Task was cancelled", confidence=0.0, confidence_reason=["User cancelled"])
            
        except Exception as e:
            log.exception(f"Task {name} ({task_id}) failed with error")
            task.status = TaskStatus.FAILED
            task.result = ToolResult.error(str(e), confidence=0.0, confidence_reason=["Internal crash"])
            
        finally:
            # A BaseException (KeyboardInterrupt, GeneratorExit) escapes the
            # excepts above with task.result still None. The publishes below
            # dereference it, so the AttributeError raised *inside* finally
            # would replace the original exception — the crash report becomes
            # "NoneType has no attribute 'message'" and the real cause is gone.
            if task.result is None:
                task.status = TaskStatus.FAILED
                task.result = ToolResult.error(
                    f"Tool {name} exited without a result",
                    confidence=0.0,
                    confidence_reason=["No result recorded"],
                )

            task.end_time = time.perf_counter()
            latency = int((task.end_time - task.start_time) * 1000)

            # ── Observability: the ONLY report_tool_quality site ─────────
            # Every tool execution funnels through run_tool, so reporting here
            # covers success, non-success results, timeouts and crashes with one
            # call — the previous split (success branch + timeout branch, plus a
            # second report in Operator) counted some calls twice and others not
            # at all. Reported under `rid` so the UI sees the request it started,
            # not the internal task_id. Cancellations are a user action, not a
            # tool failure, so they stay out of the success rate.
            # Wrapped: this runs in `finally`, where a raising subscriber would
            # replace the tool's real exception.
            if task.status != TaskStatus.CANCELLED:
                try:
                    from backend.core.observability import engine as obs_engine
                    obs_engine.report_tool_quality(
                        rid,
                        task.result.confidence,
                        f"Status: {task.result.status.value}",
                        success=task.result.status == ToolStatus.SUCCESS,
                    )
                except Exception:
                    log.debug("observability report failed for %s", name, exc_info=True)
            # ─────────────────────────────────────────────────────────────

            get_bus().publish(ToolFinishedEvent(
                tool_name=name,
                status=task.result.status.value,
                result=task.result.message,
                error=task.result.reason if task.result.status != ToolStatus.SUCCESS else None,
                latency_ms=latency,
            ))
            
            get_bus().publish(TaskEvent(
                task_id, 
                task.status, 
                message=task.result.message or task.result.reason,
                data={
                    "latency_ms": latency, 
                    "tool": name,
                    "confidence": task.result.confidence,
                    "confidence_reason": task.result.confidence_reason
                }
            ))
            
            # Phase G2: Track tool usage for diagnostics heatmap
            try:
                from backend.server.routes.diagnostics import record_tool_usage
                success = task.result.status == ToolStatus.SUCCESS
                record_tool_usage(name, success, latency)
            except Exception:
                pass

            # `runtime` is a module-level singleton and each Task pins a whole
            # ToolResult payload, so leaving finished tasks here leaks for the
            # life of the process. Dropped rather than kept as bounded history:
            # cancel_task is the only reader and cancelling a finished task is
            # a no-op, so nothing consumes the history.
            self._tasks.pop(task_id, None)

        return task.result

    def cancel_task(self, task_id: str):
        if task_id in self._tasks:
            self._tasks[task_id].cancel()


# Global instance
runtime = Runtime()
