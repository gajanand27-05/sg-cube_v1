import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from backend.core.memory.base import MemoryEntry, MemoryType

DB_PATH = Path(__file__).resolve().parents[3] / "backend" / "database" / "memory.db"

class LongTermMemory:
    """Persistent storage for semantic facts and patterns."""
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    mtype TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    metadata TEXT,
                    relevance REAL DEFAULT 1.0
                )
            """)
            # Full-text search for facts
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(content, content='memories', content_rowid='id')")

    def store(self, entry: MemoryEntry):
        with sqlite3.connect(str(DB_PATH)) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO memories (content, mtype, timestamp, metadata, relevance) VALUES (?, ?, ?, ?, ?)",
                (entry.content, entry.mtype.value, entry.timestamp, json.dumps(entry.metadata), entry.relevance)
            )
            row_id = cur.lastrowid
            cur.execute("INSERT INTO memories_fts (rowid, content) VALUES (?, ?)", (row_id, entry.content))

    def search(self, query: str, mtype: Optional[MemoryType] = None, limit: int = 5) -> List[MemoryEntry]:
        """Keyword/FTS search for now (Simulating semantic search)."""
        with sqlite3.connect(str(DB_PATH)) as conn:
            sql = "SELECT content, mtype, timestamp, metadata, relevance FROM memories_fts JOIN memories ON memories_fts.rowid = memories.id WHERE memories_fts MATCH ?"
            params = [query]
            if mtype:
                sql += " AND mtype = ?"
                params.append(mtype.value)
            sql += " LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(sql, params).fetchall()
            return [
                MemoryEntry(
                    content=r[0],
                    mtype=MemoryType(r[1]),
                    timestamp=datetime.fromisoformat(r[2]) if isinstance(r[2], str) else r[2],
                    metadata=json.loads(r[3] or "{}"),
                    relevance=r[4]
                ) for r in rows
            ]

    def get_all(self, mtype: MemoryType) -> List[MemoryEntry]:
        with sqlite3.connect(str(DB_PATH)) as conn:
            rows = conn.execute(
                "SELECT content, mtype, timestamp, metadata, relevance FROM memories WHERE mtype = ?",
                (mtype.value,)
            ).fetchall()
            return [
                MemoryEntry(
                    content=r[0],
                    mtype=MemoryType(r[1]),
                    timestamp=datetime.fromisoformat(r[2]) if isinstance(r[2], str) else r[2],
                    metadata=json.loads(r[3] or "{}"),
                    relevance=r[4]
                ) for r in rows
            ]
