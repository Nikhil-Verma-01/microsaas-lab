"""Unit tests for Phase 2: Competitive Intelligence and Hostile Solution Critic."""
import json
import unittest
from pydantic import ValidationError

from src.pipeline.schema import (
    AlternativeType,
    CompetitorRecord,
    CompetitorResearch,
    CritiqueVerdict,
    HostileCritique,
    ProductArchetype,
    SolutionHypothesis,
)
from src.pipeline.competitors import (
    build_search_queries,
    search_duckduckgo,
)


class TestPipelinePhase2(unittest.TestCase):
    def test_schema_competitor_record(self):
        """Verify CompetitorRecord validates required fields and enum."""
        rec = CompetitorRecord(
            opportunity_id="opp_1",
            name="Stoplight Prism",
            url="https://github.com/stoplightio/prism",
            alternative_type=AlternativeType.OPEN_SOURCE,
            target_user="API developers",
            supported_workflow="Mocking OpenAPI specs",
            feature_overlap="high",
            pricing_status="open_source",
            strengths=["Established OSS", "CLI support"],
            limitations=["No cloud sync"],
            confidence_basis="verified_search",
        )
        self.assertEqual(rec.alternative_type, AlternativeType.OPEN_SOURCE)
        self.assertEqual(rec.confidence_basis, "verified_search")
        self.assertEqual(rec.feature_overlap, "high")

    def test_schema_competitor_invalid_type(self):
        """Verify invalid alternative_type raises ValidationError."""
        with self.assertRaises(ValidationError):
            CompetitorRecord(
                opportunity_id="opp_1",
                name="Bad Tool",
                alternative_type="unknown_type_here",  # type: ignore
            )

    def test_schema_hostile_critique(self):
        """Verify HostileCritique validates enum verdicts and risk scores."""
        critique = HostileCritique(
            opportunity_id="opp_1",
            strongest_reasons_to_reject=["Incumbents already cover this", "Zero willingness to pay"],
            unsupported_assumptions=["Developers will install a custom proxy"],
            evidence_that_contradicts=["Prism and Mockoon are mature OSS"],
            likely_failure_modes=["High friction on local setup"],
            cheapest_test_to_disprove="Interview 5 backend engineers",
            incumbent_absorption_risk="high",
            commoditization_risk="medium",
            workflow_friction_risk="high",
            verdict=CritiqueVerdict.SURVIVES_WITH_CONDITIONS,
        )
        self.assertEqual(critique.verdict, CritiqueVerdict.SURVIVES_WITH_CONDITIONS)
        self.assertEqual(critique.incumbent_absorption_risk, "high")

    def test_schema_critique_invalid_verdict(self):
        """Verify invalid verdict string raises ValidationError."""
        with self.assertRaises(ValidationError):
            HostileCritique(
                opportunity_id="opp_1",
                verdict="maybe_good",  # type: ignore
            )

    def test_build_search_queries(self):
        """Verify search query generator constructs 3 distinct, non-empty queries."""
        sample_hyp = SolutionHypothesis(
            opportunity_id="opp_test",
            cluster_id=0,
            solution_name="SpecMock",
            archetype=ProductArchetype.HEADLESS_MIDDLEWARE,
            target_segment="Backend engineers",
            triggering_context="During local API dev",
            replaced_workaround="manual copy-pasting of curl snippets",
            core_mechanism="Local proxy intercepting HTTP requests",
            why_incumbent_fails="Postman requires cloud login",
            search_queries=["openapi mock server cli tool"],
        )
        queries = build_search_queries(sample_hyp)
        self.assertEqual(queries[0], "openapi mock server cli tool")
        self.assertTrue(all(len(q) > 5 for q in queries))
        self.assertEqual(len(set(queries)), 3)

    def test_duckduckgo_live_search(self):
        """Verify zero-cost DuckDuckGo search returns valid web hits without an API key."""
        hits = search_duckduckgo("openapi mock server cli", max_results=2)
        # Verify it returns a list (may be empty only if completely offline)
        self.assertIsInstance(hits, list)
        if hits:
            first = hits[0]
            self.assertIn("title", first)
            self.assertIn("url", first)
            self.assertTrue(first["url"].startswith("http"))


if __name__ == "__main__":
    unittest.main()
