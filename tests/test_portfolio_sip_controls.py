from decimal import Decimal

import pytest

from core.portfolio_sip_controls import (
    PortfolioInputError,
    build_decision_trace,
    calculate_lookthrough_exposure,
    evaluate_classified_concentration,
    calculate_saa_drift,
    reconcile_total_portfolio,
    route_incremental_sip,
    allocate_candidate_sip,
    screen_candidates_before_scoring,
)


def _asset(asset_id="cas-1", value="100000", asset_class="equity"):
    return {
        "asset_id": asset_id,
        "asset_class": asset_class,
        "value_inr": value,
        "source_ref": "sha256:source",
        "owner_scope": "investor-household",
        "as_of_date": "2026-10-31",
    }




@pytest.mark.parametrize("age", [True, 1.5, "30", -1])
def test_candidate_screening_rejects_invalid_evidence_age(age):
    with pytest.raises(PortfolioInputError, match="non-negative integer"):
        screen_candidates_before_scoring(
            [], as_of_date="2026-11-04", max_evidence_age_days=age,
            mandatory_gates=["direct_plan"],
        )


@pytest.mark.parametrize("gates", ["direct_plan", b"risk", ["direct_plan", ""], ["risk", "risk"], None])
def test_candidate_screening_rejects_malformed_mandatory_gates(gates):
    with pytest.raises(PortfolioInputError, match="mandatory_gates"):
        screen_candidates_before_scoring(
            [], as_of_date="2026-11-04", max_evidence_age_days=30,
            mandatory_gates=gates,
        )

def test_portfolio_reconciliation_requires_explicit_complete_perimeter():
    result = reconcile_total_portfolio([_asset()], perimeter_complete=False,
                                       as_of_date="2026-10-31")
    assert result["status"] == "HOLD"
    assert result["total_value_inr"] is None


def test_portfolio_reconciliation_rejects_duplicate_assets_and_date_mismatch():
    with pytest.raises(PortfolioInputError):
        reconcile_total_portfolio([_asset(), _asset()], perimeter_complete=True,
                                  as_of_date="2026-10-31")
    stale = _asset()
    stale["as_of_date"] = "2026-10-30"
    with pytest.raises(PortfolioInputError):
        reconcile_total_portfolio([stale], perimeter_complete=True,
                                  as_of_date="2026-10-31")


def test_portfolio_reconciliation_sums_only_declared_included_assets():
    result = reconcile_total_portfolio(
        [_asset(), _asset("bank-1", "50000", "cash")],
        perimeter_complete=True, as_of_date="2026-10-31",
        excluded_assets=[{"asset_class": "collectibles", "reason": "not_valued"}],
    )
    assert result["status"] == "RECONCILED"
    assert result["total_value_inr"] == "150000"
    assert result["excluded_count"] == 1


def test_saa_drift_requires_exact_sleeve_match_and_100_percent_target():
    with pytest.raises(PortfolioInputError):
        calculate_saa_drift({"equity": "80000"}, {"equity": "90"},
                            tolerance_band_pct="5", portfolio_total_inr="100000")
    with pytest.raises(PortfolioInputError):
        calculate_saa_drift({"equity": "80000", "debt": "20000"},
                            {"equity": "80", "debt": "30"},
                            tolerance_band_pct="5", portfolio_total_inr="100000")


def test_incremental_sip_routes_only_to_eligible_underweight_sleeves():
    result = route_incremental_sip(
        "10000", {"equity": "40000", "debt": "60000"},
        {"equity": "60", "debt": "40"}, portfolio_total_inr="100000",
        tolerance_band_pct="5", eligible_sleeves=["equity"],
        rounding_increment_inr="500",
    )
    assert result["allocations_inr"] == {"equity": "10000"}
    assert result["unallocated_budget_inr"] == "0"
    assert result["reconciliation_ok"] is True




def test_incremental_sip_rejects_string_or_unknown_eligible_sleeves():
    common = {
        "monthly_budget_inr": "10000",
        "current_values_inr": {"equity": "40000", "debt": "60000"},
        "target_weights_pct": {"equity": "60", "debt": "40"},
        "portfolio_total_inr": "100000",
        "tolerance_band_pct": "5",
    }
    with pytest.raises(PortfolioInputError, match="not a string"):
        route_incremental_sip(**common, eligible_sleeves="equity")
    with pytest.raises(PortfolioInputError, match="unknown target sleeves"):
        route_incremental_sip(**common, eligible_sleeves=["equity", "small_cap"])


def test_incremental_sip_keeps_budget_unallocated_when_no_candidate_qualifies():
    result = route_incremental_sip(
        "7500", {"equity": "40000", "debt": "60000"},
        {"equity": "60", "debt": "40"}, portfolio_total_inr="100000",
        tolerance_band_pct="5", eligible_sleeves=[],
    )
    assert result["status"] == "HOLD"
    assert result["unallocated_budget_inr"] == "7500"


def test_candidate_scoring_is_blocked_for_missing_or_stale_evidence():
    candidates = [{
        "candidate_id": "scheme-1",
        "scheme_identity": {"scheme_id": "1", "isin": "INF000000001",
                            "plan": "Direct", "option": "Growth", "amc": "AMC",
                            "category": "Flexi Cap", "benchmark": "TRI"},
        "evidence_as_of_date": "2026-10-01",
        "evidence_ref": "sha256:abc",
        "gates": {"direct_plan": "PASS", "risk": "PASS"},
    }, {
        "candidate_id": "scheme-2",
        "scheme_identity": {"scheme_id": "2"},
        "evidence_as_of_date": "2026-01-01",
        "gates": {},
    }]
    result = screen_candidates_before_scoring(
        candidates, as_of_date="2026-10-31", max_evidence_age_days=90,
        mandatory_gates=["direct_plan", "risk"],
    )
    assert result["eligible_candidate_ids"] == ["scheme-1"]
    assert result["scoring_permitted"] is True
    assert result["candidate_results"][1]["status"] != "ELIGIBLE"


def test_lookthrough_missing_coverage_holds_instead_of_assuming_zero_overlap():
    result = calculate_lookthrough_exposure([{
        "holding_value_inr": "100000", "coverage_pct": "70",
        "constituents": {"issuer-a": "20"},
    }], required_coverage_pct="99.5")
    assert result["status"] == "HOLD"
    assert result["issuer_exposure_inr"] is None


def test_lookthrough_aggregates_verified_issuer_weights_by_portfolio_value():
    result = calculate_lookthrough_exposure([
        {"holding_value_inr": "100000", "coverage_pct": "100",
         "constituents": {"issuer-a": "20", "issuer-b": "80"}},
        {"holding_value_inr": "50000", "coverage_pct": "100",
         "constituents": {"issuer-a": "40", "issuer-b": "60"}},
    ], required_coverage_pct="99.5")
    assert result["status"] == "CALCULATED"
    # Canonicalization transforms "issuer-a" to "ISSUER A" (uppercase, hyphen->space)
    assert Decimal(result["issuer_exposure_inr"]["ISSUER A"]) == Decimal("40000")


def test_decision_trace_is_deterministic_and_requires_full_lineage():
    record = {
        "schema_version": "1", "source_digests": {"metrics": "abc"},
        "as_of_dates": {"cas": "2026-10-31"}, "policy_version": "p1",
        "engine_version": "e1", "eligibility": [], "portfolio_effect": {},
        "allocation": {"equity": Decimal("1000")}, "decision": "HOLD",
    }
    first = build_decision_trace(record)
    second = build_decision_trace(dict(reversed(list(record.items()))))
    assert first["sha256"] == second["sha256"]
    assert first["algorithm"] == "SHA-256-CANONICAL-JSON-v1"
    with pytest.raises(PortfolioInputError):
        build_decision_trace({"decision": "HOLD"})


def test_goal_mandate_requires_approval_and_approved_horizon():
    from core.portfolio_sip_controls import validate_goal_mandate

    result = validate_goal_mandate([{
        "goal_id": "education", "mandate_approved": True,
        "source_ref": "sha256:goal", "evidence_as_of_date": "2026-10-31",
        "target_amount_inr": "2500000", "liabilities_inr": "100000",
        "target_date": "2034-10-31", "asset_class": "equity",
        "approved_risk_profile": "Moderate",
    }], as_of_date="2026-10-31", max_evidence_age_days=90,
       minimum_horizon_days_by_asset_class={"equity": 365 * 5})
    assert result["status"] == "VALIDATED"


def test_liquidity_reserve_and_monthly_surplus_are_separate_controls():
    from core.portfolio_sip_controls import assess_liquidity_and_sip_surplus

    refs = {k: "source:" + k for k in
            ("cash", "reserve", "obligations", "income", "expenses", "debt_service")}
    refs["as_of_dates"] = {k: "2026-10-31" for k in
                           ("cash", "reserve", "obligations", "income", "expenses", "debt_service")}
    result = assess_liquidity_and_sip_surplus(
        verified_cash_inr="100000", approved_reserve_target_inr="50000",
        near_term_obligations_inr="10000", monthly_net_income_inr="100000",
        essential_monthly_expenses_inr="50000", monthly_debt_service_inr="10000",
        proposed_monthly_sip_inr="30000", evidence_refs=refs,
        as_of_date="2026-10-31", max_evidence_age_days=30,
    )
    assert result["status"] == "AFFORDABLE"
    assert result["sustainable_monthly_sip_inr"] == "40000"


def test_liquidity_missing_source_or_insufficient_reserve_holds():
    from core.portfolio_sip_controls import assess_liquidity_and_sip_surplus

    result = assess_liquidity_and_sip_surplus(
        verified_cash_inr="1000", approved_reserve_target_inr="5000",
        near_term_obligations_inr="1000", monthly_net_income_inr="100000",
        essential_monthly_expenses_inr="20000", monthly_debt_service_inr="0",
        proposed_monthly_sip_inr="10000", evidence_refs={},
        as_of_date="2026-10-31", max_evidence_age_days=30,
    )
    assert result["status"] == "HOLD"
    assert result["reason"] == "LIQUIDITY_EVIDENCE_REFERENCE_MISSING"


def test_affordability_stress_test_does_not_assume_future_income_growth():
    from core.portfolio_sip_controls import stress_test_sip_affordability

    result = stress_test_sip_affordability(
        monthly_net_income_inr="100000", essential_monthly_expenses_inr="50000",
        monthly_debt_service_inr="10000", proposed_monthly_sip_inr="30000",
        scenarios=[{"scenario_id": "income-down", "income_reduction_pct": "20",
                    "expense_increase_pct": "10"}],
    )
    assert result["all_scenarios_sustainable"] is False
    assert result["scenarios"][0]["status"] == "UNSUSTAINABLE"


def test_scheme_operational_feasibility_requires_current_evidence_and_minimum():
    from core.portfolio_sip_controls import validate_scheme_operational_feasibility

    scheme = {
        "scheme_identity": {"scheme_id": "1", "isin": "INF000000001",
                            "plan": "Direct", "option": "Growth", "amc": "AMC"},
        "evidence_ref": "sha256:scheme", "evidence_as_of_date": "2026-10-31",
        "scheme_status": "ACTIVE", "minimum_monthly_sip_inr": "500",
        "exit_load_evidence_ref": "sha256:exit",
        "lockin_evidence_ref": "sha256:lock",
        "subscription_status_evidence_ref": "sha256:subscription",
    }
    result = validate_scheme_operational_feasibility(
        scheme, requested_monthly_sip_inr="1000",
        as_of_date="2026-10-31", max_evidence_age_days=30,
    )
    assert result["status"] == "FEASIBLE_FOR_REVIEW"
    assert result["execution_authorized"] is False
    too_small = validate_scheme_operational_feasibility(
        scheme, requested_monthly_sip_inr="100",
        as_of_date="2026-10-31", max_evidence_age_days=30,
    )
    assert "REQUEST_BELOW_SCHEME_MINIMUM" in too_small["reasons"]


def test_recommendation_freshness_blocks_expired_or_event_invalidated_plan():
    from core.portfolio_sip_controls import evaluate_recommendation_freshness

    result = evaluate_recommendation_freshness(
        recommendation_as_of_date="2026-01-01", current_as_of_date="2026-10-31",
        max_age_days=90, event_flags={"manager_change": True, "life_event": False},
    )
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["execution_authorized"] is False


def test_recommendation_lifecycle_requires_independent_review_and_is_monotonic():
    from core.portfolio_sip_controls import transition_recommendation_lifecycle

    digest = "a" * 64
    with pytest.raises(PortfolioInputError):
        transition_recommendation_lifecycle(
            current_state="DRAFT", requested_state="REVIEWED",
            decision_trace_sha256=digest, author_id="author", reviewer_id="author",
        )
    result = transition_recommendation_lifecycle(
        current_state="DRAFT", requested_state="REVIEWED",
        decision_trace_sha256=digest, author_id="author", reviewer_id="reviewer",
    )
    assert result["state"] == "REVIEWED"
    assert result["execution_authorized"] is False
    with pytest.raises(PortfolioInputError):
        transition_recommendation_lifecycle(
            current_state="REVIEWED", requested_state="DRAFT",
            decision_trace_sha256=digest, author_id="author",
        )


def test_candidate_sip_allocation_reconciles_each_routed_sleeve():
    candidates = [
        {"candidate_id": "large-a", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "rank_score": "2", "score_evidence_ref": "sha256:score-a", "score_as_of_date": "2026-11-04"},
        {"candidate_id": "large-b", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "rank_score": "1", "score_evidence_ref": "sha256:score-b", "score_as_of_date": "2026-11-04"},
        {"candidate_id": "debt-a", "sleeve": "debt_liquid", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "rank_score": "1", "score_evidence_ref": "sha256:score-c", "score_as_of_date": "2026-11-04"},
    ]
    result = allocate_candidate_sip(
        {"large_cap": "5000", "debt_liquid": "3000"},
        candidates,
        as_of_date="2026-11-04",
        max_score_age_days=30,
        min_sip_per_fund_inr="1000",
        rounding_increment_inr="500",
        max_funds=3,
    )
    assert result["status"] == "ALLOCATED"
    assert result["reconciliation_ok"] is True
    assert result["allocated_budget_inr"] == "8000"
    assert result["unallocated_budget_inr"] == "0"
    assert {row["candidate_id"] for row in result["allocations"]} == {"large-a", "large-b", "debt-a"}


def test_candidate_sip_allocation_holds_missing_score_provenance_and_does_not_redirect():
    result = allocate_candidate_sip(
        {"mid_cap": "6000", "large_cap": "4000"},
        [{"candidate_id": "mid-a", "sleeve": "mid_cap", "eligibility_status": "ELIGIBLE",
          "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
          "rank_score": "4", "score_as_of_date": "2026-11-04"}],
        as_of_date="2026-11-04",
        max_score_age_days=30,
        min_sip_per_fund_inr="1000",
        rounding_increment_inr="500",
        max_funds=2,
    )
    assert result["status"] == "HOLD"
    assert result["allocated_budget_inr"] == "0"
    assert result["unallocated_by_sleeve_inr"] == {"mid_cap": "6000", "large_cap": "4000"}
    assert result["rejected_candidates"]["mid-a"] == ["RANK_SCORE_SOURCE_REFERENCE_MISSING"]


def test_candidate_sip_allocation_rejects_stale_scores_and_caps_fund_count():
    candidates = [
        {"candidate_id": "a", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "rank_score": "3", "score_evidence_ref": "sha256:a", "score_as_of_date": "2026-11-04"},
        {"candidate_id": "b", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "rank_score": "2", "score_evidence_ref": "sha256:b", "score_as_of_date": "2026-11-04"},
    ]
    result = allocate_candidate_sip(
        {"large_cap": "5000"}, candidates,
        as_of_date="2026-11-04", max_score_age_days=30, min_sip_per_fund_inr="1000",
        rounding_increment_inr="500", max_funds=1,
    )
    assert len(result["allocations"]) == 1
    assert result["rejected_candidates"]["b"] == ["MAX_CORE_FUND_COUNT_REACHED"]


def test_candidate_sip_allocation_with_zero_remaining_fund_slots_is_fail_closed():
    result = allocate_candidate_sip(
        {"large_cap": "5000"},
        [{"candidate_id": "a", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
          "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
          "rank_score": "2", "score_evidence_ref": "sha256:a", "score_as_of_date": "2026-11-04"}],
        as_of_date="2026-11-04", max_score_age_days=30, min_sip_per_fund_inr="1000",
        rounding_increment_inr="500", max_funds=0,
    )
    assert result["status"] == "HOLD"
    assert result["unallocated_budget_inr"] == "5000"
    assert result["rejected_candidates"]["a"] == ["MAX_CORE_FUND_COUNT_REACHED"]


def test_classified_concentration_blocks_sector_market_cap_and_theme_breaches():
    result = evaluate_classified_concentration(
        {"issuer-a": "30000", "issuer-b": "25000"},
        {
            "issuer-a": {"sector": "Financials", "market_cap_bucket": "large_cap", "themes": ["banks"]},
            "issuer-b": {"sector": "Financials", "market_cap_bucket": "mid_cap", "themes": ["banks", "credit"]},
        },
        total_portfolio_inr="100000",
        as_of_date="2026-11-04",
        classification_as_of_date="2026-11-01",
        classification_source_ref="sha256:issuer-classifications",
        max_evidence_age_days=30,
        max_sector_pct="50",
        max_market_cap_pct="25",
        max_theme_pct="40",
    )
    assert result["status"] == "HOLD"
    assert result["breaches"]["sector"]["Financials"] == "55.00"
    assert result["breaches"]["theme"]["banks"] == "55.00"
    assert float(result["breaches"]["market_cap"]["large_cap"]) == 30.0


def test_classified_concentration_holds_on_missing_classification_or_stale_source():
    missing = evaluate_classified_concentration(
        {"issuer-a": "10000"}, {},
        total_portfolio_inr="100000",
        as_of_date="2026-11-04",
        classification_as_of_date="2026-11-01",
        classification_source_ref="sha256:class",
        max_evidence_age_days=30,
        max_sector_pct="50", max_market_cap_pct="50", max_theme_pct="50",
    )
    stale = evaluate_classified_concentration(
        {"issuer-a": "10000"},
        {"issuer-a": {"sector": "IT", "market_cap_bucket": "large_cap", "themes": []}},
        total_portfolio_inr="100000",
        as_of_date="2026-11-04",
        classification_as_of_date="2026-01-01",
        classification_source_ref="sha256:class",
        max_evidence_age_days=30,
        max_sector_pct="50", max_market_cap_pct="50", max_theme_pct="50",
    )
    assert missing["status"] == "HOLD"
    assert missing["unclassified_issuers"] == ["issuer-a"]
    assert stale["status"] == "HOLD"
    assert stale["reason"] == "ISSUER_CLASSIFICATION_STALE_OR_FUTURE"


def test_candidate_allocator_preserves_first_candidate_per_routed_sleeve():
    candidates = [
        {"candidate_id": "large-a", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "rank_score": "100", "score_evidence_ref": "sha256:a", "score_as_of_date": "2026-11-04"},
        {"candidate_id": "large-b", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "rank_score": "90", "score_evidence_ref": "sha256:b", "score_as_of_date": "2026-11-04"},
        {"candidate_id": "mid-a", "sleeve": "mid_cap", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "rank_score": "1", "score_evidence_ref": "sha256:c", "score_as_of_date": "2026-11-04"},
        {"candidate_id": "debt-a", "sleeve": "debt_liquid", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "rank_score": "2", "score_evidence_ref": "sha256:d", "score_as_of_date": "2026-11-04"},
    ]
    result = allocate_candidate_sip(
        {"large_cap": "5000", "mid_cap": "3000", "debt_liquid": "2000"},
        candidates,
        as_of_date="2026-11-04",
        max_score_age_days=30,
        min_sip_per_fund_inr="1000",
        rounding_increment_inr="500",
        max_funds=3,
    )
    assert result["reconciliation_ok"] is True
    assert {row["candidate_id"] for row in result["allocations"]} == {
        "large-a", "mid-a", "debt-a",
    }


def test_sip_routing_does_not_redistribute_an_ineligible_sleeve_gap():
    result = route_incremental_sip(
        "10000",
        {"large_cap": "30000", "flexi_multi_cap": "30000", "debt_liquid": "140000"},
        {"large_cap": "40", "flexi_multi_cap": "40", "debt_liquid": "20"},
        portfolio_total_inr="200000",
        tolerance_band_pct="0",
        eligible_sleeves={"large_cap"},
        rounding_increment_inr="500",
    )
    assert result["status"] == "ROUTED"
    assert result["allocations_inr"] == {"large_cap": "5000"}
    assert result["allocated_budget_inr"] == "5000"
    assert result["unallocated_budget_inr"] == "5000"
    assert result["unallocated_by_sleeve_inr"]["flexi_multi_cap"] == "5000"
    assert result["reconciliation_ok"] is True


def test_sip_routing_rounding_remainder_remains_unallocated():
    result = route_incremental_sip(
        "1000",
        {"large_cap": "30000", "mid_cap": "30000", "debt_liquid": "40000"},
        {"large_cap": "60", "mid_cap": "40", "debt_liquid": "0"},
        portfolio_total_inr="100000",
        tolerance_band_pct="0",
        eligible_sleeves={"large_cap", "mid_cap"},
        rounding_increment_inr="500",
    )
    assert result["allocated_budget_inr"] == "500"
    assert result["unallocated_budget_inr"] == "500"
    assert result["reconciliation_ok"] is True


def test_candidate_allocator_enforces_actual_per_scheme_minimum_not_total_budget():
    candidates = [
        {"candidate_id": "a", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "minimum_monthly_sip_inr": "6000", "rank_score": "2",
         "score_evidence_ref": "sha256:a", "score_as_of_date": "2026-11-04"},
        {"candidate_id": "b", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
         "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
         "minimum_monthly_sip_inr": "6000", "rank_score": "1",
         "score_evidence_ref": "sha256:b", "score_as_of_date": "2026-11-04"},
    ]
    result = allocate_candidate_sip(
        {"large_cap": "10000"}, candidates,
        as_of_date="2026-11-04",
        max_score_age_days=30,
        min_sip_per_fund_inr="1000",
        rounding_increment_inr="500",
        max_funds=6,
    )
    assert result["status"] == "ALLOCATED"
    assert len(result["allocations"]) == 1
    assert result["allocations"][0]["candidate_id"] == "a"
    assert result["allocations"][0]["monthly_sip_inr"] == "10000"
    assert Decimal(result["allocations"][0]["monthly_sip_inr"]) >= Decimal(
        result["allocations"][0]["scheme_minimum_monthly_sip_inr"]
    )
    assert result["rejected_candidates"]["b"] == ["SLEEVE_BUDGET_CANNOT_SUPPORT_SCHEME_MINIMUM"]


def test_candidate_allocator_holds_when_sleeve_budget_cannot_meet_scheme_minimum():
    result = allocate_candidate_sip(
        {"large_cap": "5000"},
        [{"candidate_id": "a", "sleeve": "large_cap", "eligibility_status": "ELIGIBLE",
          "overlap_status": "ASSESSED", "operational_status": "FEASIBLE_FOR_REVIEW",
          "minimum_monthly_sip_inr": "6000", "rank_score": "2",
          "score_evidence_ref": "sha256:a", "score_as_of_date": "2026-11-04"}],
        as_of_date="2026-11-04",
        max_score_age_days=30,
        min_sip_per_fund_inr="1000",
        rounding_increment_inr="500",
        max_funds=6,
    )
    assert result["status"] == "HOLD"
    assert result["allocated_budget_inr"] == "0"
    assert result["unallocated_budget_inr"] == "5000"
    assert result["rejected_candidates"]["a"] == [
        "ALLOCATED_SLEEVE_BUDGET_BELOW_EFFECTIVE_SCHEME_MINIMUM"
    ]


def test_scheme_operational_precheck_defers_minimum_comparison_until_fund_allocation():
    from core.portfolio_sip_controls import validate_scheme_operational_feasibility

    scheme = {
        "scheme_identity": {"scheme_id": "1", "isin": "INF000000001",
                            "plan": "Direct", "option": "Growth", "amc": "AMC"},
        "evidence_ref": "sha256:scheme", "evidence_as_of_date": "2026-11-04",
        "scheme_status": "ACTIVE", "minimum_monthly_sip_inr": "6000",
        "exit_load_evidence_ref": "sha256:exit",
        "lockin_evidence_ref": "sha256:lock",
        "subscription_status_evidence_ref": "sha256:subscription",
    }
    precheck = validate_scheme_operational_feasibility(
        scheme, requested_monthly_sip_inr="10000",
        as_of_date="2026-11-04", max_evidence_age_days=30,
        check_requested_minimum=False,
    )
    final_check = validate_scheme_operational_feasibility(
        scheme, requested_monthly_sip_inr="5000",
        as_of_date="2026-11-04", max_evidence_age_days=30,
    )
    assert precheck["status"] == "FEASIBLE_FOR_REVIEW"
    assert precheck["minimum_monthly_sip_inr"] == "6000"
    assert final_check["status"] == "HOLD"
    assert "REQUEST_BELOW_SCHEME_MINIMUM" in final_check["reasons"]


def test_candidate_allocator_rejects_all_duplicate_candidate_ids():
    candidate = {
        "candidate_id": "duplicate", "sleeve": "large_cap",
        "eligibility_status": "ELIGIBLE", "overlap_status": "ASSESSED",
        "operational_status": "FEASIBLE_FOR_REVIEW",
        "minimum_monthly_sip_inr": "1000", "rank_score": "2",
        "score_evidence_ref": "sha256:duplicate", "score_as_of_date": "2026-11-04",
    }
    result = allocate_candidate_sip(
        {"large_cap": "5000"}, [candidate, dict(candidate)],
        as_of_date="2026-11-04", max_score_age_days=30,
        min_sip_per_fund_inr="1000", rounding_increment_inr="500",
        max_funds=2,
    )
    assert result["status"] == "HOLD"
    assert result["allocations"] == []
    assert result["unallocated_budget_inr"] == "5000"
    assert result["rejected_candidates"]["duplicate"] == ["DUPLICATE_CANDIDATE_ID"]


def test_candidate_allocator_enforces_configured_score_freshness_window():
    result = allocate_candidate_sip(
        {"large_cap": "5000"},
        [{"candidate_id": "stale", "sleeve": "large_cap",
          "eligibility_status": "ELIGIBLE", "overlap_status": "ASSESSED",
          "operational_status": "FEASIBLE_FOR_REVIEW", "minimum_monthly_sip_inr": "1000",
          "rank_score": "2", "score_evidence_ref": "sha256:stale",
          "score_as_of_date": "2026-10-01"}],
        as_of_date="2026-11-04", max_score_age_days=30,
        min_sip_per_fund_inr="1000", rounding_increment_inr="500", max_funds=2,
    )
    assert result["status"] == "HOLD"
    assert result["unallocated_budget_inr"] == "5000"
    assert result["rejected_candidates"]["stale"] == ["RANK_SCORE_STALE_OR_FUTURE"]

def test_incremental_sip_routing_respects_saa_tolerance_deadband():
    within_band = route_incremental_sip(
        "10000",
        {"equity": "58000", "debt": "42000"},
        {"equity": "60", "debt": "40"},
        portfolio_total_inr="100000",
        tolerance_band_pct="5",
        eligible_sleeves={"equity"},
    )
    assert within_band["status"] == "HOLD"
    assert within_band["allocations_inr"] == {}
    assert within_band["unallocated_budget_inr"] == "10000"
    assert within_band["reason"] == "NO_ELIGIBLE_UNDERWEIGHT_SLEEVE"

    beyond_band = route_incremental_sip(
        "10000",
        {"equity": "50000", "debt": "50000"},
        {"equity": "60", "debt": "40"},
        portfolio_total_inr="100000",
        tolerance_band_pct="5",
        eligible_sleeves={"equity"},
    )
    # 10 percentage-point shortfall less 5-point tolerance = 5-point gap.
    assert beyond_band["status"] == "ROUTED"
    assert beyond_band["allocations_inr"] == {"equity": "10000"}
    assert beyond_band["unallocated_budget_inr"] == "0"
    assert beyond_band["reconciliation_ok"] is True


def test_incremental_sip_post_contribution_weights_reconcile_when_partially_unallocated():
    """P1 invariant: When part of the SIP budget is unallocated, post-contribution
    weights must reconcile to 100% of the invested portfolio, and unallocated money
    must be explicitly accounted for outside the invested perimeter.
    """
    current = {"large_cap": "30000", "mid_cap": "10000", "debt": "60000"}
    targets = {"large_cap": "35", "mid_cap": "25", "debt": "40"}
    # Underweight: large_cap (5% deficit), mid_cap (15% deficit). Total gap = 20%.
    # Budget = 10,000.
    # But only large_cap is eligible! mid_cap has no eligible fund.
    routing = route_incremental_sip(
        monthly_budget_inr="10000",
        current_values_inr=current,
        target_weights_pct=targets,
        portfolio_total_inr="100000",
        tolerance_band_pct="0",
        eligible_sleeves={"large_cap"},
        rounding_increment_inr="100",
    )
    assert routing["status"] == "ROUTED"
    # large_cap receives 5/20 of 10,000 = 2,500
    assert routing["allocations_inr"] == {"large_cap": "2500"}
    # Remaining 7,500 remains unallocated
    assert routing["allocated_budget_inr"] == "2500"
    assert routing["unallocated_budget_inr"] == "7500"
    assert routing["unallocated_cash_inr"] == "7500"

    # Post-contribution invested total = 100,000 + 2,500 = 102,500
    assert routing["post_contribution_invested_total_inr"] == "102500"
    assert routing["post_contribution_total_inr"] == "102500"
    assert routing["post_contribution_perimeter_total_inr"] == "110000"

    # Values: large_cap=32,500, mid_cap=10,000, debt=60,000. Sum = 102,500
    vals = routing["post_contribution_values_inr"]
    assert vals["large_cap"] == "32500"
    assert vals["mid_cap"] == "10000"
    assert vals["debt"] == "60000"
    assert sum(Decimal(v) for v in vals.values()) == Decimal("102500")

    # Weights reconcile to 100% of invested portfolio
    w = routing["post_contribution_weights_pct"]
    total_w = sum(Decimal(v) for v in w.values())
    assert pytest.approx(float(total_w), abs=0.05) == 100.0

    assert routing["reconciliation_ok"] is True
