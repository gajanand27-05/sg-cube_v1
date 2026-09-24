"""What this machine can actually run, and the defaults that follow from it.

The shipped defaults were tuned on the dev box — a 6 GB NVIDIA card with
Ollama resident. The laptop floor is 8 GB RAM, no GPU, no Ollama. This probes
once at boot and fills in settings the user left UNSET; anything set in .env
or the environment wins (pydantic records those in model_fields_set), and an
explicit setting the machine cannot honour is reported, not overridden.

Rules here follow from what the machine HAS, never from tuned thresholds: a
RAM cutoff for model size would be a guess until measured on real hardware.
STT device choice is not here — stt_manager.select_profile() already asks
cuda_available() per utterance, including the forced-profile fallback.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Hardware:
    ram_gb: float
    nvidia_gpu: bool      # a device exists, whether or not its libraries do
    cuda_usable: bool     # device + cuBLAS/cuDNN + float16 (the `gpu` extra)
    on_battery: bool
    ollama_up: bool
    ollama_models: tuple[str, ...]

    def has_ollama_model(self, name: str) -> bool:
        """Ollama lists 'phi3:latest' for a model pulled as 'phi3'."""
        wanted = {name, f"{name}:latest"} if ":" not in name else {name}
        return self.ollama_up and any(m in wanted for m in self.ollama_models)

    def summary(self) -> dict:
        return {**asdict(self), "ollama_models": list(self.ollama_models)}


@dataclass(frozen=True)
class Adjustment:
    field: str
    value: object
    reason: str


def probe(ollama_url: str, timeout: float = 2.0, connect_timeout: float = 0.3) -> Hardware:
    """Every part fails soft: a missing capability is the floor, not an error."""
    ram_gb = 0.0
    try:
        import psutil

        ram_gb = round(psutil.virtual_memory().total / 2**30, 1)
    except Exception as e:
        log.debug("probe: RAM unreadable: %s", e)

    nvidia_gpu = False
    try:
        import ctranslate2

        nvidia_gpu = ctranslate2.get_cuda_device_count() > 0
    except Exception as e:
        log.debug("probe: ctranslate2 device count failed: %s", e)

    from backend.ai_modules.speech.stt_manager import cuda_available, on_battery

    ollama_up, models = False, ()
    try:
        import httpx

        # Short CONNECT, normal READ. No Ollama is the laptop floor, and a
        # refused loopback connect costs ~1.1s on Windows (measured, 3 runs)
        # against a 1s flat timeout — paid on every boot. A busy Ollama
        # connects fast and answers slowly, so the read budget stays generous:
        # misreading it as down would switch vision off for the session.
        r = httpx.get(f"{ollama_url.rstrip('/')}/api/tags",
                      timeout=httpx.Timeout(timeout, connect=connect_timeout))
        r.raise_for_status()
        ollama_up = True
        models = tuple(sorted(m["name"] for m in r.json().get("models", [])))
    except Exception as e:
        log.debug("probe: Ollama not reachable at %s: %s", ollama_url, e)

    return Hardware(ram_gb=ram_gb, nvidia_gpu=nvidia_gpu,
                    cuda_usable=nvidia_gpu and cuda_available(),
                    on_battery=on_battery(), ollama_up=ollama_up,
                    ollama_models=models)


def _recommend(settings, hw: Hardware) -> list[Adjustment]:
    out: list[Adjustment] = []
    if settings.enable_vision and not hw.has_ollama_model(settings.vision_model):
        where = "Ollama is not running" if not hw.ollama_up else "it is not pulled"
        out.append(Adjustment(
            "enable_vision", False,
            f"passive vision needs {settings.vision_model} in local Ollama and {where}; "
            "every glance would fail (describe_screen/ocr_screen still work on demand)"))
    return out


def apply(settings, hw: Hardware) -> list[Adjustment]:
    """Set each recommendation the user did not set explicitly. Returns what
    was applied."""
    applied = []
    for adj in _recommend(settings, hw):
        if adj.field in settings.model_fields_set:
            continue
        setattr(settings, adj.field, adj.value)
        applied.append(adj)
    return applied


def conflicts(settings, hw: Hardware) -> list[Adjustment]:
    """Recommendations the user has explicitly overridden — kept as set, but
    worth a warning at boot."""
    return [a for a in _recommend(settings, hw) if a.field in settings.model_fields_set]


# Set at boot by the server lifespan; read by /diagnostics/hardware.
last: dict | None = None


def probe_and_apply(settings) -> dict:
    global last
    hw = probe(settings.ollama_url)
    applied = apply(settings, hw)
    kept = conflicts(settings, hw)
    for a in applied:
        log.info("hardware: %s=%r — %s", a.field, a.value, a.reason)
    for a in kept:
        log.warning("hardware: %s is set explicitly, but %s", a.field, a.reason)
    last = {
        "hardware": hw.summary(),
        "applied": [asdict(a) for a in applied],
        "explicit_conflicts": [asdict(a) for a in kept],
    }
    log.info("hardware: %s", hw.summary())
    return last
