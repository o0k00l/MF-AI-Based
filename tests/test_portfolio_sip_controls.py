from decimal import Decimal

import pytest

from core.portfolio_sip_controls import (
    PortfolioInputError,
    build_decision_trace,
    calculate_lookthrough_exposure,
    calculate_saa_drift,
    reconcile_total_portfolio,
    route_incremental_sip,
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
         "constituents": {"issuer-a": "20", "issuer-b": "10"}},
        {"holding_value_inr": "50000", "coverage_pct": "100",
         "constituents": {"issuer-a": "40"}},
    ], required_coverage_pct="99.5")
    assert result["status"] == "CALCULATED"
    assert Decimal(result["issuer_exposure_inr"]["issuer-a"]) == Decimal("40000")


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
