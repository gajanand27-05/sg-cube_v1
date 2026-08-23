"""Audio control tools (Phase 11b) — system master volume and mute via pycaw."""
import gc
import threading
from concurrent.futures import ThreadPoolExecutor
from ctypes import POINTER, cast

import comtypes
from comtypes import CLSCTX_ALL
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from backend.core.tools.registry import CapabilityTier, tool

# COM apartments are PER THREAD. `import comtypes` initialises COM on the
# importing thread only — which is the MAIN thread — while every one of these
# tools actually runs on a worker: runtime.run_tool dispatches sync tools to
# the default executor, and post-conditions run on _VERIFY_EXECUTOR, a
# different pool again. Measured live against the real endpoint before this
# guard existed, on both threads:
#
#   OSError: [WinError -2147221008] CoInitialize has not been called
#
# i.e. every audio tool failed outright off the main thread, and had the body
# somehow survived, its post-condition would still have raised on the verify
# thread and degraded silently to "unconfirmed" forever. Nothing in the test
# suite noticed, because tests call the verify callables directly from the
# main thread where COM is already up.
# Initialising COM per calling thread was the first fix and it was not enough.
# Those worker threads DIE — asyncio.run() tears down its default executor at
# the end of every turn — and an apartment dies with its thread. A live probe
# driving real turns then produced, without ever raising into the turn:
#
#   Win32 exception occurred releasing IUnknown at 0x...
#   ValueError: COM method call without VTable        <- a zeroed interface
#   Windows STATUS_ACCESS_VIOLATION (0xC0000005)      <- hard process crash
#
# So COM work is confined to ONE dedicated thread that is created once and
# never exits. Its apartment therefore outlives every pointer created in it,
# and no pointer is ever released from a foreign thread. Callers marshal work
# to it and get back plain ints and bools — an interface pointer must never
# escape this module, which is why _endpoint() is private and every public
# helper wraps it in _on_com_thread.
_COM_WORKER = ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio-com")
_com_ready = threading.local()


def _ensure_com() -> None:
    """Initialise COM on the calling thread, once. Only the COM worker calls this."""
    if getattr(_com_ready, "done", False):
        return
    try:
        comtypes.CoInitialize()
    except OSError as e:
        # RPC_E_CHANGED_MODE (-2147417850): this thread already has an
        # apartment of the other kind, which is still usable — don't retry on
        # every call. Anything else is a real failure and must not be
        # swallowed into a permanently misleading CO_E_NOTINITIALIZED later.
        if getattr(e, "winerror", None) != -2147417850:
            raise
    _com_ready.done = True


def _run_com_free(fn):
    """Run `fn`, letting nothing COM escape this thread — not even a traceback.

    Confining the pointer is not enough on its own. An exception raised while
    an interface pointer is a live local carries a traceback -> frame -> locals
    cycle that still references it. That cycle is collected later, by whichever
    thread the GC happens to run on, and releasing a COM pointer from a foreign
    apartment is an access violation. The Guardian-rejection path raises often,
    which is why this showed up under repeated real turns and not in any
    single-call test. So the exception is flattened to a plain RuntimeError
    here, while still on the owning thread; `from None` and the implicit `del`
    of the bound name drop the original and its traceback with it.
    """
    try:
        return fn()
    except BaseException as exc:
        detail = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(f"audio COM call failed: {detail}") from None
    finally:
        # Refcounting alone does not retire these pointers: comtypes objects
        # land in reference cycles, so they survive as garbage until some
        # later, arbitrary GC pass frees them — on whatever thread happened to
        # allocate at the wrong moment. Captured live via faulthandler, the
        # crashing thread was a context-builder worker in the middle of a
        # ChromaDB query, releasing an audio COM pointer:
        #
        #   Garbage-collecting
        #     comtypes ... Release / __del__
        #     chromadb ... _get
        #     context/builder.py _get_screen_objects
        #   -> STATUS_ACCESS_VIOLATION
        #
        # Collecting here retires those cycles on the thread that owns the
        # apartment. Audio calls are user-initiated and rare, so a full
        # collection per call is affordable; the alternative is a crash whose
        # stack points at ChromaDB and blames the wrong subsystem entirely.
        gc.collect()


def _on_com_thread(fn):
    """Run `fn` on the dedicated COM thread and return its (COM-free) result."""
    if threading.current_thread().name.startswith("audio-com"):
        # Already there. Re-submitting would deadlock: the pool has one worker.
        return _run_com_free(fn)
    return _COM_WORKER.submit(_run_com_free, fn).result()


def _endpoint():
    """PRIVATE. The returned pointer is only valid on the COM worker thread —
    never return it, store it, or let it cross a thread boundary."""
    _ensure_com()
    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


def _clamp(v: int) -> int:
    return max(0, min(100, int(v)))


# ── COM-thread-only bodies ────────────────────────────────────────────
# These touch an interface pointer, so they must only ever run inside
# _on_com_thread. They return plain values; nothing COM crosses back out.


def _shift_volume(delta: int) -> tuple[int, int]:
    """Read, clamp-shift and write the volume in one apartment visit."""
    ep = _endpoint()
    current = int(round(ep.GetMasterVolumeLevelScalar() * 100))
    new = _clamp(current + delta)
    ep.SetMasterVolumeLevelScalar(new / 100.0, None)
    return current, new


def _toggle_mute() -> bool:
    """Flip mute, returning whether it WAS muted before the flip."""
    ep = _endpoint()
    was_muted = bool(ep.GetMute())
    ep.SetMute(0 if was_muted else 1, None)
    return was_muted


def _read_volume() -> int:
    """Current master volume, 0-100, read fresh from the endpoint."""
    return _on_com_thread(
        lambda: int(round(_endpoint().GetMasterVolumeLevelScalar() * 100))
    )


def _read_muted() -> bool:
    return _on_com_thread(lambda: bool(_endpoint().GetMute()))


# ── Post-conditions ───────────────────────────────────────────────────
#
# Each returns None when the world agrees, or a short human reason when it
# does not. Relative tools (volume_up/down, mute) cannot be checked from args
# alone -- volume_up(10) is only meaningful against the pre-state the tool
# read -- so those tools record the end-state they expected in result.data and
# the check reads it back from there.


def _volume_matches(expected: int):
    got = _read_volume()
    return None if got == expected else f"volume is {got}%, expected {expected}%"


def _verify_set_volume(args, result):
    return _volume_matches(_clamp(args.get("level")))


def _verify_relative_volume(args, result):
    expected = (result.data or {}).get("expect_level")
    if expected is None:
        raise ValueError("tool recorded no expected level to check against")
    return _volume_matches(int(expected))


def _verify_mute(args, result):
    expected = (result.data or {}).get("expect_muted")
    if expected is None:
        raise ValueError("tool recorded no expected mute state to check against")
    got = _read_muted()
    if got == bool(expected):
        return None
    return f"mute is {'on' if got else 'off'}, expected {'on' if expected else 'off'}"


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_verify_set_volume)  # tier: audio state change, reversible; trusted: everyday volume tweak, no need to prompt
def set_volume(level: int) -> dict:
    """Set system master volume. `level` is 0-100."""
    level = _clamp(level)
    _on_com_thread(lambda: _endpoint().SetMasterVolumeLevelScalar(level / 100.0, None))
    return {"status": "success", "message": f"volume set to {level}%",
            "data": {"expect_level": level}}


@tool(tier=CapabilityTier.READONLY)  # tier: reads current volume, no side effects
def get_volume() -> dict:
    """Return current system master volume (0-100)."""
    percent = _read_volume()
    return {"status": "success", "message": f"volume is {percent}%", "args": {"level": percent}}


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_verify_relative_volume)  # trusted: same capability as set_volume, which was already trusted; reversible
def volume_up(amount: int = 10) -> dict:
    """Raise system volume by `amount` percentage points (default 10)."""
    # Read-modify-write in ONE hop: two marshals would let the volume change
    # between them, and would also mean holding a pointer across the gap.
    current, new = _on_com_thread(lambda: _shift_volume(amount))
    return {"status": "success", "message": f"volume raised from {current}% to {new}%",
            "data": {"expect_level": new}}


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_verify_relative_volume)  # trusted: same capability as set_volume, which was already trusted; reversible
def volume_down(amount: int = 10) -> dict:
    """Lower system volume by `amount` percentage points (default 10)."""
    current, new = _on_com_thread(lambda: _shift_volume(-amount))
    return {"status": "success", "message": f"volume lowered from {current}% to {new}%",
            "data": {"expect_level": new}}


@tool(tier=CapabilityTier.SYSTEM_WRITE, trusted=True, verify=_verify_mute)  # trusted: toggles mute, reversible by saying it again
def mute() -> dict:
    """Toggle system mute on/off."""
    was_muted = _on_com_thread(_toggle_mute)
    return {"status": "success", "message": "unmuted" if was_muted else "muted",
            "data": {"expect_muted": not was_muted}}
