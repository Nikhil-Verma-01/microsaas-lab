"""Check existing tools via Brave Search API for top clusters (Stage 5).

  python -m src.validate [--top-n 25]

Reads:  data/scored.csv
Writes: data/validated.csv  (adds: brave_top_results, brave_top_urls, existing_tools_found, adsense_opportunity)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time

import httpx
import pandas as pd

from .config import BRAVE_API_KEY, SCORED_PATH, USER_AGENT

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
VALIDATED_PATH = SCORED_PATH.parent / "validated.csv"

def brave_search(query: str, client: httpx.Client, count: int = 5) -> list[dict]:
    if BRAVE_API_KEY:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_API_KEY,
        }
        try:
            r = client.get(BRAVE_URL, params={"q": query, "count": count}, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json().get("web", {}).get("results", [])
            log.warning("Brave search returned status %s for query %r: %s", r.status_code, query, r.text[:100])
        except Exception as exc:
            log.error("Brave search error: %s", exc)

    # Zero-cost fallback search using Scrapling / search_engine_urls
    try:
        from .collect_general import search_engine_urls
        hits = search_engine_urls(query, max_results=count)
        return [{"title": h["title"], "url": h["url"], "description": h["snippet"]} for h in hits]
    except Exception as exc:
        log.debug("Search fallback error: %s", exc)
        return []

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top-n", type=int, default=25)
    args = ap.parse_args()

    if not SCORED_PATH.exists():
        print(f"Error: {SCORED_PATH} does not exist. Run score first.")
        return

    df = pd.read_csv(SCORED_PATH).head(args.top_n)
    if df.empty:
        print("No scored clusters found.")
        return

    has_key = bool(BRAVE_API_KEY)
    if not has_key:
        print("Note: BRAVE_API_KEY not configured in .env yet. Existing-tool validation will use placeholder defaults.")

    results = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for _, row in df.iterrows():
            queries = [q.strip() for q in str(row.get("search_queries", "")).split(";") if q.strip()][:2]
            all_hits = []
            
            if has_key:
                for q in queries:
                    hits = brave_search(f"{q} tool online free", client)
                    all_hits.extend(hits)
                    time.sleep(1.1)  # Brave free tier rate pacing (1 query/sec)

            tool_names = [h.get("title", "") for h in all_hits[:5]]
            tool_urls = [h.get("url", "") for h in all_hits[:5]]

            existing_count = len(all_hits)
            if has_key:
                adsense_opp = "high" if existing_count < 3 else "medium" if existing_count < 6 else "low"
            else:
                adsense_opp = "medium"

            results.append({
                **row.to_dict(),
                "brave_top_results": "; ".join(tool_names) if tool_names else "Pending validation",
                "brave_top_urls": "; ".join(tool_urls) if tool_urls else "",
                "existing_tools_found": existing_count,
                "adsense_opportunity": adsense_opp,
            })
            if has_key:
                log.info("Checked %s: %d existing tools identified", row["name"], existing_count)

    out = pd.DataFrame(results).sort_values("score", ascending=False)
    VALIDATED_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(VALIDATED_PATH, index=False)

    print(f"\n{'='*70}")
    print(f"STAGE 5 VALIDATED CLUSTERS ({len(out)} rows)")
    print(f"{'='*70}")
    print(out[["cluster_id", "name", "score", "existing_tools_found", "adsense_opportunity"]].to_string())
    print(f"\nOutput written to: {VALIDATED_PATH}")

if __name__ == "__main__":
    main()
