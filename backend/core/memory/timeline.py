import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

from chromadb.api.types import Documents, Embeddings, EmbeddingFunction
from backend.core.memory.base import MemoryEntry, MemoryType, parse_ts
from backend.core.memory.embedding import (
    EmbeddingUnavailable,
    ProviderEmbeddingFunction,
    report_write_failure,
)
from backend.database import CHROMA_PATH, get_chroma_client

log = logging.getLogger(__name__)


class TimelineMemory:
    """Manages the chronological activity tracking (Timeline Memory)."""
    
    def __init__(self):
        self.client = get_chroma_client()
        self.ef = ProviderEmbeddingFunction("sg_cube_timeline")
        
        # Specific collection for chronological events
        self.collection = self.client.get_or_create_collection(
            name="sg_cube_timeline",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"}
        )

    def record_event(self, content: str, source: str, app: Optional[str] = None, metadata: Optional[dict] = None) -> bool:
        """Record a discrete event into the timeline."""
        now = datetime.now()
        
        meta = metadata or {}
        meta.update({
            "type": MemoryType.EVENT.value,
            "source": source,
            "app": app or "Unknown",
            "created_at": now.isoformat()
        })

        try:
            self.collection.add(
                ids=[str(uuid.uuid4())],
                documents=[content],
                metadatas=[meta]
            )
            log.info(f"Timeline: Recorded {source} event -> {content[:50]}...")
            return True
        except EmbeddingUnavailable as e:
            report_write_failure("sg_cube_timeline", str(e), content)
            return False
        except Exception as e:
            log.error(f"Failed to record timeline event: {e}")
            return False

    def get_recent_timeline(self, limit: int = 10) -> List[MemoryEntry]:
        """Retrieve the most recent events in reverse-chronological order."""
        try:
            # Fetch all — Chroma get(limit=N) returns the FIRST N rows in
            # insertion order (oldest first). Sorting a stale window just gave
            # "newest among the oldest 20". Python sort is fine at our scale.
            # ponytail: O(n) full-scan ceiling. At ~1000 rows this is ~10 ms.
            # Above ~10k rows this needs cursor-based pagination or a metadata
            # index — swap to collection.get(where={"created_at": ">X"}, ...)
            # when that matters.
            results = self.collection.get(
                include=["documents", "metadatas"]
            )
            
            entries = []
            if results["documents"]:
                docs = results["documents"]
                metas = results["metadatas"]

                for i in range(len(docs)):
                    m = metas[i]
                    entries.append(MemoryEntry(
                        content=docs[i],
                        mtype=MemoryType.EVENT,
                        timestamp=parse_ts(m["created_at"]),
                        metadata=m,
                        relevance=1.0
                    ))
                
                # Sort by timestamp descending
                entries.sort(key=lambda x: x.timestamp, reverse=True)
                return entries[:limit]
            
            return []
        except Exception as e:
            log.error(f"Failed to fetch timeline: {e}")
            return []

    def search_timeline(self, query: str, limit: int = 5) -> List[MemoryEntry]:
        """Semantic search for past events with temporal weighting."""
        try:
            fetch_limit = limit * 3
            results = self.collection.query(
                query_texts=[query],
                n_results=fetch_limit,
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
                    created = parse_ts(m["created_at"]) if "created_at" in m else datetime.now()
                    
                    # Semantic similarity
                    semantic_score = 1.0 - min(distances[i], 1.0)
                    
                    # Temporal decay: recent events more relevant for "what was I doing" queries
                    age_hours = (datetime.now() - created).total_seconds() / 3600
                    temporal_weight = max(0.3, 1.0 - (age_hours / 48.0) * 0.7)
                    
                    # Source/app context bonus could be added here
                    combined = (semantic_score * 0.7 + temporal_weight * 0.3)
                    
                    candidates.append({
                        "entry": MemoryEntry(
                            content=docs[i],
                            mtype=MemoryType.EVENT,
                            timestamp=created,
                            metadata=m,
                            relevance=combined
                        ),
                        "combined_score": combined
                    })

                # Rerank by combined score
                candidates.sort(key=lambda x: x["combined_score"], reverse=True)
                entries = [c["entry"] for c in candidates[:limit]]
                
                log.debug(f"Timeline search: {len(docs)} candidates -> {len(entries)} results")
            return entries
        except Exception as e:
            log.error(f"Timeline search failed: {e}")
            return []

# Global instance
timeline = TimelineMemory()
