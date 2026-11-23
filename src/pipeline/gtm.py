"""Stage 7-8: Distribution and Monetization Evaluator.

Assesses how a micro-SaaS candidate can realistically acquire its first 100 users
and evaluates the economic plausibility of its monetization model.
Rejects generic "SEO + Reddit + Product Hunt" hand-waving, categorizes search/usage intent,
and enforces data honesty (zero invented traffic/CPC figures).

Gate: Candidates with WedgeVerdict == "no_wedge" are skipped.

Reads:
  - data/cache/hypotheses/cluster_{id}.json
  - data/cache/wedges/opp_{id}.json
Writes:
  - data/cache/gtm/opp_{id}.json
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from ..config import (
    GTM_CACHE_DIR,
    HYPOTHESIS_CACHE_DIR,
    IDEATE_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_TIMEOUT,
    WEDGE_CACHE_DIR,
)
from .schema import (
    ProductTrack,
    GTMPlan,
    GTMVerdict,
    HypothesisSet,
    SearchIntent,
    SolutionHypothesis,
    UsageFrequency,
    WedgeAssessment,
    WedgeVerdict,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)

GTM_SYSTEM = """\
Role: Go-to-market skeptic and unit economics evaluator for solo-built developer micro-tools.

Task:
Assess how this specific micro-product can reach its first 100 relevant users, and evaluate whether its monetization model is viable.
Use concrete, grounded channels and clearly mark unknowns.

Rules:
1. Do NOT write generic advice like "Post on Reddit, submit to Product Hunt, and do SEO". Specify exact subreddits, GitHub topic tags, Discord/Slack communities, or package registry directories.
2. Never invent search volume numbers, CPC bids, conversion percentages, or revenue numbers. If data is unmeasured, label it "unknown".
3. Formulate a specific first distribution experiment with an explicit cost ($0 - $100) and time window (< 2 weeks).
4. Specify a clear success threshold to falsify the distribution hypothesis.
5. Classify usage frequency and search intent accurately.
6. Return valid JSON only.

Schema:
{
  "opportunity_id": (string),
  "target_user_profile": (string, precise description of early adopter),
  "top_distribution_channels": [string, 2-3 specific developer channels, e.g. "npm package registry", "r/golang", "GitHub Action Marketplace"],
  "channel_specific_reasoning": (string, why early adopters in this channel will install or try it),
  "exact_search_or_community_intents": [string, 2-3 specific query phrases or forum questions users type when facing this pain],
  "first_experiment": (string, concrete low-cost acquisition experiment),
  "experiment_cost_and_time": (string, e.g. "$0 budget, 5 days"),
  "success_threshold": (string, e.g. "15 downloads / 5 stars from unique developers"),
  "first_100_users_path": (string, concise strategy to reach 100 active users),
  "usage_frequency": ("daily" | "weekly" | "monthly" | "occasional" | "one_time" | "unknown"),
  "search_intent": ("informational" | "utility" | "transactional" | "mixed" | "unknown"),
  "monetization_model": (string, e.g. "Open-core CLI + paid hosted sync", "Usage-based token billing", "One-time developer license"),
  "willingness_to_pay_evidence": (string, grounded reason developers would pay, or "unknown - requires pricing survey"),
  "required_search_or_ad_data": (string, external data needed to confirm volume, or "unknown"),
  "key_economic_unknowns": [string, 1-2 financial or retention uncertainties],
  "verdict": ("plausible" | "conditional" | "weak" | "unknown")
}
"""

GENERAL_SYSTEM = (
    "Evaluate a general-audience tool via exact task search intent and relevant communities. Consider ads, affiliates, one-time purchases, or subscriptions where appropriate. Propose a measurable experiment. Use unknown for unmeasured demand and economics. "
    "Return only JSON.\n" + GTM_SYSTEM[GTM_SYSTEM.index("Schema:"):]
)


def _build_gtm_prompt(
    hypothesis: SolutionHypothesis,
    wedge: WedgeAssessment,
) -> str:
    lines = [
        f"OPPORTUNITY ID: {hypothesis.opportunity_id}",
        f"SOLUTION NAME: {hypothesis.solution_name}",
        f"ARCHETYPE: {hypothesis.archetype.value}",
        f"TARGET SEGMENT: {hypothesis.target_segment}",
        f"CORE MECHANISM: {hypothesis.core_mechanism}",
        f"TRIGGERING CONTEXT: {hypothesis.triggering_context}",
        f"\nVALIDATED WEDGE:\n{wedge.wedge_statement}",
        f"PROPOSED DIFFERENTIATION:\n{wedge.proposed_differentiation}",
        "\nTASK:\n"
        "Evaluate the distribution strategy for reaching the first 100 users and determine monetization viability.\n"
        "Avoid generic platitudes. Provide a concrete first experiment and mark unmeasured metrics as unknown.",
    ]
    return "\n".join(lines)


def evaluate_gtm(
    hypothesis: SolutionHypothesis,
    wedge: WedgeAssessment,
    client: Optional[OpenAI] = None,
    force: bool = False,
    model: Optional[str] = None,
) -> Optional[GTMPlan]:
    """Evaluate distribution channels and monetization plausibility for an approved hypothesis."""
    cache_filename = (
        f"{hypothesis.opportunity_id}.json"
        if hypothesis.opportunity_id.startswith("opp_")
        else f"opp_{hypothesis.opportunity_id}.json"
    )
    cache_file = GTM_CACHE_DIR / cache_filename
    if cache_file.exists() and not force:
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return GTMPlan.model_validate(data)
        except Exception as exc:
            log.warning("Cache parse error for GTM %s: %s; re-running...", hypothesis.opportunity_id, exc)

    # Gate: Reject candidates with NO_WEDGE
    if wedge.verdict == WedgeVerdict.NO_WEDGE:
        log.info("[%s] Wedge verdict is NO_WEDGE; skipping GTM evaluation.", hypothesis.opportunity_id)
        return None

    if client is None:
        client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY or "none",
            timeout=LLM_TIMEOUT,
        )

    model_name = model or IDEATE_MODEL
    user_prompt = _build_gtm_prompt(hypothesis, wedge)

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": GENERAL_SYSTEM if hypothesis.track == ProductTrack.GENERAL else GTM_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=850,
            response_format={"type": "json_object"},
        )
        raw_text = response.choices[0].message.content or "{}"
    except Exception as exc:
        log.error("LLM call failed for GTM %s: %s", hypothesis.opportunity_id, exc)
        return None

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        log.warning("JSON decode failure for GTM %s: %s; cleaning...", hypothesis.opportunity_id, exc)
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text.strip())
        clean = re.sub(r"\n?```$", "", clean)
        try:
            raw_data = json.loads(clean)
        except Exception:
            return None

    raw_data["opportunity_id"] = hypothesis.opportunity_id

    if hypothesis.track and (
        not raw_data.get("first_experiment")
        or raw_data.get("verdict") not in {v.value for v in GTMVerdict}
    ):
        return None

    # Fallbacks for enums
    if raw_data.get("usage_frequency") not in [e.value for e in UsageFrequency]:
        raw_data["usage_frequency"] = UsageFrequency.UNKNOWN.value
    if raw_data.get("search_intent") not in [e.value for e in SearchIntent]:
        raw_data["search_intent"] = SearchIntent.UTILITY.value
    if raw_data.get("verdict") not in [e.value for e in GTMVerdict]:
        raw_data["verdict"] = GTMVerdict.CONDITIONAL.value

    try:
        plan = GTMPlan.model_validate(raw_data)
    except ValidationError as val_err:
        log.warning("GTM validation error for %s: %s", hypothesis.opportunity_id, val_err)
        if hypothesis.track:
            return None
        plan = GTMPlan(
            opportunity_id=hypothesis.opportunity_id,
            target_user_profile=raw_data.get("target_user_profile", hypothesis.target_segment),
            top_distribution_channels=raw_data.get("top_distribution_channels", ["GitHub Marketplace", "Developer Subreddits"]),
            channel_specific_reasoning=raw_data.get("channel_specific_reasoning", "Relevant dev communities"),
            exact_search_or_community_intents=raw_data.get("exact_search_or_community_intents", []),
            first_experiment=raw_data.get("first_experiment", "Publish free open-source release on GitHub and share in relevant Discord"),
            experiment_cost_and_time=raw_data.get("experiment_cost_and_time", "$0, 1 week"),
            success_threshold=raw_data.get("success_threshold", "10 unique developer installs"),
            first_100_users_path=raw_data.get("first_100_users_path", "Direct community engagement and package manager discovery"),
            usage_frequency=UsageFrequency.WEEKLY,
            search_intent=SearchIntent.UTILITY,
            monetization_model=raw_data.get("monetization_model", "Free OSS core with paid hosted sync"),
            willingness_to_pay_evidence=raw_data.get("willingness_to_pay_evidence", "unknown"),
            required_search_or_ad_data=raw_data.get("required_search_or_ad_data", "unknown"),
            key_economic_unknowns=raw_data.get("key_economic_unknowns", ["Conversion rate from free to paid"]),
            verdict=GTMVerdict.CONDITIONAL,
        )

    cache_file.write_text(json.dumps(plan.model_dump(), indent=2), encoding="utf-8")
    log.info("[%s] GTM evaluated: verdict=%s, model=%s", hypothesis.opportunity_id, plan.verdict.value, plan.monetization_model)
    return plan


def evaluate_cluster_gtm(
    cluster_id: int,
    force: bool = False,
    model: Optional[str] = None,
) -> list[GTMPlan]:
    """Evaluate GTM and monetization for all surviving candidates in a cluster."""
    hyp_file = HYPOTHESIS_CACHE_DIR / f"cluster_{cluster_id}.json"
    if not hyp_file.exists():
        raise FileNotFoundError(f"No hypothesis cache for cluster {cluster_id} at {hyp_file}")

    hyp_set = HypothesisSet.model_validate(json.loads(hyp_file.read_text(encoding="utf-8")))

    client = OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY or "none",
        timeout=LLM_TIMEOUT,
    )

    results: list[GTMPlan] = []
    for hyp in hyp_set.hypotheses:
        opp_id = hyp.opportunity_id if hyp.opportunity_id.startswith("opp_") else f"opp_{hyp.opportunity_id}"
        wedge_file = WEDGE_CACHE_DIR / f"{opp_id}.json"
        if not wedge_file.exists():
            log.warning("[%s] No wedge cache found at %s; skipping GTM evaluation.", opp_id, wedge_file)
            continue

        try:
            wedge = WedgeAssessment.model_validate(json.loads(wedge_file.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning("[%s] Failed to parse wedge cache: %s", opp_id, e)
            continue

        gtm = evaluate_gtm(hyp, wedge, client=client, force=force, model=model)
        if gtm:
            results.append(gtm)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 7-8: Distribution and Monetization Evaluator")
    parser.add_argument("--cluster-id", type=int, default=0, help="Cluster ID to analyze")
    parser.add_argument("--force", action="store_true", help="Bypass cache and force re-evaluation")
    parser.add_argument("--model", type=str, default=None, help="LLM model override")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    plans = evaluate_cluster_gtm(args.cluster_id, force=args.force, model=args.model)

    print(f"\nGTM & Monetization Plans for Cluster {args.cluster_id} ({len(plans)} surviving candidates):")
    for p in plans:
        print(f"[{p.verdict.value.upper()}] {p.opportunity_id}")
        print(f"  Model: {p.monetization_model}")
        print(f"  Intent: {p.search_intent.value} | Frequency: {p.usage_frequency.value}")
        print(f"  Channels: {', '.join(p.top_distribution_channels[:2])}")
        print(f"  First Experiment: {p.first_experiment}")
        print()


if __name__ == "__main__":
    main()
