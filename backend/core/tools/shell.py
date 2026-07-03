"""Generic shell command tool (Phase T2-1).

`run_command` is the broad-utility sibling of the rule-engine's
narrow whitelist handlers: it lets the planner invoke arbitrary
executable commands when no dedicated tool applies. Marked CAUTION
so the user must approve each invocation.
"""
import subprocess

from backend.core.tools.registry import SecurityLevel, ToolResult, tool


@tool(security=SecurityLevel.CAUTION)
def run_command(command: str, timeout_seconds: int = 30) -> ToolResult:
    """Run a shell command and return its stdout/stderr. CAUTION: arbitrary code
    execution; user must approve each call. `timeout_seconds` defaults to 30."""
    if not command or not command.strip():
        return ToolResult.blocked("empty command")
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return ToolResult.error(
            f"timed out after {timeout_seconds}s",
            confidence=0.0,
            confidence_reason=["Subprocess timeout"],
        )
    except Exception as e:
        return ToolResult.error(f"failed to launch: {e}")

    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    snippet_msg = f"exit={proc.returncode}"
    if out:
        snippet_msg += f"\nstdout:\n{out[:1500]}"
    if err:
        snippet_msg += f"\nstderr:\n{err[:500]}"
    if proc.returncode == 0:
        return ToolResult.success(snippet_msg)
    return ToolResult.error(snippet_msg)
