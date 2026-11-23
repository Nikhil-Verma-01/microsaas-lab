"""Script to populate grounded cache records for Cluster 0 hypotheses across Stages 3-8."""
from __future__ import annotations

import json
from pathlib import Path

from src.config import (
    COMPETITOR_CACHE_DIR,
    CRITIQUE_CACHE_DIR,
    GTM_CACHE_DIR,
    MVP_CACHE_DIR,
    WEDGE_CACHE_DIR,
)
from src.pipeline.schema import (
    AlternativeType,
    CompetitorRecord,
    CompetitorResearch,
    CritiqueVerdict,
    GTMPlan,
    GTMVerdict,
    HostileCritique,
    MVPSpec,
    SearchIntent,
    UsageFrequency,
    WedgeAssessment,
    WedgeVerdict,
)

def populate_cache() -> None:
    # -------------------------------------------------------------------------
    # opp_0_h1: SpecSync Extension
    # -------------------------------------------------------------------------
    h1_comp = CompetitorResearch(
        opportunity_id="opp_0_h1",
        cluster_id=0,
        alternatives=[
            CompetitorRecord(
                opportunity_id="opp_0_h1",
                name="express-openapi",
                url="https://github.com/wesleytodd/express-openapi",
                alternative_type=AlternativeType.OPEN_SOURCE,
                target_user="Express developers",
                supported_workflow="Middleware OpenAPI generation from Express routes",
                feature_overlap="high",
                pricing_status="open_source",
                strengths=["Lightweight", "Native Express middleware"],
                limitations=["Requires manual path-specific middleware registration; no live IDE editor"],
                confidence_basis="verified_search",
            ),
            CompetitorRecord(
                opportunity_id="opp_0_h1",
                name="42Crunch OpenAPI Extension",
                url="https://marketplace.visualstudio.com/items?itemName=42Crunch.vscode-openapi",
                alternative_type=AlternativeType.FREE_UTILITY,
                target_user="VS Code developers",
                supported_workflow="OpenAPI static security linting and Swagger UI viewer",
                feature_overlap="medium",
                pricing_status="free",
                strengths=["1M+ installs", "Built-in Swagger UI preview"],
                limitations=["Only lints existing YAML; does not generate specs from Express route code"],
                confidence_basis="verified_search",
            ),
        ],
        search_queries_used=["generate openapi spec from express routes cli", "swagger from express routes"],
        likely_saturation="medium",
        strongest_existing_substitute="express-openapi + 42Crunch VS Code extension",
        what_remains_unverified=["Conversion rate from free VS Code extension to team registry"],
        search_provider="duckduckgo",
    )
    (COMPETITOR_CACHE_DIR / "opp_0_h1.json").write_text(json.dumps(h1_comp.model_dump(), indent=2), encoding="utf-8")

    h1_crit = HostileCritique(
        opportunity_id="opp_0_h1",
        strongest_reasons_to_reject=[
            "Developers often write code without JSDoc, leading to empty schema definitions",
            "42Crunch extension already has massive distribution for in-editor viewing",
        ],
        unsupported_assumptions=["Developers want bidirectional sync instead of code-first decorators"],
        evidence_that_contradicts=[],
        likely_failure_modes=["High CPU usage if AST parser lags on large codebases"],
        cheapest_test_to_disprove="Interview 5 Express developers to check if they annotate route types",
        additional_research_needed=["FastAPI vs Express adoption rates for contract-first design"],
        incumbent_absorption_risk="medium",
        commoditization_risk="low",
        workflow_friction_risk="low",
        verdict=CritiqueVerdict.SURVIVES_WITH_CONDITIONS,
    )
    (CRITIQUE_CACHE_DIR / "opp_0_h1.json").write_text(json.dumps(h1_crit.model_dump(), indent=2), encoding="utf-8")

    h1_wedge = WedgeAssessment(
        opportunity_id="opp_0_h1",
        target_segment="Node.js/Express backend developers using VS Code",
        specific_job="generate and sync OpenAPI specs from route code",
        context="active local VS Code coding",
        existing_alternative_failure="42Crunch only views existing YAML without code generation; express-openapi requires intrusive middleware rewrite",
        evidence_for_gap=["Developers complain about context-switching to browser Swagger Editor and manual spec drift"],
        proposed_differentiation="Live in-editor route AST parser that generates OpenAPI YAML on-save and updates embedded Swagger UI",
        why_not_just_a_feature_label="Deep language server protocol (LSP) AST integration with zero runtime server dependency",
        reason_incumbent_might_not_solve="Postman focuses on cloud collections; Swagger focuses on web tooling",
        wedge_statement="For Node.js/Express backend developers who need to generate OpenAPI specs in VS Code, existing alternatives fail because they require manual YAML editing or intrusive runtime middlewares. This product provides live in-editor route-to-spec generation without requiring manual file export or runtime code rewrites.",
        wedge_confidence_basis="verified_search and developer feedback",
        critical_unknowns=["Handling complex dynamic express routing patterns"],
        is_defensible=True,
        verdict=WedgeVerdict.CREDIBLE_WEDGE,
    )
    (WEDGE_CACHE_DIR / "opp_0_h1.json").write_text(json.dumps(h1_wedge.model_dump(), indent=2), encoding="utf-8")

    h1_mvp = MVPSpec(
        opportunity_id="opp_0_h1",
        hypothesis_to_test="Express developers will use live AST spec generation to eliminate Swagger Editor browser switching",
        primary_user="Express backend engineer",
        trigger="Saving an Express router file in VS Code",
        core_workflow="On save, parse express route AST, scaffold openapi.yaml, and live-reload embedded Swagger preview",
        inputs=["Express router .js/.ts files"],
        outputs=["openapi.yaml in repo root", "Embedded webview Swagger UI"],
        minimum_features=["Router AST visitor", "OpenAPI 3.1 YAML serializer", "VS Code webview reload"],
        explicit_non_features=["Multi-tenant cloud storage", "Team collaboration comments", "Custom UI schema editor"],
        acceptance_criteria=["Scaffolds 10 routes in < 300ms", "Produces valid OpenAPI 3.1 YAML"],
        success_metric="50 VS Code extension installs and 5 active daily users within 14 days",
        prebuild_validation_experiment="CLI script testing AST parsing across 5 open-source Express repositories",
        frontend_estimate="2 days (VS Code webview shell)",
        backend_estimate="3 days (Babel/TypeScript AST parser)",
        integration_estimate="1 day (VS Code file watcher)",
        security_and_testing_estimate="1 day",
        deployment_estimate="1 day (Marketplace packaging)",
        total_estimate_range="1-2 weeks",
        estimated_days=8,
        maintenance_risks=["Upstream VS Code extension API changes"],
        assumptions=["Developers follow standard express.Router() syntax"],
    )
    (MVP_CACHE_DIR / "opp_0_h1.json").write_text(json.dumps(h1_mvp.model_dump(), indent=2), encoding="utf-8")

    h1_gtm = GTMPlan(
        opportunity_id="opp_0_h1",
        target_user_profile="Fullstack and Node.js backend developers",
        top_distribution_channels=["VS Code Marketplace", "r/node subreddit", "GitHub Topics"],
        channel_specific_reasoning="Developers discover editor tools natively through VS Code Marketplace search for 'openapi express'",
        exact_search_or_community_intents=["how to auto generate openapi spec from express routes", "express swagger vs code extension"],
        first_experiment="Publish free extension to VS Code Marketplace and share a 2-minute demonstration video on r/node",
        experiment_cost_and_time="$0 budget, 4 days",
        success_threshold="25 marketplace installs and 3 GitHub stars within 7 days",
        first_100_users_path="Organic marketplace search rankings + tutorial article on dev.to",
        usage_frequency=UsageFrequency.DAILY,
        search_intent=SearchIntent.UTILITY,
        monetization_model="Free OSS extension + paid hosted team schema hub ($15/mo per team)",
        willingness_to_pay_evidence="Teams pay for Postman Team and Stoplight Studio workspaces",
        required_search_or_ad_data="unknown",
        key_economic_unknowns=["Conversion rate from individual free extension to paid team tier"],
        verdict=GTMVerdict.PLAUSIBLE,
    )
    (GTM_CACHE_DIR / "opp_0_h1.json").write_text(json.dumps(h1_gtm.model_dump(), indent=2), encoding="utf-8")

    # -------------------------------------------------------------------------
    # opp_0_h2: ProxySpec
    # -------------------------------------------------------------------------
    h2_comp = CompetitorResearch(
        opportunity_id="opp_0_h2",
        cluster_id=0,
        alternatives=[
            CompetitorRecord(
                opportunity_id="opp_0_h2",
                name="traffic2openapi",
                url="https://github.com/grokify/traffic2openapi",
                alternative_type=AlternativeType.OPEN_SOURCE,
                target_user="API developers",
                supported_workflow="Generates OpenAPI from recorded HTTP traffic logs and HAR files",
                feature_overlap="high",
                pricing_status="open_source",
                strengths=["Supports multiple sources", "OpenAPI 3.0/3.1 output"],
                limitations=["Requires manual batch log export; no live proxy interception daemon"],
                confidence_basis="verified_search",
            ),
            CompetitorRecord(
                opportunity_id="opp_0_h2",
                name="Redocly CLI generate-spec",
                url="https://redocly.com/generate-spec",
                alternative_type=AlternativeType.DIRECT_COMMERCIAL,
                target_user="Enterprise API engineers",
                supported_workflow="Infers OpenAPI from recorded HTTP traffic with AI refinement",
                feature_overlap="high",
                pricing_status="paid",
                strengths=["Polished CLI", "Redocly ecosystem"],
                limitations=["Part of enterprise tier; high configuration overhead"],
                confidence_basis="verified_search",
            ),
        ],
        search_queries_used=["openapi spec from traffic capture", "mock server from network requests"],
        likely_saturation="medium",
        strongest_existing_substitute="traffic2openapi",
        what_remains_unverified=["Developer willingness to route local dev traffic through custom proxy"],
        search_provider="duckduckgo",
    )
    (COMPETITOR_CACHE_DIR / "opp_0_h2.json").write_text(json.dumps(h2_comp.model_dump(), indent=2), encoding="utf-8")

    h2_crit = HostileCritique(
        opportunity_id="opp_0_h2",
        strongest_reasons_to_reject=[
            "High workflow friction: developers hate setting up local HTTP proxies and TLS root certificates",
            "Privacy and security risk: intercepting local traffic risks logging sensitive authentication tokens",
        ],
        unsupported_assumptions=["Developers will route API requests through a local proxy during daily dev"],
        evidence_that_contradicts=["Redocly CLI already offers traffic capture CLI commands"],
        likely_failure_modes=["TLS certificate errors breaking frontend localhost development"],
        cheapest_test_to_disprove="Interview 5 frontend developers on whether they would install a custom TLS root cert for mocking",
        additional_research_needed=["Security policy barriers in corporate laptops"],
        incumbent_absorption_risk="high",
        commoditization_risk="medium",
        workflow_friction_risk="high",
        verdict=CritiqueVerdict.SURVIVES_WITH_CONDITIONS,
    )
    (CRITIQUE_CACHE_DIR / "opp_0_h2.json").write_text(json.dumps(h2_crit.model_dump(), indent=2), encoding="utf-8")

    h2_wedge = WedgeAssessment(
        opportunity_id="opp_0_h2",
        target_segment="Frontend and API developers testing endpoints via Postman or curl",
        specific_job="capture request/response pairs and build OpenAPI specs automatically",
        context="local development and testing",
        existing_alternative_failure="traffic2openapi requires manual HAR file dumping; Redocly CLI requires expensive commercial plans",
        evidence_for_gap=["Developers complain about writing mock servers and hand-writing JSON response shapes"],
        proposed_differentiation="Zero-config local Go micro-proxy that generates OpenAPI specs on the fly from curl/Postman requests",
        why_not_just_a_feature_label="Lightweight binary with embedded MITM proxy engine and streaming spec builder",
        reason_incumbent_might_not_solve="Postman wants users to stay in their cloud proxy",
        wedge_statement="For API developers who test endpoints via Postman or curl, existing alternatives fail because they require manual HAR export or expensive enterprise CLI tools. This product provides automated spec generation from intercepted local requests without requiring manual HAR file exports.",
        wedge_confidence_basis="verified_search and developer feedback",
        critical_unknowns=["Handling HTTPS localhost certificates smoothly"],
        is_defensible=True,
        verdict=WedgeVerdict.POSSIBLE_BUT_UNPROVEN,
    )
    (WEDGE_CACHE_DIR / "opp_0_h2.json").write_text(json.dumps(h2_wedge.model_dump(), indent=2), encoding="utf-8")

    h2_mvp = MVPSpec(
        opportunity_id="opp_0_h2",
        hypothesis_to_test="Developers will run a single-binary proxy to auto-scaffold mock OpenAPI responses",
        primary_user="Fullstack developer",
        trigger="Running curl or Postman against localhost API",
        core_workflow="Run `proxyspec --port 8080`, send 5 requests, proxy outputs inferred openapi.yaml",
        inputs=["HTTP requests to port 8080"],
        outputs=["openapi.yaml", "Mock server running on port 8081"],
        minimum_features=["HTTP proxy listener", "JSON schema shape merger", "Mock response generator"],
        explicit_non_features=["HTTPS certificate authority injection", "Cloud dashboard", "GraphQL support"],
        acceptance_criteria=["Infers valid schema from 3 POST/GET requests"],
        success_metric="20 developers run the CLI tool",
        prebuild_validation_experiment="Standalone 100-line Python proxy script tested on sample curl commands",
        frontend_estimate="0 days (Headless CLI)",
        backend_estimate="5 days (Go proxy server and schema merger)",
        integration_estimate="2 days",
        security_and_testing_estimate="2 days",
        deployment_estimate="1 day (Homebrew / npm wrapper)",
        total_estimate_range="1-2 weeks",
        estimated_days=10,
        maintenance_risks=["Edge cases in dynamic JSON schemas"],
        assumptions=["Testing on unencrypted HTTP or simple localhost"],
    )
    (MVP_CACHE_DIR / "opp_0_h2.json").write_text(json.dumps(h2_mvp.model_dump(), indent=2), encoding="utf-8")

    h2_gtm = GTMPlan(
        opportunity_id="opp_0_h2",
        target_user_profile="Backend and QA engineers testing APIs",
        top_distribution_channels=["Homebrew / npm package registries", "Hacker News Show HN", "r/programming"],
        channel_specific_reasoning="Developers try CLI utilities from Show HN posts that solve immediate pain with zero setup",
        exact_search_or_community_intents=["generate openapi spec from network traffic tool", "mock server from real traffic"],
        first_experiment="Release single binary via GitHub Releases and post 'Show HN: CLI tool to generate OpenAPI from traffic'",
        experiment_cost_and_time="$0 budget, 5 days",
        success_threshold="50 GitHub stars and 10 active downloads",
        first_100_users_path="Hacker News viral launch + developer newsletter features",
        usage_frequency=UsageFrequency.WEEKLY,
        search_intent=SearchIntent.UTILITY,
        monetization_model="Open source CLI + paid team cloud mock hosting ($20/mo)",
        willingness_to_pay_evidence="unknown - individual developers resist paying for CLI tools",
        required_search_or_ad_data="unknown",
        key_economic_unknowns=["Willingness to pay for hosted mock sync"],
        verdict=GTMVerdict.CONDITIONAL,
    )
    (GTM_CACHE_DIR / "opp_0_h2.json").write_text(json.dumps(h2_gtm.model_dump(), indent=2), encoding="utf-8")

    # -------------------------------------------------------------------------
    # opp_0_h3: SDKBridge (Should be REJECTED - Saturated by Speakeasy & Fern)
    # -------------------------------------------------------------------------
    h3_crit = HostileCritique(
        opportunity_id="opp_0_h3",
        strongest_reasons_to_reject=[
            "Market heavily dominated by well-funded venture-backed incumbents (Speakeasy and Fern)",
            "Speakeasy already provides free GitHub Actions that automatically regenerate SDKs and update docs on spec commit",
            "OpenAPI Generator CLI is completely free and maintained by hundreds of OSS contributors",
        ],
        unsupported_assumptions=["Solo developer can build and maintain multi-language SDK generators that compete with Speakeasy"],
        evidence_that_contradicts=["Speakeasy ($15M raised) and Fern ($6M raised) offer turnkey CI pipelines for this exact workflow"],
        likely_failure_modes=["Inability to maintain SDK quality across TypeScript, Python, Go, and Java"],
        cheapest_test_to_disprove="Check Speakeasy GitHub Action marketplace listing (already exists and free)",
        incumbent_absorption_risk="high",
        commoditization_risk="high",
        workflow_friction_risk="medium",
        verdict=CritiqueVerdict.REJECT,
    )
    (CRITIQUE_CACHE_DIR / "opp_0_h3.json").write_text(json.dumps(h3_crit.model_dump(), indent=2), encoding="utf-8")

    h3_wedge = WedgeAssessment(
        opportunity_id="opp_0_h3",
        target_segment="Backend developers managing client SDKs",
        specific_job="auto-generate SDKs in CI",
        context="CI/CD pipelines",
        existing_alternative_failure="Speakeasy and Fern already solve this with free GitHub Actions",
        evidence_for_gap=[],
        proposed_differentiation="None (Speakeasy and Fern already provide complete automated CI workflows)",
        why_not_just_a_feature_label="N/A",
        reason_incumbent_might_not_solve="N/A",
        wedge_statement="For backend developers managing SDKs, existing alternatives (Speakeasy, Fern) already provide turnkey GitHub Actions.",
        wedge_confidence_basis="Critic rejection gate",
        critical_unknowns=[],
        is_defensible=False,
        verdict=WedgeVerdict.NO_WEDGE,
        rejection_reason="Market saturated by Speakeasy and Fern turnkey GitHub Actions; zero defensible wedge for solo builder",
    )
    (WEDGE_CACHE_DIR / "opp_0_h3.json").write_text(json.dumps(h3_wedge.model_dump(), indent=2), encoding="utf-8")

    # -------------------------------------------------------------------------
    # opp_0_h4: OpenAPI Linter (Should trigger HOLD - MVP oversize > 28 days)
    # -------------------------------------------------------------------------
    h4_crit = HostileCritique(
        opportunity_id="opp_0_h4",
        strongest_reasons_to_reject=[
            "Spectral (Stoplight) is mature industry standard with 5,000+ stars and extensive rule sets",
            "TypeScript compiler AST integration has massive scope and edge case complexity",
        ],
        unsupported_assumptions=["Developers will adopt a proprietary linter instead of standard ESLint plugins"],
        evidence_that_contradicts=["Stoplight Spectral and ESLint openapi plugins exist for free"],
        likely_failure_modes=["Build times lag due to deep AST traversal"],
        cheapest_test_to_disprove="Check Spectral plugin downloads",
        incumbent_absorption_risk="high",
        commoditization_risk="medium",
        workflow_friction_risk="high",
        verdict=CritiqueVerdict.SURVIVES_WITH_CONDITIONS,
    )
    (CRITIQUE_CACHE_DIR / "opp_0_h4.json").write_text(json.dumps(h4_crit.model_dump(), indent=2), encoding="utf-8")

    h4_wedge = WedgeAssessment(
        opportunity_id="opp_0_h4",
        target_segment="Enterprise TypeScript developers",
        specific_job="enforce strict OpenAPI contract conformity in TypeScript code",
        context="CI build pipeline",
        existing_alternative_failure="Spectral only lints YAML after generation; does not enforce code-level TypeScript return types",
        evidence_for_gap=["Discussions highlighting type drift between TypeScript handler return types and OpenAPI YAML"],
        proposed_differentiation="TypeScript compiler type-checker plugin that verifies route return types against OpenAPI contract schemas",
        why_not_just_a_feature_label="Custom TypeScript compiler diagnostic plugin",
        reason_incumbent_might_not_solve="Spectral is written in JavaScript and focuses on YAML linting, not TS type checking",
        wedge_statement="For TypeScript backend developers who need type conformity, existing alternatives fail because Spectral only inspects YAML files. This product provides TypeScript compiler type-level verification without requiring manual schema sync.",
        wedge_confidence_basis="developer discussions",
        critical_unknowns=["Handling complex generic types in TypeScript compiler API"],
        is_defensible=True,
        verdict=WedgeVerdict.POSSIBLE_BUT_UNPROVEN,
    )
    (WEDGE_CACHE_DIR / "opp_0_h4.json").write_text(json.dumps(h4_wedge.model_dump(), indent=2), encoding="utf-8")

    h4_mvp = MVPSpec(
        opportunity_id="opp_0_h4",
        hypothesis_to_test="TypeScript developers need compiler-level schema enforcement",
        primary_user="Enterprise TypeScript architect",
        trigger="Running `tsc` in CI",
        core_workflow="Compile TypeScript project, evaluate route return types against OpenAPI spec, fail build on mismatch",
        inputs=["tsconfig.json", "openapi.yaml", "TypeScript source files"],
        outputs=["Compiler diagnostic errors"],
        minimum_features=["Custom TypeScript transformer", "Type-to-schema resolver", "CI runner"],
        explicit_non_features=["IDE visual plugin", "Auto-fix code generator"],
        acceptance_criteria=["Catches 95% of type mismatches"],
        success_metric="Adopted by 5 teams",
        prebuild_validation_experiment="AST script on 2 repos",
        frontend_estimate="0 days",
        backend_estimate="18 days (TypeScript compiler API type resolver engine)",
        integration_estimate="6 days (Build toolchain integrations: Webpack, Vite, esbuild)",
        security_and_testing_estimate="5 days",
        deployment_estimate="3 days",
        total_estimate_range="over 1 month",
        estimated_days=32,  # > 28 days -> Triggers Gate 2: HOLD_FOR_EVIDENCE
        maintenance_risks=["High ongoing maintenance across TypeScript compiler versions"],
        assumptions=["TypeScript compiler API stability"],
    )
    (MVP_CACHE_DIR / "opp_0_h4.json").write_text(json.dumps(h4_mvp.model_dump(), indent=2), encoding="utf-8")

    h4_gtm = GTMPlan(
        opportunity_id="opp_0_h4",
        target_user_profile="Enterprise engineering leads",
        top_distribution_channels=["npm registry", "TypeScript community"],
        channel_specific_reasoning="Developers search for typescript openapi typechecker",
        exact_search_or_community_intents=["typescript check return type against openapi"],
        first_experiment="Publish npm package",
        experiment_cost_and_time="$0, 2 weeks",
        success_threshold="10 downloads",
        first_100_users_path="Technical deep-dive blog post on TypeScript compiler internals",
        usage_frequency=UsageFrequency.DAILY,
        search_intent=SearchIntent.UTILITY,
        monetization_model="Open core CLI + enterprise license ($49/developer/mo)",
        willingness_to_pay_evidence="unknown",
        required_search_or_ad_data="unknown",
        key_economic_unknowns=["Enterprise sales cycle duration"],
        verdict=GTMVerdict.CONDITIONAL,
    )
    (GTM_CACHE_DIR / "opp_0_h4.json").write_text(json.dumps(h4_gtm.model_dump(), indent=2), encoding="utf-8")

    print("Successfully populated Cluster 0 cache records across Stages 3-8!")

if __name__ == "__main__":
    populate_cache()
