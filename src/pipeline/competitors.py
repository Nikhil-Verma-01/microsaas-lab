"""Stage 3: Competitive Intelligence & Alternative Discovery.

Discovers real existing alternatives (commercial products, OSS libraries, native platform features)
using zero-cost DuckDuckGo search (or optional Brave search), structured into verified CompetitorRecord models.

Reads:  data/cache/hypotheses/cluster_{id}.json
Writes: data/cache/competitors/opp_{id}.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from ..config import (
    BRAVE_API_KEY,
    CLUSTERS_PATH,
    COMPETITOR_CACHE_DIR,
    HYPOTHESIS_CACHE_DIR,
    IDEATE_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_TIMEOUT,
    USER_AGENT,
)
from .schema import (
    ProductTrack,
    AlternativeType,
    CompetitorRecord,
    CompetitorResearch,
    HypothesisSet,
    SolutionHypothesis,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)

COMPETITOR_SYSTEM = """\
You are an expert competitive intelligence analyst for developer tools and micro-SaaS.
Your goal is to identify and structure 2 to 4 concrete, existing alternatives to the proposed product hypothesis.

Include:
- Direct commercial tools / SaaS
- Open-source projects / GitHub repositories / npm packages
- Free online utilities
- Native features in existing platforms (e.g. GitHub, VS Code, Postman, Swagger)
- Common manual workarounds

CRITICAL RULES:
1. Grounded URLs: If tools are present in the search results, attach their URLs and mark confidence_basis="verified_search".
2. Knowledge Fallback: If search hits are sparse or empty, you MUST still identify 2 to 3 well-known real open-source libraries or tools from your knowledge base (e.g. Stoplight Prism, Swagger UI, swagger-ui-express, tsoa, MockServer) and mark confidence_basis="llm_memory".
3. NEVER return an empty alternatives list unless NO software whatsoever exists in this domain.
4. Do NOT fabricate fake product names. Cite real, recognizable tools.
5. Feature overlap must be one of: "low", "medium", "high", "unknown".
6. Alternative type must be one of: "direct_commercial", "open_source", "free_utility", "native_platform", "general_purpose", "manual_workaround".

Return a valid JSON object matching this schema:
{
  "opportunity_id": (string),
  "cluster_id": (integer),
  "alternatives": [
    {
      "opportunity_id": (string),
      "name": (string, tool name),
      "url": (string, URL or repository link),
      "alternative_type": (one of the valid types above),
      "target_user": (string),
      "supported_workflow": (string),
      "feature_overlap": ("low" | "medium" | "high" | "unknown"),
      "pricing_status": ("free" | "paid" | "open_source" | "bundled" | "unknown"),
      "strengths": [string],
      "limitations": [string],
      "confidence_basis": ("verified_search" | "llm_memory" | "unknown")
    }
  ],
  "search_queries_used": [string],
  "likely_saturation": ("low" | "medium" | "high" | "unknown"),
  "strongest_existing_substitute": (string),
  "what_remains_unverified": [string],
  "search_provider": ("duckduckgo" | "brave" | "llm_only")
}
"""

GENERAL_SYSTEM = (
    "Research alternatives for the exact general-audience workflow: web tools, native app features, templates, and manual workarounds. Return an empty list if no alternatives can be grounded. "
    "Return only JSON.\n" + COMPETITOR_SYSTEM[COMPETITOR_SYSTEM.index("Return a valid JSON object"):]
)


def build_search_queries(hypothesis: SolutionHypothesis) -> list[str]:
    """Build 3 distinct query variants to discover commercial, OSS, and native alternatives."""
    queries = []
    
    # 1. Use high-intent search queries provided in the hypothesis
    for q in hypothesis.search_queries:
        clean_q = q.strip()
        if clean_q and len(clean_q.split()) >= 2:
            queries.append(clean_q)
            if len(queries) >= 2:
                break

    if hypothesis.track == ProductTrack.GENERAL:
        task = hypothesis.triggering_context.strip() or hypothesis.core_mechanism.strip()
        queries.extend([f"{task} online tool", f"{task} alternative"])
        return list(dict.fromkeys(queries))[:3]

    # 2. Add an open-source GitHub query focused on the core task/tools
    terms = [
        w for w in (hypothesis.target_segment + " " + hypothesis.core_mechanism).split()
        if len(w) > 3 and w.lower() not in {"using", "with", "when", "that", "this", "from", "into", "their", "developer", "developers"}
    ]
    core_terms = " ".join(terms[:3])
    if core_terms:
        queries.append(f"{core_terms} github")

    # 3. Add an alternative/tool query if under 3
    if len(queries) < 3:
        queries.append(f"{hypothesis.solution_name} alternative open source tool")

    # Deduplicate while preserving order
    seen = set()
    deduped = []
    for q in queries:
        clean = q.strip()
        if clean and clean.lower() not in seen:
            seen.add(clean.lower())
            deduped.append(clean)

    return deduped[:3]


def search_duckduckgo(query: str, max_results: int = 4) -> list[dict]:
    """Execute zero-cost web search using ddgs (DuckDuckGo Search)."""
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            from duckduckgo_search import DDGS  # fallback import

        results = []
        with DDGS() as ddgs:
            raw_hits = list(ddgs.text(query, max_results=max_results))
            for h in raw_hits:
                results.append({
                    "title": h.get("title", ""),
                    "url": h.get("href", ""),
                    "snippet": h.get("body", ""),
                })
        return results
    except Exception as exc:
        log.warning("DuckDuckGo search error for query %r: %s", query, exc)
        return []


def search_brave(query: str, max_results: int = 4) -> list[dict]:
    """Fallback search using Brave Search API if configured."""
    if not BRAVE_API_KEY:
        return []
    import httpx
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": BRAVE_API_KEY,
    }
    url = "https://api.search.brave.com/res/v1/web/search"
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10.0) as client:
            resp = client.get(url, params={"q": query, "count": max_results}, headers=headers)
            if resp.status_code == 200:
                raw_results = resp.json().get("web", {}).get("results", [])
                return [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "snippet": r.get("description", ""),
                    }
                    for r in raw_results
                ]
    except Exception as exc:
        log.warning("Brave search error for query %r: %s", query, exc)
    return []


def search_alternatives(queries: list[str]) -> tuple[list[dict], str]:
    """Perform searches across multiple queries and return deduplicated hits and provider."""
    all_hits = []
    seen_urls = set()
    provider = "duckduckgo"

    for q in queries:
        if BRAVE_API_KEY:
            hits = search_brave(q, max_results=3)
            provider = "brave"
        else:
            hits = search_duckduckgo(q, max_results=3)
            provider = "duckduckgo"

        for h in hits:
            url = h.get("url", "").strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                all_hits.append(h)
        time.sleep(0.5)  # polite rate-pacing

    if not all_hits:
        provider = "llm_only"

    return all_hits, provider


def research_competitors_for_hypothesis(
    hypothesis: SolutionHypothesis,
    client: OpenAI,
    force: bool = False,
    model: Optional[str] = None,
) -> Optional[CompetitorResearch]:
    cache_filename = f"{hypothesis.opportunity_id}.json" if hypothesis.opportunity_id.startswith("opp_") else f"opp_{hypothesis.opportunity_id}.json"
    cache_file = COMPETITOR_CACHE_DIR / cache_filename
    if cache_file.exists() and not force:
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return CompetitorResearch.model_validate(data)
        except Exception as exc:
            log.warning("Cache parse error for opp %s: %s; re-running...", hypothesis.opportunity_id, exc)

    queries = build_search_queries(hypothesis)
    raw_hits, provider = search_alternatives(queries)

    hits_text = ""
    if raw_hits:
        lines = []
        for idx, h in enumerate(raw_hits[:8], 1):
            lines.append(f"{idx}. Title: {h['title']}\n   URL: {h['url']}\n   Snippet: {h['snippet']}")
        hits_text = "\n\n".join(lines)
    elif hypothesis.track == ProductTrack.GENERAL:
        hits_text = "No live search results available. Leave alternatives empty."
    else:
        hits_text = "No live web search hits found. Identify well-known alternatives from model memory and mark confidence_basis='llm_memory'."

    user_msg = f"""
Solution Hypothesis: {hypothesis.solution_name} (ID: {hypothesis.opportunity_id})
Archetype: {hypothesis.archetype.value}
Target Segment: {hypothesis.target_segment}
Triggering Context: {hypothesis.triggering_context}
Replaced Workaround: {hypothesis.replaced_workaround}
Core Mechanism: {hypothesis.core_mechanism}
Why Incumbent Fails: {hypothesis.why_incumbent_fails}

Search Queries Run:
{json.dumps(queries, indent=2)}

Live Web Search Results ({provider}):
{hits_text}

Identify existing alternatives to this hypothesis. Ground findings in the search URLs where available.
Return valid JSON only.
"""

    target_model = model or IDEATE_MODEL
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": GENERAL_SYSTEM if hypothesis.track == ProductTrack.GENERAL else COMPETITOR_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=900,
            )
            raw = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw)
            parsed["opportunity_id"] = hypothesis.opportunity_id
            parsed["cluster_id"] = hypothesis.cluster_id
            parsed["search_provider"] = provider
            parsed["search_queries_used"] = queries

            hit_urls = {h["url"].rstrip("/") for h in raw_hits}
            # Search provenance only covers links present in retrieved results.
            for alt in parsed.get("alternatives", []):
                alt["opportunity_id"] = hypothesis.opportunity_id
                if alt.get("confidence_basis", "verified_search") == "verified_search" and (alt.get("url") or "").rstrip("/") not in hit_urls:
                    alt["confidence_basis"] = "unknown"

            research = CompetitorResearch.model_validate(parsed)
            cache_file.write_text(json.dumps(research.model_dump(), indent=2), encoding="utf-8")
            return research
        except ValidationError as val_err:
            log.warning("Validation error on opp %s attempt %d: %s", hypothesis.opportunity_id, attempt, val_err)
        except Exception as exc:
            log.warning("LLM call failed for opp %s attempt %d: %s", hypothesis.opportunity_id, attempt, exc)

    return None


def research_competitors_for_cluster(
    cluster_id: int,
    client: OpenAI,
    force: bool = False,
) -> dict[str, CompetitorResearch]:
    """Research competitors for all hypotheses in a cluster."""
    hyp_cache = HYPOTHESIS_CACHE_DIR / f"cluster_{cluster_id}.json"
    if not hyp_cache.exists():
        log.warning("No hypothesis cache found for cluster %s. Run hypothesize first.", cluster_id)
        return {}

    hyp_set = HypothesisSet.model_validate(json.loads(hyp_cache.read_text(encoding="utf-8")))
    results = {}
    for hyp in hyp_set.hypotheses:
        res = research_competitors_for_hypothesis(hyp, client, force=force)
        if res:
            results[hyp.opportunity_id] = res
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cluster-id", type=int, default=0, help="Cluster ID to research")
    ap.add_argument("--force", action="store_true", help="Bypass cache and force re-search")
    args = ap.parse_args()

    client_kwargs = {"api_key": LLM_API_KEY, "timeout": LLM_TIMEOUT}
    if LLM_BASE_URL:
        client_kwargs["base_url"] = LLM_BASE_URL
    client = OpenAI(**client_kwargs)

    print(f"\n=== Stage 3: Competitor Research for Cluster #{args.cluster_id} ===\n")
    results = research_competitors_for_cluster(args.cluster_id, client, force=args.force)

    if not results:
        print("No competitor research generated.")
        return

    for opp_id, r in results.items():
        print(f"\n--- Opportunity: {opp_id} (Provider: {r.search_provider}, Saturation: {r.likely_saturation}) ---")
        print(f"Strongest Substitute: {r.strongest_existing_substitute}")
        print(f"Discovered Alternatives ({len(r.alternatives)}):")
        for alt in r.alternatives:
            print(f"  * [{alt.alternative_type.value}] {alt.name} ({alt.url or 'no URL'})")
            print(f"    Overlap: {alt.feature_overlap} | Pricing: {alt.pricing_status}")
            if alt.strengths:
                print(f"    Strengths: {', '.join(alt.strengths[:2])}")
            if alt.limitations:
                print(f"    Limitations: {', '.join(alt.limitations[:2])}")


if __name__ == "__main__":
    main()
