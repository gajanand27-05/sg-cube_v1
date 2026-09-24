"""Re-embed memory into the active embedder's collections, from stored text.

Each store has one collection per embedder (embedding.collection_name). When
the active embedder's collection holds fewer rows than another collection of
the same store — the pre-2026-09-25 nomic one ("sg_cube_memories", no
suffix), or a previous embedder's — its rows are copied across with the text
and metadata unchanged and fresh vectors computed locally.

  * never touches the source: switching back is free, nothing is lost
  * upserts by id, in batches, so an interrupted run resumes and a re-run
    adds nothing
  * runs on a background thread at boot; measured ~62-70 s for all 2,709
    real memories on this CPU. Until it finishes, recall covers only the
    rows already migrated — status() says so (GET /diagnostics/memory).
"""
from __future__ import annotations

import logging
import threading
import time

from backend.core.memory.embedding import (
    EMBEDDERS,
    LocalEmbeddingFunction,
    active_embedder,
    collection_name,
)

log = logging.getLogger(__name__)

STORES = ("sg_cube_memories", "sg_cube_visual", "sg_cube_timeline")
BATCH = 64

_state: dict = {"running": False, "stores": {}, "error": None}
_lock = threading.Lock()


def status() -> dict:
    with _lock:
        return {"embedder": active_embedder(), "running": _state["running"],
                "stores": {k: dict(v) for k, v in _state["stores"].items()},
                "error": _state["error"]}


def _source_for(client, base: str, target: str):
    """The largest other collection of this store, or None."""
    best = None
    for c in client.list_collections():
        name = c if isinstance(c, str) else c.name
        if name == target or not (name == base or name.startswith(base + "__")):
            continue
        col = client.get_collection(name)
        if best is None or col.count() > best.count():
            best = col
    return best


def migrate_store(client, base: str, embedder: str, batch: int = BATCH) -> dict:
    ef = LocalEmbeddingFunction(base, embedder)
    target = client.get_or_create_collection(
        name=collection_name(base, embedder), embedding_function=ef,
        metadata={"hnsw:space": "cosine", "embedder": embedder, "dim": EMBEDDERS[embedder]})
    source = _source_for(client, base, target.name)
    info = {"source": getattr(source, "name", None), "source_rows": source.count() if source else 0,
            "target": target.name, "migrated": 0, "done": False}
    if source is None or target.count() >= source.count():
        info["done"] = True
        return info

    offset, total = 0, source.count()
    while offset < total:
        page = source.get(limit=batch, offset=offset, include=["documents", "metadatas"])
        offset += batch
        rows = [(i, d, m) for i, d, m in zip(page["ids"], page["documents"], page["metadatas"])
                if d]  # a row with no text has nothing to re-embed from
        if not rows:
            continue
        have = set(target.get(ids=[r[0] for r in rows], include=[])["ids"])
        todo = [r for r in rows if r[0] not in have]
        if todo:
            target.upsert(ids=[r[0] for r in todo], documents=[r[1] for r in todo],
                          metadatas=[r[2] or None for r in todo])
            info["migrated"] += len(todo)
        with _lock:
            _state["stores"][base] = dict(info)
    info["done"] = True
    return info


def run(client=None, embedder: str | None = None) -> dict:
    from backend.database import get_chroma_client

    client = client or get_chroma_client()
    embedder = embedder or active_embedder()
    with _lock:
        _state.update(running=True, error=None)
    t0 = time.perf_counter()
    try:
        for base in STORES:
            info = migrate_store(client, base, embedder)
            with _lock:
                _state["stores"][base] = info
            if info["migrated"]:
                log.info("memory migration: %s -> %s, %d rows re-embedded",
                         info["source"], info["target"], info["migrated"])
        log.info("memory migration to %s finished in %.1fs", embedder, time.perf_counter() - t0)
    except Exception as e:
        log.exception("memory migration failed (sources untouched; resumes next boot)")
        with _lock:
            _state["error"] = f"{type(e).__name__}: {e}"
    finally:
        with _lock:
            _state["running"] = False
    return status()


def start_background() -> None:
    threading.Thread(target=run, name="memory-migration", daemon=True).start()
