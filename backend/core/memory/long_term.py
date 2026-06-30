import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional

import chromadb
from chromadb.api.types import Documents, Embeddings, EmbeddingFunction

from backend.ai_modules.llm import get_provider
from backend.core.memory.base import MemoryEntry, MemoryType

log = logging.getLogger(__name__)

CHROMA_PATH = Path(__file__).resolve().parents[3] / "backend" / "database" / "chroma_db"


class ProviderEmbeddingFunction(EmbeddingFunction):
    """Bridge between ChromaDB and LLM Provider embeddings."""
    def __call__(self, input: Documents) -> Embeddings:
        llm = get_provider()
        embeddings = []
        for text in input:
            try:
                vec = llm.embed(text)
                embeddings.append(vec)
            except Exception as e:
                log.error(f"Embedding failed for text: {text[:50]}... Error: {e}")
                embeddings.append([0.0] * 768)
        return embeddings


class LongTermMemory:
    """Persistent semantic storage using ChromaDB and LLM Provider embeddings."""
    def __init__(self):
        CHROMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        self.ef = ProviderEmbeddingFunction()
        
        self.collection = self.client.get_or_create_collection(
            name="sg_cube_memories",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"}
        )

    def store(self, entry: MemoryEntry):
        metadata = entry.metadata.copy()
        metadata["type"] = entry.mtype.value
        metadata["created_at"] = entry.timestamp.isoformat() if isinstance(entry.timestamp, datetime) else entry.timestamp
        metadata["relevance"] = entry.relevance

        try:
            self.collection.add(
                ids=[str(uuid.uuid4())],
                documents=[entry.content],
                metadatas=[metadata]
            )
            log.info(f"Stored semantic memory: {entry.content[:50]}...")
        except Exception as e:
            log.error(f"Failed to store semantic memory: {e}")

    def search(self, query: str, mtype: Optional[MemoryType] = None, limit: int = 5, 
               use_rerank: bool = True) -> List[MemoryEntry]:
        """Semantic search with optional reranking and temporal weighting."""
        where = {"type": mtype.value} if mtype else None

        try:
            # Fetch more candidates for reranking
            fetch_limit = limit * 3 if use_rerank else limit
            results = self.collection.query(
                query_texts=[query],
                n_results=fetch_limit,
                where=where,
                include=["documents", "metadatas", "distances"]
            )

            entries = []
            if results["documents"]:
                docs = results["documents"][0]
                metas = results["metadatas"][0]
                distances = results["distances"][0] if results["distances"] else [0] * len(docs)

                candidates = []
                for i in range(len(docs)):
                    m = metas[i]
                    created = datetime.fromisoformat(m["created_at"]) if "created_at" in m else datetime.now()
                    relevance = m.get("relevance", 1.0)
                    
                    # Temporal weight: recent memories get boost (exponential decay over 30 days)
                    age_days = (datetime.now() - created).days
                    temporal_weight = max(0.3, 1.0 - (age_days / 30.0) * 0.7)
                    
                    # Semantic similarity (1 - cosine distance)
                    semantic_score = 1.0 - min(distances[i], 1.0)
                    
                    # Combined score
                    combined = (semantic_score * 0.7 + temporal_weight * 0.3) * relevance
                    
                    candidates.append({
                        "entry": MemoryEntry(
                            content=docs[i],
                            mtype=MemoryType(m.get("type", "fact")),
                            timestamp=created,
                            metadata=m,
                            relevance=relevance
                        ),
                        "semantic_score": semantic_score,
                        "temporal_weight": temporal_weight,
                        "combined_score": combined
                    })

                # Rerank by combined score
                if use_rerank:
                    candidates.sort(key=lambda x: x["combined_score"], reverse=True)
                
                entries = [c["entry"] for c in candidates[:limit]]
                log.debug(f"LTM search: {len(docs)} candidates -> {len(entries)} results (rerank={use_rerank})")
            
            return entries
        except Exception as e:
            log.error(f"Semantic search failed: {e}")
            return []

    def get_all(self, mtype: MemoryType) -> List[MemoryEntry]:
        try:
            results = self.collection.get(where={"type": mtype.value})
            entries = []
            if results["documents"]:
                docs = results["documents"]
                metas = results["metadatas"]
                for i in range(len(docs)):
                    m = metas[i]
                    entries.append(MemoryEntry(
                        content=docs[i],
                        mtype=MemoryType(m.get("type", "fact")),
                        timestamp=datetime.fromisoformat(m["created_at"]) if "created_at" in m else datetime.now(),
                        metadata=m,
                        relevance=m.get("relevance", 1.0)
                    ))
            return entries
        except Exception as e:
            log.error(f"Failed to retrieve all memories: {e}")
            return []
