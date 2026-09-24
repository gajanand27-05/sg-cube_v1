"""Memory embeds locally (no Ollama) into one collection per embedder, and the
old collections are re-embedded from their stored text — never modified."""
import chromadb
import numpy as np
import pytest

from backend.core.memory import embedding, migration
from backend.core.memory.embedding import (
    EmbeddingUnavailable,
    LocalEmbeddingFunction,
    collection_name,
)


def test_the_real_minilm_embeds_to_384_dims():
    """The shipped default, not a stub — a wrong width would make every
    write an EmbeddingUnavailable."""
    out = LocalEmbeddingFunction("t", "minilm-l6")(["my cat is called Luna"])
    assert len(out) == 1 and len(out[0]) == 384 and any(out[0])


def test_similar_text_is_closer_than_unrelated_text():
    ef = LocalEmbeddingFunction("t", "minilm-l6")
    a, b, c = (np.array(v) for v in ef(["my favourite colour is blue",
                                        "which colour do I like best?",
                                        "set a timer for the pasta"]))
    cos = lambda x, y: float(x @ y / np.linalg.norm(x) / np.linalg.norm(y))
    assert cos(a, b) > cos(a, c)


@pytest.mark.parametrize("vec", [[0.0] * 384, [0.1] * 12])
def test_unusable_vectors_are_refused_not_stored(monkeypatch, vec):
    monkeypatch.setattr(embedding, "get_embedder", lambda name: (lambda texts: [vec]))
    with pytest.raises(EmbeddingUnavailable):
        LocalEmbeddingFunction("t", "minilm-l6")(["x"])


def test_collections_are_named_per_embedder():
    assert collection_name("sg_cube_memories", "minilm-l6") == "sg_cube_memories__minilm-l6"


class _FakeEF(LocalEmbeddingFunction):
    """Deterministic, fast 384-d vectors so migration is tested without a model."""
    def __call__(self, input):
        return [[float((hash(t) >> i) % 7 + 1) for i in range(384)] for t in input]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(migration, "LocalEmbeddingFunction", _FakeEF)
    c = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    legacy = c.get_or_create_collection("sg_cube_memories", metadata={"hnsw:space": "cosine"})
    legacy.add(ids=[f"m{i}" for i in range(150)],
               documents=[f"memory number {i}" for i in range(150)],
               metadatas=[{"type": "fact", "importance": 0.5, "i": i} for i in range(150)],
               embeddings=[[0.5] * 768 for _ in range(150)])   # nomic-shaped
    return c


def test_migration_copies_text_and_metadata_and_leaves_the_source(client):
    info = migration.migrate_store(client, "sg_cube_memories", "minilm-l6", batch=64)
    assert info["migrated"] == 150 and info["done"]
    target = client.get_collection("sg_cube_memories__minilm-l6")
    got = target.get(ids=["m7"], include=["documents", "metadatas", "embeddings"])
    assert got["documents"] == ["memory number 7"]
    assert got["metadatas"][0]["i"] == 7
    assert len(got["embeddings"][0]) == 384, "re-embedded, not copied"
    legacy = client.get_collection("sg_cube_memories")
    assert legacy.count() == 150
    assert len(legacy.get(ids=["m7"], include=["embeddings"])["embeddings"][0]) == 768


def test_a_rerun_adds_nothing(client):
    migration.migrate_store(client, "sg_cube_memories", "minilm-l6")
    again = migration.migrate_store(client, "sg_cube_memories", "minilm-l6")
    assert again["migrated"] == 0
    assert client.get_collection("sg_cube_memories__minilm-l6").count() == 150


def test_an_interrupted_migration_resumes(client, monkeypatch):
    target = client.get_or_create_collection(
        "sg_cube_memories__minilm-l6", embedding_function=_FakeEF("t", "minilm-l6"),
        metadata={"hnsw:space": "cosine"})
    target.upsert(ids=["m0", "m1", "m2"], documents=["memory number 0", "memory number 1",
                                                     "memory number 2"])
    info = migration.migrate_store(client, "sg_cube_memories", "minilm-l6")
    assert info["migrated"] == 147
    assert target.count() == 150
