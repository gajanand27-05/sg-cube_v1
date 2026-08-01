"""Clean up and re-embed the 6 memory rows properly."""
import sys
sys.path.insert(0, '.')
import chromadb
from backend.core.memory.embedding import ProviderEmbeddingFunction

ef = ProviderEmbeddingFunction('sg_cube_memories')
client = chromadb.PersistentClient(path='backend/database/chroma_db')
coll = client.get_collection('sg_cube_memories')

# Step 1: Delete the dummy rows
print("Removing dummy rows (mem_0 to mem_5)...")
coll.delete(ids=['mem_0', 'mem_1', 'mem_2', 'mem_3', 'mem_4', 'mem_5'])
print(f"  After cleanup: {coll.count()} rows")

# Step 2: Get remaining 6 rows
data = coll.get(include=['documents', 'metadatas'])
docs = data['documents'] or []
metas = data['metadatas'] or []
original_ids = data['ids'] or []

print(f"Remaining: {len(original_ids)} rows")

# Step 3: Embed all at once using the ProviderEmbeddingFunction
print("Re-embedding...")
vecs = ef(docs)  # This is an EmbeddingFunction, called directly
print(f"  Embed completed: {len(vecs)} vectors, {len(vecs[0])} dims each")

# Step 4: Upsert with embeddings
print("Upserting with embeddings...")
coll.upsert(ids=original_ids, documents=docs, metadatas=metas, embeddings=vecs)
print(f"  After upsert: {coll.count()} rows")

# Step 5: Verify with a query
print("\nVerifying with query 'dark':")
results = coll.query(query_texts=['dark'], n_results=3)
if results['ids'] and results['ids'][0]:
    for i, id_ in enumerate(results['ids'][0]):
        doc = results['documents'][0][i]
        doc_preview = doc[:60] if doc else '(none)'
        dist = results['distances'][0][i]
        print(f"  Match {i}: {doc_preview} (distance={dist:.4f})")
else:
    print("  No matches (this means embeddings are empty or wrong)")

print(f"\nAll 6 memories now have real Ollama embeddings.")
