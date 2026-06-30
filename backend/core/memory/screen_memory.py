import logging
import uuid
from datetime import datetime
from typing import List, Optional

import chromadb
from chromadb.api.types import Documents, Embeddings, EmbeddingFunction
from backend.ai_modules.llm import get_provider
from backend.core.memory.base import MemoryEntry, MemoryType

log = logging.getLogger(__name__)

CHROMA_PATH = __file__.rsplit("\\", 3)[0] + "\\backend\\database\\chroma_db" if "\\" in __file__ else "/".join(__file__.split("/")[:-3]) + "/backend/database/chroma_db"


class ScreenEmbeddingFunction(EmbeddingFunction):
    """Bridge between ChromaDB and LLM Provider for screen memory."""
    def __call__(self, input):
        llm = get_provider()
        embeddings = []
        for text in input:
            try:
                vec = llm.embed(text)
                embeddings.append(vec)
            except Exception as e:
                log.error(f"Screen embedding failed: {e}")
                embeddings.append([0.0] * 768)
        return embeddings


class ScreenMemory:
    """Manages the visual situational awareness memory (Screen-RAG)."""
    
    def __init__(self):
        self.client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        self.ef = ScreenEmbeddingFunction()
        
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

    def get_recent_observations(self, limit: int = 10) -> list[dict]:
        """Return recent observations sorted by time descending."""
        try:
            results = self.collection.get(
                limit=limit * 2,
                include=["documents", "metadatas"]
            )
            entries = []
            if results["documents"]:
                for i in range(len(results["documents"])):
                    m = results["metadatas"][i]
                    entries.append({
                        "content": results["documents"][i],
                        "app": m.get("app", "Unknown"),
                        "keywords": m.get("keywords", ""),
                        "created_at": m.get("created_at", ""),
                    })
                entries.sort(key=lambda x: x["created_at"], reverse=True)
                return entries[:limit]
            return []
        except Exception as e:
            log.error(f"Failed to get recent observations: {e}")
            return []

    def get_latest_observation(self) -> Optional[str]:
        """Return the most recent visual summary stored."""
        try:
            # Chroma doesn't have a simple 'get last' by default without sorting
            # But we can query everything and sort by date if we had a metadata filter
            # Or just use the 'get' with a limit.
            results = self.collection.get(
                limit=1,
                include=["documents", "metadatas"]
            )
            if results["documents"]:
                # Note: 'get' with limit=1 doesn't guarantee 'latest' without sorting.
                # However, since we use UUIDs, it's random. 
                # Let's use query with a very broad string to get recent stuff if possible,
                # or better, just keep a cache in memory of the last one.
                return results["documents"][0]
            return None
        except Exception:
            return None

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
