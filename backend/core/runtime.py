import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from backend.core.events import bus
from backend.core.tools.registry import ToolResult, ToolStatus

log = logging.getLogger(__name__)


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
            bus.publish(TaskEvent(self.id, self.status, message="Task cancelled by user"))


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
        bus.publish(TaskEvent(task_id, task.status, message=f"Starting tool {name}"))

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
                )
            
            task.result = res
            task.status = TaskStatus.COMPLETED if res.status == ToolStatus.SUCCESS else TaskStatus.FAILED
            
            # ── Observability Integration ────────────────────────────
            from backend.core.observability import engine as obs_engine
            quality = 100.0 if res.status == ToolStatus.SUCCESS else 0.0
            obs_engine.report_tool_quality(rid, quality, f"Status: {res.status}")
            # ─────────────────────────────────────────────────────────
            
        except asyncio.TimeoutError:
            log.error(f"Task {name} ({task_id}) timed out after {timeout}s")
            task.status = TaskStatus.FAILED
            task.result = ToolResult.error(f"Execution timed out after {timeout}s")
            from backend.core.observability import engine as obs_engine
            obs_engine.report_tool_quality(task_id, 0.0, "Timeout")
            
        except asyncio.CancelledError:
            log.info(f"Task {name} ({task_id}) was cancelled")
            task.status = TaskStatus.CANCELLED
            task.result = ToolResult.blocked("Task was cancelled")
            
        except Exception as e:
            log.exception(f"Task {name} ({task_id}) failed with error")
            task.status = TaskStatus.FAILED
            task.result = ToolResult.error(str(e))
            
        finally:
            task.end_time = time.perf_counter()
            latency = int((task.end_time - task.start_time) * 1000)
            
            bus.publish(TaskEvent(
                task_id, 
                task.status, 
                message=task.result.message or task.result.reason,
                data={"latency_ms": latency, "tool": name}
            ))
            
            # Clean up (optionally keep for history)
            # del self._tasks[task_id]
            
        return task.result

    def cancel_task(self, task_id: str):
        if task_id in self._tasks:
            self._tasks[task_id].cancel()


# Global instance
runtime = Runtime()
