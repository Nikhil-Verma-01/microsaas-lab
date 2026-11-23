from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, HttpUrl, model_validator


class ProductTrack(str, Enum):
    DEVELOPER = "developer"
    GENERAL = "general"


class ProductArchetype(str, Enum):
    """Enforced product archetypes to prevent mode collapse into generic web forms."""
    IN_SITU_DEVFLOW = "in_situ_devflow"          # CLI, pre-commit hook, GitHub Action, IDE/LSP plugin
    HEADLESS_MIDDLEWARE = "headless_middleware"  # Micro-proxy, webhook gateway, background sync daemon
    ZERO_DATA_CLIENT_WASM = "zero_data_client_wasm"  # In-browser, client-only WASM/JS utility, zero server persistence
    WORKFLOW_GLUE = "workflow_glue"              # Bi-directional bridge between disjoint tools/APIs
    OPINIONATED_LINTER_SCAFFOLD = "opinionated_linter_scaffold"  # Framework rule validator or scaffold generator
    SPECIALIZED_CLI = "specialized_cli"          # High-performance focused terminal utility
    WEB_UTILITY = "web_utility"
    CALCULATOR = "calculator"
    BROWSER_EXTENSION = "browser_extension"
    WORKFLOW_AUTOMATION = "workflow_automation"


class EvidenceRecord(BaseModel):
    """Normalized evidence record linking to an empirical developer statement."""
    doc_id: str
    quote: str
    user_type: str = "developer"
    pain_level: int = Field(default=3, ge=1, le=5)
    source: str = ""
    url: str = ""
    author: str = ""
    created_at: str = ""


class ProblemContext(BaseModel):
    """Normalized context for a validated problem cluster passed into hypothesis generation."""
    cluster_id: int
    cluster_name: str
    member_count: int
    user_types: list[str] = Field(default_factory=list)
    observed_workarounds: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    evidence_records: list[EvidenceRecord] = Field(default_factory=list)


class SolutionHypothesis(BaseModel):
    """A distinct, concrete product hypothesis derived from a validated problem."""
    opportunity_id: str
    cluster_id: int
    track: ProductTrack | None = None
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    solution_name: str
    archetype: ProductArchetype
    target_segment: str
    triggering_context: str
    replaced_workaround: str
    core_mechanism: str
    why_incumbent_fails: str
    key_assumptions: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    likely_failure_modes: list[str] = Field(default_factory=list)


class HypothesisSet(BaseModel):
    """A set of 3-5 diverse solution hypotheses for a single problem cluster."""
    cluster_id: int
    cluster_name: str
    track: ProductTrack | None = None
    hypotheses: list[SolutionHypothesis] = Field(..., max_length=5)

    @model_validator(mode="after")
    def validate_hypothesis_count(self) -> HypothesisSet:
        if self.track == ProductTrack.GENERAL:
            if len(self.hypotheses) > 3:
                raise ValueError("General track accepts up to three hypotheses")
        elif len(self.hypotheses) < 3:
            raise ValueError("Developer hypothesis sets require at least three hypotheses")
        return self


# ---------------------------------------------------------------------------
# Downstream Schema Stubs (Phases 2-4)
# ---------------------------------------------------------------------------

class AlternativeType(str, Enum):
    DIRECT_COMMERCIAL = "direct_commercial"
    OPEN_SOURCE = "open_source"
    FREE_UTILITY = "free_utility"
    NATIVE_PLATFORM = "native_platform"
    GENERAL_PURPOSE = "general_purpose"
    MANUAL_WORKAROUND = "manual_workaround"


class CompetitorRecord(BaseModel):
    opportunity_id: str
    name: str
    url: str = ""
    alternative_type: AlternativeType
    target_user: str = ""
    supported_workflow: str = ""
    feature_overlap: str = "medium"  # low | medium | high | unknown
    pricing_status: str = "unknown"   # free | paid | open_source | bundled | unknown
    strengths: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence_basis: str = "verified_search"  # verified_search | llm_memory | unknown


class CompetitorResearch(BaseModel):
    opportunity_id: str
    cluster_id: int
    alternatives: list[CompetitorRecord] = Field(default_factory=list)
    search_queries_used: list[str] = Field(default_factory=list)
    likely_saturation: str = "unknown"  # low | medium | high | unknown
    strongest_existing_substitute: str = ""
    what_remains_unverified: list[str] = Field(default_factory=list)
    search_provider: str = "duckduckgo"  # "duckduckgo" | "brave" | "llm_only"


class CritiqueVerdict(str, Enum):
    SURVIVES = "survives"
    SURVIVES_WITH_CONDITIONS = "survives_with_conditions"
    NEEDS_EVIDENCE = "needs_evidence"
    REJECT = "reject"


class HostileCritique(BaseModel):
    opportunity_id: str
    strongest_reasons_to_reject: list[str] = Field(default_factory=list)
    unsupported_assumptions: list[str] = Field(default_factory=list)
    evidence_that_contradicts: list[str] = Field(default_factory=list)
    likely_failure_modes: list[str] = Field(default_factory=list)
    cheapest_test_to_disprove: str = ""
    additional_research_needed: list[str] = Field(default_factory=list)
    incumbent_absorption_risk: str = "medium"  # low | medium | high
    commoditization_risk: str = "medium"       # low | medium | high
    workflow_friction_risk: str = "medium"     # low | medium | high
    verdict: CritiqueVerdict = CritiqueVerdict.NEEDS_EVIDENCE


class WedgeVerdict(str, Enum):
    CREDIBLE_WEDGE = "credible_wedge"
    POSSIBLE_BUT_UNPROVEN = "possible_but_unproven"
    NO_WEDGE = "no_wedge"


class WedgeAssessment(BaseModel):
    opportunity_id: str
    target_segment: str
    specific_job: str = ""
    context: str = ""
    existing_alternative_failure: str
    evidence_for_gap: list[str] = Field(default_factory=list)
    proposed_differentiation: str = ""
    why_not_just_a_feature_label: str = ""
    reason_incumbent_might_not_solve: str = ""
    wedge_statement: str
    wedge_confidence_basis: str = ""
    critical_unknowns: list[str] = Field(default_factory=list)
    is_defensible: bool = True
    verdict: WedgeVerdict = WedgeVerdict.CREDIBLE_WEDGE
    rejection_reason: Optional[str] = None


class MVPSpec(BaseModel):
    opportunity_id: str
    hypothesis_to_test: str = ""
    primary_user: str = ""
    trigger: str = ""
    core_workflow: str
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    minimum_features: list[str] = Field(default_factory=list)
    explicit_non_features: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    success_metric: str = ""
    prebuild_validation_experiment: str = ""
    frontend_estimate: str = "1-2 days"
    backend_estimate: str = "2-3 days"
    integration_estimate: str = "1-2 days"
    security_and_testing_estimate: str = "1-2 days"
    deployment_estimate: str = "1 day"
    total_estimate_range: str = "1-2 weeks"
    estimated_days: int = 7
    maintenance_risks: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class UsageFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    OCCASIONAL = "occasional"
    ONE_TIME = "one_time"
    UNKNOWN = "unknown"


class SearchIntent(str, Enum):
    INFORMATIONAL = "informational"
    UTILITY = "utility"
    TRANSACTIONAL = "transactional"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class GTMVerdict(str, Enum):
    PLAUSIBLE = "plausible"
    CONDITIONAL = "conditional"
    WEAK = "weak"
    UNKNOWN = "unknown"


class GTMPlan(BaseModel):
    opportunity_id: str
    target_user_profile: str
    top_distribution_channels: list[str] = Field(default_factory=list)
    channel_specific_reasoning: str = ""
    exact_search_or_community_intents: list[str] = Field(default_factory=list)
    first_experiment: str = ""
    experiment_cost_and_time: str = ""
    success_threshold: str = ""
    first_100_users_path: str = ""
    usage_frequency: UsageFrequency = UsageFrequency.UNKNOWN
    search_intent: SearchIntent = SearchIntent.UNKNOWN
    monetization_model: str = ""
    willingness_to_pay_evidence: str = ""
    required_search_or_ad_data: str = ""
    key_economic_unknowns: list[str] = Field(default_factory=list)
    verdict: GTMVerdict = GTMVerdict.UNKNOWN


class DecisionStatus(str, Enum):
    RANK = "rank"
    HOLD_FOR_EVIDENCE = "hold_for_evidence"
    REJECTED = "rejected"


class MarketEvidence(BaseModel):
    """A user-reviewed observation about demand for a specific opportunity."""
    basis: Literal["paid_demand", "search_demand"]
    url: HttpUrl
    observation: str = Field(min_length=1)


class DecisionGate(BaseModel):
    opportunity_id: str
    solution_name: str = ""
    cluster_id: int = 0
    status: DecisionStatus
    opportunity_score: float
    component_scores: dict[str, float] = Field(default_factory=dict)
    rejection_reasons: list[str] = Field(default_factory=list)
    wedge_verdict: str = ""
    gtm_verdict: str = ""
    mvp_days: int = 0
    scored_at: str = ""
