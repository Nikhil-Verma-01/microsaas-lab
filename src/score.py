"""Score clusters by weighted problem-quality metrics (Stage 4).

  python -m src.score

Reads:  data/clusters.json  +  data/problems.jsonl
Writes: data/scored.csv
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import CLUSTERS_PATH, PROBLEMS_PATH, SCORED_PATH

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)

WEIGHTS = {
    "frequency": 0.25,
    "severity": 0.20,
    "recurrence": 0.15,
    "growth": 0.15,
    "source_diversity": 0.10,
    "existing_gap": 0.10,
    "specificity": 0.05,
}

def _growth_score(dates: list[str]) -> float:
    """Recency weighting: newer items score higher."""
    now = datetime.now(timezone.utc).timestamp()
    if not dates:
        return 0.5
    scores = []
    for d in dates:
        try:
            # Handle standard ISO strings
            clean_d = d.replace("Z", "+00:00")
            ts = datetime.fromisoformat(clean_d).timestamp()
            age_days = (now - ts) / 86400
            # Decay over ~2 years (730 days)
            scores.append(max(0.1, min(1.0, 1.0 - (age_days / 730))))
        except Exception:
            scores.append(0.5)
    return sum(scores) / len(scores)

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if not CLUSTERS_PATH.exists() or not PROBLEMS_PATH.exists():
        print("Error: clusters.json or problems.jsonl not found.")
        return

    data = json.loads(CLUSTERS_PATH.read_text(encoding="utf-8"))
    probs_by_id = {}
    for line in PROBLEMS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                p = json.loads(line)
                probs_by_id[p["doc_id"]] = p
            except Exception:
                pass

    rows = []
    for c in data.get("clusters", []):
        members = [probs_by_id[m] for m in c["members"] if m in probs_by_id]
        if not members:
            continue

        n = len(members)
        # Normalised metric factors (0.0 to 1.0)
        freq_factor = min(n / 10.0, 1.0)
        severity_factor = (sum(m["pain_level"] for m in members) / n - 1.0) / 4.0
        recurrence_factor = sum(1 for m in members if m.get("frequency") == "recurring") / n
        growth_factor = _growth_score([m.get("created_at", "") for m in members if m.get("created_at")])
        src_div_factor = min(len(c["distinct_sources"]) / 2.0, 1.0)
        gap_factor = 1.0 - (sum(1 for m in members if m.get("existing_tools_mentioned")) / n)
        specificity_factor = sum(m.get("confidence", 0.8) for m in members) / n

        composite_score = (
            WEIGHTS["frequency"] * freq_factor +
            WEIGHTS["severity"] * severity_factor +
            WEIGHTS["recurrence"] * recurrence_factor +
            WEIGHTS["growth"] * growth_factor +
            WEIGHTS["source_diversity"] * src_div_factor +
            WEIGHTS["existing_gap"] * gap_factor +
            WEIGHTS["specificity"] * specificity_factor
        )

        user_types = list({m["user_type"] for m in members if m.get("user_type")})
        search_queries = list({m["likely_search_query"] for m in members if m.get("likely_search_query")})
        workarounds = list({m["current_workaround"] for m in members if m.get("current_workaround")})

        rows.append({
            "cluster_id": c["id"],
            "name": c["name"],
            "score": round(composite_score, 4),
            "members": n,
            "distinct_authors": c.get("distinct_authors", n),
            "distinct_sources": ",".join(c.get("distinct_sources", [])),
            "avg_pain": c.get("avg_pain", 3.0),
            "recurrence_pct": round(recurrence_factor * 100, 1),
            "growth": round(growth_factor, 3),
            "gap_score": round(gap_factor, 3),
            "top_user_types": "; ".join(user_types[:3]),
            "search_queries": "; ".join(search_queries[:5]),
            "top_workarounds": "; ".join(workarounds[:3]),
        })

    if not rows:
        print("No clusters to score.")
        return

    df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    SCORED_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(SCORED_PATH, index=False)

    print(f"\n{'='*70}")
    print(f"STAGE 4 SCORED CLUSTERS ({len(df)} scored)")
    print(f"{'='*70}")
    print(df[["cluster_id", "name", "score", "members", "avg_pain", "recurrence_pct"]].to_string())
    print(f"\nOutput written to: {SCORED_PATH}")

if __name__ == "__main__":
    main()
