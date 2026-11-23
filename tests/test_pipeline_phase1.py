"""Unit tests for Phase 1: Data Contracts and Multi-Archetype Hypothesis Generation."""
import json
import unittest
from pydantic import ValidationError

from src.config import CLUSTERS_PATH, PROBLEMS_PATH, LLM_API_KEY, LLM_BASE_URL, LLM_TIMEOUT
from src.pipeline.schema import (
    EvidenceRecord,
    HypothesisSet,
    ProblemContext,
    ProductArchetype,
    SolutionHypothesis,
)
from src.pipeline.hypothesize import (
    build_problem_context,
    generate_hypotheses_for_cluster,
)
from openai import OpenAI


class TestPipelinePhase1(unittest.TestCase):
    def test_schema_valid_hypothesis(self):
        """Verify that SolutionHypothesis validates valid archetypes."""
        hyp = SolutionHypothesis(
            opportunity_id="opp_1",
            cluster_id=0,
            solution_name="SpecMock CLI",
            archetype=ProductArchetype.IN_SITU_DEVFLOW,
            target_segment="Backend engineers",
            triggering_context="During local development",
            replaced_workaround="Manual stubbing with Express",
            core_mechanism="Parses OpenAPI spec and generates local mock server",
            why_incumbent_fails="Postman requires cloud sync and account login",
            key_assumptions=["OpenAPI 3.x support"],
            search_queries=["openapi local mock server cli"],
            likely_failure_modes=["Spec complexity edge cases"],
        )
        self.assertEqual(hyp.archetype, ProductArchetype.IN_SITU_DEVFLOW)
        self.assertEqual(hyp.solution_name, "SpecMock CLI")

    def test_schema_invalid_archetype(self):
        """Verify that invalid archetype strings raise a ValidationError."""
        with self.assertRaises(ValidationError):
            SolutionHypothesis(
                opportunity_id="opp_bad",
                cluster_id=0,
                solution_name="Bad App",
                archetype="generic_web_app",  # type: ignore
                target_segment="Devs",
                triggering_context="Now",
                replaced_workaround="None",
                core_mechanism="Does stuff",
                why_incumbent_fails="None",
            )

    def test_schema_hypothesis_set_bounds(self):
        """Verify that HypothesisSet enforces between 3 and 5 hypotheses."""
        sample_hyp = SolutionHypothesis(
            opportunity_id="opp_1",
            cluster_id=0,
            solution_name="Tool",
            archetype=ProductArchetype.SPECIALIZED_CLI,
            target_segment="Devs",
            triggering_context="CI",
            replaced_workaround="Scripts",
            core_mechanism="Transforms data",
            why_incumbent_fails="None",
        )

        with self.assertRaises(ValidationError):
            HypothesisSet(
                cluster_id=0,
                cluster_name="Test",
                hypotheses=[sample_hyp, sample_hyp],
            )

        valid_set = HypothesisSet(
            cluster_id=0,
            cluster_name="Test",
            hypotheses=[sample_hyp, sample_hyp, sample_hyp],
        )
        self.assertEqual(len(valid_set.hypotheses), 3)

    def test_build_problem_context(self):
        """Verify build_problem_context normalizes evidence records properly."""
        cluster = {
            "id": 99,
            "name": "Test Cluster",
            "member_count": 2,
            "user_types": ["backend devs"],
            "sample_workarounds": ["manual curl"],
            "search_queries": ["openapi curl generator"],
        }
        problems = [
            {
                "doc_id": "github:101",
                "evidence_quote": "I hate writing manual curl examples",
                "user_type": "backend devs",
                "pain_level": 4,
            }
        ]
        ctx = build_problem_context(cluster, problems)
        self.assertEqual(ctx.cluster_id, 99)
        self.assertEqual(len(ctx.evidence_records), 1)
        self.assertEqual(ctx.evidence_records[0].pain_level, 4)
        self.assertIn("manual curl", ctx.evidence_records[0].quote)

    def test_generate_hypotheses_cluster_0_anti_drift(self):
        """Live verification on Cluster 0: ensure OpenAPI focus and archetype diversity."""
        if not CLUSTERS_PATH.exists() or not PROBLEMS_PATH.exists():
            self.skipTest("Data files missing")

        clusters_data = json.loads(CLUSTERS_PATH.read_text(encoding="utf-8"))
        cluster_0 = next((c for c in clusters_data["clusters"] if c["id"] == 0), None)
        if not cluster_0:
            self.skipTest("Cluster 0 not found")

        problems_by_id = {}
        for line in PROBLEMS_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                p = json.loads(line)
                problems_by_id[p["doc_id"]] = p

        member_probs = [problems_by_id[m] for m in cluster_0["members"] if m in problems_by_id]

        client_kwargs = {"api_key": LLM_API_KEY, "timeout": LLM_TIMEOUT}
        if LLM_BASE_URL:
            client_kwargs["base_url"] = LLM_BASE_URL
        client = OpenAI(**client_kwargs)

        res = generate_hypotheses_for_cluster(cluster_0, member_probs, client, force=False)
        self.assertIsNotNone(res, "Hypothesis generation failed for Cluster 0")
        self.assertGreaterEqual(len(res.hypotheses), 3, "Expected at least 3 hypotheses")

        # Verify archetype diversity
        archetypes = {h.archetype for h in res.hypotheses}
        self.assertGreaterEqual(len(archetypes), 2, f"Archetypes lack diversity: {archetypes}")

        # Verify anti-drift: none should hallucinate CSVForge or CSV parsers
        for h in res.hypotheses:
            combined = f"{h.solution_name} {h.core_mechanism} {h.triggering_context}".lower()
            self.assertNotIn("csv", combined, f"Evidence drift detected! Solution mentioned CSV: {h.solution_name}")
            has_api_theme = any(
                term in combined
                for term in ["api", "spec", "openapi", "swagger", "mock", "sdk", "endpoint", "curl"]
            )
            self.assertTrue(has_api_theme, f"Solution not anchored in API domain: {h.solution_name}")


if __name__ == "__main__":
    unittest.main()
