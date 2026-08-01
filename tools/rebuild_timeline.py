"""Rebuild sg_cube_timeline with fresh Ollama embeddings.

Why: the HNSW index is corrupt — reading embeddings raises
'InternalError: Error finding id' — so timeline semantic search is dead.

Approach:
1. Dump all docs+metas from the old collection to a JSON checkpoint.
2. Create a fresh collection with the same config (cosine space).
3. Upsert rows in batches with ProviderEmbeddingFunction (Ollama).
   Resumable: IDs already present in the new collection are skipped, so a
   re-run continues where it stopped instead of re-embedding everything.
4. Verify count matches the dump and spot-check 5 docs against it.
5. Only then delete the old collection and rename the new one into place.

Usage:
  python tools/rebuild_timeline.py            # full rebuild
  python tools/rebuild_timeline.py --resume   # skip rows already in new coll
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb

from backend.core.memory.embedding import ProviderEmbeddingFunction

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = str(ROOT / "backend" / "database" / "chroma_db")
DUMP = ROOT / "tools" / "timeline_dump.json"
COLL_NAME = "sg_cube_timeline"
NEW_NAME = "sg_cube_timeline_rebuilt"
BATCH = 64

RESUME = "--resume" in sys.argv


def dump_old(client) -> None:
    coll = client.get_collection(COLL_NAME)
    data = coll.get(include=["documents", "metadatas"])
    ids = data["ids"] or []
    docs = data["documents"] or []
    metas = data["metadatas"] or []
    rows = [{"id": i, "doc": d, "meta": m} for i, d, m in zip(ids, docs, metas)]
    DUMP.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"Dumped {len(rows)} rows -> {DUMP.name}")


def main() -> None:
    client = chromadb.PersistentClient(path=DB_PATH)
    old = client.get_collection(COLL_NAME)
    print(f"Old {COLL_NAME}: {old.count()} rows")

    if not DUMP.exists():
        dump_old(client)
    dump = json.loads(DUMP.read_text(encoding="utf-8"))
    print(f"Dump: {len(dump)} rows")

    new = client.get_or_create_collection(
        name=NEW_NAME,
        embedding_function=ProviderEmbeddingFunction(COLL_NAME),
        metadata={"hnsw:space": "cosine"},
    )

    existing = set(new.get()["ids"]) if new.count() else set()
    todo = [r for r in dump if r["id"] not in existing]
    print(f"New collection has {len(existing)} rows, {len(todo)} to add")

    ef = ProviderEmbeddingFunction(COLL_NAME)
    t0 = time.time()
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        docs = [r["doc"] for r in batch]
        vecs = ef(docs)  # raises if Ollama down — resumable on re-run
        new.upsert(
            ids=[r["id"] for r in batch],
            documents=docs,
            metadatas=[r["meta"] for r in batch],
            embeddings=vecs,
        )
        done = start + len(batch)
        print(f"  {done}/{len(todo)}  ({time.time() - t0:.0f}s)")

    # Verify: count + spot-check content against the dump
    final = client.get_collection(NEW_NAME)
    got = final.get()
    assert len(got["ids"]) == len(dump), \
        f"count mismatch: {len(got['ids'])} vs dump {len(dump)}"
    print(f"\nVerified: {NEW_NAME} has {len(got['ids'])} rows (dump {len(dump)})")

    for i in range(0, min(5, len(dump)), 1):
        rid = dump[i]["id"]
        idx = got["ids"].index(rid)
        match = got["documents"][idx] == dump[i]["doc"]
        print(f"  spot-check {rid[:8]}: {'OK' if match else 'MISMATCH'}")
        assert match, f"content mismatch for {rid}"

    # Embeddings readable?
    emb = final.get(include=["embeddings"])["embeddings"]
    zero = sum(1 for e in emb if e is None or not any(e))
    print(f"  embeddings: {len(emb)} readable, {zero} zero")

    # Swap into place
    client.delete_collection(COLL_NAME)
    client.get_collection(NEW_NAME).modify(name=COLL_NAME)
    print(f"\nDiscarded original, renamed {NEW_NAME} -> {COLL_NAME}")
    print(f"Final: {client.get_collection(COLL_NAME).count()} rows")


if __name__ == "__main__":
    main()
