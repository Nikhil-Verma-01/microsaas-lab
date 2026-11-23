"""Stage 10: Deterministic Scoring and Kill Gates Engine.

Calculates objective opportunity scores directly from verified stage variables
and enforces hard programmatic kill gates (Critic veto, No Wedge, MVP oversize, Weak GTM).
Zero LLM calls -- purely deterministic Python execution.

Reads:
  - data/cache/hypotheses/cluster_{id}.json
  - data/cache/competitors/opp_{id}.json
  - data/cache/critiques/opp_{id}.json
  - data/cache/wedges/opp_{id}.json
  - data/cache/mvps/opp_{id}.json
  - data/cache/gtm/opp_{id}.json
Writes:
  - data/cache/decisions/opp_{id}.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import (
    COMPETITOR_CACHE_DIR,
    CRITIQUE_CACHE_DIR,
    DECISION_CACHE_DIR,
    GTM_CACHE_DIR,
    HYPOTHESIS_CACHE_DIR,
    MVP_CACHE_DIR,
    WEDGE_CACHE_DIR,
)
from .schema import (
    CompetitorResearch,
    CritiqueVerdict,
    DecisionGate,
    DecisionStatus,
    GTMPlan,
    GTMVerdict,
    HostileCritique,
    HypothesisSet,
    MVPSpec,
    MarketEvidence,
    ProductTrack,
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

# ---------------------------------------------------------------------------
# Calibration Weights & Enum Mappings
# ---------------------------------------------------------------------------

WEIGHTS = {
    "wedge_strength": 0.22,
    "evidence_confidence": 0.18,
    "competition_risk": 0.15,
    "buildability": 0.15,
    "distribution_potential": 0.12,
    "monetization_potential": 0.10,
    "commoditization_risk": 0.08,
}

WEDGE_SCORE = {
    "credible_wedge": 1.0,
    "possible_but_unproven": 0.55,
    "no_wedge": 0.0,
}

CRITIQUE_RISK = {
    "low": 0.15,
    "medium": 0.45,
    "high": 0.80,
}

GTM_SCORE = {
    "plausible": 1.0,
    "conditional": 0.65,
    "weak": 0.25,
    "unknown": 0.40,
}

FREQUENCY_SCORE = {
    "daily": 1.0,
    "weekly": 0.75,
    "monthly": 0.50,
    "occasional": 0.30,
    "one_time": 0.10,
    "unknown": 0.40,
}

INTENT_SCORE = {
    "transactional": 1.0,
    "utility": 0.80,
    "mixed": 0.60,
    "informational": 0.35,
    "unknown": 0.40,
}

SATURATION_PENALTY = {
    "low": 0.0,
    "medium": 0.35,
    "high": 0.70,
    "unknown": 0.30,
}


def buildability_score(estimated_days: int) -> float:
    """Computes buildability factor: 1.0 at 5 days, declining to 0.0 at 28+ days."""
    if estimated_days <= 0:
        return 0.5
    if estimated_days <= 5:
        return 1.0
    if estimated_days >= 28:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (estimated_days - 5) / 23.0))


def apply_kill_gates(
    wedge: WedgeAssessment,
    critique: Optional[HostileCritique],
    mvp: Optional[MVPSpec],
    gtm: Optional[GTMPlan],
) -> tuple[Optional[DecisionStatus], list[str]]:
    """Checks programmatic kill gates in order before calculating scores."""
    reasons: list[str] = []

    # Gate 1: No defensible wedge found or rejected by critic
    if wedge.verdict == WedgeVerdict.NO_WEDGE or str(wedge.verdict) == "no_wedge":
        reason = wedge.rejection_reason or "No defensible wedge found"
        return DecisionStatus.REJECTED, [reason]

    # Gate 2: MVP scope exceeds solo builder threshold (> 4 weeks / 28 days)
    if mvp and mvp.estimated_days > 28:
        reasons.append(f"MVP estimated at {mvp.estimated_days} days (> 28 days) exceeds solo builder limit")
        return DecisionStatus.HOLD_FOR_EVIDENCE, reasons

    # Gate 3: GTM verdict weak with no willingness-to-pay evidence
    if gtm and (gtm.verdict == GTMVerdict.WEAK or str(gtm.verdict) == "weak"):
        wtp = (gtm.willingness_to_pay_evidence or "").lower()
        if not wtp or "unknown" in wtp:
            reasons.append("GTM verdict weak with no verified willingness-to-pay evidence")
            return DecisionStatus.HOLD_FOR_EVIDENCE, reasons

    return None, []


def score_opportunity(
    hypothesis: SolutionHypothesis,
    wedge: WedgeAssessment,
    critique: Optional[HostileCritique] = None,
    competitors: Optional[CompetitorResearch] = None,
    mvp: Optional[MVPSpec] = None,
    gtm: Optional[GTMPlan] = None,
    force: bool = False,
    market_evidence: MarketEvidence | None = None,
) -> DecisionGate:
    """Deterministically evaluates and scores a single solution candidate."""
    opp_id = hypothesis.opportunity_id
    cache_filename = f"{opp_id}.json" if opp_id.startswith("opp_") else f"opp_{opp_id}.json"
    cache_file = DECISION_CACHE_DIR / cache_filename

    if not hypothesis.track and cache_file.exists() and not force:
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return DecisionGate.model_validate(data)
        except Exception as exc:
            log.warning("Cache parse error for decision %s: %s; re-scoring...", opp_id, exc)

    # 1. Apply hard kill gates
    gate_status, gate_reasons = apply_kill_gates(wedge, critique, mvp, gtm)
    authors = {(e.source, e.author.casefold()) for e in hypothesis.evidence if e.author and e.quote and e.url}
    urls = {e.url for e in hypothesis.evidence if e.author and e.quote and e.url}
    reviewed_basis = market_evidence.basis if market_evidence and market_evidence.observation.strip() else None
    if hypothesis.track and gate_status != DecisionStatus.REJECTED:
        if wedge.verdict != WedgeVerdict.CREDIBLE_WEDGE or not wedge.is_defensible:
            gate_reasons.append("The proposed advantage needs verification")
        if min(len(authors), len(urls)) < 2:
            gate_reasons.append("Need matching excerpts from two independent authors and discussions")
        if not competitors or not any(
            a.confidence_basis == "verified_search" and a.url for a in competitors.alternatives
        ):
            gate_reasons.append("Need search evidence for existing alternatives")
        if critique and critique.verdict == CritiqueVerdict.NEEDS_EVIDENCE:
            gate_reasons.append("Critique identified questions that require evidence")
        if not critique or not mvp or not gtm:
            gate_reasons.append("Critique, MVP scope and distribution plan are required")
        elif gtm.verdict in {GTMVerdict.WEAK, GTMVerdict.UNKNOWN}:
            gate_reasons.append("Need a plausible distribution plan")
        if mvp and not 0 < mvp.estimated_days <= 14:
            gate_reasons.append("MVP estimate must fit the 14-day budget")
        allowed_basis = {"paid_demand"} if hypothesis.track == ProductTrack.DEVELOPER else {"search_demand", "paid_demand"}
        if reviewed_basis not in allowed_basis:
            gate_reasons.append("Need reviewed demand evidence for the intended market")
        if gate_reasons:
            gate_status = DecisionStatus.HOLD_FOR_EVIDENCE

    # 2. Extract and normalize component variables (0.0 - 1.0)
    wedge_key = wedge.verdict.value if hasattr(wedge.verdict, "value") else str(wedge.verdict)
    wedge_val = WEDGE_SCORE.get(wedge_key, 0.5)

    # Evidence confidence based on competitor search verification & critic findings
    ev_conf = 0.70
    if competitors and competitors.alternatives:
        if any(a.confidence_basis == "verified_search" for a in competitors.alternatives):
            ev_conf += 0.15
        if competitors.search_provider == "duckduckgo":
            ev_conf += 0.10
    if critique and critique.evidence_that_contradicts:
        ev_conf -= 0.20
    ev_conf = max(0.20, min(1.0, ev_conf))

    # Competition risk
    absorption = CRITIQUE_RISK.get(getattr(critique, "incumbent_absorption_risk", "medium"), 0.45) if critique else 0.45
    saturation = SATURATION_PENALTY.get(getattr(competitors, "likely_saturation", "unknown"), 0.30) if competitors else 0.30
    comp_risk = round(0.6 * absorption + 0.4 * saturation, 4)

    # Commoditization risk
    commod_risk = CRITIQUE_RISK.get(getattr(critique, "commoditization_risk", "medium"), 0.45) if critique else 0.45

    # Buildability
    mvp_days = mvp.estimated_days if mvp else (0 if hypothesis.track else 7)
    build_val = 0.0 if hypothesis.track and not mvp else buildability_score(mvp_days)

    # Distribution potential
    gtm_key = gtm.verdict.value if gtm and hasattr(gtm.verdict, "value") else (str(gtm.verdict) if gtm else "unknown")
    gtm_val = GTM_SCORE.get(gtm_key, 0.40)
    freq_key = gtm.usage_frequency.value if gtm and hasattr(gtm.usage_frequency, "value") else (str(gtm.usage_frequency) if gtm else "unknown")
    freq_val = FREQUENCY_SCORE.get(freq_key, 0.40)
    intent_key = gtm.search_intent.value if gtm and hasattr(gtm.search_intent, "value") else (str(gtm.search_intent) if gtm else "unknown")
    intent_val = INTENT_SCORE.get(intent_key, 0.40)
    dist_val = round(0.50 * gtm_val + 0.25 * freq_val + 0.25 * intent_val, 4)

    # Monetization potential
    monet_val = 0.50
    if gtm:
        wtp = (gtm.willingness_to_pay_evidence or "").lower()
        if wtp and "unknown" not in wtp:
            monet_val += 0.25
        if any(w in (gtm.monetization_model or "").lower() for w in ["paid", "subscription", "$", "usage"]):
            monet_val += 0.15
        if gtm.verdict == GTMVerdict.PLAUSIBLE or str(gtm.verdict) == "plausible":
            monet_val += 0.10
    monet_val = max(0.10, min(1.0, monet_val))
    if hypothesis.track:
        ev_conf = min(len(authors) / 4, len(urls) / 4, 1) if gate_status != DecisionStatus.REJECTED else 0
        monet_val = float(reviewed_basis == "paid_demand")
        if hypothesis.track == ProductTrack.GENERAL and reviewed_basis == "search_demand":
            dist_val = max(dist_val, 0.75)

    component_scores = {
        "wedge_strength": round(wedge_val, 4),
        "evidence_confidence": round(ev_conf, 4),
        "competition_risk": round(comp_risk, 4),
        "buildability": round(build_val, 4),
        "distribution_potential": round(dist_val, 4),
        "monetization_potential": round(monet_val, 4),
        "commoditization_risk": round(commod_risk, 4),
    }

    # 3. Calculate Opportunity Score
    if gate_status == DecisionStatus.REJECTED:
        final_score = 0.0
        final_status = DecisionStatus.REJECTED
    elif gate_status == DecisionStatus.HOLD_FOR_EVIDENCE:
        final_score = round(
            WEIGHTS["wedge_strength"] * wedge_val
            + WEIGHTS["evidence_confidence"] * ev_conf
            + WEIGHTS["competition_risk"] * (1.0 - comp_risk)
            + WEIGHTS["buildability"] * build_val
            + WEIGHTS["distribution_potential"] * dist_val
            + WEIGHTS["monetization_potential"] * monet_val
            + WEIGHTS["commoditization_risk"] * (1.0 - commod_risk),
            4,
        )
        final_status = DecisionStatus.HOLD_FOR_EVIDENCE
    else:
        # Status is RANK
        final_status = DecisionStatus.RANK
        composite = (
            WEIGHTS["wedge_strength"] * wedge_val
            + WEIGHTS["evidence_confidence"] * ev_conf
            + WEIGHTS["competition_risk"] * (1.0 - comp_risk)
            + WEIGHTS["buildability"] * build_val
            + WEIGHTS["distribution_potential"] * dist_val
            + WEIGHTS["monetization_potential"] * monet_val
            + WEIGHTS["commoditization_risk"] * (1.0 - commod_risk)
        )
        final_score = round(composite, 4)

    decision = DecisionGate(
        opportunity_id=opp_id,
        solution_name=hypothesis.solution_name,
        cluster_id=hypothesis.cluster_id,
        status=final_status,
        opportunity_score=final_score,
        component_scores=component_scores,
        rejection_reasons=gate_reasons,
        wedge_verdict=wedge_key,
        gtm_verdict=gtm_key,
        mvp_days=mvp_days,
        scored_at=datetime.now(timezone.utc).isoformat(),
    )

    if not hypothesis.track:
        cache_file.write_text(json.dumps(decision.model_dump(), indent=2), encoding="utf-8")
    log.info("[%s] Scored: status=%s, score=%.4f", opp_id, decision.status.value, decision.opportunity_score)
    return decision


def score_cluster(cluster_id: int, force: bool = False) -> list[DecisionGate]:
    """Scores all hypotheses in a cluster from cached stage files."""
    hyp_file = HYPOTHESIS_CACHE_DIR / f"cluster_{cluster_id}.json"
    if not hyp_file.exists():
        raise FileNotFoundError(f"No hypothesis cache for cluster {cluster_id} at {hyp_file}")

    hyp_set = HypothesisSet.model_validate(json.loads(hyp_file.read_text(encoding="utf-8")))
    decisions: list[DecisionGate] = []

    for hyp in hyp_set.hypotheses:
        opp_id = hyp.opportunity_id if hyp.opportunity_id.startswith("opp_") else f"opp_{hyp.opportunity_id}"

        # Load wedge
        wedge_file = WEDGE_CACHE_DIR / f"{opp_id}.json"
        if not wedge_file.exists():
            log.warning("[%s] No wedge cache found; skipping scoring.", opp_id)
            continue
        wedge = WedgeAssessment.model_validate(json.loads(wedge_file.read_text(encoding="utf-8")))

        # Load optional artifacts
        comp_file = COMPETITOR_CACHE_DIR / f"{opp_id}.json"
        competitors = CompetitorResearch.model_validate(json.loads(comp_file.read_text(encoding="utf-8"))) if comp_file.exists() else None

        crit_file = CRITIQUE_CACHE_DIR / f"{opp_id}.json"
        critique = HostileCritique.model_validate(json.loads(crit_file.read_text(encoding="utf-8"))) if crit_file.exists() else None

        mvp_file = MVP_CACHE_DIR / f"{opp_id}.json"
        mvp = MVPSpec.model_validate(json.loads(mvp_file.read_text(encoding="utf-8"))) if mvp_file.exists() else None

        gtm_file = GTM_CACHE_DIR / f"{opp_id}.json"
        gtm = GTMPlan.model_validate(json.loads(gtm_file.read_text(encoding="utf-8"))) if gtm_file.exists() else None

        d = score_opportunity(hyp, wedge, critique, competitors, mvp, gtm, force=force)
        decisions.append(d)

    return sorted(decisions, key=lambda x: x.opportunity_score, reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 10: Deterministic Scoring & Kill Gates Engine")
    parser.add_argument("--cluster-id", type=int, default=0, help="Cluster ID to score")
    parser.add_argument("--force", action="store_true", help="Bypass cache and force re-scoring")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    decisions = score_cluster(args.cluster_id, force=args.force)

    print(f"\n{'='*75}")
    print(f"STAGE 10 DETERMINISTIC SCORING -- CLUSTER {args.cluster_id} ({len(decisions)} candidates)")
    print(f"{'='*75}")
    for d in decisions:
        status_tag = f"[{d.status.value.upper()}]"
        print(f"{status_tag:<18} {d.opportunity_id:<14} {d.solution_name:<28} Score: {d.opportunity_score:.4f}")
        if d.rejection_reasons:
            print(f"  Reasons: {'; '.join(d.rejection_reasons)}")
        else:
            w = d.component_scores.get('wedge_strength', 0)
            c = d.component_scores.get('competition_risk', 0)
            b = d.component_scores.get('buildability', 0)
            print(f"  Components: wedge={w:.2f}, comp_risk={c:.2f}, build={b:.2f}, days={d.mvp_days}")
    print()


if __name__ == "__main__":
    main()
