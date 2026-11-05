"""
Unit and integration tests for deep remediations across Issues #25, #50, #84, #26, #30, #31, #32, #23.
"""
from __future__ import annotations

import decimal
import pytest
from datetime import date

from core.candidate_scoring import ScoringWeights, calculate_candidate_6_pillar_score
from core.math_engine import (
    compute_multi_horizon_fiduciary_score,
    calculate_cash_deployment,
    load_holdings_from_cas_excel,
)
from core.eligibility import check_eligibility_gates, load_fund_screening_policy
from core.portfolio_sip_controls import (
    validate_goal_mandate,
    assess_liquidity_and_sip_surplus,
    stress_test_sip_affordability,
    calculate_lookthrough_exposure,
    reconcile_total_portfolio,
    PortfolioInputError,
)


def _scoring_weights() -> ScoringWeights:
    return ScoringWeights(
        alpha_momentum=0.25,
        risk_adjusted=0.20,
        consistency_downside=0.15,
        cost_efficiency=0.15,
        mandate_purity_aum=0.15,
        manager_conviction=0.10,
    )


# ============================================================================
# ISSUE #25: Mandatory Eligibility Gates Fail-Closed Scoring Guards
# ============================================================================

def test_scoring_rejects_missing_eligibility_status():
    candidate = {
        "fund_id": "cand-no-status",
        "category": "Flexi Cap",
        "alpha_3y": 3.0,
        "return_1y": 20.0,
        "sharpe_3y": 0.85,
        "ter_direct_pct": 0.70,
        "cash_debt_buffer_pct": 5.0,
        "international_equity_pct": 0.0,
        "is_eligible": True,
        # eligibility_status omitted
    }
    with pytest.raises(ValueError, match="invalid, missing, or unvetted eligibility status"):
        calculate_candidate_6_pillar_score(candidate, category_key="Flexi Cap", weights=_scoring_weights())

    with pytest.raises(ValueError, match="invalid, missing, or unvetted eligibility status"):
        compute_multi_horizon_fiduciary_score(candidate, category_key="Flexi Cap", scoring_weights=_scoring_weights())


def test_scoring_rejects_none_eligibility_status():
    candidate = {
        "fund_id": "cand-none-status",
        "category": "Flexi Cap",
        "alpha_3y": 3.0,
        "return_1y": 20.0,
        "sharpe_3y": 0.85,
        "ter_direct_pct": 0.70,
        "cash_debt_buffer_pct": 5.0,
        "international_equity_pct": 0.0,
        "eligibility_status": None,
        "is_eligible": True,
    }
    with pytest.raises(ValueError, match="invalid, missing, or unvetted eligibility status"):
        calculate_candidate_6_pillar_score(candidate, category_key="Flexi Cap", weights=_scoring_weights())


def test_scoring_rejects_missing_is_eligible_boolean():
    candidate = {
        "fund_id": "cand-no-bool",
        "category": "Flexi Cap",
        "alpha_3y": 3.0,
        "return_1y": 20.0,
        "sharpe_3y": 0.85,
        "ter_direct_pct": 0.70,
        "cash_debt_buffer_pct": 5.0,
        "international_equity_pct": 0.0,
        "eligibility_status": "PASS",
        # is_eligible omitted (None)
    }
    with pytest.raises(ValueError, match="does not have verified positive eligibility"):
        calculate_candidate_6_pillar_score(candidate, category_key="Flexi Cap", weights=_scoring_weights())


def test_scoring_rejects_contradictory_eligibility_evidence():
    # Passed status but is_eligible is False
    contradictory_cand = {
        "fund_id": "cand-contra",
        "category": "Flexi Cap",
        "alpha_3y": 3.0,
        "return_1y": 20.0,
        "sharpe_3y": 0.85,
        "ter_direct_pct": 0.70,
        "cash_debt_buffer_pct": 5.0,
        "international_equity_pct": 0.0,
        "eligibility_status": "PASS",
        "is_eligible": False,
    }
    with pytest.raises(ValueError, match="does not have verified positive eligibility"):
        calculate_candidate_6_pillar_score(contradictory_cand, category_key="Flexi Cap", weights=_scoring_weights())


def test_scoring_succeeds_with_explicit_verified_positive_eligibility():
    candidate = {
        "fund_id": "cand-valid",
        "category": "Flexi Cap",
        "alpha_3y": 3.0,
        "return_1y": 20.0,
        "sharpe_3y": 0.85,
        "ter_direct_pct": 0.70,
        "cash_debt_buffer_pct": 5.0,
        "international_equity_pct": 0.0,
        "eligibility_status": "PASS",
        "is_eligible": True,
    }
    score, pillars = calculate_candidate_6_pillar_score(
        candidate, category_key="Flexi Cap", weights=_scoring_weights()
    )
    assert 0.0 <= score <= 100.0
    assert len(pillars) == 6


# ============================================================================
# ISSUE #50: Central Screening Policy & Prohibition of Runtime Overrides
# ============================================================================

def test_check_eligibility_gates_strictly_prohibits_runtime_overrides():
    fund = {
        "fund_id": "fund-override-test",
        "aum_crore": 500.0,
        "category": "Flexi Cap",
    }
    # Even if allow_threshold_overrides=True is attempted, it is rejected
    with pytest.raises(ValueError, match="Unauthorized per-call threshold override"):
        check_eligibility_gates(fund, min_aum_crore=100.0, allow_threshold_overrides=True)

    with pytest.raises(ValueError, match="Unauthorized per-call threshold override"):
        check_eligibility_gates(fund, min_sharpe=0.1)


def test_screening_policy_carries_verifiable_digest_and_schema():
    policy = load_fund_screening_policy()
    assert policy["_schema"] == "fiduciary.screening_criteria.v1"
    assert "_policy_digest" in policy
    assert len(policy["_policy_digest"]) == 64
    assert policy.get("version") is not None


# ============================================================================
# ISSUE #84: Exact Scheme Identity as Default in CAS Holdings Loader
# ============================================================================

def test_cas_holdings_loader_defaults_to_strict_exact_identity():
    import inspect
    sig = inspect.signature(load_holdings_from_cas_excel)
    param = sig.parameters["require_exact_metric_identity"]
    assert param.default is True, "require_exact_metric_identity must default to True on all paths"


# ============================================================================
# ISSUE #26: Strict Security Master Look-Through Resolution
# ============================================================================

def test_calculate_lookthrough_exposure_fails_closed_on_unresolved_security():
    master = {
        "_schema": "fiduciary.security_master.v1",
        "securities": {
            "RELIANCE": {"canonical_id": "RELIANCE", "name": "Reliance Industries Ltd"},
        }
    }
    holdings = [{
        "holding_value_inr": "100000",
        "coverage_pct": "100",
        "constituents": {
            "RELIANCE": "60",
            "UNRESOLVED_CORP_XYZ": "40",
        }
    }]
    # With security master present, unresolved constituent returns HOLD
    res = calculate_lookthrough_exposure(holdings, required_coverage_pct="99.5", security_master=master)
    assert res["status"] == "HOLD"
    assert "LOOKTHROUGH_INCOMPLETE_OR_UNRESOLVED" in res["reason"]
    assert res["unresolved_issuer"] == "UNRESOLVED_CORP_XYZ"


# ============================================================================
# ISSUE #30: Goal-Level Suitability, Priority, and Asset Earmark Checks
# ============================================================================

def test_validate_goal_mandate_detects_multi_goal_asset_double_counting():
    goals = [
        {
            "goal_id": "GOAL-RETIREMENT",
            "schema_version": "goal_mandate.v1",
            "priority": 1,
            "mandate_approved": True,
            "source_ref": "source-001",
            "evidence_as_of_date": "2026-11-01",
            "target_amount_inr": "5000000",
            "liabilities_inr": "0",
            "target_date": "2040-01-01",
            "asset_class": "equity",
            "approved_risk_profile": "Aggressive",
            "earmarked_assets": ["ASSET-FD-01", "ASSET-MUTUAL-01"],
        },
        {
            "goal_id": "GOAL-CHILD-EDUCATION",
            "schema_version": "goal_mandate.v1",
            "priority": 2,
            "mandate_approved": True,
            "source_ref": "source-002",
            "evidence_as_of_date": "2026-11-01",
            "target_amount_inr": "2500000",
            "liabilities_inr": "0",
            "target_date": "2035-01-01",
            "asset_class": "equity",
            "approved_risk_profile": "Aggressive",
            "earmarked_assets": ["ASSET-MUTUAL-01", "ASSET-GOLD-01"],  # ASSET-MUTUAL-01 double-counted!
        },
    ]
    min_horizons = {"equity": "1095", "debt": "365"}
    res = validate_goal_mandate(
        goals,
        as_of_date="2026-11-01",
        max_evidence_age_days=90,
        minimum_horizon_days_by_asset_class=min_horizons,
    )
    assert res["status"] == "HOLD"
    assert "ASSET-MUTUAL-01" in res["double_counted_assets"]
    assert any("EARMARKED_ASSET_DOUBLE_COUNTED:ASSET-MUTUAL-01" in r for r in res["goals"][1]["reasons"])


def test_validate_goal_mandate_rejects_horizon_below_policy():
    goals = [{
        "goal_id": "GOAL-SHORT-TERM",
        "mandate_approved": True,
        "source_ref": "source-001",
        "evidence_as_of_date": "2026-11-01",
        "target_amount_inr": "100000",
        "liabilities_inr": "0",
        "target_date": "2027-01-01",  # ~61 days horizon
        "asset_class": "equity",
        "approved_risk_profile": "Aggressive",
    }]
    min_horizons = {"equity": "1095"}  # 3 years minimum
    res = validate_goal_mandate(
        goals,
        as_of_date="2026-11-01",
        max_evidence_age_days=90,
        minimum_horizon_days_by_asset_class=min_horizons,
    )
    assert res["status"] == "HOLD"
    assert "GOAL_HORIZON_BELOW_APPROVED_MINIMUM" in res["goals"][0]["reasons"]


# ============================================================================
# ISSUE #31: Emergency Reserve and Cash Deployment Duration
# ============================================================================

def test_calculate_cash_deployment_does_not_default_stp_duration():
    plan = calculate_cash_deployment(
        bank_cash_inr=500000.0,
        emergency_buffer_inr=200000.0,
        emergency_months=6.0,
        stp_months=None,  # No STP duration supplied
        as_of_date="2026-11-01",
        evidence_source="BANK_TEST",
    )
    assert plan.status == "AVAILABLE"
    assert plan.deployable_surplus_inr == 300000.0
    # Must NOT invent an arbitrary 6-month duration
    assert plan.stp_duration_months is None
    assert plan.stp_monthly_amount_inr is None


def test_assess_liquidity_and_sip_surplus_fails_closed_when_cash_insufficient():
    refs = {
        "cash": "ref-1", "reserve": "ref-2", "obligations": "ref-3",
        "income": "ref-4", "expenses": "ref-5", "debt_service": "ref-6",
        "as_of_dates": {
            "cash": "2026-11-01", "reserve": "2026-11-01", "obligations": "2026-11-01",
            "income": "2026-11-01", "expenses": "2026-11-01", "debt_service": "2026-11-01",
        }
    }
    # Verified cash (150,000) is less than approved reserve (200,000) + obligations (50,000)
    res = assess_liquidity_and_sip_surplus(
        verified_cash_inr="150000",
        approved_reserve_target_inr="200000",
        near_term_obligations_inr="50000",
        monthly_net_income_inr="100000",
        essential_monthly_expenses_inr="50000",
        monthly_debt_service_inr="10000",
        proposed_monthly_sip_inr="25000",
        evidence_refs=refs,
        as_of_date="2026-11-01",
        max_evidence_age_days=90,
    )
    assert res["status"] == "HOLD"
    assert res["reason"] == "VERIFIED_CASH_BELOW_RESERVE_AND_OBLIGATIONS"
    assert res["sustainable_monthly_sip_inr"] == "0"


# ============================================================================
# ISSUE #32: Affordability Stress Testing
# ============================================================================

def test_stress_test_sip_affordability_flags_unsustainable_scenarios():
    scenarios = [
        {"scenario_id": "MILD_SHOCK", "income_reduction_pct": "10", "expense_increase_pct": "10"},
        {"scenario_id": "SEVERE_SHOCK", "income_reduction_pct": "40", "expense_increase_pct": "20"},
    ]
    # Net income 100k, expenses 50k, debt 10k -> normal surplus = 40k. Proposed SIP = 25k.
    # Mild shock: income 90k, expenses 55k, debt 10k -> surplus 25k -> sustainable.
    # Severe shock: income 60k, expenses 60k, debt 10k -> surplus -10k -> UNSUSTAINABLE.
    res = stress_test_sip_affordability(
        monthly_net_income_inr="100000",
        essential_monthly_expenses_inr="50000",
        monthly_debt_service_inr="10000",
        proposed_monthly_sip_inr="25000",
        scenarios=scenarios,
    )
    assert res["status"] == "ASSESSED"
    assert res["all_scenarios_sustainable"] is False
    assert res["scenarios"][0]["status"] == "SUSTAINABLE"
    assert res["scenarios"][1]["status"] == "UNSUSTAINABLE"


# ============================================================================
# ISSUE #23: Total Portfolio Perimeter Reconciliation Fail-Closed
# ============================================================================

def test_reconcile_total_portfolio_fails_closed_when_perimeter_not_attested():
    assets = [
        {"asset_id": "A1", "asset_class": "equity", "value_inr": "100000", "source_ref": "s1", "owner_scope": "client", "as_of_date": "2026-11-01"}
    ]
    res = reconcile_total_portfolio(assets, perimeter_complete=False, as_of_date="2026-11-01")
    assert res["status"] == "HOLD"
    assert res["reason"] == "PORTFOLIO_PERIMETER_NOT_ATTESTED"
    assert res["total_value_inr"] is None
