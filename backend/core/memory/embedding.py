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
