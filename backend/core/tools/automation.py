"""Automation and background monitoring tools (Phase 14)."""

from backend.core.tools.registry import SecurityLevel, ToolResult, tool
from backend.core.agents.watcher import watcher

@tool(security=SecurityLevel.SAFE)
def monitor_battery(threshold_pct: int, action_query: str) -> ToolResult:
    """Monitor the system battery in the background. When it drops below
    `threshold_pct`, the system will autonomously execute `action_query`.
    Example: threshold_pct=20, action_query="Tell me the battery is low".
    """
    watcher.add_battery_task(threshold_pct, action_query)
    return ToolResult.success(f"Monitoring battery. Will execute '{action_query}' when below {threshold_pct}%.")

@tool(security=SecurityLevel.SAFE)
def monitor_folder(folder_path: str, file_pattern: str, action_query: str) -> ToolResult:
    """Monitor a folder for new files matching a pattern. When a new file appears,
    the system will autonomously execute `action_query`.
    Example: folder_path='~/Downloads', file_pattern='*.pdf', action_query='Notify me'.
    """
    success = watcher.add_folder_task(folder_path, file_pattern, action_query)
    if success:
        return ToolResult.success(f"Monitoring {folder_path} for {file_pattern}.")
    return ToolResult.error(f"Could not access folder {folder_path}. Make sure the path is correct.", confidence=0.0)
