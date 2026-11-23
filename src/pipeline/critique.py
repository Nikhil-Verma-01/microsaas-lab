"""Stage 4: Adversarial Hostile Solution Critic.

An adversarial reviewer that attempts to disprove the viability of each solution hypothesis
using the discovered competitor research and workflow friction as evidence.

Reads:  data/cache/hypotheses/cluster_{id}.json + data/cache/competitors/opp_{id}.json
Writes: data/cache/critiques/opp_{id}.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from openai import OpenAI
from pydantic import ValidationError

from ..config import (
    COMPETITOR_CACHE_DIR,
    CRITIQUE_CACHE_DIR,
    HYPOTHESIS_CACHE_DIR,
    IDEATE_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_TIMEOUT,
)
from .schema import (
    ProductTrack,
    CompetitorResearch,
    CritiqueVerdict,
    HostileCritique,
    HypothesisSet,
    SolutionHypothesis,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)

CRITIQUE_SYSTEM = """\
Role: Independent, skeptical product reviewer and adversarial critic.

Task:
Try to disprove the viability of the supplied product hypothesis.
Do NOT improve the pitch or protect the idea.
Use the supplied solution architecture, target segment, and discovered competitor alternatives to attack the proposal.

Evaluate these fatal flaw categories:
1. EXISTING SUBSTITUTES & OSS: Does an existing free tool, native feature, or open-source repo already solve this well enough?
2. INCUMBENT ABSORPTION: Can an incumbent (GitHub, VS Code, Postman, Cursor) add this capability with a minor release?
3. WORKFLOW INERTIA: Does adopting this require changing an entrenched developer habit or breaking CI workflows?
4. WILLINGNESS TO PAY: Is there zero commercial budget or willingness to pay for this specific utility?
5. AI COMMODITIZATION: Can a developer achieve this exact outcome with a 1-shot prompt in ChatGPT/Claude?
6. HIDDEN COMPLEXITY: Is the MVP hiding major edge cases, maintenance burdens, or security/privacy risks?

Verdict guidelines:
- "survives": The concept has a genuine, defensible differentiation that existing tools and incumbents do not easily cover.
- "survives_with_conditions": The concept has fatal risks in its current framing, but could survive if narrowed to a specific condition or unserved niche.
- "needs_evidence": Cannot be judged without specific external proof (e.g. search volume data or user interviews).
- "reject": Dead on arrival; completely saturated by existing tools, trivial for incumbents to absorb, or zero willingness to adopt.

Return a valid JSON object matching this schema:
{
  "opportunity_id": (string),
  "strongest_reasons_to_reject": [string, list of 2-3 fatal objections],
  "unsupported_assumptions": [string, assumptions that lack proof],
  "evidence_that_contradicts": [string, existing tools/facts that contradict the idea],
  "likely_failure_modes": [string, 1-2 ways this tool will fail in the wild],
  "cheapest_test_to_disprove": (string, smallest 1-day experiment to falsify the idea),
  "additional_research_needed": [string],
  "incumbent_absorption_risk": ("low" | "medium" | "high"),
  "commoditization_risk": ("low" | "medium" | "high"),
  "workflow_friction_risk": ("low" | "medium" | "high"),
  "verdict": ("survives" | "survives_with_conditions" | "needs_evidence" | "reject")
}
"""

GENERAL_SYSTEM = (
    "Assess the general-audience workflow. Focus on free substitutes, discoverability, adoption friction, repeat visits, and maintenance. Use the business model appropriate to this utility. "
    "Return only JSON.\n" + CRITIQUE_SYSTEM[CRITIQUE_SYSTEM.index("Return a valid JSON object"):]
)


def critique_hypothesis(
    hypothesis: SolutionHypothesis,
    competitors: Optional[CompetitorResearch],
    client: OpenAI,
    force: bool = False,
    model: Optional[str] = None,
) -> Optional[HostileCritique]:
    cache_filename = f"{hypothesis.opportunity_id}.json" if hypothesis.opportunity_id.startswith("opp_") else f"opp_{hypothesis.opportunity_id}.json"
    cache_file = CRITIQUE_CACHE_DIR / cache_filename
    if cache_file.exists() and not force:
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return HostileCritique.model_validate(data)
        except Exception as exc:
            log.warning("Cache parse error for critique %s: %s; re-running...", hypothesis.opportunity_id, exc)

    comp_summary = "No competitor research provided."
    if competitors and competitors.alternatives:
        lines = []
        for alt in competitors.alternatives:
            lines.append(f"- {alt.name} ({alt.alternative_type.value}, overlap: {alt.feature_overlap}): {', '.join(alt.strengths or ['functional'])}")
        comp_summary = f"Strongest substitute: {competitors.strongest_existing_substitute}\nSaturation: {competitors.likely_saturation}\nDiscovered alternatives:\n" + "\n".join(lines)

    user_msg = f"""
CANDIDATE PRODUCT HYPOTHESIS:
Opportunity ID: {hypothesis.opportunity_id}
Solution Name: {hypothesis.solution_name}
Archetype: {hypothesis.archetype.value}
Target Segment: {hypothesis.target_segment}
Triggering Context: {hypothesis.triggering_context}
Replaced Workaround: {hypothesis.replaced_workaround}
Core Mechanism: {hypothesis.core_mechanism}
Why Creator Thinks Incumbents Fail: {hypothesis.why_incumbent_fails}
Assumptions: {json.dumps(hypothesis.key_assumptions)}

DISCOVERED COMPETITIVE LANDSCAPE:
{comp_summary}

ATTACK THIS PRODUCT HYPOTHESIS. Find credible reasons why it will fail.
Return valid JSON only matching the schema.
"""

    target_model = model or IDEATE_MODEL
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=target_model,
                messages=[
                    {"role": "system", "content": GENERAL_SYSTEM if hypothesis.track == ProductTrack.GENERAL else CRITIQUE_SYSTEM},
                    {"role": "user", "content": user_msg},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=850,
            )
            raw = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw)
            parsed["opportunity_id"] = hypothesis.opportunity_id

            critique = HostileCritique.model_validate(parsed)
            cache_file.write_text(json.dumps(critique.model_dump(), indent=2), encoding="utf-8")
            return critique
        except ValidationError as val_err:
            log.warning("Validation error on critique %s attempt %d: %s", hypothesis.opportunity_id, attempt, val_err)
        except Exception as exc:
            log.warning("LLM call failed for critique %s attempt %d: %s", hypothesis.opportunity_id, attempt, exc)

    return None


def critique_cluster(
    cluster_id: int,
    client: OpenAI,
    force: bool = False,
) -> dict[str, HostileCritique]:
    """Run hostile critique across all hypotheses in a cluster."""
    hyp_cache = HYPOTHESIS_CACHE_DIR / f"cluster_{cluster_id}.json"
    if not hyp_cache.exists():
        log.warning("No hypothesis cache found for cluster %s. Run hypothesize first.", cluster_id)
        return {}

    hyp_set = HypothesisSet.model_validate(json.loads(hyp_cache.read_text(encoding="utf-8")))
    results = {}

    for hyp in hyp_set.hypotheses:
        # Load competitor research if available
        comp_filename = f"{hyp.opportunity_id}.json" if hyp.opportunity_id.startswith("opp_") else f"opp_{hyp.opportunity_id}.json"
        comp_file = COMPETITOR_CACHE_DIR / comp_filename
        competitors = None
        if comp_file.exists():
            try:
                competitors = CompetitorResearch.model_validate(json.loads(comp_file.read_text(encoding="utf-8")))
            except Exception:
                pass

        res = critique_hypothesis(hyp, competitors, client, force=force)
        if res:
            results[hyp.opportunity_id] = res

    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cluster-id", type=int, default=0, help="Cluster ID to critique")
    ap.add_argument("--force", action="store_true", help="Bypass cache and force re-critique")
    args = ap.parse_args()

    client_kwargs = {"api_key": LLM_API_KEY, "timeout": LLM_TIMEOUT}
    if LLM_BASE_URL:
        client_kwargs["base_url"] = LLM_BASE_URL
    client = OpenAI(**client_kwargs)

    print(f"\n=== Stage 4: Hostile Critique for Cluster #{args.cluster_id} ===\n")
    results = critique_cluster(args.cluster_id, client, force=args.force)

    if not results:
        print("No critiques generated.")
        return

    for opp_id, c in results.items():
        print(f"\n--- Opportunity: {opp_id} | Verdict: [{c.verdict.value.upper()}] ---")
        print(f"Risks -> Incumbent: {c.incumbent_absorption_risk} | Commoditization: {c.commoditization_risk} | Friction: {c.workflow_friction_risk}")
        print("Strongest Objections:")
        for obj in c.strongest_reasons_to_reject:
            print(f"  * {obj}")
        print(f"Cheapest Test to Disprove: {c.cheapest_test_to_disprove}")


if __name__ == "__main__":
    main()
