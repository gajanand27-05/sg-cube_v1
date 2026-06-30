"""ContextBuilder — single source of truth for agent context.

Collects STM, LTM, timeline, screen, running apps, tools, capabilities.
Passed to Planner, Guardian, Commander for consistent context.
"""
import logging
from typing import Any, Optional

from backend.core.context.types import AgentContext, RequestContext, WindowInfo, DetectedObject
from backend.core.memory.manager import memory as memory_manager
from backend.core.memory.timeline import timeline
from backend.core.memory.screen_memory import screen_memory
from backend.core.tools.registry import REGISTRY, Tool
from backend.core.caps.registry import capability_registry
from backend.ai_modules.llm import get_provider
from backend.ai_modules.llm.routing import TaskType

log = logging.getLogger(__name__)


class ContextBuilder:
    """Builds complete AgentContext for the intelligence pipeline."""
    
    def __init__(self):
        self.llm = get_provider()
    
    async def collect(self, request: RequestContext) -> AgentContext:
        """Single call to build full context for all downstream agents."""
        
        # Parallel collection for speed
        import asyncio
        
        # 1. STM (conversation history)
        stm_task = asyncio.to_thread(self._get_stm_context)
        
        # 2. LTM (semantic search)
        ltm_task = asyncio.to_thread(self._get_ltm_context, request.user_intent)
        
        # 3. Timeline (chronological)
        timeline_task = asyncio.to_thread(self._get_timeline_context)
        
        # 4. Screen memory (visual RAG)
        screen_task = asyncio.to_thread(self._get_screen_context, request.user_intent)
        
        # 5. Active window + running apps (sync, fast)
        active_window = self._get_active_window()
        running_apps = self._get_running_apps()
        
        # 6. Visual objects from latest vision
        screen_objects = self._get_screen_objects()
        
        # 7. Tools & capabilities
        tools = list(REGISTRY.values())
        capabilities = capability_registry.get_all()
        
        # Await all
        stm_context, ltm_context, timeline_context, screen_context = await asyncio.gather(
            stm_task, ltm_task, timeline_task, screen_task,
            return_exceptions=True
        )
        
        # Handle exceptions gracefully
        if isinstance(stm_context, Exception):
            log.warning(f"STM collection failed: {stm_context}")
            stm_context = []
        if isinstance(ltm_context, Exception):
            log.warning(f"LTM collection failed: {ltm_context}")
            ltm_context = []
        if isinstance(timeline_context, Exception):
            log.warning(f"Timeline collection failed: {timeline_context}")
            timeline_context = []
        if isinstance(screen_context, Exception):
            log.warning(f"Screen context failed: {screen_context}")
            screen_context = []
        
        return AgentContext(
            user_intent=request.user_intent,
            input_mode=request.input_mode,
            recent_conversation=stm_context,
            long_term_memory=ltm_context,
            active_window=active_window,
            screen_objects=screen_objects,
            running_apps=running_apps,
            recent_events=timeline_context,
            available_tools=tools,
            capabilities=capabilities,
            confidence=request.metadata.get("confidence", 0.0),
            user_id=request.user_id,
            session_id=request.session_id,
            request_id=request.request_id,
            metadata=request.metadata,
        )
    
    def _get_stm_context(self) -> list[dict]:
        """Get recent conversation from STM."""
        try:
            return memory_manager.stm.render()
        except Exception as e:
            log.debug(f"STM render failed: {e}")
            return []
    
    def _get_ltm_context(self, query: str) -> list:
        """Semantic search in LTM for relevant facts."""
        try:
            return memory_manager.ltm.search(query, limit=5)
        except Exception as e:
            log.debug(f"LTM search failed: {e}")
            return []
    
    def _get_timeline_context(self) -> list:
        """Get recent chronological events."""
        try:
            return timeline.get_recent_timeline(limit=10)
        except Exception as e:
            log.debug(f"Timeline fetch failed: {e}")
            return []
    
    def _get_screen_context(self, query: str) -> list:
        """Semantic search in visual memory."""
        try:
            return screen_memory.search_visual(query, limit=3)
        except Exception as e:
            log.debug(f"Screen search failed: {e}")
            return []
    
    def _get_active_window(self) -> WindowInfo | None:
        """Get currently focused window."""
        try:
            import pygetwindow as gw
            win = gw.getActiveWindow()
            if win:
                return WindowInfo(
                    title=win.title,
                    app=win._hWnd,  # app name would need psutil
                    hwnd=win._hWnd,
                    bounds=(win.left, win.top, win.right, win.bottom) if all([
                        win.left, win.top, win.right, win.bottom
                    ]) else None,
                )
        except Exception:
            pass
        return None
    
    def _get_running_apps(self) -> list[str]:
        """Get list of running application names."""
        try:
            import psutil
            apps = set()
            for proc in psutil.process_iter(['name']):
                name = proc.info.get('name')
                if name and name.endswith('.exe'):
                    apps.add(name[:-4])  # strip .exe
            return sorted(apps)[:50]  # cap
        except Exception:
            return []
    
    def _get_screen_objects(self) -> list[DetectedObject]:
        """Get latest detected objects from vision loop."""
        try:
            latest = screen_memory.get_latest_observation()
            if latest:
                keywords = latest.get("keywords", "")
                if keywords:
                    return [
                        DetectedObject(label=k.strip(), confidence=0.8)
                        for k in keywords.split(",") if k.strip()
                    ]
        except Exception:
            pass
        return []


# Global instance
context_builder = ContextBuilder()