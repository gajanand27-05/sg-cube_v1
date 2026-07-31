"""Memory-engine health report: zero vectors and duplicate rows.

Consolidates five throwaway `_check_*.py` scripts that lived in the repo root
while T-memory-zero-vectors and T-memory-duplicate-rows were being
investigated. Kept as a permanent tool rather than deleted because it is the
before/after instrument for both of those fixes — neither can be called done
without a run of this showing zeros.

    python tools/memory_health.py            # report; exit 0 unless the tool failed
    python tools/memory_health.py --strict   # exit 1 if problem rows exist

Exit code is 0 by default even when it finds problems: findings are the output,
not a tool failure, and an interactive probe that "fails" every run trains you to
ignore it. `--strict` is the gate to use from CI or a preflight check.

Read-only. Touches nothing, writes nothing.
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Not unused: importing the package makes stdout encoding-safe, without which
# the box-drawing characters below raise UnicodeEncodeError on a cp1252 console.
# See T-log-cp1252 — this script was what proved the fix only reaches code that
# imports `backend`, which most of tools/ does but a standalone script need not.
import backend  # noqa: F401

import chromadb
import numpy as np

CHROMA_PATH = Path(__file__).resolve().parents[1] / "backend" / "database" / "chroma_db"
COLLECTIONS = ("sg_cube_memories", "sg_cube_visual", "sg_cube_timeline")
ZERO_NORM = 1e-10


def report_collection(client, name: str) -> dict:
    print(f"\n── {name}")
    try:
        coll = client.get_collection(name)
    except Exception as e:
        print(f"   unavailable: {type(e).__name__}: {e}")
        return {"name": name, "error": str(e)}

    total = coll.count()
    print(f"   rows: {total}")
    if total == 0:
        return {"name": name, "rows": 0, "zero_vectors": 0, "duplicate_rows": 0}

    # ── zero vectors (T-memory-zero-vectors) ──
    zero = unknown = 0
    try:
        embeddings = coll.get(include=["embeddings"]).get("embeddings")
        if embeddings is None or len(embeddings) == 0:
            unknown = total
        else:
            for vec in embeddings:
                if float(np.linalg.norm(vec)) < ZERO_NORM:
                    zero += 1
    except Exception as e:
        print(f"   embedding read failed: {type(e).__name__}: {e}")
        unknown = total

    if unknown:
        print(f"   zero vectors: unknown ({unknown} unreadable)")
    else:
        pct = zero / total * 100
        flag = "  <-- these are unsearchable" if zero else ""
        print(f"   zero vectors: {zero}/{total} ({pct:.1f}%){flag}")

    # ── duplicate rows (T-memory-duplicate-rows) ──
    docs = [d for d in (coll.get().get("documents") or []) if d]
    counts = Counter(docs)
    dupe_rows = 0
    if name == "sg_cube_timeline":
        # Timeline is an event log — repetition is normal and expected.
        # Only duplicate counting matters for fact stores (memories, visual).
        print(f"   distinct documents: {len(counts)}   (duplicates not counted — event log)")
    else:
        dupe_rows = sum(c - 1 for c in counts.values() if c > 1)
        print(f"   distinct documents: {len(counts)}   duplicate rows: {dupe_rows}")
    for doc, c in sorted(counts.items(), key=lambda kv: -kv[1])[:5]:
        if c > 1:
            print(f"      {c:3d}x  {doc[:64]!r}")

    return {
        "name": name,
        "rows": total,
        "zero_vectors": zero if not unknown else None,
        "duplicate_rows": dupe_rows,
    }


def main() -> int:
    print(f"chroma path: {CHROMA_PATH}")
    if not CHROMA_PATH.exists():
        print("   no database at that path")
        return 2

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    results = [report_collection(client, name) for name in COLLECTIONS]

    print("\n── summary")
    bad = 0
    for r in results:
        if r.get("error"):
            continue
        z, d = r.get("zero_vectors"), r.get("duplicate_rows", 0)
        bad += (z or 0) + (d or 0)
        print(f"   {r['name']:20} rows={r['rows']:<6} "
              f"zero_vectors={'?' if z is None else z:<6} duplicate_rows={d}")
    print(f"\n   {'CLEAN' if bad == 0 else f'{bad} problem row(s)'}")
    if bad and "--strict" in sys.argv:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
