import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.discover import discussion_key
from src.extract import extract_one
from src.pipeline.decision import score_opportunity
from src.pipeline.hypothesize import generate_hypotheses_for_cluster
from src.pipeline.schema import (
    CompetitorRecord, CompetitorResearch, DecisionStatus, EvidenceRecord, GTMPlan,
    HostileCritique, MarketEvidence, MVPSpec, ProductTrack, SolutionHypothesis, WedgeAssessment,
)


class DiscoveryTrackTests(unittest.TestCase):
    def test_extraction_drops_unmatched_quote_and_separates_track_caches(self):
        doc = {
            "id": "web:1", "text": "I spend hours sorting clips.", "author": "a",
            "url": "https://example.com/1",
        }
        client = MagicMock()
        response = client.chat.completions.create.return_value
        response.choices[0].message.content = json.dumps({
            "is_real_problem": True, "tool_shaped": True, "evidence_quote": "I pay to sort clips.",
        })
        with tempfile.TemporaryDirectory() as temp, patch("src.extract.EXTRACT_CACHE_DIR", Path(temp)), patch("src.extract.time.sleep"):
            rejected_quote = extract_one(doc, client, "test", track=ProductTrack.GENERAL)
            response.choices[0].message.content = json.dumps({"evidence_quote": "I spend hours sorting clips."})
            accepted_quote = extract_one(doc, client, "test", track=ProductTrack.DEVELOPER)
            cached = extract_one(doc, client, "test", track=ProductTrack.GENERAL)
        self.assertEqual(rejected_quote.evidence_quote, "")
        self.assertEqual(cached, rejected_quote)
        self.assertEqual(accepted_quote.evidence_quote, doc["text"])
        self.assertEqual(accepted_quote.author, "a")
        self.assertEqual(accepted_quote.frequency, "unknown")
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_general_track_generates_one_idea_and_holds_without_validation(self):
        cluster = {"id": 1, "name": "Estimate room paint"}
        idea = dict(
            solution_name="Paint estimator", archetype="calculator",
            target_segment="Homeowners", triggering_context="Painting a room",
            replaced_workaround="Manual calculation", core_mechanism="Estimate paint from dimensions",
            why_incumbent_fails="Unknown",
        )
        client = MagicMock()
        client.chat.completions.create.return_value.choices[0].message.content = json.dumps(
            {"hypotheses": [idea]},
        )
        with tempfile.TemporaryDirectory() as temp, patch("src.pipeline.hypothesize.HYPOTHESIS_CACHE_DIR", Path(temp)):
            result = generate_hypotheses_for_cluster(cluster, [], client, track=ProductTrack.GENERAL)
            changed_model = generate_hypotheses_for_cluster(
                cluster, [], client, model="different", track=ProductTrack.GENERAL,
            )
        hypothesis = result.hypotheses[0]
        self.assertEqual(hypothesis.track, ProductTrack.GENERAL)
        self.assertNotEqual(hypothesis.opportunity_id, changed_model.hypotheses[0].opportunity_id)
        wedge = WedgeAssessment(
            opportunity_id=hypothesis.opportunity_id, target_segment=hypothesis.target_segment,
            existing_alternative_failure="Unknown", wedge_statement="Possible paint calculator.",
        )
        decision = score_opportunity(hypothesis, wedge)
        self.assertEqual(decision.status, DecisionStatus.HOLD_FOR_EVIDENCE)
        self.assertEqual(decision.mvp_days, 0)

    def test_reddit_comment_and_thread_have_same_discussion_key(self):
        self.assertEqual(
            discussion_key("https://www.reddit.com/r/example/comments/123/title/xyz/?utm_source=example"),
            discussion_key("https://old.reddit.com/r/example/comments/123/title/"),
        )

    def test_search_demand_can_promote_a_general_tool_only(self):
        key = "opp_test_track"
        idea = SolutionHypothesis(
            opportunity_id=key, cluster_id=1, track=ProductTrack.GENERAL,
            solution_name="Import checker", archetype="web_utility", target_segment="Operators",
            triggering_context="An import fails", replaced_workaround="Manual review",
            core_mechanism="Check rows", why_incumbent_fails="Manual setup",
            evidence=[
                EvidenceRecord(doc_id=str(i), quote="I check failed imports.",
                               source="forum", author=str(i), url=f"https://example.com/{i}")
                for i in range(2)
            ],
        )
        wedge = WedgeAssessment(
            opportunity_id=key, target_segment="Operators",
            existing_alternative_failure="Manual setup", wedge_statement="Check rows without setup.",
        )
        critique = HostileCritique(opportunity_id=key, verdict="survives")
        competitor = CompetitorRecord(
            opportunity_id=key, name="Existing checker", url="https://example.com/tool",
            alternative_type="free_utility",
        )
        competitors = CompetitorResearch(opportunity_id=key, cluster_id=1, alternatives=[competitor])
        mvp = MVPSpec(opportunity_id=key, core_workflow="Check rows", estimated_days=5)
        gtm = GTMPlan(opportunity_id=key, target_user_profile="Operators", verdict="plausible")
        market = MarketEvidence(
            basis="search_demand", url="https://example.com/observations", observation="Observed task searches.",
        )
        for track, expected in (
            (ProductTrack.GENERAL, DecisionStatus.RANK),
            (ProductTrack.DEVELOPER, DecisionStatus.HOLD_FOR_EVIDENCE),
        ):
            candidate = idea.model_copy(update={"track": track})
            decision = score_opportunity(candidate, wedge, critique, competitors, mvp, gtm, market_evidence=market)
            self.assertEqual(decision.status, expected)
