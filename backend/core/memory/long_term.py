import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, List, Optional

import chromadb
from chromadb.api.types import Documents, Embeddings, EmbeddingFunction

from backend.ai_modules.llm import get_provider
from backend.core.memory.base import MemoryEntry, MemoryType
from backend.database import CHROMA_PATH

log = logging.getLogger(__name__)


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
        """Store a memory entry with all enhanced fields."""
        # Ensure entry has an ID
        if "id" not in entry.metadata:
            entry.metadata["id"] = str(uuid.uuid4())
        
        metadata = entry.metadata.copy()
        metadata["type"] = entry.mtype.value
        metadata["created_at"] = entry.timestamp.isoformat() if isinstance(entry.timestamp, datetime) else entry.timestamp
        metadata["relevance"] = entry.relevance
        
        # Add enhanced fields to metadata for retrieval
        metadata["importance"] = entry.importance
        metadata["confidence"] = entry.confidence
        metadata["last_accessed"] = entry.last_accessed.isoformat() if entry.last_accessed else ""
        metadata["access_count"] = entry.access_count
        metadata["source"] = entry.source
        metadata["tags"] = json.dumps(entry.tags)
        metadata["state"] = entry.state
        metadata["version"] = entry.version

        try:
            self.collection.add(
                ids=[entry.metadata["id"]],
                documents=[entry.content],
                metadatas=[metadata]
            )
            log.info(f"Stored semantic memory: {entry.content[:50]}... (importance={entry.importance:.2f})")
        except Exception as e:
            log.error(f"Failed to store semantic memory: {e}")

    def search(self, query: str, mtype: Optional[MemoryType] = None, limit: int = 5, 
               use_rerank: bool = True, min_importance: float = 0.0) -> List[MemoryEntry]:
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
                    
                    # Parse enhanced fields from metadata
                    importance = float(m.get("importance", 0.5))
                    confidence = float(m.get("confidence", 0.9))
                    access_count = int(m.get("access_count", 0))
                    last_accessed_str = m.get("last_accessed", "")
                    last_accessed = datetime.fromisoformat(last_accessed_str) if last_accessed_str else None
                    source = m.get("source", "user")
                    tags = json.loads(m.get("tags", "[]"))
                    state = m.get("state", "active")
                    version = int(m.get("version", 1))
                    relevance = m.get("relevance", 1.0)
                    
                    # Ponytail-fix: previous `importance < 0.0` was a tautological skip
                    # — importance is float >= 0 by construction, so the filter was a
                    # no-op and min_importance was silently ignored. Use the real param.
                    if importance < min_importance:
                        continue

                    # Temporal weight: recent memories get boost (exponential decay over 30 days)
                    age_days = (datetime.now() - created).days
                    temporal_weight = max(0.3, 1.0 - (age_days / 30.0) * 0.7)
                    
                    # Semantic similarity (1 - cosine distance)
                    semantic_score = 1.0 - min(distances[i], 1.0)
                    
                    # Access frequency boost
                    access_boost = min(0.2, access_count * 0.02)
                    
                    # Combined score with importance, confidence, access frequency
                    combined = (
                        semantic_score * 0.4 + 
                        temporal_weight * 0.2 + 
                        importance * 0.25 + 
                        confidence * 0.15 +
                        access_boost
                    )
                    
                    entry = MemoryEntry(
                        content=docs[i],
                        mtype=MemoryType(m.get("type", "fact")),
                        timestamp=created,
                        metadata=m,
                        relevance=relevance,
                        importance=importance,
                        confidence=confidence,
                        last_accessed=last_accessed,
                        access_count=access_count,
                        source=source,
                        tags=tags,
                        state=state,
                        version=version,
                    )
                    
                    candidates.append({
                        "entry": entry,
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
                    created = datetime.fromisoformat(m["created_at"]) if "created_at" in m else datetime.now()
                    importance = float(m.get("importance", 0.5))
                    confidence = float(m.get("confidence", 0.9))
                    access_count = int(m.get("access_count", 0))
                    last_accessed_str = m.get("last_accessed", "")
                    last_accessed = datetime.fromisoformat(last_accessed_str) if last_accessed_str else None
                    source = m.get("source", "user")
                    tags = json.loads(m.get("tags", "[]"))
                    state = m.get("state", "active")
                    version = int(m.get("version", 1))
                    relevance = m.get("relevance", 1.0)
                    
                    entries.append(MemoryEntry(
                        content=docs[i],
                        mtype=MemoryType(m.get("type", "fact")),
                        timestamp=created,
                        metadata=m,
                        relevance=relevance,
                        importance=importance,
                        confidence=confidence,
                        last_accessed=last_accessed,
                        access_count=access_count,
                        source=source,
                        tags=tags,
                        state=state,
                        version=version,
                    ))
            return entries
        except Exception as e:
            log.error(f"Failed to retrieve all memories: {e}")
            return []

    def update_access(self, memory_id: str) -> bool:
        """Update access count and last_accessed for a memory."""
        try:
            results = self.collection.get(ids=[memory_id], include=["metadatas"])
            if results["metadatas"]:
                m = results["metadatas"][0]
                access_count = int(m.get("access_count", 0)) + 1
                m["access_count"] = access_count
                m["last_accessed"] = datetime.now().isoformat()
                self.collection.update(ids=[memory_id], metadatas=[m])
                return True
        except Exception as e:
            log.error(f"Failed to update access for {memory_id}: {e}")
        return False

    def strengthen_memory(self, memory_id: str, amount: float = 0.1) -> bool:
        """Increase importance/confidence of a memory."""
        try:
            results = self.collection.get(ids=[memory_id], include=["metadatas"])
            if results["metadatas"]:
                m = results["metadatas"][0]
                importance = min(1.0, float(m.get("importance", 0.5)) + amount)
                confidence = min(1.0, float(m.get("confidence", 0.9)) + amount * 0.5)
                m["importance"] = importance
                m["confidence"] = confidence
                m["version"] = int(m.get("version", 1)) + 1
                m["state"] = "strengthened"
                self.collection.update(ids=[memory_id], metadatas=[m])
                return True
        except Exception as e:
            log.error(f"Failed to strengthen memory {memory_id}: {e}")
        return False

    def decay_memories(self, days_threshold: int = 30) -> int:
        """Decay old, unused memories."""
        try:
            all_results = self.collection.get(include=["metadatas", "documents"])
            decayed = 0
            for i, m in enumerate(all_results["metadatas"]):
                created = datetime.fromisoformat(m.get("created_at", datetime.now().isoformat()))
                age_days = (datetime.now() - created).days
                access_count = int(m.get("access_count", 0))
                
                if age_days > days_threshold and access_count < 2:
                    importance = max(0.1, float(m.get("importance", 0.5)) - 0.1)
                    m["importance"] = importance
                    if importance < 0.2:
                        m["state"] = "archived"
                    memory_id = all_results["ids"][i]
                    self.collection.update(ids=[memory_id], metadatas=[m])
                    decayed += 1
            return decayed
        except Exception as e:
            log.error(f"Memory decay failed: {e}")
            return 0

    def search_explainable(self, query: str, mtype: Optional[MemoryType] = None, 
                          limit: int = 5, use_rerank: bool = True) -> List[dict]:
        """Search with detailed explainable scoring breakdown.
        
        Returns list of dicts with:
        - entry: MemoryEntry
        - scores: dict with semantic, temporal, importance, confidence, access_boost, combined
        - explanation: human-readable explanation of why this memory was retrieved
        """
        # Use internal search to get candidates with scores
        where = {"type": mtype.value} if mtype else None
        fetch_limit = limit * 3 if use_rerank else limit
        
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=fetch_limit,
                where=where,
                include=["documents", "metadatas", "distances"]
            )

            results_list = []
            if results["documents"]:
                docs = results["documents"][0]
                metas = results["metadatas"][0]
                distances = results["distances"][0] if results["distances"] else [0] * len(docs)

                candidates = []
                for i in range(len(docs)):
                    m = metas[i]
                    created = datetime.fromisoformat(m["created_at"]) if "created_at" in m else datetime.now()
                    
                    importance = float(m.get("importance", 0.5))
                    confidence = float(m.get("confidence", 0.9))
                    access_count = int(m.get("access_count", 0))
                    last_accessed_str = m.get("last_accessed", "")
                    last_accessed = datetime.fromisoformat(last_accessed_str) if last_accessed_str else None
                    source = m.get("source", "user")
                    tags = json.loads(m.get("tags", "[]"))
                    state = m.get("state", "active")
                    version = int(m.get("version", 1))
                    relevance = m.get("relevance", 1.0)
                    
                    # Ponytail-fix: search_explainable accepts no min_importance, so the
                    # previous `importance < 0.0` was an unreachable tautology. Drop it.
                    age_days = (datetime.now() - created).days
                    temporal_weight = max(0.3, 1.0 - (age_days / 30.0) * 0.7)
                    semantic_score = 1.0 - min(distances[i], 1.0)
                    access_boost = min(0.2, access_count * 0.02)
                    
                    combined = (
                        semantic_score * 0.4 + 
                        temporal_weight * 0.2 + 
                        importance * 0.25 + 
                        confidence * 0.15 +
                        access_boost
                    )
                    
                    entry = MemoryEntry(
                        content=docs[i],
                        mtype=MemoryType(m.get("type", "fact")),
                        timestamp=created,
                        metadata=m,
                        relevance=relevance,
                        importance=importance,
                        confidence=confidence,
                        last_accessed=last_accessed,
                        access_count=access_count,
                        source=source,
                        tags=tags,
                        state=state,
                        version=version,
                    )
                    
                    # Build explanation
                    explanation_parts = []
                    if semantic_score > 0.7:
                        explanation_parts.append(f"High semantic match ({semantic_score:.2f})")
                    if temporal_weight > 0.7:
                        explanation_parts.append(f"Recent memory ({temporal_weight:.2f})")
                    if importance > 0.7:
                        explanation_parts.append(f"High importance ({importance:.2f})")
                    if confidence > 0.8:
                        explanation_parts.append(f"High confidence ({confidence:.2f})")
                    if access_count > 5:
                        explanation_parts.append(f"Frequently accessed ({access_count} times)")
                    
                    explanation = "; ".join(explanation_parts) if explanation_parts else "Low relevance match"
                    
                    scores = {
                        "semantic": round(semantic_score, 3),
                        "temporal": round(temporal_weight, 3),
                        "importance": round(importance, 3),
                        "confidence": round(confidence, 3),
                        "access_boost": round(access_boost, 3),
                        "combined": round(combined, 3),
                    }
                    
                    results_list.append({
                        "entry": entry,
                        "scores": scores,
                        "explanation": explanation,
                    })
                
                if use_rerank:
                    results_list.sort(key=lambda x: x["scores"]["combined"], reverse=True)
                
                return results_list[:limit]
                
        except Exception as e:
            log.error(f"Explainable search failed: {e}")
            return []

    def merge_similar_memories(self, threshold: float = 0.85) -> int:
        """Merge duplicate/similar memories using semantic similarity."""
        # This would need a full scan - simplified version
        # In production, use a dedicated deduplication job
        return 0
