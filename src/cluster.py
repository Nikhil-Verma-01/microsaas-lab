"""Embed problems + cluster with semantic clustering (Stage 3).

  python -m src.cluster [--min-cluster-size 2] [--model BAAI/bge-small-en-v1.5]

Reads:  data/problems.jsonl
Writes: data/clusters.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import numpy as np
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering

from .config import (
    CLUSTERS_PATH,
    IDEATE_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    PROBLEMS_PATH,
)

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)

CLUSTER_REVIEW_SAMPLES = 3

def name_cluster(problems: list[str], client: OpenAI, model: str) -> str:
    sample = "\n".join(f"- {p}" for p in problems[:8])
    prompt = (
        f"These real-world user problems all share a common theme:\n{sample}\n\n"
        "Give a short 3-6 word descriptive title for this problem cluster. "
        "Be concrete (e.g., 'CSV & Spreadsheet Reconciliation', 'Daily Habit & Achievement Log', 'Video Silence & Clip Extractor', 'Visual Task Hierarchy Planner'). "
        "Reply with ONLY the title."
    )
    for _ in range(2):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=150,
            )
            raw = (resp.choices[0].message.content or "").strip()
            # Clean markdown bold/quotes
            cleaned = raw.replace("**", "").replace('"', "").replace("'", "").strip()
            # If multiple lines, take the first line
            cleaned = cleaned.split("\n")[0].strip()
            if cleaned:
                time.sleep(1.2)  # rate limit buffer
                return cleaned
        except Exception as exc:
            log.warning("Cluster naming error: %s", exc)
            time.sleep(2)
    return "Workflow Automation & Productivity Tool"

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--distance-threshold", type=float, default=0.45, help="Cosine distance threshold (0.35-0.55)")
    ap.add_argument("--min-cluster-size", type=int, default=2)
    ap.add_argument("--model", default="BAAI/bge-small-en-v1.5")
    args = ap.parse_args()

    if not PROBLEMS_PATH.exists():
        print(f"Error: {PROBLEMS_PATH} does not exist. Run extract first.")
        return

    probs = [json.loads(line) for line in PROBLEMS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
    log.info("Loaded %d problems from %s", len(probs), PROBLEMS_PATH)

    if len(probs) < args.min_cluster_size:
        print(f"Not enough problems ({len(probs)}) to cluster.")
        return

    texts = [f"{p['problem']} {p['potential_automation']}" for p in probs]
    log.info("Loading embedding model %s ...", args.model)
    try:
        embedder = SentenceTransformer(args.model)
    except Exception as exc:
        log.warning("Could not load %s (%s); falling back to all-MiniLM-L6-v2", args.model, exc)
        embedder = SentenceTransformer("all-MiniLM-L6-v2")

    embeddings = embedder.encode(texts, show_progress_bar=True, normalize_embeddings=True)

    log.info("Clustering with Agglomerative Clustering (cosine distance <= %.2f) ...", args.distance_threshold)
    clusterer = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=args.distance_threshold,
        metric="cosine",
        linkage="average",
    )
    labels = clusterer.fit_predict(embeddings)

    unique_labels = sorted(set(labels))
    log.info("Identified %d initial semantic clusters", len(unique_labels))

    client_kwargs = {"api_key": LLM_API_KEY}
    if LLM_BASE_URL:
        client_kwargs["base_url"] = LLM_BASE_URL
    oai_client = OpenAI(**client_kwargs)

    clusters = []
    noise_count = 0
    for cid in unique_labels:
        members = [probs[i] for i, l in enumerate(labels) if l == cid]
        if len(members) < args.min_cluster_size:
            noise_count += len(members)
            continue

        name = name_cluster([m["problem"] for m in members], oai_client, IDEATE_MODEL)
        distinct_sources = list({m["doc_id"].split(":")[0] for m in members})
        distinct_authors = len(set(m.get("doc_id", "") for m in members))
        avg_pain = round(sum(m["pain_level"] for m in members) / len(members), 2)
        
        clusters.append({
            "id": int(cid),
            "name": name,
            "member_count": len(members),
            "members": [m["doc_id"] for m in members],
            "distinct_authors": distinct_authors,
            "distinct_sources": distinct_sources,
            "avg_pain": avg_pain,
            "user_types": list({m["user_type"] for m in members}),
            "sample_problems": [m["problem"] for m in members[:CLUSTER_REVIEW_SAMPLES]],
            "sample_workarounds": [m["current_workaround"] for m in members[:CLUSTER_REVIEW_SAMPLES]],
            "search_queries": list({m["likely_search_query"] for m in members if m.get("likely_search_query")}),
        })

    # Sort clusters by member count descending
    clusters.sort(key=lambda c: c["member_count"], reverse=True)

    output = {
        "clusters": clusters,
        "noise_count": noise_count,
        "total_problems": len(probs),
    }
    CLUSTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLUSTERS_PATH.write_text(json.dumps(output, indent=2), encoding="utf-8")

    # ── Review Printout ──────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"STAGE 3 CLUSTER REVIEW -- {len(clusters)} Clusters ({noise_count} singletons)")
    print(f"{'='*70}")
    for c in clusters:
        print(f"\n[Cluster {c['id']}] {c['name']} (n={c['member_count']} | avg_pain={c['avg_pain']}/5)")
        print(f"  Sources: {', '.join(c['distinct_sources'])} | Users: {', '.join(c['user_types'][:2])}")
        for sp in c["sample_problems"]:
            clean_sp = sp[:90].replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
            print(f"  * {clean_sp}")
    print(f"\nOutput written to: {CLUSTERS_PATH}")

if __name__ == "__main__":
    main()
