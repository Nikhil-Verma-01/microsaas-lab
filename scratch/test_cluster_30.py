import json
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
from src.config import PROBLEMS_PATH

probs = [json.loads(line) for line in PROBLEMS_PATH.open(encoding="utf-8") if line.strip()]
texts = [f"{p['problem']} {p['potential_automation']}" for p in probs]

embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")
embeddings = embedder.encode(texts, normalize_embeddings=True)

c = AgglomerativeClustering(n_clusters=None, distance_threshold=0.30, metric="cosine", linkage="average")
labels = c.fit_predict(embeddings)

unique = sorted(set(labels))
valid_clusters = []
for cid in unique:
    members = [probs[i] for i, l in enumerate(labels) if l == cid]
    if len(members) >= 2:
        valid_clusters.append((cid, members))

print(f"Clusters with size >= 2: {len(valid_clusters)}")
for cid, members in valid_clusters[:10]:
    print(f"\n--- Cluster {cid} ({len(members)} problems) ---")
    for m in members[:3]:
        print(f"  [{m.get('user_type')}] {m.get('problem')[:90]}")
