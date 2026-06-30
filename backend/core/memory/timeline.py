import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

import chromadb
from chromadb.api.types import Documents, Embeddings, EmbeddingFunction
from backend.core.memory.base import MemoryEntry, MemoryType
from backend.ai_modules.llm import get_provider

log = logging.getLogger(__name__)

CHROMA_PATH = __file__.rsplit("\\", 3)[0] + "\\backend\\database\\chroma_db" if "\\" in __file__ else "/".join(__file__.split("/")[:-3]) + "/backend/database/chroma_db"


class TimelineEmbeddingFunction(EmbeddingFunction):
    """Bridge between ChromaDB and LLM Provider for timeline embeddings."""
    def __call__(self, input: Documents) -> Embeddings:
        llm = get_provider()
        embeddings = []
        for text in input:
            try:
                vec = llm.embed(text)
                embeddings.append(vec)
            except Exception as e:
                log.error(f"Timeline embedding failed: {e}")
                embeddings.append([0.0] * 768)
        return embeddings


class TimelineMemory:
    """Manages the chronological activity tracking (Timeline Memory)."""
    
    def __init__(self):
        self.client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        self.ef = TimelineEmbeddingFunction()
        
        # Specific collection for chronological events
        self.collection = self.client.get_or_create_collection(
            name="sg_cube_timeline",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"}
        )

    def record_event(self, content: str, source: str, app: Optional[str] = None, metadata: Optional[dict] = None):
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
        except Exception as e:
            log.error(f"Failed to record timeline event: {e}")

    def get_recent_timeline(self, limit: int = 10) -> List[MemoryEntry]:
        """Retrieve the most recent events in reverse-chronological order."""
        try:
            # We fetch everything and sort manually because Chroma 'get' 
            # with sorting isn't always reliable across versions, 
            # and 'query' is semantic, not chronological.
            results = self.collection.get(
                limit=limit * 2, # Fetch more to allow for filtering/sorting
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
                        timestamp=datetime.fromisoformat(m["created_at"]),
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
        """Semantic search for past events (e.g., 'What was I doing with PDF?')"""
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=limit
            )

            entries = []
            if results["documents"]:
                docs = results["documents"][0]
                metas = results["metadatas"][0]

                for i in range(len(docs)):
                    m = metas[i]
                    entries.append(MemoryEntry(
                        content=docs[i],
                        mtype=MemoryType.EVENT,
                        timestamp=datetime.fromisoformat(m["created_at"]),
                        metadata=m,
                        relevance=1.0
                    ))
            return entries
        except Exception as e:
            log.error(f"Timeline search failed: {e}")
            return []

# Global instance
timeline = TimelineMemory()
