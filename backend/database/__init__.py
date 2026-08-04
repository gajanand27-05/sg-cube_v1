from pathlib import Path

CHROMA_PATH = Path(__file__).resolve().parent / "chroma_db"


# Audit HIGH-7: three memory modules each built their own PersistentClient on
# the same path; Chroma holds a sqlite handle per client and concurrent
# access degraded to lock contention under voice/main-thread traffic. One
# memoized client for the process, shared by all collections.
import threading

import chromadb

_client: "chromadb.ClientAPI | None" = None
_client_lock = threading.Lock()


def get_chroma_client() -> "chromadb.ClientAPI":
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                CHROMA_PATH.parent.mkdir(parents=True, exist_ok=True)
                _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client
