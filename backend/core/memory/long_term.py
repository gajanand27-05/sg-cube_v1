import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import chromadb
from chromadb.api.types import Documents, Embeddings, EmbeddingFunction

from backend.ai_modules.llm import ollama_client
from backend.core.memory.base import MemoryEntry, MemoryType
from backend.server.config import settings

log = logging.getLogger(__name__)

CHROMA_PATH = Path(__file__).resolve().parents[3] / "backend" / "database" / "chroma_db"

class OllamaEmbeddingFunction(EmbeddingFunction):
    """Bridge between ChromaDB and local Ollama embeddings."""
    def __call__(self, input: Documents) -> Embeddings:
        # ChromaDB calls this with a list of strings.
        # We call our Ollama client for each.
        embeddings = []
        for text in input:
            try:
                vec = ollama_client.embed(text)
                embeddings.append(vec)
            except Exception as e:
                log.error(f"Embedding failed for text: {text[:50]}... Error: {e}")
                # Fallback to zero vector if embedding fails (prevents crash)
                embeddings.append([0.0] * 768) # nomic-embed-text is 768d usually
        return embeddings

class LongTermMemory:
    """Persistent semantic storage using ChromaDB and Ollama embeddings."""
    def __init__(self):
        CHROMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        self.ef = OllamaEmbeddingFunction()
        
        # Initialize or get the collection
        self.collection = self.client.get_or_create_collection(
            name="sg_cube_memories",
            embedding_function=self.ef,
            metadata={"hnsw:space": "cosine"}
        )

    def store(self, entry: MemoryEntry):
        """Store a fact or pattern with semantic embedding and metadata."""
        # Ensure metadata contains required fields from Phase 12 plan
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

    def search(self, query: str, mtype: Optional[MemoryType] = None, limit: int = 5) -> List[MemoryEntry]:
        """Perform semantic search (RAG) against the vector store."""
        where = {}
        if mtype:
            where["type"] = mtype.value

        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=limit,
                where=where
            )

            entries = []
            # results['documents'], results['metadatas'], results['distances'] are lists of lists
            if results["documents"]:
                docs = results["documents"][0]
                metas = results["metadatas"][0]
                # distances = results["distances"][0] if results["distances"] else [0] * len(docs)

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
            log.error(f"Semantic search failed: {e}")
            return []

    def get_all(self, mtype: MemoryType) -> List[MemoryEntry]:
        """Retrieve all memories of a specific type (non-semantic)."""
        try:
            results = self.collection.get(
                where={"type": mtype.value}
            )
            
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
