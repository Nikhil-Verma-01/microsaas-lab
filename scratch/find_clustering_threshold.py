import json
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering
from src.config import PROBLEMS_PATH

probs = [json.loads(line) for line in PROBLEMS_PATH.open(encoding="utf-8") if line.strip()]
texts = [f"{p['problem']} {p['potential_automation']}" for p in probs]

embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")
embeddings = embedder.encode(texts, normalize_embeddings=True)

# Test different distance thresholds
for thresh in [0.15, 0.20, 0.25, 0.30, 0.35]:
    c = AgglomerativeClustering(n_clusters=None, distance_threshold=thresh, metric="cosine", linkage="average")
    labels = c.fit_predict(embeddings)
    unique = set(labels)
    cluster_sizes = [sum(1 for l in labels if l == cid) for cid in unique]
    print(f"Threshold {thresh:.2f}: {len(unique)} clusters, min size={min(cluster_sizes)}, max size={max(cluster_sizes)}")
