"""Automation and background monitoring tools (Phase 14).

A watcher used to store free text (`action_query`) and hand it to the planner
when it fired — hours later, with nobody present, under a trigger source the
verifier read as an explicit wake. So whatever the planner made of the text
ran with no check at all.

Now the action is resolved into a FIXED tool call at setup, while the user is
there: the tool must exist, its arguments must match its schema, and it must
be allowed to run unattended (tool_policy.background_refusal — read-only or
allowlisted, never destructive). The reply states exactly what will run; that
spoken echo is the confirmation. At fire time the same call runs verbatim,
re-checked, and is never re-planned.
"""
import json

from backend.core.agent import tool_policy
from backend.core.agents.watcher import watcher
from backend.core.tools.registry import CapabilityTier, ToolResult, _resolve_name, tool


def _resolve_action(announce: str, action_tool: str, action_args: dict | None):
    """-> (action dict, human description) or (None, reason it was refused)."""
    announce = (announce or "").strip()
    action_tool = (action_tool or "").strip()
    args = dict(action_args or {})
    if not announce and not action_tool:
        return None, "give something to announce, a tool to run, or both"

    name = ""
    if action_tool:
        name = _resolve_name(action_tool, args) or ""
        if not name:
            return None, f"{action_tool!r} is not a known tool"
        problem = tool_policy.schema_problem(name, args)
        if problem:
            return None, problem
        refusal = tool_policy.background_refusal(name, args)
        if refusal:
            return None, f"that cannot run unattended: {refusal}"

    parts = []
    if announce:
        parts.append(f"say {announce!r}")
    if name:
        parts.append(f"run {name}({json.dumps(args, ensure_ascii=False)})")
    return ({"announce": announce, "tool": name, "args": args,
             "fingerprint": tool_policy.policy_fingerprint(name) if name else ""},
            " and ".join(parts))


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: starts a watcher whose action is itself gated at setup and at fire time
def monitor_battery(threshold_pct: int, announce: str = "", action_tool: str = "",
                    action_args: dict | None = None) -> ToolResult:
    """Watch the battery. When it drops below `threshold_pct`, say `announce`
    and/or run ONE fixed tool call (`action_tool` with `action_args`), decided
    now and never re-planned. The tool must be read-only or on the background
    allowlist; destructive tools are refused.
    Example: threshold_pct=20, announce="Battery is low", action_tool="set_brightness", action_args={"level": 30}.
    """
    action, desc = _resolve_action(announce, action_tool, action_args)
    if action is None:
        return ToolResult.blocked(f"Battery monitor not set: {desc}")
    watcher.add_battery_task(threshold_pct, action)
    return ToolResult.success(f"Monitoring the battery. Below {threshold_pct}% I will {desc}.")


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)  # trusted: starts a watcher whose action is itself gated at setup and at fire time
def monitor_folder(folder_path: str, file_pattern: str, announce: str = "",
                   action_tool: str = "", action_args: dict | None = None) -> ToolResult:
    """Watch a folder for new files matching `file_pattern`. When one appears,
    say `announce` and/or run ONE fixed tool call (`action_tool` with
    `action_args`), decided now and never re-planned. The tool must be
    read-only or on the background allowlist; destructive tools are refused.
    Example: folder_path='~/Downloads', file_pattern='*.pdf', announce='A new PDF arrived'.
    """
    action, desc = _resolve_action(announce, action_tool, action_args)
    if action is None:
        return ToolResult.blocked(f"Folder monitor not set: {desc}")
    if not watcher.add_folder_task(folder_path, file_pattern, action):
        return ToolResult.error(f"Could not access folder {folder_path}. Make sure the path is correct.",
                                confidence=0.0)
    return ToolResult.success(f"Monitoring {folder_path} for {file_pattern}. On a new file I will {desc}.")
