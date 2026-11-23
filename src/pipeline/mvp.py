"""Stage 6: Minimal Wedge-Testing MVP Designer.

Designs the smallest viable implementation required to test the validated wedge.
Enforces tight scope constraints: exactly 1 core workflow, explicit non-features,
pre-build validation experiment, and category-level build estimates for a solo builder.

Gate: Candidates with WedgeVerdict == "no_wedge" are skipped / rejected.

Reads:
  - data/cache/hypotheses/cluster_{id}.json
  - data/cache/wedges/opp_{id}.json
Writes:
  - data/cache/mvps/opp_{id}.json
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
    HYPOTHESIS_CACHE_DIR,
    IDEATE_MODEL,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_TIMEOUT,
    MVP_CACHE_DIR,
    WEDGE_CACHE_DIR,
)
from .schema import (
    ProductTrack,
    HypothesisSet,
    MVPSpec,
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

MVP_SYSTEM = """\
Role: Lean product engineer and technical scoping specialist for solo micro-SaaS builders.

Task:
Design the absolute smallest implementation that tests the accepted wedge hypothesis.
Do NOT expand the product into a bloated multi-tenant SaaS or generic platform.
Your goal is to validate the specific value proposition within a 1-2 week solo-builder budget.

Rules:
1. Exactly ONE end-to-end core workflow (no secondary features).
2. Explicitly specify non-features (features intentionally omitted to stay lean).
3. Provide granular time estimates across frontend, backend, integration, security/testing, and deploy.
4. Total solo builder build time must NOT exceed 4 weeks (ideally 1-2 weeks).
5. Include a pre-build validation experiment (e.g. CLI prototype, landing page with video demo, concierge test).
6. Return valid JSON only.

Schema:
{
  "opportunity_id": (string),
  "hypothesis_to_test": (string, the core value hypothesis to validate),
  "primary_user": (string, specific developer role),
  "trigger": (string, when the developer initiates the tool),
  "core_workflow": (string, single end-to-end workflow description),
  "inputs": [string, 1-3 direct inputs],
  "outputs": [string, 1-3 direct outputs],
  "minimum_features": [string, max 3-4 essential features needed to test the wedge],
  "explicit_non_features": [string, at least 3 features explicitly excluded from MVP],
  "acceptance_criteria": [string, 2-3 objective criteria for MVP completion],
  "success_metric": (string, measurable indicator that the wedge works, e.g. 5 active repos, 50 CLI executions),
  "prebuild_validation_experiment": (string, fastest zero-code or low-code test before full build),
  "frontend_estimate": (string, e.g. "1-2 days" or "0 days (headless CLI)"),
  "backend_estimate": (string, e.g. "2-3 days"),
  "integration_estimate": (string, e.g. "1-2 days"),
  "security_and_testing_estimate": (string, e.g. "1 day"),
  "deployment_estimate": (string, e.g. "1 day"),
  "total_estimate_range": (string, e.g. "1-2 weeks"),
  "estimated_days": (integer, total working days, typically 5-14),
  "maintenance_risks": [string, 1-2 ongoing operational or upstream risks],
  "assumptions": [string, 2-3 key technical or user assumptions]
}
"""

GENERAL_SYSTEM = (
    "Scope a single-workflow utility for the target audience within two weeks. Favor a simple browser workflow when feasible. Use task completion as a metric and propose a pre-build experiment. "
    "Return only JSON.\n" + MVP_SYSTEM[MVP_SYSTEM.index("Schema:"):]
)


def _build_mvp_prompt(
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
        f"REPLACED WORKAROUND: {hypothesis.replaced_workaround}",
        f"\nVALIDATED WEDGE STATEMENT:\n{wedge.wedge_statement}",
        f"PROPOSED DIFFERENTIATION:\n{wedge.proposed_differentiation}",
        f"WHY NOT JUST A FEATURE LABEL:\n{wedge.why_not_just_a_feature_label}",
        "\nTASK:\n"
        "Design the minimal, scope-constrained MVP to test this exact wedge. "
        "Strictly list at least 3 explicit non-features that are deliberately deferred.",
    ]
    return "\n".join(lines)


def design_mvp(
    hypothesis: SolutionHypothesis,
    wedge: WedgeAssessment,
    client: Optional[OpenAI] = None,
    force: bool = False,
    model: Optional[str] = None,
) -> Optional[MVPSpec]:
    """Design a tight wedge-testing MVP for an approved hypothesis."""
    cache_filename = (
        f"{hypothesis.opportunity_id}.json"
        if hypothesis.opportunity_id.startswith("opp_")
        else f"opp_{hypothesis.opportunity_id}.json"
    )
    cache_file = MVP_CACHE_DIR / cache_filename
    if cache_file.exists() and not force:
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            return MVPSpec.model_validate(data)
        except Exception as exc:
            log.warning("Cache parse error for MVP %s: %s; re-running...", hypothesis.opportunity_id, exc)

    # Gate: Reject ideas that failed the wedge discovery
    if wedge.verdict == WedgeVerdict.NO_WEDGE:
        log.info("[%s] Wedge verdict is NO_WEDGE; skipping MVP design.", hypothesis.opportunity_id)
        return None

    if client is None:
        client = OpenAI(
            base_url=LLM_BASE_URL,
            api_key=LLM_API_KEY or "none",
            timeout=LLM_TIMEOUT,
        )

    model_name = model or IDEATE_MODEL
    user_prompt = _build_mvp_prompt(hypothesis, wedge)

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": GENERAL_SYSTEM if hypothesis.track == ProductTrack.GENERAL else MVP_SYSTEM},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=900,
            response_format={"type": "json_object"},
        )
        raw_text = response.choices[0].message.content or "{}"
    except Exception as exc:
        log.error("LLM call failed for MVP %s: %s", hypothesis.opportunity_id, exc)
        return None

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        log.warning("JSON decode failure for MVP %s: %s; cleaning...", hypothesis.opportunity_id, exc)
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text.strip())
        clean = re.sub(r"\n?```$", "", clean)
        try:
            raw_data = json.loads(clean)
        except Exception:
            return None

    raw_data["opportunity_id"] = hypothesis.opportunity_id

    if hypothesis.track and (
        not raw_data.get("core_workflow")
        or not raw_data.get("prebuild_validation_experiment")
        or not raw_data.get("estimated_days")
    ):
        return None

    # Fallback guarantees
    if not raw_data.get("core_workflow"):
        raw_data["core_workflow"] = hypothesis.core_mechanism
    if not raw_data.get("explicit_non_features"):
        raw_data["explicit_non_features"] = [
            "Multi-tenant user dashboard",
            "Custom enterprise SSO / SAML",
            "Complex visual UI editor",
        ]
    if not raw_data.get("hypothesis_to_test"):
        raw_data["hypothesis_to_test"] = wedge.proposed_differentiation or hypothesis.core_mechanism

    try:
        spec = MVPSpec.model_validate(raw_data)
    except ValidationError as val_err:
        log.warning("MVP validation error for %s: %s", hypothesis.opportunity_id, val_err)
        if hypothesis.track:
            return None
        spec = MVPSpec(
            opportunity_id=hypothesis.opportunity_id,
            hypothesis_to_test=raw_data.get("hypothesis_to_test", hypothesis.core_mechanism),
            primary_user=raw_data.get("primary_user", hypothesis.target_segment),
            trigger=raw_data.get("trigger", hypothesis.triggering_context),
            core_workflow=raw_data.get("core_workflow", hypothesis.core_mechanism),
            inputs=raw_data.get("inputs", ["Source code / API spec"]),
            outputs=raw_data.get("outputs", ["Configured tool / schema"]),
            minimum_features=raw_data.get("minimum_features", [hypothesis.core_mechanism]),
            explicit_non_features=raw_data.get("explicit_non_features", ["Custom UI", "Multi-tenancy"]),
            acceptance_criteria=raw_data.get("acceptance_criteria", ["Executes without crashing"]),
            success_metric=raw_data.get("success_metric", "Adoption by 5 developer users"),
            prebuild_validation_experiment=raw_data.get("prebuild_validation_experiment", "CLI smoke script demo"),
            frontend_estimate=raw_data.get("frontend_estimate", "0-1 days"),
            backend_estimate=raw_data.get("backend_estimate", "3-5 days"),
            integration_estimate=raw_data.get("integration_estimate", "2 days"),
            security_and_testing_estimate=raw_data.get("security_and_testing_estimate", "1 day"),
            deployment_estimate=raw_data.get("deployment_estimate", "1 day"),
            total_estimate_range=raw_data.get("total_estimate_range", "1-2 weeks"),
            estimated_days=raw_data.get("estimated_days", 8),
            maintenance_risks=raw_data.get("maintenance_risks", []),
            assumptions=raw_data.get("assumptions", []),
        )

    cache_file.write_text(json.dumps(spec.model_dump(), indent=2), encoding="utf-8")
    log.info("[%s] MVP spec designed: %s (estimate: %s)", hypothesis.opportunity_id, spec.core_workflow[:40], spec.total_estimate_range)
    return spec


def design_cluster_mvps(
    cluster_id: int,
    force: bool = False,
    model: Optional[str] = None,
) -> list[MVPSpec]:
    """Design MVPs for all hypotheses in a cluster that passed the wedge gate."""
    hyp_file = HYPOTHESIS_CACHE_DIR / f"cluster_{cluster_id}.json"
    if not hyp_file.exists():
        raise FileNotFoundError(f"No hypothesis cache for cluster {cluster_id} at {hyp_file}")

    hyp_set = HypothesisSet.model_validate(json.loads(hyp_file.read_text(encoding="utf-8")))

    client = OpenAI(
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY or "none",
        timeout=LLM_TIMEOUT,
    )

    results: list[MVPSpec] = []
    for hyp in hyp_set.hypotheses:
        opp_id = hyp.opportunity_id if hyp.opportunity_id.startswith("opp_") else f"opp_{hyp.opportunity_id}"
        wedge_file = WEDGE_CACHE_DIR / f"{opp_id}.json"
        if not wedge_file.exists():
            log.warning("[%s] No wedge cache found at %s; skipping MVP design.", opp_id, wedge_file)
            continue

        try:
            wedge = WedgeAssessment.model_validate(json.loads(wedge_file.read_text(encoding="utf-8")))
        except Exception as e:
            log.warning("[%s] Failed to parse wedge cache: %s", opp_id, e)
            continue

        mvp = design_mvp(hyp, wedge, client=client, force=force, model=model)
        if mvp:
            results.append(mvp)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage 6: Minimal Wedge-Testing MVP Designer")
    parser.add_argument("--cluster-id", type=int, default=0, help="Cluster ID to analyze")
    parser.add_argument("--force", action="store_true", help="Bypass cache and force re-scoping")
    parser.add_argument("--model", type=str, default=None, help="LLM model override")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    mvps = design_cluster_mvps(args.cluster_id, force=args.force, model=args.model)

    print(f"\nMVP Specs for Cluster {args.cluster_id} ({len(mvps)} surviving candidates):")
    for m in mvps:
        print(f"[{m.opportunity_id}] Workflow: {m.core_workflow}")
        print(f"  Estimate: {m.total_estimate_range} (~{m.estimated_days} days)")
        print(f"  Explicit Non-Features: {', '.join(m.explicit_non_features[:3])}")
        print(f"  Validation Experiment: {m.prebuild_validation_experiment}")
        print()


if __name__ == "__main__":
    main()
