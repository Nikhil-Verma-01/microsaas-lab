"""Generate micro-SaaS / free-tool opportunities for top clusters (Stage 6).

  python -m src.ideate [--top-n 20]

Reads:  data/validated.csv  +  data/problems.jsonl  +  data/clusters.json
Writes: data/report.md  +  data/report.csv
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
from openai import OpenAI
from tqdm import tqdm

from .config import (
    CLUSTERS_PATH,
    IDEATE_CACHE_DIR,
    IDEATE_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    PROBLEMS_PATH,
    REPORT_CSV_PATH,
    REPORT_MD_PATH,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)
VALIDATED_PATH = REPORT_MD_PATH.parent / "validated.csv"

IDEATE_SYSTEM = """\
You are an expert micro-SaaS and web utility opportunity strategist for an indie developer.
The developer wants to discover viable, high-quality ideas:
1. Free web utilities (converters, calculators, formatters, checkers, visualizers, diff tools) monetized by Google AdSense and global organic search traffic.
2. Lightweight paid micro-SaaS tools (recurring workflow automation for freelancers, solopreneurs, content creators, office workers, and small teams).

Given a validated problem cluster with real user evidence:
- Generate ONE concrete, high-potential micro-SaaS or free tool opportunity.
- REJECT all generic AI-wrapper clichés (e.g., 'AI email assistant', 'AI meeting notes generator', 'AI resume writer').
- REJECT ideas requiring massive infrastructure, proprietary datasets, enterprise sales, or network effects.
- Focus on utilities that can be built by a solo developer in 1-2 weeks.

Output a valid JSON object matching these exact keys:
{
  "opportunity_name": (string) snappy, memorable product or tool name,
  "problem_summary": (string) 1-2 sentences summarizing the core recurring pain,
  "why_exists": (string) why existing tools or native features fail to solve this,
  "current_workaround": (string) how developers currently cope,
  "existing_products": (list of strings) existing commercial or open-source solutions,
  "gap": (string) what is missing in the current ecosystem,
  "mvp_description": (string) concrete 1-2 week MVP scope for a solo builder,
  "build_complexity": (string: "low" | "medium" | "high"),
  "target_user": (string) specific target audience,
  "monetization": (string) AdSense search-traffic model, freemium tier, or micro-subscription,
  "content_ideas": (list of strings) 2-4 search-optimized article/guide titles for traffic,
  "paid_saas_score": (integer 1-10) commercial pain and willingness to pay,
  "adsense_score": (integer 1-10) search demand and utility traffic potential,
  "confidence_pct": (integer 0-100) confidence in the opportunity
}
"""

def ideate_cluster(
    cluster: dict,
    problems: list[dict],
    val_row: dict,
    client: OpenAI,
) -> dict | None:
    cid = cluster["id"]
    cache_path = IDEATE_CACHE_DIR / f"cluster_{cid}.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    evidence_lines = []
    for p in problems[:8]:
        quote = p.get("evidence_quote", "").replace("\n", " ")
        evidence_lines.append(f"- [{p.get('user_type', 'user')}] \"{quote}\" (Pain: {p.get('pain_level', 3)}/5)")

    evidence_text = "\n".join(evidence_lines)
    search_queries = val_row.get("search_queries", "")
    existing_tools = val_row.get("brave_top_results", "None identified")
    workarounds = val_row.get("top_workarounds", "Manual scripts")

    user_msg = f"""
Cluster: {cluster['name']}
Member count: {cluster['member_count']} evidence records
Sources: {', '.join(cluster.get('distinct_sources', []))}
Target personas: {', '.join(cluster.get('user_types', [])[:3])}
Current workarounds: {workarounds}
Target search queries: {search_queries}
Existing tools found: {existing_tools}

Verbatim evidence quotes:
{evidence_text}
"""
    for attempt in range(3):
        try:
            resp = client.chat.completions.create(
                model=IDEATE_MODEL,
                messages=[
                    {"role": "system", "content": IDEATE_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            raw = resp.choices[0].message.content or "{}"
            result = json.loads(raw)
            cache_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
            return result
        except Exception as exc:
            log.warning("Ideation attempt %d failed for cluster %s: %s", attempt, cid, exc)
    return None

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--top-n", type=int, default=20)
    args = ap.parse_args()

    if not VALIDATED_PATH.exists():
        print(f"Error: {VALIDATED_PATH} not found. Run validate first.")
        return

    val_df = pd.read_csv(VALIDATED_PATH).head(args.top_n)
    clusters_data = json.loads(CLUSTERS_PATH.read_text(encoding="utf-8"))
    clusters_by_id = {c["id"]: c for c in clusters_data.get("clusters", [])}

    probs_by_id = {}
    for line in PROBLEMS_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                p = json.loads(line)
                probs_by_id[p["doc_id"]] = p
            except Exception:
                pass

    client_kwargs = {"api_key": LLM_API_KEY}
    if LLM_BASE_URL:
        client_kwargs["base_url"] = LLM_BASE_URL
    oai_client = OpenAI(**client_kwargs)

    report_rows = []
    md_sections = [
        "# MicroSaaS Lab -- Ranked Opportunity Report\n\n",
        "Discovered from real developer pain points across GitHub and Hacker News.\n\n",
    ]

    for rank, (_, row) in enumerate(val_df.iterrows(), 1):
        cid = int(row["cluster_id"])
        cluster = clusters_by_id.get(cid)
        if not cluster:
            continue

        member_probs = [probs_by_id[m] for m in cluster["members"] if m in probs_by_id]
        idea = ideate_cluster(cluster, member_probs, row.to_dict(), oai_client)
        if not idea:
            continue

        name = idea.get("opportunity_name", cluster["name"])
        paid_score = idea.get("paid_saas_score", "N/A")
        adsense_score = idea.get("adsense_score", "N/A")
        conf = idea.get("confidence_pct", "N/A")
        complexity = idea.get("build_complexity", "medium")

        md_sections.append(f"""---
## #{rank}  {name}
**Problem Score:** {row['score']:.3f} | **Evidence:** {cluster['member_count']} records ({row.get('distinct_sources', '')}) | **Avg Pain:** {cluster.get('avg_pain', 3)}/5  
**Paid-SaaS Potential:** {paid_score}/10 | **AdSense Potential:** {adsense_score}/10 | **Confidence:** {conf}% | **Complexity:** {complexity.capitalize()}

### Problem & Gap
* **The Problem:** {idea.get('problem_summary', '')}
* **Why it Exists:** {idea.get('why_exists', '')}
* **Current Workaround:** {idea.get('current_workaround', '')}
* **Existing Products:** {', '.join(idea.get('existing_products', [])) or 'None cited'}
* **The Gap:** {idea.get('gap', '')}

### Solution & Execution
* **MVP Scope (1-2 Weeks):** {idea.get('mvp_description', '')}
* **Target Audience:** {idea.get('target_user', '')}
* **Monetization Angle:** {idea.get('monetization', '')}
* **SEO & Content Hooks:** {'; '.join(idea.get('content_ideas', []))}

### Evidence Signals
* **Top Search Queries:** `{row.get('search_queries', '')}`
* **Sample Quotes:**
""")
        for p in member_probs[:3]:
            quote = p.get("evidence_quote", "").replace("\n", " ")
            md_sections.append(f"  > \"{quote}\" -- *({p.get('user_type', 'user')})*\n")

        report_rows.append({
            "rank": rank,
            "opportunity_name": name,
            "problem_score": row["score"],
            "evidence_count": cluster["member_count"],
            "avg_pain": cluster.get("avg_pain", 3),
            "paid_saas_score": paid_score,
            "adsense_score": adsense_score,
            "confidence_pct": conf,
            "build_complexity": complexity,
            "target_user": idea.get("target_user", ""),
            "mvp": idea.get("mvp_description", "")[:200],
            "search_queries": row.get("search_queries", "")[:200],
        })
        print(f"#{rank} Ideated: {name} (Paid: {paid_score}/10, AdSense: {adsense_score}/10)")

    REPORT_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD_PATH.write_text("".join(md_sections), encoding="utf-8")
    pd.DataFrame(report_rows).to_csv(REPORT_CSV_PATH, index=False)

    print(f"\nReport markdown written to : {REPORT_MD_PATH}")
    print(f"Report summary CSV written to: {REPORT_CSV_PATH}")

if __name__ == "__main__":
    main()
