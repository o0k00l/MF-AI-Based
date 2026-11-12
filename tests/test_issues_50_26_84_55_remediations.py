"""
Regression tests for Remediations:
- Issue #50: Central fund screening policy runtime binding & elimination of hardcoded defaults
- Issue #26: Portfolio-level concentration, overlap and look-through controls with strict security master
- Issue #84: Exact identity tuple binding (AMC, Category, Plan, Option) for metrics
- Issue #55: End-to-end Decimal money contract across ingestion, plans, and serialization
"""
from decimal import Decimal
import hashlib
import json
from datetime import date
from pathlib import Path
import pytest

from core.models import (
    HoldingItem,
    DeterministicSIPPlan,
    DeterministicSIPRecommendation,
    DeterministicLumpsumPlan,
    LumpsumTrancheItem,
    PlanType,
    AssetClass,
    quantize_inr,
)
from core.eligibility import (
    check_eligibility_gates,
    filter_candidates,
    evaluate_no_action,
    load_fund_screening_policy,
)
from core.math_engine import (
    compute_candidate_portfolio_overlap,
    evaluate_candidate_portfolio_concentration_controls,
    _find_matching_metric_by_scheme_identity,
    _validated_ips_numeric_inputs,
    compute_deterministic_sip_blueprint,
)
from core.traceability import _canonical_json_value


# =============================================================================
# Issue #50 Tests: Runtime Screening Policy Binding
# =============================================================================

def test_check_eligibility_gates_binds_loaded_policy():
    policy = load_fund_screening_policy()
    assert "_policy_digest" in policy
    assert "version" in policy

    fund = {
        "fund_id": "TEST_SCHEME_1",
        "fund_name": "Test Scheme Direct Growth",
        "scheme_id": "TEST_SCHEME_1",
        "isin": "TEST123",
        "scheme_name": "Test Scheme Direct Growth",
        "category": "Flexi Cap",
        "amc_name": "HDFC Mutual Fund",
        "aum_crore": 5000.0,
        "aum_stable": True,
        "top10_concentration_pct": 30.0,
        "max_sector_concentration_pct": 20.0,
        "sharpe_3y": 0.8,
        "alpha_3y": 2.5,
        "downside_capture_ratio": 75.0,
        "upside_capture_ratio": 95.0,
        "manager_tenure_years": 4.5,
        "track_record_years": 5.0,
        "confidence_score": 0.95,
        "benchmark_type": "TRI",
        "is_direct": True,
        "plan": "Direct Growth",
        "expense_ratio": 0.75,
        "riskometer_score": 4,
        "mandate_suitable": True,
        "data_complete": True,
        "direct_plan_evidence": {
            "source_file": "test_factsheet.json",
            "source_document_sha256": "82f90ed538237ab9bda27b384ca87b1685da532fb3a748074fa3a6dd4eec3932",
            "source_url": "https://www.hdfcmutualfund.com/factsheet",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Test Scheme Direct Growth",
            "scheme_id": "TEST_SCHEME_1",
            "isin": "TEST123",
            "amc_name": "HDFC Mutual Fund",
            "reviewed_at": "2026-09-01",
        },
        "_evidence_root": str(Path(__file__).resolve().parent.parent / "evidence"),
    }
    holdings = [
        {"amc_name": "ICICI Mutual Fund", "current_value_inr": 100000.0}
    ]

    res = check_eligibility_gates(
        fund_data=fund,
        portfolio_holdings=holdings,
        policy=policy,
        client_risk_tier_num=6,
        as_of_date=date(2026, 10, 5),
    )
    assert res.passed is True
    assert res.policy_version == policy["version"]
    assert res.policy_digest == policy["_policy_digest"]


def test_check_eligibility_gates_fails_closed_on_missing_gate_thresholds():
    malformed_policy = {"version": "bad.1.0"}
    fund = {"fund_id": "TEST_SCHEME_1", "fund_name": "Test Fund", "amc_name": "HDFC Mutual Fund"}
    res = check_eligibility_gates(
        fund_data=fund,
        portfolio_holdings=[],
        policy=malformed_policy,
    )
    assert res.passed is False
    assert any("missing 'gate_thresholds'" in f for f in res.failed_gates)


def test_filter_candidates_requires_policy_gate_thresholds():
    malformed_policy = {"version": "bad.1.0"}
    with pytest.raises(ValueError, match="missing 'gate_thresholds'"):
        filter_candidates(
            candidate_universe=[],
            current_portfolio=[],
            policy=malformed_policy,
        )


# =============================================================================
# Issue #26 Tests: Concentration Controls & Strict Security Master
# =============================================================================

def test_compute_candidate_portfolio_overlap_strict_security_master():
    candidate = {
        "fund_id": "CAND1",
        "constituent_weights": {"INE002A01018": 100.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    # Security master containing Reliance ISIN INE002A01018
    sec_master = {
        "_schema": "fiduciary.security_master.v1",
        "securities": {
            "INE002A01018": {
                "isin": "INE002A01018",
                "canonical_name": "Reliance Industries Limited",
                "aliases": ["RELIANCE", "RIL"],
            }
        }
    }
    holding = HoldingItem(
        fund_id="H1",
        scheme="Holding 1",
        fund_name="Holding 1",
        folio="FOLIO1",
        asset_class=AssetClass.EQUITY,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=Decimal("100000.00"),
        invested_value_inr=Decimal("80000.00"),
        units=Decimal("1000.000"),
        nav=Decimal("100.0000"),
        constituent_weights={"RELIANCE": 100.0},
        constituent_weights_coverage_pct=100.0,
    )

    overlap = compute_candidate_portfolio_overlap(
        cand=candidate,
        holdings=[holding],
        security_master=sec_master,
        strict=True,
    )
    assert overlap == 100.0


def test_compute_candidate_portfolio_overlap_rejects_unresolved_security_in_strict_mode():
    candidate = {
        "fund_id": "CAND1",
        "constituent_weights": {"UNRESOLVED_UNKNOWN_SECURITY_XYZ": 100.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    sec_master = {
        "_schema": "fiduciary.security_master.v1",
        "securities": {}
    }
    holding = HoldingItem(
        fund_id="H1",
        scheme="Holding 1",
        fund_name="Holding 1",
        folio="FOLIO1",
        asset_class=AssetClass.EQUITY,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=Decimal("100000.00"),
        invested_value_inr=Decimal("80000.00"),
        units=Decimal("1000.000"),
        nav=Decimal("100.0000"),
        constituent_weights={"INE002A01018": 100.0},
        constituent_weights_coverage_pct=100.0,
    )

    # In strict mode, unresolved security cannot pass normalization, returning None (fail closed)
    overlap = compute_candidate_portfolio_overlap(
        cand=candidate,
        holdings=[holding],
        security_master=sec_master,
        strict=True,
    )
    assert overlap is None


def test_concentration_controls_starter_portfolio_prohibits_thematic():
    candidate = {
        "fund_id": "THEMATIC1",
        "category": "Thematic Healthcare",
        "constituent_weights": {"INE002A01018": 100.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    sec_master = {
        "_schema": "fiduciary.security_master.v1",
        "securities": {"INE002A01018": {"isin": "INE002A01018", "canonical_name": "Reliance"}}
    }
    res = evaluate_candidate_portfolio_concentration_controls(
        candidate=candidate,
        holdings=[],
        security_master=sec_master,
        is_starter=True,
    )
    assert res["passed"] is False
    assert res["reason"] == "STARTER_PORTFOLIO_THEMATIC_PROHIBITED"


# =============================================================================
# Issue #84 Tests: Exact Identity Tuple Binding (AMC, Category, Plan, Option)
# =============================================================================

def test_metrics_identity_tuple_complete_match():
    metrics = {
        "s1": {
            "scheme_id": "SCHEME_1",
            "isin": "INF123456789",
            "amc_name": "HDFC Mutual Fund",
            "category": "Flexi Cap",
            "plan_type": "DIRECT",
            "option_type": "GROWTH",
            "expense_ratio": 0.65,
        }
    }
    identity = {
        "scheme_id": "SCHEME_1",
        "isin": "INF123456789",
        "amc_name": "HDFC Mutual Fund",
        "category": "Flexi Cap",
        "plan_type": "DIRECT",
        "option_type": "GROWTH",
    }
    matched = _find_matching_metric_by_scheme_identity(
        scheme_id="SCHEME_1",
        isin="INF123456789",
        metrics=metrics,
        identity=identity,
    )
    assert matched is not None
    assert matched["scheme_id"] == "SCHEME_1"


def test_metrics_identity_tuple_fails_on_missing_or_conflicting_attribute():
    metrics = {
        "s1": {
            "scheme_id": "SCHEME_1",
            "isin": "INF123456789",
            "amc_name": "HDFC Mutual Fund",
            "category": "Flexi Cap",
            "plan_type": "REGULAR",  # Conflicts with DIRECT
            "option_type": "GROWTH",
        }
    }
    identity = {
        "scheme_id": "SCHEME_1",
        "isin": "INF123456789",
        "amc_name": "HDFC Mutual Fund",
        "category": "Flexi Cap",
        "plan_type": "DIRECT",
        "option_type": "GROWTH",
    }
    with pytest.raises(ValueError, match="conflicts with verified scheme Plan"):
        _find_matching_metric_by_scheme_identity(
            scheme_id="SCHEME_1",
            isin="INF123456789",
            metrics=metrics,
            identity=identity,
        )

    # Missing option in metric
    metric_missing_option = {
        "s1": {
            "scheme_id": "SCHEME_1",
            "isin": "INF123456789",
            "amc_name": "HDFC Mutual Fund",
            "category": "Flexi Cap",
            "plan_type": "DIRECT",
        }
    }
    with pytest.raises(ValueError, match="missing required Option"):
        _find_matching_metric_by_scheme_identity(
            scheme_id="SCHEME_1",
            isin="INF123456789",
            metrics=metric_missing_option,
            identity=identity,
        )


# =============================================================================
# Issue #55 Tests: End-to-End Decimal Money Contract
# =============================================================================

def test_deterministic_sip_plan_decimal_exact_budget_reconciliation():
    rec1 = DeterministicSIPRecommendation(
        category_role="Core Flexi-Cap",
        scheme_name="HDFC Flexi Cap Direct Growth",
        monthly_inr=Decimal("15000.33"),
        allocation_pct=60.0,
        rational_code="CORE_COMPOUNDER",
        fiduciary_rationale="Core compounder",
    )
    rec2 = DeterministicSIPRecommendation(
        category_role="Mid-Cap Alpha",
        scheme_name="HDFC Mid Cap Direct Growth",
        monthly_inr=Decimal("9999.67"),
        allocation_pct=40.0,
        rational_code="ALPHA_ENGINE",
        fiduciary_rationale="Mid-cap alpha",
    )
    plan = DeterministicSIPPlan(
        total_monthly_budget_inr=Decimal("25000.00"),
        unallocated_budget_inr=Decimal("0.00"),
        equity_sip_pct=100.0,
        debt_sip_pct=0.0,
        items=[rec1, rec2],
    )
    assert plan.total_monthly_budget_inr == Decimal("25000.00")
    # Verify exact equality: 15000.33 + 9999.67 = 25000.00
    assert rec1.monthly_inr + rec2.monthly_inr == plan.total_monthly_budget_inr

    # Test serialization retains Decimal string in canonical json
    canonical = _canonical_json_value(rec1.monthly_inr)
    assert isinstance(canonical, str)
    assert canonical == "15000.33"


def test_deterministic_sip_plan_detects_unreconciled_budget_in_decimal():
    rec1 = DeterministicSIPRecommendation(
        category_role="Core Flexi-Cap",
        scheme_name="HDFC Flexi Cap Direct Growth",
        monthly_inr=Decimal("15000.00"),
        allocation_pct=60.0,
        rational_code="CORE_COMPOUNDER",
        fiduciary_rationale="Core compounder",
    )
    with pytest.raises(ValueError, match="must equal the monthly budget"):
        DeterministicSIPPlan(
            total_monthly_budget_inr=Decimal("25000.00"),
            unallocated_budget_inr=Decimal("0.00"),  # Leaves 10,000 unallocated without declaring it
            equity_sip_pct=60.0,
            debt_sip_pct=0.0,
            items=[rec1],
        )


def test_deterministic_lumpsum_plan_decimal_exact_reconciliation():
    t1 = LumpsumTrancheItem(
        role="Immediate Equity Deployment",
        scheme_name="HDFC Flexi Cap Direct Growth",
        amount_inr=Decimal("400000.00"),
        allocation_pct=40.0,
        timing="Immediate",
        source_vehicle="Bank Account",
        fiduciary_rationale="Immediate tranche",
    )
    t2 = LumpsumTrancheItem(
        role="Liquid Parking Vehicle",
        scheme_name="HDFC Liquid Fund Direct Growth",
        amount_inr=Decimal("600000.00"),
        allocation_pct=60.0,
        timing="Month 1 STP",
        source_vehicle="Bank Account",
        fiduciary_rationale="Liquid parking",
    )
    plan = DeterministicLumpsumPlan(
        total_lumpsum_inr=Decimal("1000000.00"),
        unallocated_amount_inr=Decimal("0.00"),
        is_big_ticket=True,
        stp_duration_months=6,
        immediate_amount_inr=Decimal("400000.00"),
        stp_total_amount_inr=Decimal("600000.00"),
        monthly_stp_total_inr=Decimal("100000.00"),
        parking_vehicle="Liquid Fund",
        tranches=[t1, t2],
    )
    assert plan.total_lumpsum_inr == Decimal("1000000.00")
    assert t1.amount_inr + t2.amount_inr == plan.total_lumpsum_inr


def test_validated_ips_numeric_inputs_returns_exact_decimals():
    ips = {
        "monthly_sip_budget": "50000.50",
        "lumpsum_budget": "1500000.75",
        "emergency_months": 6.0,
    }
    sip, lump, em = _validated_ips_numeric_inputs(ips)
    assert isinstance(sip, Decimal)
    assert isinstance(lump, Decimal)
    assert sip == Decimal("50000.50")
    assert lump == Decimal("1500000.75")
    assert em == 6.0



def test_check_eligibility_gates_rejects_unauthorized_threshold_overrides():
    fund = {
        "fund_id": "TEST_SCHEME_1",
        "fund_name": "Test Scheme Direct Growth",
        "category": "Flexi Cap",
        "amc_name": "HDFC Mutual Fund",
        "aum_crore": 5000.0,
    }
    with pytest.raises(ValueError, match="Unauthorized per-call threshold override for 'min_sharpe'"):
        check_eligibility_gates(
            fund_data=fund,
            portfolio_holdings=[],
            min_sharpe=0.55,  # Override without authorization
            allow_threshold_overrides=False,
        )


def test_check_eligibility_gates_prohibits_caller_controlled_boolean_override():
    fund = {
        "fund_id": "TEST_SCHEME_1",
        "fund_name": "Test Scheme Direct Growth",
        "category": "Flexi Cap",
        "amc_name": "HDFC Mutual Fund",
        "aum_crore": 5000.0,
    }
    holdings = [{"amc_name": "ICICI Mutual Fund", "current_value_inr": 100000.0}]
    # Caller-controlled boolean cannot authorize overriding central screening policy
    with pytest.raises(ValueError, match="Unauthorized per-call threshold override for 'min_sharpe'"):
        check_eligibility_gates(
            fund_data=fund,
            portfolio_holdings=holdings,
            min_sharpe=0.55,
            allow_threshold_overrides=True,
        )


def test_check_eligibility_gates_authorizes_overrides_via_validated_policy():
    fund = {
        "fund_id": "TEST_SCHEME_1",
        "fund_name": "Test Scheme Direct Growth",
        "category": "Flexi Cap",
        "amc_name": "HDFC Mutual Fund",
        "aum_crore": 5000.0,
        "top10_concentration_pct": 30.0,
        "sector_concentration_pct": 20.0,
        "sharpe": 0.45,  # Passes default 0.40, but will fail strict 0.55
        "alpha": 2.5,
        "downside_capture_ratio": 75.0,
        "upside_capture_ratio": 95.0,
        "manager_tenure_years": 4.5,
        "confidence_score": 0.95,
        "benchmark_type": "TRI",
        "is_direct": True,
        "plan": "Direct",
        "expense_ratio": 0.75,
        "riskometer_score": 4,
    }
    holdings = [{"amc_name": "ICICI Mutual Fund", "current_value_inr": 100000.0}]
    
    # 1. With standard policy (min_sharpe = 0.40), fund passes Gate 4
    std_policy = load_fund_screening_policy()
    res1 = check_eligibility_gates(fund_data=fund, portfolio_holdings=holdings, policy=std_policy)
    assert res1.sharpe_alpha_gate is True

    # 2. Legitimate threshold change must be supplied via an authoritative policy object
    import copy
    strict_policy = copy.deepcopy(std_policy)
    strict_policy["gate_thresholds"]["min_sharpe"] = 0.55  # Stricter sharpe
    # A policy override is a separately digest-bound snapshot. The base policy's
    # source path and digest cannot authorize modified policy contents.
    strict_policy.pop("_policy_path", None)
    strict_policy.pop("_policy_digest", None)
    strict_policy["_policy_digest"] = hashlib.sha256(
        json.dumps(strict_policy, sort_keys=True).encode("utf-8")
    ).hexdigest()

    res2 = check_eligibility_gates(fund_data=fund, portfolio_holdings=holdings, policy=strict_policy)
    # Now fails Gate 4 under the stricter policy
    assert res2.sharpe_alpha_gate is False
    assert any("Sharpe" in f for f in res2.failed_gates)
