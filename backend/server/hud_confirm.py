"""Answering a confirmation prompt from the HUD.

The HUD and voice answer the same pending (agents/pending_confirmation.py):
whichever arrives first consumes it, once. An answer names the pending by id
AND by the digest of its exact tool calls, so it can only approve what the
dialog showed. Expiry is a refusal — nothing runs.
"""
from __future__ import annotations

import logging

from backend.core.agents.pending_confirmation import resolved, store
from backend.core.events import Priority, get_bus
from backend.daemon.ui_events import SpokenResponse

log = logging.getLogger(__name__)


async def _speak(text: str) -> None:
    """Say the outcome aloud, as a voice answer would. Separate so tests can
    record it instead of playing audio."""
    from backend.ai_modules.speech.tts_piper import speak_stream

    async for _ in speak_stream(text):
        pass


async def answer(pending_id: str, digest: str, decision: str) -> tuple[bool, str]:
    """-> (consumed, what to tell the user)."""
    pending, why = store.take_by_id(pending_id, digest)
    if pending is None:
        log.info("HUD confirmation answer not applied: %s", why)
        return False, why

    if decision != "yes":
        resolved(pending, "declined")
        spoken = f"Okay, I won't {pending.tool_name}."
    else:
        resolved(pending, "approved")
        log.info("Confirmation granted on the HUD for %r", pending.tool_name)
        from backend.core.agents.commander import commander

        _results, spoken = await commander.execute_confirmed(
            pending, request_id=f"hud-{pending.id[:8]}")

    get_bus().publish(SpokenResponse(text=spoken), priority=Priority.NORMAL)
    try:
        await _speak(spoken)
    except Exception as e:  # noqa: BLE001 — the action already ran; speech is a courtesy
        log.warning("could not speak the HUD confirmation outcome: %s", e)
    return True, spoken
