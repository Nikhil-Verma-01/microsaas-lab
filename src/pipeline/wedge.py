"""Stage 5: Differentiated Wedge Finder and Validator.

Analyzes problem evidence, competitive research, and hostile critique to discover
and validate whether a defensible narrow wedge exists for each solution candidate.

Formula:
  For [specific user] who needs to [specific job] in [specific context],
  existing alternatives fail because [evidence-backed limitation].
  This product provides [specific advantage] without requiring [important source of friction].

Reads:
  - data/cache/hypotheses/cluster_{id}.json
  - data/cache/competitors/opp_{id}.json
  - data/cache/critiques/opp_{id}.json
Writes:
  - data/cache/wedges/opp_{id}.json
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
    COMPETITOR_CACHE_DIR,
    CRITIQUE_CACHE_DIR,
    HYPOTHESIS_CACHE_DIR,
    IDEATE_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_TIMEOUT,
    WEDGE_CACHE_DIR,
)
from .schema import (
    ProductTrack,
    CompetitorResearch,
    CritiqueVerdict,
    HostileCritique,
    HypothesisSet,
    SolutionHypothesis,
    WedgeAssessment,
    WedgeVerdict,
)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)

WEDGE_SYSTEM = """\
Role: Product positioning analyst and wedge discoverer.

Task:
Given a solution hypothesis, competitor research, and hostile critique, decide whether a defensible narrow wedge exists.
A wedge is NOT a generic claim such as "AI-powered", "simpler", "faster", or "better UX".
It is a specific unmet need for a defined segment in a specific workflow context.

You must formulate a clear wedge statement following this exact formula:
"For [target user] who needs to [specific job] in [specific context], existing alternatives fail because [limitation]. This product provides [specific advantage] without requiring [source of friction]."

Rules:
1. Do NOT use "AI-powered", "simpler", or "better UX" alone as differentiation.
2. If existing alternatives already cover the need, or if the hostile critic identified fatal incumbent/OSS coverage, mark verdict as "no_wedge".
3. A wedge must be specific to a concrete user, job, and context.
4. Return valid JSON only.

Schema:
{
  "opportunity_id": (string),
  "target_segment": (string, narrow specific user group),
  "specific_job": (string, exact workflow task),
  "context": (string, tooling environment or development trigger),
  "existing_alternative_failure": (string, concrete reason existing tools fall short),
  "evidence_for_gap": [string, 1-2 points of evidence or cited competitor limits],
  "proposed_differentiation": (string, structural advantage or non-obvious architecture),
  "why_not_just_a_feature_label": (string, why this is a real mechanism, not just buzzwords),
  "reason_incumbent_might_not_solve": (string, why Postman/GitHub/incumbents overlook this),
  "source_of_friction_avoided": (string, heavy setup, cloud vendor lock-in, manual config),
  "wedge_statement": (string, full canonical wedge sentence matching the formula),
  "wedge_confidence_basis": (string),
  "critical_unknowns": [string],
  "is_defensible": (boolean),
  "verdict": ("credible_wedge" | "possible_but_unproven" | "no_wedge"),
  "rejection_reason": (string or null)
}
"""

GENERAL_SYSTEM = (
    "Assess a general-audience utility and its exact user task. Compare with relevant free tools, native features and manual workarounds. "
    "Return only JSON.\n" + WEDGE_SYSTEM[WEDGE_SYSTEM.index("Schema:"):]
)


def _build_wedge_prompt(
    hypothesis: SolutionHypothesis,
    competitors: Optional[CompetitorResearch],
    critique: Optional[HostileCritique],
) -> str:
    lines = [
        f"OPPORTUNITY ID: {hypothesis.opportunity_id}",
        f"SOLUTION NAME: {hypothesis.solution_name}",
        f"ARCHETYPE: {hypothesis.archetype.value}",
        f"TARGET SEGMENT: {hypothesis.target_segment}",
        f"TRIGGERING CONTEXT: {hypothesis.triggering_context}",
        f"REPLACED WORKAROUND: {hypothesis.replaced_workaround}",
        f"CORE MECHANISM: {hypothesis.core_mechanism}",
        f"HYPOTHESIS WHY INCUMBENT FAILS: {hypothesis.why_incumbent_fails}",
    ]

    if competitors and competitors.alternatives:
        lines.append("\nDISCOVERED COMPETITORS & ALTERNATIVES:")
        for comp in competitors.alternatives[:4]:
            lines.append(
                f"- {comp.name} ({comp.alternative_type.value}, {comp.pricing_status}): "
                f"Overlap={comp.feature_overlap}. Limitations: {'; '.join(comp.limitations[:2]) if comp.limitations else 'None noted'}"
            )
        if competitors.strongest_existing_substitute:
            lines.append(f"STRONGEST EXISTING SUBSTITUTE: {competitors.strongest_existing_substitute}")

    if critique:
        lines.append(f"\nHOSTILE CRITIC VERDICT: {critique.verdict.value}")
        lines.append(f"CRITIC OBJECTIONS:\n- " + "\n- ".join(critique.strongest_reasons_to_reject[:3]))
        lines.append(f"INCUMBENT ABSORPTION RISK: {critique.incumbent_absorption_risk}")
        lines.append(f"COMMODITIZATION RISK: {critique.commoditization_risk}")
        lines.append(f"WORKFLOW FRICTION RISK: {critique.workflow_friction_risk}")

    lines.append(
        "\nTASK:\n"
        "Synthesize a defensible narrow wedge statement and verdict for this candidate.\n"
        "Remember: If incumbents or OSS already cover this workflow completely, return verdict='no_wedge'."
    )
    return "\n".join(lines)


def format_canonical_wedge(
    target_segment: str,
    specific_job: str,
    context: str,
    limitation: str,
    advantage: str,
    friction: str,
) -> str:
    """Helper to format the exact canonical wedge template."""
    return (
        f"For {target_segment.strip()} who needs to {specific_job.strip()} in {context.strip()}, "
        f"existing alternatives fail because {limitation.strip()}. "
        f"This product provides {advantage.strip()} without requiring {friction.strip()}."
    )


def assess_wedge(
    hypothesis: SolutionHypothesis,
    competitors: Optional[CompetitorResearch],
    critique: Optional[HostileCritique],
    client: Optional[OpenAI] = None,
    force: bool = False,
    model: Optional[str] = None,
) -> Optional[WedgeAssessment]:
    """Discover and validate the wedge for a single solution candidate."""
    cache_filename = (
        f"{hypothesis.opportunity_id}.json"
        if hypothesis.opportunity_id.startswith("opp_")
        else f"opp_{hypothesis.opportunity_id}.json"
    )
    cache_file = WEDGE_CACHE_DIR / cache_filename
    if cache_file.exists() and not force:
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return WedgeAssessment.model_validate(data)
        except Exception as exc:
            log.warning("Cache parse error for wedge %s: %s; re-running...", hypothesis.opportunity_id, exc)

    # Fast gate: If hostile critic rejected, immediately fail-fast to NO_WEDGE
    if critique and critique.verdict == CritiqueVerdict.REJECT:
        log.info("[%s] Hostile critic rejected; creating NO_WEDGE assessment without LLM call.", hypothesis.opportunity_id)
        reject_reason = (
            critique.strongest_reasons_to_reject[0]
            if critique.strongest_reasons_to_reject
            else "Fatal flaws identified during adversarial review."
        )
        assessment = WedgeAssessment(
            opportunity_id=hypothesis.opportunity_id,
            target_segment=hypothesis.target_segment,
            specific_job=hypothesis.core_mechanism,
            context=hypothesis.triggering_context,
            existing_alternative_failure="Hostile critique found fatal flaws",
            evidence_for_gap=[],
            proposed_differentiation="None (fatal flaws identified in critique)",
            why_not_just_a_feature_label="N/A",
            reason_incumbent_might_not_solve="N/A",
            wedge_statement=f"For {hypothesis.target_segment} in {hypothesis.triggering_context}, existing alternatives already satisfy the workflow.",
            wedge_confidence_basis="Critic rejection gate",
            critical_unknowns=[],
            is_defensible=False,
            verdict=WedgeVerdict.NO_WEDGE,
            rejection_reason=f"Rejected in hostile critique: {reject_reason}",
        )
        cache_file.write_text(json.dumps(assessment.model_dump(), indent=2), encoding="utf-8")
        return assessment

    if client is None:
        client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY or "none",
            timeout=LLM_TIMEOUT,
        )

    model_name = model or IDEATE_MODEL
    user_prompt = _build_wedge_prompt(hypothesis, competitors, critique)

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": GENERAL_SYSTEM if hypothesis.track == ProductTrack.GENERAL else WEDGE_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=850,
            response_format={"type": "json_object"},
        )
        raw_text = response.choices[0].message.content or "{}"
    except Exception as exc:
        log.error("LLM call failed for wedge %s: %s", hypothesis.opportunity_id, exc)
        return None

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        log.warning("JSON decode failure for wedge %s: %s; cleaning...", hypothesis.opportunity_id, exc)
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text.strip())
        clean = re.sub(r"\n?```$", "", clean)
        try:
            raw_data = json.loads(clean)
        except Exception:
            return None

    raw_data["opportunity_id"] = hypothesis.opportunity_id

    if hypothesis.track and raw_data.get("verdict") not in {v.value for v in WedgeVerdict}:
        return None

    # Anti-buzzword inspection: Check if differentiation is just generic labels
    diff = raw_data.get("proposed_differentiation", "").lower()
    buzzwords = ["ai-powered", "simpler", "better ux", "user friendly", "faster"]
    if any(b == diff.strip() for b in buzzwords):
        raw_data["verdict"] = "no_wedge"
        raw_data["rejection_reason"] = f"Proposed differentiation relies purely on buzzwords: '{diff}'"
        raw_data["is_defensible"] = False

    # Ensure canonical wedge statement format if missing or malformed
    stmt = raw_data.get("wedge_statement", "")
    if not stmt or not stmt.lower().startswith("for "):
        friction = raw_data.get("source_of_friction_avoided", "heavy manual overhead")
        raw_data["wedge_statement"] = format_canonical_wedge(
            target_segment=raw_data.get("target_segment", hypothesis.target_segment),
            specific_job=raw_data.get("specific_job", hypothesis.core_mechanism),
            context=raw_data.get("context", hypothesis.triggering_context),
            limitation=raw_data.get("existing_alternative_failure", hypothesis.why_incumbent_fails),
            advantage=raw_data.get("proposed_differentiation", hypothesis.core_mechanism),
            friction=friction,
        )

    try:
        assessment = WedgeAssessment.model_validate(raw_data)
    except ValidationError as val_err:
        log.warning("Wedge validation error: %s", val_err)
        if hypothesis.track:
            return None
        assessment = WedgeAssessment(
            opportunity_id=hypothesis.opportunity_id,
            target_segment=raw_data.get("target_segment", hypothesis.target_segment),
            specific_job=raw_data.get("specific_job", hypothesis.core_mechanism),
            context=raw_data.get("context", hypothesis.triggering_context),
            existing_alternative_failure=raw_data.get("existing_alternative_failure", hypothesis.why_incumbent_fails),
            evidence_for_gap=raw_data.get("evidence_for_gap", []),
            proposed_differentiation=raw_data.get("proposed_differentiation", hypothesis.core_mechanism),
            why_not_just_a_feature_label=raw_data.get("why_not_just_a_feature_label", "Mechanical workflow difference"),
            reason_incumbent_might_not_solve=raw_data.get("reason_incumbent_might_not_solve", hypothesis.why_incumbent_fails),
            wedge_statement=raw_data.get("wedge_statement", ""),
            wedge_confidence_basis=raw_data.get("wedge_confidence_basis", "model_synthesis"),
            critical_unknowns=raw_data.get("critical_unknowns", []),
            is_defensible=raw_data.get("is_defensible", True),
            verdict=WedgeVerdict.POSSIBLE_BUT_UNPROVEN,
            rejection_reason=raw_data.get("rejection_reason"),
        )

    cache_file.write_text(json.dumps(assessment.model_dump(), indent=2), encoding="utf-8")
    log.info("[%s] Wedge synthesized: verdict=%s", hypothesis.opportunity_id, assessment.verdict.value)
    return assessment


def assess_cluster_wedges(
    cluster_id: int,
    force: bool = False,
    model: Optional[str] = None,
) -> list[WedgeAssessment]:
    """Run wedge assessment on all hypotheses for a given cluster."""
    hyp_file = HYPOTHESIS_CACHE_DIR / f"cluster_{cluster_id}.json"
    if not hyp_file.exists():
        raise FileNotFoundError(f"No hypothesis cache for cluster {cluster_id} at {hyp_file}")

    hyp_set = HypothesisSet.model_validate(json.loads(hyp_file.read_text(encoding="utf-8")))

    client = OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY or "none",
        timeout=LLM_TIMEOUT,
    )

    results: list[WedgeAssessment] = []
    for hyp in hyp_set.hypotheses:
        # Load competitors if available
        comp_id = hyp.opportunity_id if hyp.opportunity_id.startswith("opp_") else f"opp_{hyp.opportunity_id}"
        comp_file = COMPETITOR_CACHE_DIR / f"{comp_id}.json"
        competitors = None
        if comp_file.exists():
            try:
                competitors = CompetitorResearch.model_validate(json.loads(comp_file.read_text(encoding="utf-8")))
            except Exception as e:
                log.warning("Could not load competitors for %s: %s", comp_id, e)

        # Load critique if available
        crit_file = CRITIQUE_CACHE_DIR / f"{comp_id}.json"
        critique = None
        if crit_file.exists():
            try:
                critique = HostileCritique.model_validate(json.loads(crit_file.read_text(encoding="utf-8")))
            except Exception as e:
                log.warning("Could not load critique for %s: %s", comp_id, e)

        assessment = assess_wedge(hyp, competitors, critique, client=client, force=force, model=model)
        if assessment:
            results.append(assessment)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 5: Differentiated Wedge Finder")
    parser.add_argument("--cluster-id", type=int, default=0, help="Cluster ID to analyze")
    parser.add_argument("--force", action="store_true", help="Bypass cache and force re-analysis")
    parser.add_argument("--model", type=str, default=None, help="LLM model override")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    wedges = assess_cluster_wedges(args.cluster_id, force=args.force, model=args.model)

    print(f"\nWedge Assessment for Cluster {args.cluster_id} ({len(wedges)} candidates):")
    for w in wedges:
        print(f"[{w.verdict.value.upper()}] {w.opportunity_id}")
        print(f"  Statement: {w.wedge_statement}")
        if w.rejection_reason:
            print(f"  Rejection Reason: {w.rejection_reason}")
        print()


if __name__ == "__main__":
    main()
