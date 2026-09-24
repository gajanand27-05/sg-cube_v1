"""Picks and owns the Whisper model: which one, on what device, for how long.

Three jobs, all of which used to be one hardcoded line
(`WhisperModel(settings.whisper_model, device="cpu", compute_type="int8")`):

1. Use the GPU when there is one. faster-whisper runs on CTranslate2, not
   torch, so `torch.cuda.is_available()` being False says nothing about it —
   CTranslate2 saw the card all along. What was missing was cuBLAS/cuDNN,
   which pip ships as the nvidia-* wheels; see _register_cuda_libs for why
   PATH and not os.add_dll_directory.

2. Trade accuracy for battery on the power source. On AC, run the big model on
   the GPU. On battery, drop to a smaller CPU model — a laptop unplugged at a
   demo should not be spending its charge on float16 attention.

3. Release the model when the conversation is over. Whisper does not need to
   be resident between utterances, but unloading after every single one would
   pay the 2-3s load cost on the very next command, so this unloads on an idle
   timer instead.

Everything is settings-driven, so a bad autodetect can always be overridden
from .env without a code change.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from backend.server.config import settings

log = logging.getLogger(__name__)

_cuda_registered = False
_cuda_lock = threading.Lock()


def _register_cuda_libs() -> None:
    """Put the pip-installed CUDA DLLs where Windows will find them.

    os.add_dll_directory() is NOT enough and was tried first: it governs DLLs
    Python itself loads, but cublas64_12.dll is loaded BY ctranslate2's own
    native library, which goes through the standard Windows search order.
    That order includes PATH, so PATH is what has to change. Symptom when this
    is wrong: the model constructs fine and the first transcribe() raises
    "Library cublas64_12.dll is not found or cannot be loaded".
    """
    global _cuda_registered
    if _cuda_registered or sys.platform != "win32":
        return
    with _cuda_lock:
        if _cuda_registered:
            return
        bins = sorted((Path(sys.prefix) / "Lib" / "site-packages" / "nvidia").glob("*/bin"))
        if bins:
            os.environ["PATH"] = (
                os.pathsep.join(str(p) for p in bins) + os.pathsep + os.environ["PATH"]
            )
            log.debug("registered %d CUDA lib dir(s) on PATH", len(bins))
        _cuda_registered = True


# CTranslate2 resolves these through PATH at the first GPU op, NOT at model
# load. Without them a Whisper model loads onto the GPU fine and then dies on
# its first decode — measured on a fresh `uv sync` without the gpu extra:
# "Library cublas64_12.dll is not found or cannot be loaded". That is the
# offline STT fallback, i.e. it fails exactly when the network is down.
_CUDA_DLLS = ("cublas64_12.dll", "cudnn64_9.dll")


def _cuda_libs_present() -> bool:
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    return all(any((Path(d) / dll).is_file() for d in dirs) for dll in _CUDA_DLLS)


def cuda_available() -> bool:
    """True when CTranslate2 can actually run on the GPU here.

    Needs the device AND the cuBLAS/cuDNN DLLs, which ship as the optional
    `gpu` extra (`uv sync --extra gpu`, ~2 GB) — an 8 GB laptop with no NVIDIA
    card should not download them. Without them this answers False and the
    profile falls back to the CPU, which works.

    Deliberately not torch.cuda.is_available(): torch is not a dependency, and
    when it was, the venv's CPU-only build reported False while CTranslate2
    reported a working device.
    """
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            return False
        _register_cuda_libs()
        if not _cuda_libs_present():
            log.debug("cuda_available: GPU present but cuBLAS/cuDNN DLLs are not "
                      "(install the 'gpu' extra); using the CPU")
            return False
        return "float16" in ctranslate2.get_supported_compute_types("cuda")
    except Exception as e:
        log.debug("cuda_available: %s", e)
        return False


def on_battery() -> bool:
    """True when running unplugged. False if it cannot be determined — the
    conservative answer is 'plugged in', because wrongly assuming battery
    would silently downgrade accuracy on a desktop."""
    try:
        import psutil

        power = psutil.sensors_battery()
        return bool(power is not None and not power.power_plugged)
    except Exception as e:
        log.debug("on_battery: %s", e)
        return False


@dataclass(frozen=True)
class SttProfile:
    """A concrete (model, device, compute type) choice, and why."""
    model: str
    device: str
    compute_type: str
    reason: str

    def key(self) -> tuple[str, str, str]:
        return (self.model, self.device, self.compute_type)

    def __str__(self) -> str:
        return f"{self.model}/{self.device}/{self.compute_type} ({self.reason})"


_forced_fallback_warned = False


def select_profile() -> SttProfile:
    """Choose the model for current conditions.

    STT_PROFILE=auto (default) picks; anything else forces a named profile so
    a demo can pin the good one regardless of what the battery is doing.
    """
    forced = (settings.stt_profile or "auto").strip().lower()

    if forced == "accurate":
        # A pin overrides the BATTERY heuristic, not the absence of a GPU.
        # Honouring it on a machine that cannot run it loaded Whisper onto
        # cuda and killed the first decode (cublas64_12.dll missing) — the
        # offline STT path, dying exactly when offline.
        if not cuda_available():
            global _forced_fallback_warned
            if not _forced_fallback_warned:  # runs per utterance; say it once
                _forced_fallback_warned = True
                log.warning("STT_PROFILE=accurate needs a usable GPU and there is none "
                            "(no NVIDIA card, or the 'gpu' extra is not installed); "
                            "using %s on the CPU", settings.whisper_model_cpu)
            return SttProfile(settings.whisper_model_cpu, "cpu", "int8",
                              "forced accurate, but no usable GPU")
        return SttProfile(settings.whisper_model_gpu, "cuda", "float16", "forced accurate")
    if forced == "fast":
        return SttProfile(settings.whisper_model_cpu, "cpu", "int8", "forced fast")
    if forced != "auto":
        log.warning("unknown STT_PROFILE %r; falling back to auto", forced)

    if not cuda_available():
        return SttProfile(settings.whisper_model_cpu, "cpu", "int8", "no usable GPU")
    if on_battery():
        # ponytail: a binary plugged/unplugged switch, not a battery-level or
        # thermal policy. Ceiling — it will drop to the small model at 99%
        # charge the moment the cable comes out. Upgrade path is to also read
        # percent and only downgrade below a threshold, which needs a real
        # measurement of what STT actually costs per utterance to be worth it.
        return SttProfile(settings.whisper_model_cpu, "cpu", "int8", "on battery")
    return SttProfile(settings.whisper_model_gpu, "cuda", "float16", "on AC power")


class _ModelCache:
    """Holds at most one loaded model, and drops it once it goes idle.

    Replaces an @lru_cache(maxsize=1) that held the model for the life of the
    process and could never switch device when the power source changed.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._model = None
        self._key: tuple[str, str, str] | None = None
        self._last_used = 0.0
        self._timer: threading.Timer | None = None

    def get(self, profile: SttProfile):
        from faster_whisper import WhisperModel

        with self._lock:
            if self._model is not None and self._key != profile.key():
                log.info("STT profile changed -> %s; reloading", profile)
                self._release_locked()

            if self._model is None:
                if profile.device == "cuda":
                    _register_cuda_libs()
                t0 = time.perf_counter()
                self._model = WhisperModel(
                    profile.model, device=profile.device,
                    compute_type=profile.compute_type,
                )
                self._key = profile.key()
                log.info("loaded Whisper %s in %.1fs", profile,
                         time.perf_counter() - t0)

            self._last_used = time.monotonic()
            self._arm_locked()
            return self._model

    def _arm_locked(self) -> None:
        idle = settings.stt_idle_unload_s
        if idle <= 0:
            return
        if self._timer is not None:
            self._timer.cancel()
        # +1s so the timer never fires a hair before the deadline and
        # reschedules itself for a fraction of a second.
        self._timer = threading.Timer(idle + 1.0, self._on_idle)
        self._timer.daemon = True
        self._timer.start()

    def _on_idle(self) -> None:
        with self._lock:
            idle_for = time.monotonic() - self._last_used
            if self._model is None:
                return
            if idle_for < settings.stt_idle_unload_s:
                self._arm_locked()          # used again while we waited
                return
            log.info("Whisper idle %.0fs — releasing", idle_for)
            self._release_locked()

    def _release_locked(self) -> None:
        self._model = None
        self._key = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def release(self) -> None:
        """Drop the model now. Used by tests and at shutdown."""
        with self._lock:
            self._release_locked()

    @property
    def loaded_key(self) -> tuple[str, str, str] | None:
        with self._lock:
            return self._key


_cache = _ModelCache()


def get_model():
    """The model to transcribe with, loading it if needed."""
    return _cache.get(select_profile())


def release_model() -> None:
    _cache.release()


def loaded_key() -> tuple[str, str, str] | None:
    return _cache.loaded_key
