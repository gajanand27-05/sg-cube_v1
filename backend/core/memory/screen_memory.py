import logging
import uuid
from datetime import datetime, timedelta
from typing import List, Optional

import chromadb
from chromadb.api.types import Documents, Embeddings, EmbeddingFunction
from backend.ai_modules.llm import get_provider
from backend.core.memory.base import MemoryEntry, MemoryType
from backend.database import CHROMA_PATH

log = logging.getLogger(__name__)


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
            # Get recent and sort by time
            recent = self.get_recent_observations(limit=1)
            if recent:
                return recent[0]["content"]
            return None
        except Exception:
            return None

    def search_visual(self, query: str, limit: int = 3, current_app: str = None) -> List[MemoryEntry]:
        """Retrieve relevant past visual context with relevance scoring."""
        try:
            # Fetch more candidates for scoring
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
                    created = datetime.fromisoformat(m["created_at"]) if "created_at" in m else datetime.now()
                    
                    # Visual relevance scoring
                    semantic_score = 1.0 - min(distances[i], 1.0)
                    
                    # App match bonus (if currently in same app)
                    app_bonus = 0.2 if current_app and m.get("app") == current_app else 0.0
                    
                    # Keyword overlap bonus
                    query_keywords = set(query.lower().split())
                    stored_keywords = set(m.get("keywords", "").lower().split(","))
                    keyword_overlap = len(query_keywords & stored_keywords) / max(len(query_keywords), 1)
                    keyword_bonus = min(keyword_overlap * 0.3, 0.3)
                    
                    # Temporal decay (recent visual context more relevant)
                    age_hours = (datetime.now() - created).total_seconds() / 3600
                    temporal_weight = max(0.4, 1.0 - (age_hours / 24.0) * 0.6)
                    
                    combined = (semantic_score * 0.5 + keyword_bonus + app_bonus) * temporal_weight
                    
                    candidates.append({
                        "entry": MemoryEntry(
                            content=docs[i],
                            mtype=MemoryType.VISUAL,
                            timestamp=created,
                            metadata=m,
                            relevance=combined
                        ),
                        "combined_score": combined
                    })

                # Rerank by combined score
                candidates.sort(key=lambda x: x["combined_score"], reverse=True)
                entries = [c["entry"] for c in candidates[:limit]]
                
                log.debug(f"Visual search: {len(docs)} candidates -> {len(entries)} results")
            return entries
        except Exception as e:
            log.error(f"Visual search failed: {e}")
            return []


# Global instance
screen_memory = ScreenMemory()
