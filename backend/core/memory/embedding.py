"""One embedding function for every memory collection — see T-memory-zero-vectors.

`long_term.py`, `screen_memory.py` and `timeline.py` each carried their own
near-identical copy, and all three had the same defect: on an embed failure they
logged the error and appended `[0.0] * 768`, then let the row be stored anyway.

A zero vector has no direction, so cosine distance to it is degenerate and the
row can never rank in a similarity search. The failure was silent in the worst
way — `store()` logged "Stored semantic memory", `count()` grew, and the UI
reported a healthy collection. With local Ollama down for a day, 32 of 37
long-term memories ended up unsearchable: the assistant had, in effect, no
long-term memory while insisting it did.

A write that cannot be embedded is not a degraded write, it is a lost one. This
raises instead, so the caller has to decide, and the row is never persisted in a
state where nothing can find it.

The same applies on the read side. Chroma calls this function for `query()` too,
and searching *with* a zero vector returns arbitrary nearest neighbours — the
raise turns silently-wrong results into an empty result the caller already
handles.
"""
import logging
import threading

from chromadb.api.types import Documents, EmbeddingFunction, Embeddings

from backend.ai_modules.llm import get_provider

log = logging.getLogger(__name__)

# nomic-embed-text. Kept as a named constant because the old code hard-coded
# this width in three separate zero-vector fallbacks.
EMBEDDING_DIM = 768


class EmbeddingUnavailable(RuntimeError):
    """The embedding backend could not produce a vector.

    Distinct from a storage error: this is usually transient (Ollama not
    running) and the right response is to refuse the write and surface it, not
    to persist something unsearchable.
    """


class ProviderEmbeddingFunction(EmbeddingFunction):
    """Bridge between ChromaDB and the LLM provider's embedding backend."""

    def __init__(self, label: str = "memory"):
        # `label` names the collection in errors so a failure says which write
        # was lost. Chroma warns when an EmbeddingFunction has no __init__.
        self.label = label

    def __call__(self, input: Documents) -> Embeddings:
        llm = get_provider()
        embeddings: Embeddings = []
        for text in input:
            try:
                vec = llm.embed(text)
            except Exception as e:
                raise EmbeddingUnavailable(
                    f"{self.label}: embedding backend unavailable ({type(e).__name__}: {e})"
                ) from e

            if not vec or len(vec) != EMBEDDING_DIM or not any(vec):
                # A backend that returns nothing, the wrong width, or an
                # all-zero vector is the same lost write by another route.
                raise EmbeddingUnavailable(
                    f"{self.label}: embedding backend returned an unusable vector "
                    f"(len={len(vec) if vec else 0})"
                )
            embeddings.append(vec)
        return embeddings

    def name(self) -> str:
        # Chroma deprecation warning asks for this.
        return f"provider-{self.label}"


def report_write_failure(collection: str, reason: str, content: str) -> None:
    """Log and publish a refused memory write.

    ERROR level because a dropped memory is data loss, not a warning. The event
    is what makes it visible without reading logs — see MemoryWriteFailedEvent
    for why this does not reuse ProviderDegradedEvent.
    """
    preview = (content or "")[:80]
    log.error(
        "Refused memory write to %s (%s) — NOT stored, would be unsearchable: %r",
        collection, reason, preview,
    )
    try:
        # Imported here: ui_events and events are heavier than this module needs
        # at import time, and telemetry must never be why a write path explodes.
        from backend.core.events import Priority, get_bus
        from backend.daemon.ui_events import MemoryWriteFailedEvent

        get_bus().publish(
            MemoryWriteFailedEvent(
                collection=collection,
                reason=reason[:200],
                content_preview=preview,
            ),
            priority=Priority.NORMAL,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("Could not publish MemoryWriteFailedEvent: %s", e)


# ── Local embedders (no Ollama) ─────────────────────────────────────────
#
# Memory used nomic-embed-text through local Ollama, so a laptop without
# Ollama refused every memory write. Measured 2026-09-24/25 on the real 65
# long-term memories (25 hand-written English paraphrase questions, plus 10
# Hindi/Kannada ones against the English memories), through production
# ranking (top-15 cosine -> search_scored blend):
#
#   model                          EN @1 / @3   HI+KN @3   hit-vs-miss AUC   size
#   nomic-embed-text (Ollama)      19 / 24      -          0.96              -
#   all-MiniLM-L6-v2 (ONNX)        20 / 25      3 / 10     1.00              90 MB
#   multilingual-MiniLM-L12 int8   20 / 23      9 / 10     0.95              118 MB
#
# Both run on CPU in milliseconds per query. The English model is the default
# (MEMORY_EMBEDDER); the multilingual one is a setting away, and switching
# is a re-embed from stored text (memory/migration.py), not a data loss.

EMBEDDERS: dict[str, int] = {          # name -> vector width
    "minilm-l6": 384,
    "multilingual-minilm-l12": 384,
}
_MULTI_REPO = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_MULTI_FILE = "onnx/model_quint8_avx2.onnx"   # int8: fp32 quality at a quarter of the size

_models: dict = {}
_models_lock = threading.Lock()


class _MultilingualMiniLM:
    def __init__(self) -> None:
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        self._session = ort.InferenceSession(hf_hub_download(_MULTI_REPO, _MULTI_FILE),
                                             providers=["CPUExecutionProvider"])
        self._tok = Tokenizer.from_file(hf_hub_download(_MULTI_REPO, "tokenizer.json"))
        self._tok.enable_truncation(128)
        self._tok.enable_padding()

    def __call__(self, texts: list[str]):
        import numpy as np

        enc = self._tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], dtype=np.int64)
        mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
        out = self._session.run(None, {"input_ids": ids, "attention_mask": mask,
                                       "token_type_ids": np.zeros_like(ids)})[0]
        m = mask[..., None].astype(np.float32)
        return (out * m).sum(1) / np.clip(m.sum(1), 1e-9, None)   # mean pooling


def _load(name: str):
    if name == "minilm-l6":
        # ONE held instance. chromadb's DefaultEmbeddingFunction builds a new
        # ONNXMiniLM_L6_V2 per call, reloading the 90 MB model every query:
        # measured ~210 ms/query that way against ~18 ms held.
        from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

        return ONNXMiniLM_L6_V2()
    if name == "multilingual-minilm-l12":
        return _MultilingualMiniLM()
    raise ValueError(f"unknown MEMORY_EMBEDDER {name!r}; choose one of {sorted(EMBEDDERS)}")


def get_embedder(name: str):
    with _models_lock:
        if name not in _models:
            _models[name] = _load(name)
        return _models[name]


def active_embedder() -> str:
    from backend.server.config import settings

    return settings.memory_embedder


def collection_name(base: str, embedder: str | None = None) -> str:
    """One collection per embedder: vectors from different models are not
    comparable, and keeping the old collection makes switching back free."""
    return f"{base}__{embedder or active_embedder()}"


class LocalEmbeddingFunction(EmbeddingFunction):
    """Chroma embedding function over a local ONNX model. Same refusal
    contract as ProviderEmbeddingFunction: no vector, the wrong width, or an
    all-zero vector raises EmbeddingUnavailable instead of storing a row that
    can never be found."""

    def __init__(self, label: str = "memory", embedder: str | None = None):
        self.label = label
        self.embedder = embedder or active_embedder()
        self.dim = EMBEDDERS.get(self.embedder, 0)

    def __call__(self, input: Documents) -> Embeddings:
        try:
            vectors = get_embedder(self.embedder)(list(input))
        except Exception as e:
            raise EmbeddingUnavailable(
                f"{self.label}: local embedder {self.embedder} failed "
                f"({type(e).__name__}: {e})") from e
        out: Embeddings = []
        for vec in vectors:
            vec = [float(x) for x in vec]
            if len(vec) != self.dim or not any(vec):
                raise EmbeddingUnavailable(
                    f"{self.label}: {self.embedder} returned an unusable vector (len={len(vec)})")
            out.append(vec)
        return out

    def name(self) -> str:
        return f"local-{self.embedder}"
