"""Unit tests for Phase 4: Deterministic Scoring Engine and End-to-End Orchestrator."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.pipeline.decision import (
    WEDGE_SCORE,
    apply_kill_gates,
    buildability_score,
    score_opportunity,
)
from src.pipeline.orchestrator import generate_pipeline_reports, run_pipeline_for_cluster
from src.pipeline.schema import (
    AlternativeType,
    CompetitorRecord,
    CompetitorResearch,
    CritiqueVerdict,
    DecisionGate,
    DecisionStatus,
    GTMPlan,
    GTMVerdict,
    HostileCritique,
    MVPSpec,
    ProductArchetype,
    SearchIntent,
    SolutionHypothesis,
    UsageFrequency,
    WedgeAssessment,
    WedgeVerdict,
)


class TestPipelinePhase4(unittest.TestCase):
    def setUp(self) -> None:
        self.hypothesis = SolutionHypothesis(
            opportunity_id="opp_score_001",
            cluster_id=0,
            solution_name="SpecSync Extension",
            archetype=ProductArchetype.IN_SITU_DEVFLOW,
            target_segment="FastAPI backend developers in VS Code",
            triggering_context="Writing routes and OpenAPI schemas",
            replaced_workaround="Manual Swagger Editor editing",
            core_mechanism="In-editor live route generation and linting",
            why_incumbent_fails="Postman requires cloud sync",
            key_assumptions=["Developers use VS Code"],
            search_queries=["openapi vs code extension"],
            likely_failure_modes=["Extension bloat"],
        )

        self.credible_wedge = WedgeAssessment(
            opportunity_id="opp_score_001",
            target_segment="FastAPI backend developers",
            specific_job="live route generation",
            context="VS Code",
            existing_alternative_failure="Postman requires cloud export",
            proposed_differentiation="Live in-editor AST generation",
            why_not_just_a_feature_label="Direct language server protocol integration",
            reason_incumbent_might_not_solve="Postman focuses on web testing",
            wedge_statement="For FastAPI developers who need live sync in VS Code, existing tools fail. SpecSync provides live AST sync without cloud export.",
            is_defensible=True,
            verdict=WedgeVerdict.CREDIBLE_WEDGE,
        )

        self.mvp_spec = MVPSpec(
            opportunity_id="opp_score_001",
            core_workflow="On save, parse openapi.yaml and scaffold route stubs",
            minimum_features=["AST parser", "Route generator", "Watcher"],
            explicit_non_features=["Multi-tenant cloud", "Team comments", "Visual designer"],
            acceptance_criteria=["Scaffolds routes in < 500ms"],
            estimated_days=7,
            total_estimate_range="1-2 weeks",
        )

        self.gtm_plan = GTMPlan(
            opportunity_id="opp_score_001",
            target_user_profile="Python FastAPI developers",
            top_distribution_channels=["VS Code Marketplace", "r/FastAPI"],
            first_experiment="Publish free extension + Loom video on r/FastAPI",
            experiment_cost_and_time="$0, 4 days",
            success_threshold="20 installs",
            usage_frequency=UsageFrequency.DAILY,
            search_intent=SearchIntent.UTILITY,
            monetization_model="Free OSS CLI + paid team schema registry ($19/mo)",
            willingness_to_pay_evidence="Teams pay for shared schema registries like Stoplight/Postman",
            verdict=GTMVerdict.PLAUSIBLE,
        )

        self.critique = HostileCritique(
            opportunity_id="opp_score_001",
            strongest_reasons_to_reject=["Incumbents could release an official extension"],
            unsupported_assumptions=["Developers prefer code generation over manual coding"],
            likely_failure_modes=["Linter latency"],
            incumbent_absorption_risk="medium",
            commoditization_risk="low",
            workflow_friction_risk="low",
            verdict=CritiqueVerdict.SURVIVES_WITH_CONDITIONS,
        )

    def test_wedge_verdict_to_score_mapping(self) -> None:
        """Verify enum mappings match calibrated bounds."""
        self.assertEqual(WEDGE_SCORE["credible_wedge"], 1.0)
        self.assertEqual(WEDGE_SCORE["possible_but_unproven"], 0.55)
        self.assertEqual(WEDGE_SCORE["no_wedge"], 0.0)

        # Buildability function
        self.assertEqual(buildability_score(5), 1.0)
        self.assertEqual(buildability_score(28), 0.0)
        self.assertAlmostEqual(buildability_score(16), 0.5217, places=3)

    def test_kill_gate_no_wedge_rejected(self) -> None:
        """Verify candidate with no_wedge is disqualified with REJECTED status and score 0.0."""
        rejected_wedge = WedgeAssessment(
            opportunity_id="opp_score_001",
            target_segment="Developers",
            existing_alternative_failure="Market saturated",
            wedge_statement="No wedge.",
            is_defensible=False,
            verdict=WedgeVerdict.NO_WEDGE,
            rejection_reason="Completely covered by existing free open-source tools",
        )

        status, reasons = apply_kill_gates(rejected_wedge, self.critique, self.mvp_spec, self.gtm_plan)
        self.assertEqual(status, DecisionStatus.REJECTED)
        self.assertIn("Completely covered", reasons[0])

        decision = score_opportunity(
            self.hypothesis,
            rejected_wedge,
            self.critique,
            None,
            self.mvp_spec,
            self.gtm_plan,
            force=True,
        )
        self.assertEqual(decision.status, DecisionStatus.REJECTED)
        self.assertEqual(decision.opportunity_score, 0.0)

    def test_kill_gate_mvp_oversize(self) -> None:
        """Verify MVP with > 28 days build estimate triggers HOLD_FOR_EVIDENCE."""
        oversized_mvp = MVPSpec(
            opportunity_id="opp_score_001",
            core_workflow="Full API gateway and management console",
            estimated_days=45,  # Exceeds solo builder 28-day limit
        )

        status, reasons = apply_kill_gates(self.credible_wedge, self.critique, oversized_mvp, self.gtm_plan)
        self.assertEqual(status, DecisionStatus.HOLD_FOR_EVIDENCE)
        self.assertIn("exceeds solo builder limit", reasons[0])

        decision = score_opportunity(
            self.hypothesis,
            self.credible_wedge,
            self.critique,
            None,
            oversized_mvp,
            self.gtm_plan,
            force=True,
        )
        self.assertEqual(decision.status, DecisionStatus.HOLD_FOR_EVIDENCE)
        self.assertGreater(decision.opportunity_score, 0.0)

    def test_kill_gate_weak_gtm_no_wtp(self) -> None:
        """Verify weak GTM with unverified WTP triggers HOLD_FOR_EVIDENCE."""
        weak_gtm = GTMPlan(
            opportunity_id="opp_score_001",
            target_user_profile="Generic devs",
            verdict=GTMVerdict.WEAK,
            willingness_to_pay_evidence="unknown - no willingness to pay verified",
        )

        status, reasons = apply_kill_gates(self.credible_wedge, self.critique, self.mvp_spec, weak_gtm)
        self.assertEqual(status, DecisionStatus.HOLD_FOR_EVIDENCE)
        self.assertIn("GTM verdict weak", reasons[0])

    def test_score_ordering_and_components(self) -> None:
        """Verify high-conviction candidate gets ranked with all 7 component scores preserved."""
        decision = score_opportunity(
            self.hypothesis,
            self.credible_wedge,
            self.critique,
            None,
            self.mvp_spec,
            self.gtm_plan,
            force=True,
        )
        self.assertEqual(decision.status, DecisionStatus.RANK)
        self.assertGreater(decision.opportunity_score, 0.50)

        # Check all 7 components are stored
        comps = decision.component_scores
        required_keys = [
            "wedge_strength",
            "evidence_confidence",
            "competition_risk",
            "buildability",
            "distribution_potential",
            "monetization_potential",
            "commoditization_risk",
        ]
        for k in required_keys:
            self.assertIn(k, comps)
            self.assertGreaterEqual(comps[k], 0.0)
            self.assertLessEqual(comps[k], 1.0)

    def test_decision_gate_schema_expansion(self) -> None:
        """Verify expanded fields on DecisionGate serialize and validate properly."""
        decision = DecisionGate(
            opportunity_id="opp_test_schema",
            solution_name="Test Tool",
            cluster_id=0,
            status=DecisionStatus.RANK,
            opportunity_score=0.725,
            component_scores={"wedge_strength": 1.0, "buildability": 0.85},
            wedge_verdict="credible_wedge",
            gtm_verdict="plausible",
            mvp_days=7,
            scored_at="2026-10-10T00:00:00Z",
        )
        self.assertEqual(decision.solution_name, "Test Tool")
        self.assertEqual(decision.mvp_days, 7)
        self.assertEqual(decision.status, DecisionStatus.RANK)

    def test_generate_pipeline_reports(self) -> None:
        """Verify markdown and CSV reports are properly rendered and non-empty."""
        decision = score_opportunity(
            self.hypothesis,
            self.credible_wedge,
            self.critique,
            None,
            self.mvp_spec,
            self.gtm_plan,
            force=True,
        )

        temp_md = Path("data/cache/test_report.md")
        temp_csv = Path("data/cache/test_report.csv")

        generate_pipeline_reports(
            decisions=[decision],
            hypotheses_by_id={decision.opportunity_id: self.hypothesis},
            wedges_by_id={decision.opportunity_id: self.credible_wedge},
            mvps_by_id={decision.opportunity_id: self.mvp_spec},
            gtms_by_id={decision.opportunity_id: self.gtm_plan},
            output_md_path=temp_md,
            output_csv_path=temp_csv,
        )

        self.assertTrue(temp_md.exists())
        self.assertTrue(temp_csv.exists())

        md_content = temp_md.read_text(encoding="utf-8")
        self.assertIn("MicroSaaS Lab -- Ranked Opportunity Dossier", md_content)
        self.assertIn("SpecSync Extension", md_content)
        self.assertIn("Differentiated Wedge Statement", md_content)
        self.assertIn("Deterministic Component Score Breakdown", md_content)

        csv_content = temp_csv.read_text(encoding="utf-8")
        self.assertIn("SpecSync Extension", csv_content)
        self.assertIn("opportunity_score", csv_content)

        # Cleanup test files
        temp_md.unlink(missing_ok=True)
        temp_csv.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
