"""Re-embed zero-vector rows in sg_cube_visual."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import chromadb

from backend.core.memory.embedding import ProviderEmbeddingFunction

client = chromadb.PersistentClient(
    path=str(Path(__file__).resolve().parent.parent / "backend" / "database" / "chroma_db")
)
coll = client.get_collection("sg_cube_visual")
result = coll.get(include=["documents", "metadatas", "embeddings"])
docs = result["documents"] or []
metas = result["metadatas"] or []
ids = result["ids"] or []
embeds = result["embeddings"]
embeds = list(embeds) if embeds is not None else []

zero_idx = [i for i, e in enumerate(embeds) if e is None or not any(e)]
print(f"zero-vector rows: {len(zero_idx)}")
for i in zero_idx:
    print(f"  {ids[i]}  {docs[i][:60]}")

if zero_idx:
    ef = ProviderEmbeddingFunction("sg_cube_visual")
    vecs = ef([docs[i] for i in zero_idx])
    coll.update(ids=[ids[i] for i in zero_idx], embeddings=vecs)
    print(f"re-embedded {len(zero_idx)} rows")

result2 = coll.get(include=["embeddings"])
emb2 = result2["embeddings"]
emb2 = list(emb2) if emb2 is not None else []
print(f"after: {coll.count()} rows, zero vectors: {sum(1 for e in emb2 if e is None or not any(e))}")
