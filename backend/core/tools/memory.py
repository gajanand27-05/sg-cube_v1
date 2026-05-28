from backend.core.memory.manager import memory as memory_manager
from backend.core.tools.registry import tool


@tool
def remember(fact: str) -> dict:
    """Store a piece of information for long-term recall.
    Example: 'remember that my cat is named Luna'
    """
    memory_manager.remember_fact(fact)
    return {"status": "success", "message": f"I'll remember that: {fact}"}


@tool
def set_preference(preference: str) -> dict:
    """Store a user preference for future behavior.
    Example: 'always open chrome in incognito mode'
    """
    memory_manager.remember_preference(preference)
    return {"status": "success", "message": "Preference saved."}


@tool
def update_task_state(key: str, value: str) -> dict:
    """Store temporary state for the current complex task.
    Use this to 'save' progress during multi-step plans.
    """
    memory_manager.wm.set(key, value)
    return {"status": "success", "message": f"Saved {key} to working memory."}
