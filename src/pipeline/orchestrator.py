"""End-to-End MicroSaaS Solution & Opportunity Pipeline Orchestrator.

Stitches all 8 evaluation stages together for one or more problem clusters:
  Stage 2: Multi-Archetype Hypotheses (hypothesize.py)
  Stage 3: Zero-Cost Competitive Intelligence (competitors.py)
  Stage 4: Adversarial Hostile Critic (critique.py)
  Stage 5: Differentiated Wedge Finder (wedge.py)
  Stage 6: Minimal Wedge-Testing MVP (mvp.py)
  Stage 7-8: GTM & Monetization Evaluator (gtm.py)
  Stage 10: Deterministic Scoring & Kill Gates (decision.py)

Uses cached stage outputs by default (fast execution); passes --force to re-run LLM/search calls.
Generates:
  - data/pipeline_report.md
  - data/pipeline_scores.csv
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from openai import OpenAI

from ..config import (
    CLUSTERS_PATH,
    COMPETITOR_CACHE_DIR,
    CRITIQUE_CACHE_DIR,
    DECISION_CACHE_DIR,
    GTM_CACHE_DIR,
    HYPOTHESIS_CACHE_DIR,
    IDEATE_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_TIMEOUT,
    MVP_CACHE_DIR,
    PIPELINE_REPORT_MD_PATH,
    PIPELINE_SCORES_CSV_PATH,
    PROBLEMS_PATH,
    WEDGE_CACHE_DIR,
)
from .competitors import research_competitors_for_hypothesis as research_hypothesis
from .critique import critique_hypothesis
from .decision import score_opportunity
from .gtm import evaluate_gtm
from .mvp import design_mvp
from .schema import (
    CompetitorResearch,
    DecisionGate,
    DecisionStatus,
    GTMPlan,
    HostileCritique,
    HypothesisSet,
    MVPSpec,
    MarketEvidence,
    SolutionHypothesis,
    WedgeAssessment,
    WedgeVerdict,
)
from .wedge import assess_wedge

# Try importing hypothesize functions
try:
    from .hypothesize import generate_hypotheses_for_cluster
except ImportError:
    generate_hypotheses_for_cluster = None

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

log = logging.getLogger(__name__)


def run_pipeline_for_cluster(
    cluster_id: int,
    client: Optional[OpenAI] = None,
    force: bool = False,
    model: Optional[str] = None,
) -> list[DecisionGate]:
    """Runs the full pipeline for all hypotheses in a cluster."""
    if client is None:
        client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY or "none",
            timeout=LLM_TIMEOUT,
        )

    hyp_file = HYPOTHESIS_CACHE_DIR / f"cluster_{cluster_id}.json"
    if force or not hyp_file.exists():
        if generate_hypotheses_for_cluster is not None and CLUSTERS_PATH.exists() and PROBLEMS_PATH.exists():
            log.info("Hypothesis cache not found for cluster %d. Generating hypotheses...", cluster_id)
            clusters_data = json.loads(CLUSTERS_PATH.read_text(encoding="utf-8"))
            cluster_dict = next((c for c in clusters_data.get("clusters", []) if c["id"] == cluster_id), None)
            if not cluster_dict:
                raise ValueError(f"Cluster ID {cluster_id} not found in {CLUSTERS_PATH}")
            probs_by_id = {}
            for line in PROBLEMS_PATH.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        p = json.loads(line)
                        probs_by_id[p["doc_id"]] = p
                    except Exception:
                        pass
            member_probs = [probs_by_id[m] for m in cluster_dict.get("members", []) if m in probs_by_id]
            hyp_set = generate_hypotheses_for_cluster(cluster_dict, member_probs, client, force=force, model=model)
            if not hyp_set:
                raise RuntimeError(f"Failed to generate hypotheses for cluster {cluster_id}")
        else:
            raise FileNotFoundError(f"Hypothesis cache missing for cluster {cluster_id} at {hyp_file}")
    else:
        hyp_set = HypothesisSet.model_validate(json.loads(hyp_file.read_text(encoding="utf-8")))

    cluster_decisions: list[DecisionGate] = []

    for hyp in hyp_set.hypotheses:
        opp_id = hyp.opportunity_id
        log.info(">>> Processing opportunity: %s (%s)", opp_id, hyp.solution_name)

        result = evaluate_candidate(hyp, client=client, force=force, model=model)
        if result:
            cluster_decisions.append(result[0])

    return cluster_decisions


def evaluate_candidate(
    hypothesis: SolutionHypothesis,
    client: OpenAI,
    force: bool = False,
    model: str | None = None,
    market_evidence: MarketEvidence | None = None,
) -> tuple[DecisionGate, WedgeAssessment, MVPSpec | None, GTMPlan | None] | None:
    options = {"client": client, "force": force, "model": model}
    competitors = research_hypothesis(hypothesis, **options)
    critique = critique_hypothesis(hypothesis, competitors=competitors, **options)
    wedge = assess_wedge(hypothesis, competitors=competitors, critique=critique, **options)
    mvp = None
    gtm = None
    if not wedge:
        if not hypothesis.track:
            log.warning("[%s] Failed to assess wedge", hypothesis.opportunity_id)
            return None
        wedge = WedgeAssessment(
            opportunity_id=hypothesis.opportunity_id,
            target_segment=hypothesis.target_segment,
            existing_alternative_failure="Unknown",
            wedge_statement="Differentiation assessment unavailable.",
            is_defensible=False,
            verdict=WedgeVerdict.POSSIBLE_BUT_UNPROVEN,
        )
    elif wedge.verdict != WedgeVerdict.NO_WEDGE:
        mvp = design_mvp(hypothesis, wedge=wedge, **options)
        gtm = evaluate_gtm(hypothesis, wedge=wedge, **options)

    decision = score_opportunity(
        hypothesis, wedge, critique, competitors, mvp, gtm,
        force=force, market_evidence=market_evidence,
    )
    return decision, wedge, mvp, gtm


def generate_pipeline_reports(
    decisions: list[DecisionGate],
    hypotheses_by_id: dict[str, SolutionHypothesis],
    wedges_by_id: dict[str, WedgeAssessment],
    mvps_by_id: dict[str, MVPSpec],
    gtms_by_id: dict[str, GTMPlan],
    output_md_path: Path = PIPELINE_REPORT_MD_PATH,
    output_csv_path: Path = PIPELINE_SCORES_CSV_PATH,
    market_evidence: dict[str, MarketEvidence] | None = None,
    run_summary: str = "",
) -> None:
    """Renders the final ranked markdown report and structured CSV dataset."""
    status_order = {DecisionStatus.RANK: 0, DecisionStatus.HOLD_FOR_EVIDENCE: 1, DecisionStatus.REJECTED: 2}
    sorted_decisions = sorted(decisions, key=lambda d: (status_order[d.status], -d.opportunity_score))

    csv_rows = []
    md_lines = [
        "# MicroSaaS Lab -- Ranked Opportunity Dossier (Pipeline v2)\n",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        "**Methodology:** Multi-stage adversarial synthesis with zero-cost search, kill-gate filtering, and deterministic scoring.  \n",
        run_summary,
        "---\n",
        "## Executive Summary Table\n",
        "| Rank | Status | Opportunity | Archetype | Score | Wedge | Est. Days | GTM Verdict |",
        "|---|---|---|---|---|---|---|---|",
    ]

    if not sorted_decisions:
        md_lines.append("\nNo candidates were generated for this run.\n")

    for rank, d in enumerate(sorted_decisions, 1):
        hyp = hypotheses_by_id.get(d.opportunity_id)
        arch = hyp.archetype.value if hyp else "unknown"
        days = f"{d.mvp_days}d" if d.mvp_days else "Unknown"
        score_str = f"**{d.opportunity_score:.4f}**" if d.status == DecisionStatus.RANK else f"*{d.opportunity_score:.4f}*"
        md_lines.append(
            f"| #{rank} | `{d.status.value.upper()}` | **{d.solution_name}** (`{d.opportunity_id}`) | `{arch}` | {score_str} | {d.wedge_verdict} | {days} | {d.gtm_verdict} |"
        )

        csv_rows.append({
            "rank": rank,
            "opportunity_id": d.opportunity_id,
            "solution_name": d.solution_name,
            "cluster_id": d.cluster_id,
            "status": d.status.value,
            "track": hyp.track.value if hyp and hyp.track else "",
            "opportunity_score": d.opportunity_score,
            "wedge_strength": d.component_scores.get("wedge_strength", 0.0),
            "evidence_confidence": d.component_scores.get("evidence_confidence", 0.0),
            "competition_risk": d.component_scores.get("competition_risk", 0.0),
            "buildability": d.component_scores.get("buildability", 0.0),
            "distribution_potential": d.component_scores.get("distribution_potential", 0.0),
            "monetization_potential": d.component_scores.get("monetization_potential", 0.0),
            "commoditization_risk": d.component_scores.get("commoditization_risk", 0.0),
            "mvp_days": d.mvp_days,
            "rejection_reasons": "; ".join(d.rejection_reasons),
        })

    md_lines.append("\n---\n")

    # Detailed Opportunity Sections
    for rank, d in enumerate(sorted_decisions, 1):
        hyp = hypotheses_by_id.get(d.opportunity_id)
        wedge = wedges_by_id.get(d.opportunity_id)
        mvp = mvps_by_id.get(d.opportunity_id)
        gtm = gtms_by_id.get(d.opportunity_id)

        status_badge = d.status.value.upper()
        md_lines.append(f"## #{rank} [{status_badge}] {d.solution_name}  (Score: {d.opportunity_score:.4f})")
        md_lines.append(f"**ID:** `{d.opportunity_id}` | **Cluster ID:** {d.cluster_id} | **Status:** `{d.status.value}`  ")
        if hyp:
            md_lines.append(f"**Archetype:** `{hyp.archetype.value}` | **Target Segment:** {hyp.target_segment}  ")

        if hyp and hyp.evidence:
            md_lines.append("\n### Source evidence")
            for e in hyp.evidence:
                date = e.created_at[:10] or "Date unknown"
                md_lines.append(f"- {e.quote} — {date} | {e.source} | {e.url}")
        if market_evidence and d.opportunity_id in market_evidence:
            evidence = market_evidence[d.opportunity_id]
            md_lines.append(f"\n**Reviewed market evidence:** {evidence.observation} ({evidence.url})")

        if d.rejection_reasons:
            md_lines.append("\n> [!WARNING]")
            md_lines.append(f"> **Gate Triggered:** {'; '.join(d.rejection_reasons)}\n")

        if wedge:
            md_lines.append("\n### 1. Differentiated Wedge Statement")
            md_lines.append(f"> {wedge.wedge_statement}\n")
            md_lines.append(f"* **Defensible Differentiation:** {wedge.proposed_differentiation}")
            md_lines.append(f"* **Why Not Just a Feature Label:** {wedge.why_not_just_a_feature_label}")
            md_lines.append(f"* **Why Incumbents Overlook:** {wedge.reason_incumbent_might_not_solve}")

        if mvp:
            md_lines.append("\n### 2. Scoped 1-Workflow MVP")
            md_lines.append(f"* **Core Workflow:** {mvp.core_workflow}")
            md_lines.append(f"* **Explicit Non-Features:** {'; '.join(mvp.explicit_non_features)}")
            md_lines.append(f"* **Acceptance Criteria:** {'; '.join(mvp.acceptance_criteria)}")
            md_lines.append(f"* **Pre-Build Validation Test:** {mvp.prebuild_validation_experiment}")
            md_lines.append(
                f"* **Build Estimate Breakdown:** Frontend: `{mvp.frontend_estimate}` | Backend: `{mvp.backend_estimate}` | "
                f"Integration: `{mvp.integration_estimate}` | Total: `{mvp.total_estimate_range}` (~{mvp.estimated_days} days)"
            )

        if gtm:
            md_lines.append("\n### 3. Distribution & Monetization (First 100 Users)")
            md_lines.append(f"* **Channels:** {', '.join(gtm.top_distribution_channels)}")
            md_lines.append(f"* **Search & Intent:** `{gtm.search_intent.value}` (Usage Frequency: `{gtm.usage_frequency.value}`)")
            md_lines.append(f"* **First Experiment:** {gtm.first_experiment} ({gtm.experiment_cost_and_time})")
            md_lines.append(f"* **Success Threshold:** {gtm.success_threshold}")
            md_lines.append(f"* **Monetization Model:** {gtm.monetization_model}")
            md_lines.append(f"* **Willingness to Pay Evidence:** {gtm.willingness_to_pay_evidence}")

        # Deterministic Score Breakdown Table
        md_lines.append("\n### 4. Deterministic Component Score Breakdown")
        md_lines.append("| Dimension | Factor Value | Weight | Direction |")
        md_lines.append("|---|---|---|---|")
        comp = d.component_scores
        md_lines.append(f"| Wedge Strength | {comp.get('wedge_strength', 0.0):.2f} | 22% | Higher is better |")
        md_lines.append(f"| Evidence Confidence | {comp.get('evidence_confidence', 0.0):.2f} | 18% | Higher is better |")
        md_lines.append(f"| Competition Risk | {comp.get('competition_risk', 0.0):.2f} | 15% | Lower is better (inverted) |")
        md_lines.append(f"| Buildability (<=28d) | {comp.get('buildability', 0.0):.2f} | 15% | Higher is better |")
        md_lines.append(f"| Distribution Potential | {comp.get('distribution_potential', 0.0):.2f} | 12% | Higher is better |")
        md_lines.append(f"| Monetization Potential | {comp.get('monetization_potential', 0.0):.2f} | 10% | Higher is better |")
        md_lines.append(f"| Commoditization Risk | {comp.get('commoditization_risk', 0.0):.2f} | 8% | Lower is better (inverted) |")
        md_lines.append(f"| **Composite Opportunity Score** | **{d.opportunity_score:.4f}** | **100%** | **Status: {d.status.value.upper()}** |")
        md_lines.append("\n---\n")

    output_md_path.parent.mkdir(parents=True, exist_ok=True)
    output_md_path.write_text("\n".join(md_lines), encoding="utf-8")
    log.info("Report written to %s", output_md_path)

    columns = [
        "rank", "opportunity_id", "solution_name", "cluster_id", "status", "track",
        "opportunity_score", "wedge_strength", "evidence_confidence", "competition_risk",
        "buildability", "distribution_potential", "monetization_potential",
        "commoditization_risk", "mvp_days", "rejection_reasons",
    ]
    df = pd.DataFrame(csv_rows, columns=columns)
    output_csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv_path, index=False)
    log.info("Scores CSV written to %s", output_csv_path)


def run_orchestrator(
    cluster_ids: list[int],
    force: bool = False,
    model: Optional[str] = None,
) -> None:
    """Executes the pipeline over the specified clusters and generates final reports."""
    client = OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY or "none",
        timeout=LLM_TIMEOUT,
    )

    all_decisions: list[DecisionGate] = []
    hypotheses_map: dict[str, SolutionHypothesis] = {}
    wedges_map: dict[str, WedgeAssessment] = {}
    mvps_map: dict[str, MVPSpec] = {}
    gtms_map: dict[str, GTMPlan] = {}

    for cid in cluster_ids:
        print(f"\n{'='*75}")
        print(f"RUNNING PIPELINE FOR CLUSTER {cid}")
        print(f"{'='*75}")
        decisions = run_pipeline_for_cluster(cid, client=client, force=force, model=model)
        all_decisions.extend(decisions)

        # Load artifacts into maps for reporting
        hyp_file = HYPOTHESIS_CACHE_DIR / f"cluster_{cid}.json"
        if hyp_file.exists():
            hset = HypothesisSet.model_validate(json.loads(hyp_file.read_text(encoding="utf-8")))
            for h in hset.hypotheses:
                hypotheses_map[h.opportunity_id] = h

                opp_id = h.opportunity_id if h.opportunity_id.startswith("opp_") else f"opp_{h.opportunity_id}"
                w_file = WEDGE_CACHE_DIR / f"{opp_id}.json"
                if w_file.exists():
                    try:
                        wedges_map[h.opportunity_id] = WedgeAssessment.model_validate(json.loads(w_file.read_text(encoding="utf-8")))
                    except Exception:
                        pass

                m_file = MVP_CACHE_DIR / f"{opp_id}.json"
                if m_file.exists():
                    try:
                        mvps_map[h.opportunity_id] = MVPSpec.model_validate(json.loads(m_file.read_text(encoding="utf-8")))
                    except Exception:
                        pass

                g_file = GTM_CACHE_DIR / f"{opp_id}.json"
                if g_file.exists():
                    try:
                        gtms_map[h.opportunity_id] = GTMPlan.model_validate(json.loads(g_file.read_text(encoding="utf-8")))
                    except Exception:
                        pass

    generate_pipeline_reports(
        decisions=all_decisions,
        hypotheses_by_id=hypotheses_map,
        wedges_by_id=wedges_map,
        mvps_by_id=mvps_map,
        gtms_by_id=gtms_map,
    )

    print(f"\n{'='*75}")
    print(f"PIPELINE COMPLETE ({len(all_decisions)} total candidates evaluated)")
    print(f"{'='*75}")
    sorted_d = sorted(all_decisions, key=lambda x: x.opportunity_score, reverse=True)
    for rank, d in enumerate(sorted_d, 1):
        status_tag = f"[{d.status.value.upper()}]"
        print(f"#{rank:<2} {status_tag:<18} {d.opportunity_id:<14} {d.solution_name:<28} Score: {d.opportunity_score:.4f}")

    print(f"\nReports saved to:")
    print(f"  - Markdown: {PIPELINE_REPORT_MD_PATH}")
    print(f"  - CSV:      {PIPELINE_SCORES_CSV_PATH}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-End MicroSaaS Pipeline Orchestrator")
    parser.add_argument("--cluster-id", type=int, nargs="+", default=[0], help="One or more cluster IDs to evaluate")
    parser.add_argument("--force", action="store_true", help="Bypass cache and force re-evaluation")
    parser.add_argument("--model", type=str, default=None, help="LLM model override")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_orchestrator(args.cluster_id, force=args.force, model=args.model)


if __name__ == "__main__":
    main()
