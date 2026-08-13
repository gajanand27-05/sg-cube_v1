"""Phone camera control — drive the camera by voice instead of by QR scan.

The capture page holds a control socket open whenever it is open at all (see
core/vision/phone_session.py), so these tools can start and stop the camera on
a phone nobody is touching.

Honest limit, and the reason `connect_phone_camera` reports a URL on failure:
the browser cannot be reached before it has loaded the page once, and it will
not hand over the camera without a tap until the user has granted permission
to this origin. So the FIRST pairing still needs the page opened once by hand;
every use after that is voice-only.
"""
import asyncio
import logging

from backend.core.tools.registry import CapabilityTier, ToolResult, tool
from backend.core.vision.phone_session import VALID_MODES, registry

log = logging.getLogger(__name__)


def _hint() -> str:
    """Where to open the page, for the first-run case."""
    try:
        from backend.server.routes.phone_stream import _phone_url
        url = _phone_url()
    except Exception:  # never let a hint failure mask the real result
        url = None
    return f" Open {url} on the phone once to pair it." if url else ""


# tier: turns on a camera — a real-world side effect, but reversible and
# trusted because the spoken request IS the confirmation. Prompting again
# would make the hands-free path useless, which is the point of the feature.
@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)
async def connect_phone_camera(mode: str = "navigate") -> ToolResult:
    """Start the phone camera and begin streaming to the assistant's vision.

    Use for "connect phone camera", "turn on the phone camera", "start vision",
    "what do you see" when the phone camera is not already running.
    `mode` is "navigate" (continuous obstacle alerts), "scan" (look without
    speaking) or "read".
    """
    if mode not in VALID_MODES:
        return ToolResult.error(
            f"unknown vision mode {mode!r} — use one of: {', '.join(sorted(VALID_MODES))}"
        )

    ok, err = await registry.command("start", mode=mode)
    if ok:
        return ToolResult.success(
            message=f"phone camera is streaming in {mode} mode",
            data={"streaming": True, "mode": mode, "phones": ok},
        )
    return ToolResult.error(f"could not start the phone camera: {err or 'unknown error'}.{_hint()}")


# tier: reads the frame the phone is already sending — no side effects.
@tool(tier=CapabilityTier.READONLY)
async def describe_scene() -> ToolResult:
    """Say what the phone camera can currently see — objects, people, obstacles.

    Use for "what do you see", "what's in front of me", "describe the scene",
    "what's around me". Needs the phone camera to be streaming already.
    """
    from backend.core.vision.frame_ingest import frame_ingestor
    from backend.core.vision.obstacle_detector import describe, detect

    frame, meta = frame_ingestor.latest_frame()
    if frame is None:
        hint = _hint() if registry.count == 0 else " Say 'connect phone camera' first."
        return ToolResult.error(f"no camera frame available.{hint}")

    loop = asyncio.get_running_loop()
    # detect() is 40-150ms of blocking CPU — never inline on the caller's loop.
    seen = await loop.run_in_executor(None, detect, frame, True)
    if not seen:
        return ToolResult.success(message="nothing recognizable in view",
                                  data={"objects": [], "frame_id": meta.frame_id})

    return ToolResult.success(
        message=describe(seen),
        data={
            "objects": [{"label": o.label, "direction": o.direction,
                         "distance_m": o.distance_m, "confidence": o.confidence}
                        for o in seen],
            "frame_id": meta.frame_id,
        },
    )


# tier: reads text from the phone frame — no side effects.
@tool(tier=CapabilityTier.READONLY)
async def ocr_read() -> ToolResult:
    """Read text visible through the phone camera. Recognizes signs, labels,
    documents. Use for "read this sign", "what does it say", "read the text",
    "OCR this". Needs the phone camera to be streaming already."""
    from backend.core.vision.frame_ingest import frame_ingestor
    from backend.core.vision.ocr_reader import OCRUnavailable, ocr_frame, ocr_text

    frame, meta = frame_ingestor.latest_frame()
    if frame is None:
        hint = _hint() if registry.count == 0 else " Say 'connect phone camera' first."
        return ToolResult.error(f"no camera frame available.{hint}")

    loop = asyncio.get_running_loop()
    try:
        lines = await loop.run_in_executor(None, ocr_frame, frame)
    except OCRUnavailable as e:
        # An error, never "no readable text": the user is asking because they
        # cannot see the sign, and "no text here" would send them away from a
        # sign that is right in front of them.
        return ToolResult.error(f"text reading is unavailable. {e}")
    if not lines:
        return ToolResult.success(message="no readable text in view",
                                   data={"lines": [], "frame_id": meta.frame_id})

    texts = [line.text for line in lines]
    return ToolResult.success(
        message=ocr_text(lines),
        data={
            "lines": [{"text": l.text, "confidence": l.confidence} for l in lines],
            "frame_id": meta.frame_id,
        },
    )


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)
async def set_vision_mode(mode: str) -> ToolResult:
    """Switch what the phone camera is doing.

    "navigate" speaks obstacles continuously as you walk, "scan" describes the
    scene once, "read" is text/sign reading, "idle" stops analysis.
    Use for "switch to scan mode", "start navigating", "stop analysing".
    """
    if mode not in VALID_MODES:
        return ToolResult.error(
            f"unknown vision mode {mode!r} — use one of: {', '.join(sorted(VALID_MODES))}"
        )
    if registry.count == 0:
        return ToolResult.error(f"no phone camera connected.{_hint()}")
    await registry.push({"type": "command", "action": "mode", "mode": mode})
    return ToolResult.success(message=f"vision mode is now {mode}",
                              data={"mode": mode})


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)
async def set_silent_vision(silent: bool = True) -> ToolResult:
    """Stop (or resume) spoken obstacle alerts while keeping the phone's
    vibration warnings. Use for "silent mode", "stop talking but keep warning
    me", "quiet mode", "you can talk again".

    Vibration deliberately continues in silent mode — removing the alert
    entirely would leave the user unwarned in exactly the crowded public place
    where silence was requested.
    """
    registry.silent = bool(silent)
    return ToolResult.success(
        message=("silent mode on — alerts are vibration only"
                 if registry.silent else "speaking alerts again"),
        data={"silent": registry.silent},
    )


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True)
async def disconnect_phone_camera() -> ToolResult:
    """Stop the phone camera stream. Use for "disconnect phone camera",
    "turn the camera off", "stop vision"."""
    if registry.count == 0:
        return ToolResult.success(message="no phone camera was connected")
    ok, err = await registry.command("stop")
    if ok:
        return ToolResult.success(message="phone camera stopped", data={"streaming": False})
    return ToolResult.error(f"could not stop the phone camera: {err or 'unknown error'}")
