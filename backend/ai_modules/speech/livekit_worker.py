"""Phase C3: LiveKit Agent worker — optional voice pipeline.

When VOICE_PIPELINE=livekit, this replaces the local VAD→STT→TTS chain
with LiveKit's built-in streaming STT, VAD, turn detection, endpointing,
and TTS — all managed by the LiveKit server.

Start with:
    python -m backend.ai_modules.speech.livekit_worker
"""
import logging
from typing import Optional

from backend.server.config import settings

log = logging.getLogger(__name__)

# Lazy imports — only import livekit when this module is used
_agent = None
_voice_pipeline = None


def is_available() -> bool:
    return settings.voice_pipeline == "livekit" and bool(settings.livekit_url)


async def start_worker() -> None:
    """Start the LiveKit agent worker."""
    if not is_available():
        log.info("LiveKit pipeline not configured — using local pipeline.")
        return

    try:
        from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli
        from livekit.agents.voice import Agent, AgentSession, RunContext, function_tool
        from livekit.plugins import deepgram, openai, silero, turn_detector

        class SGCubeVoiceAgent(Agent):
            async def on_enter(self):
                self.session.say("SG Cube online. How can I help?")

            @function_tool
            async def process_command(self, context: RunContext, command: str):
                """Process a voice command through the SG_CUBE orchestrator."""
                from backend.core.orchestrator.router import process_input
                from backend.daemon.trigger import DAEMON_USER_ID

                routed = await process_input(command, DAEMON_USER_ID)
                reply = f"Executed {routed.intent.action}"
                self.session.say(reply)

        async def entrypoint(ctx: JobContext):
            ctx.connect()
            session = AgentSession(
                stt=deepgram.STT(),
                tts=openai.TTS(),
                vad=silero.VAD(),
                turn_detector=turn_detector.EOU(),
            )
            await session.start(agent=SGCubeVoiceAgent(), room=ctx.room)

        log.info("Starting LiveKit worker...")
        await cli.run_app(
            WorkerOptions(entrypoint_fnc=entrypoint),
            url=settings.livekit_url,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
        )
    except ImportError as e:
        log.error(
            "LiveKit dependencies not installed. "
            "Run: pip install livekit livekit-agents livekit-plugins-deepgram livekit-plugins-openai"
        )
        raise
    except Exception as e:
        log.error("LiveKit worker failed: %s", e)
        raise


if __name__ == "__main__":
    import asyncio
    asyncio.run(start_worker())
