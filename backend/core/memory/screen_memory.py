import logging
import uuid
from datetime import datetime
from typing import List, Optional

import chromadb
from backend.core.memory.long_term import OllamaEmbeddingFunction, CHROMA_PATH
from backend.core.memory.base import MemoryEntry, MemoryType

log = logging.getLogger(__name__)

class ScreenMemory:
    """Manages the visual situational awareness memory (Screen-RAG)."""
    
    def __init__(self):
        self.client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        self.ef = OllamaEmbeddingFunction()
        
        # Specific collection for visual context
        self.collection = self.client.get_or_create_collection(
            name="sg_cube_visual",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"}
        )

    def store_observation(self, observation: dict):
        """Embed and store a structured visual observation.
        
        observation format: {"app": str, "summary": str, "keywords": list}
        """
        app = observation.get("app", "Unknown")
        summary = observation.get("summary", "")
        keywords = observation.get("keywords", [])
        
        # Construct the text to be embedded
        content = f"User was looking at {app}: {summary}. Keywords: {', '.join(keywords)}"
        
        metadata = {
            "type": "visual",
            "app": app,
            "created_at": datetime.now().isoformat(),
            "keywords": ",".join(keywords)
        }

        try:
            self.collection.add(
                ids=[str(uuid.uuid4())],
                documents=[content],
                metadatas=[metadata]
            )
            log.info(f"Stored visual memory: {app} -> {summary[:40]}...")
        except Exception as e:
            log.error(f"Failed to store visual memory: {e}")

    def search_visual(self, query: str, limit: int = 3) -> List[MemoryEntry]:
        """Retrieve relevant past visual context."""
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
                        mtype=MemoryType.VISUAL, # Visuals are effectively episodic context
                        timestamp=datetime.fromisoformat(m["created_at"]),
                        metadata=m,
                        relevance=1.0
                    ))
            return entries
        except Exception as e:
            log.error(f"Visual search failed: {e}")
            return []

# Global instance
screen_memory = ScreenMemory()
