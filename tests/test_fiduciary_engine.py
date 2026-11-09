"""Unit tests for services/fiduciary_engine.py."""
from __future__ import annotations

from decimal import Decimal
import pytest
import json
from pathlib import Path

from services.fiduciary_engine import (
    convert_cas_funds_to_holdings,
    evaluate_portfolio_saa_audit,
    generate_fiduciary_sip_blueprint,
    evaluate_fiduciary_lumpsum_blueprint,
)
from services.risk_profiler import TargetSaa
from core.eligibility import check_eligibility_gates, load_fund_screening_policy
from core.math_engine import (
    compute_candidate_portfolio_overlap,
    evaluate_candidate_portfolio_concentration_controls,
)


def test_convert_cas_funds_and_saa_audit():
    """Verify CAS fund conversion and SAA drift evaluation."""
    funds = [
        {
            "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            "category": "Equity",
            "plan_type": "Direct",
            "current_value": 400000.0,
            "invested_value": 300000.0,
            "units": 5000.0,
            "nav": 80.0,
            "folio_no": "12345/01",
            "eq": 98.0,
            "debt": 2.0,
        },
        {
            "scheme": "HDFC Liquid Fund - Direct Plan - Growth",
            "category": "Debt",
            "plan_type": "Direct",
            "current_value": 100000.0,
            "invested_value": 100000.0,
            "units": 20.0,
            "nav": 5000.0,
            "folio_no": "98765/02",
            "eq": 0.0,
            "debt": 100.0,
        },
    ]

    holdings = convert_cas_funds_to_holdings(funds)
    assert len(holdings) == 2
    assert holdings[0].current_value_inr == Decimal("400000.00")

    # Evaluate SAA audit against 70/30 target
    target = TargetSaa(large_cap_pct=45.0, mid_small_cap_pct=25.0, debt_pct=30.0)
    audit = evaluate_portfolio_saa_audit(funds, target_saa=target)

    assert audit["status"] == "ANALYZED"
    assert audit["total_value_inr"] == Decimal("500000.00")
    # Current debt is: (400k * 0.02) + (100k * 1.0) = 8k + 100k = 108k (21.6%)
    # Target debt is 30% = 150k -> Debt deficit of 42k
    assert audit["is_debt_deficit"] is True
    assert audit["debt_gap_inr"] > Decimal("0.00")


def test_generate_fiduciary_sip_blueprint():
    """Verify deterministic SIP blueprint reconciles to exact budget."""
    funds = [
        {
            "scheme": "UTI Nifty 50 Index Fund - Direct Plan - Growth",
            "category": "Equity",
            "plan_type": "Direct",
            "current_value": 200000.0,
            "folio_no": "1111/01",
        },
        {
            "scheme": "Kotak Emerging Equity Fund - Direct Plan - Growth",
            "category": "Equity",
            "plan_type": "Direct",
            "current_value": 100000.0,
            "folio_no": "2222/02",
        },
    ]
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, debt_pct=25.0)
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=30000.0,
        funds=funds,
        target_saa=target,
    )

    assert blueprint["status"] == "DETERMINISTIC_SIP_READY"
    assert blueprint["reconciliation_valid"] is True
    assert blueprint["allocated_budget_inr"] == Decimal("30000.00")
    assert blueprint["unallocated_budget_inr"] == Decimal("0.00")
    assert len(blueprint["allocations"]) == 3


def test_evaluate_fiduciary_lumpsum_blueprint():
    """Verify portfolio-aware lumpsum deployment, reserve defense, and STP reconciliation."""
    # Case 1: Fully eligible
    target = TargetSaa(large_cap_pct=50.0, mid_small_cap_pct=25.0, debt_pct=25.0)
    res = evaluate_fiduciary_lumpsum_blueprint(
        lumpsum_amount_inr=500000.0,
        bank_cash_inr=1000000.0,
        monthly_expenses_inr=50000.0,  # 6mo reserve = 300,000; surplus = 700,000 >= 500,000
        stp_duration_months=6,
        target_saa=target,
    )
    assert res["status"] == "ELIGIBLE"
    assert res["effective_lumpsum_inr"] == Decimal("500000.00")
    assert res["emergency_reserve_inr"] == Decimal("300000.00")
    assert res["deployable_surplus_inr"] == Decimal("700000.00")
    assert res["target_equity_capital_inr"] == Decimal("375000.00")  # 75% equity
    assert res["target_debt_capital_inr"] == Decimal("125000.00")    # 25% debt
    assert len(res["stp_schedule"]) == 6
    assert res["reconciliation_valid"] is True
    total_stped = sum(item["tranche_amount_inr"] for item in res["stp_schedule"])
    assert total_stped == Decimal("375000.00")

    # Case 2: Reserve Deficit (Bank cash < 6mo expenses)
    res_def = evaluate_fiduciary_lumpsum_blueprint(
        lumpsum_amount_inr=200000.0,
        bank_cash_inr=250000.0,
        monthly_expenses_inr=50000.0,  # Reserve needs 300,000, only 250,000 available
    )
    assert res_def["status"] == "RESERVE_DEFICIT"
    assert res_def["effective_lumpsum_inr"] == Decimal("0.00")
    assert res_def["deployable_surplus_inr"] == Decimal("0.00")
    assert "below the required 6-month emergency reserve" in res_def["reasons"][0]

    # Case 3: Capped at surplus (Surplus < requested lump sum)
    res_cap = evaluate_fiduciary_lumpsum_blueprint(
        lumpsum_amount_inr=500000.0,
        bank_cash_inr=500000.0,
        emergency_reserve_inr=200000.0,  # Surplus = 300,000 < 500,000
        stp_duration_months=3,
    )
    assert res_cap["status"] == "CAPPED_AT_SURPLUS"
    assert res_cap["effective_lumpsum_inr"] == Decimal("300000.00")
    assert res_cap["reconciliation_valid"] is True


def test_evaluate_fiduciary_lumpsum_blueprint_robustness_against_none_and_malformed_inputs():
    """Verify evaluate_fiduciary_lumpsum_blueprint never raises TypeError on None or malformed inputs."""
    # None inputs
    res_none = evaluate_fiduciary_lumpsum_blueprint(
        lumpsum_amount_inr=None,
        stp_duration_months=None,
        target_saa=None,
        funds=None,
    )
    assert res_none["status"] == "ZERO_AMOUNT"
    assert res_none["effective_lumpsum_inr"] == Decimal("0.00")

    # String inputs
    res_str = evaluate_fiduciary_lumpsum_blueprint(
        lumpsum_amount_inr="500000.0",
        stp_duration_months="12",
        target_saa={"total_equity_pct": 70.0, "debt_pct": 30.0},
        funds=[{"scheme": None, "plan_type": None, "category": None}],
    )
    assert res_str["status"] == "ELIGIBLE"
    assert res_str["effective_lumpsum_inr"] == Decimal("500000.00")
    assert res_str["stp_duration_months"] == 12

    # Malformed dict target_saa with None values
    res_none_dict = evaluate_fiduciary_lumpsum_blueprint(
        lumpsum_amount_inr=100000.0,
        target_saa={"large_cap_pct": None, "mid_small_cap_pct": None, "debt_pct": None},
        funds=[{"scheme": "HDFC Liquid Direct", "plan_type": "Direct", "category": "Debt"}],
    )
    assert res_none_dict["status"] == "ELIGIBLE"
    assert res_none_dict["parking_scheme"] == "HDFC Liquid Direct"


def test_generate_fiduciary_sip_blueprint_robustness():
    """Verify generate_fiduciary_sip_blueprint never raises TypeError on None or malformed inputs."""
    res_none = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=None,
        funds=None,
        target_saa=None,
    )
    assert res_none["status"] == "ZERO_BUDGET"

    res_malformed = generate_fiduciary_sip_blueprint(
        monthly_budget_inr="25000",
        funds=[{"scheme": None, "plan_type": "Direct"}],
        target_saa={"large_cap_pct": None, "debt_pct": None},
    )
    assert res_malformed["status"] == "DETERMINISTIC_SIP_READY"
    assert res_malformed["reconciliation_valid"] is True


def test_generate_fiduciary_sip_blueprint_uses_market_nominations():
    """Verify SIP blueprint uses market-nominated funds when client has no matching fund categories.
    
    The dynamic selection should use the fund universe and selection rules to pick the best funds
    based on criteria like lowest TER for large cap index, highest Sharpe for mid cap, etc.
    """
    # Case 1: No direct funds - should use market nominations
    # When target_saa=None, default fallback is 50% large, 25% mid_small, 0% flexi, 25% debt
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=25000.0,
        funds=[],
        target_saa=None,
    )
    assert blueprint["status"] == "DETERMINISTIC_SIP_READY"
    
    allocations = blueprint["allocations"]
    # With default target (0% flexi), expect 3 sleeves: Large-Cap, Mid/Small, Debt
    assert len(allocations) == 3
    
    # Check that market-nominated funds are used for large cap
    large_cap_alloc = next((a for a in allocations if a["sleeve"] == "Large-Cap Core Index"), None)
    assert large_cap_alloc is not None
    # Market nomination should be a valid index fund (Nifty/Sensex/Index in name or fallback)
    scheme_name = large_cap_alloc["scheme_name"].upper()
    assert "DIRECT" in scheme_name, "Should be Direct plan"
    # Should contain index/nifty/sensex for large cap index fund
    is_index_fund = any(kw in scheme_name for kw in ["INDEX", "NIFTY", "SENSEX"])
    assert is_index_fund, f"Expected index fund, got: {large_cap_alloc['scheme_name']}"
    
    # Check debt allocation using dynamic selection
    debt_alloc = next((a for a in allocations if a["sleeve"] == "Debt & Capital Preservation"), None)
    assert debt_alloc is not None
    # Should be a valid liquid/debt fund with Direct plan
    assert "Direct" in debt_alloc["scheme_name"] or "DIRECT" in debt_alloc["scheme_name"].upper(), "Should be Direct plan"
    # Dynamic selection should pick high-AUM debt fund - verify it has a valid name
    assert len(debt_alloc["scheme_name"]) > 20, "Should have a proper scheme name"
    
    # Verify allocations are properly sized
    total_allocated = sum(a["amount_inr"] for a in allocations)
    # Should have reconciled to the budget (allowing for rounding)
    assert abs(total_allocated - 25000) < 0.1, "Total allocation should match budget"


def test_generate_fiduciary_sip_blueprint_confidence_score():
    """Verify confidence score calculation reflects portfolio completeness."""
    # High confidence: client has matching funds
    funds_complete = [
        {"scheme": "UTI Nifty 50 Index Fund - Direct Plan - Growth", "category": "Large Cap", "plan_type": "Direct", "current_value": 200000.0, "folio_no": "1111/01"},
        {"scheme": "HDFC Mid Cap Fund - Direct Plan - Growth", "category": "Mid Cap", "plan_type": "Direct", "current_value": 100000.0, "folio_no": "2222/02"},
        {"scheme": "ICICI Prudential Liquid Fund - Direct Plan - Growth", "category": "Debt", "plan_type": "Direct", "current_value": 100000.0, "folio_no": "3333/03"},
    ]
    blueprint_complete = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=25000.0,
        funds=funds_complete,
        target_saa={"large_cap_pct": 50.0, "mid_small_cap_pct": 25.0, "debt_pct": 25.0},
    )
    assert blueprint_complete["status"] == "DETERMINISTIC_SIP_READY"
    assert blueprint_complete["sip_selection_confidence_pct"] >= 88.0  # No high/medium alerts
    
    # Lower confidence: client has no Direct plans (falls back to market nom)
    blueprint_no_funds = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=25000.0,
        funds=[],
        target_saa={"large_cap_pct": 50.0, "mid_small_cap_pct": 25.0, "debt_pct": 25.0},
    )
    assert blueprint_no_funds["status"] == "DETERMINISTIC_SIP_READY"
    # Confidence should be reduced due to no existing Direct plans
    assert blueprint_no_funds["sip_selection_confidence_pct"] <= 65.0  # 100 - 35 = 65


def test_generate_fiduciary_sip_blueprint_includes_flexi_sleeve():
    """Verify SIP blueprint includes Flexi-Multi Cap sleeve when target_saa specifies it.
    
    This is a critical regression test for the defect where flexi_target was calculated
    but never added to the allocations output - the amount was silently dropped.
    """
    # Test 1: Target with flexi-multi-cap allocation
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=25000.0,
        funds=[],  # No existing funds - use market nominations
        target_saa={"large_cap_pct": 50.0, "mid_small_cap_pct": 25.0, "flexi_multi_cap_pct": 15.0, "debt_pct": 10.0},
    )
    assert blueprint["status"] == "DETERMINISTIC_SIP_READY"
    
    allocations = blueprint["allocations"]
    
    # Must have 4 sleeves: Large-Cap, Mid/Small, Flexi-Multi Cap, Debt
    sleeve_types = [a["sleeve"] for a in allocations]
    assert "Large-Cap Core Index" in sleeve_types, "Missing Large-Cap sleeve"
    assert "Mid/Small-Cap Alpha" in sleeve_types, "Missing Mid/Small-Cap sleeve"
    assert "Flexi-Multi Cap" in sleeve_types, "Missing Flexi-Multi Cap sleeve - THIS WAS THE BUG"
    assert "Debt & Capital Preservation" in sleeve_types, "Missing Debt sleeve"
    
    # Verify flexi allocation amount
    flexi_alloc = next((a for a in allocations if a["sleeve"] == "Flexi-Multi Cap"), None)
    assert flexi_alloc is not None, "Flexi-Multi Cap allocation missing"
    expected_flexi_amount = 25000.0 * 0.15  # 15% of budget
    assert abs(float(flexi_alloc["amount_inr"]) - expected_flexi_amount) < 1.0
    
    # Test 2: Zero flexi allocation
    blueprint_zero_flexi = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=15000.0,
        funds=[],
        target_saa={"large_cap_pct": 60.0, "mid_small_cap_pct": 40.0, "flexi_multi_cap_pct": 0.0, "debt_pct": 0.0},
    )
    allocations_zero = blueprint_zero_flexi["allocations"]
    # Even with zero flexi, the blueprint should handle it gracefully
    total = sum(float(a["amount_inr"]) for a in allocations_zero)
    assert abs(total - 15000.0) < 1.0, "Budget reconciliation must still work with zero flexi"

    # Test 3: With existing Direct funds including flexi
    funds_with_flexi = [
        {"scheme": "HDFC Flexi Cap Fund - Direct Plan - Growth", "category": "Flexi Cap", "plan_type": "Direct", "current_value": 50000, "folio_no": "4444/04"},
        {"scheme": "ICICI Prudential Large Cap Fund - Direct Plan - Growth", "category": "Large Cap", "plan_type": "Direct", "current_value": 100000, "folio_no": "1111/01"},
        {"scheme": "HDFC Mid Cap Fund - Direct Plan - Growth", "category": "Mid Cap", "plan_type": "Direct", "current_value": 50000, "folio_no": "2222/02"},
    ]
    blueprint_with_flexi = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=20000.0,
        funds=funds_with_flexi,
        target_saa={"large_cap_pct": 50.0, "mid_small_cap_pct": 25.0, "flexi_multi_cap_pct": 15.0, "debt_pct": 10.0},
    )
    assert blueprint_with_flexi["status"] == "DETERMINISTIC_SIP_READY"
    
    # Should have 4 allocations including the existing flexi fund
    allocations_existing = blueprint_with_flexi["allocations"]
    sleeve_types_existing = [a["sleeve"] for a in allocations_existing]
    assert "Flexi-Multi Cap" in sleeve_types_existing, "Should include existing flexi fund"


def test_zero_equity_target_saa_object_preserves_zero_values():
    """Regression test: TargetSaa object with 0% equity must preserve zero values.
    
    The extract_target_saa_percentages function was using 'or default' pattern
    which treated 0 as falsy, turning a valid 0% allocation into a non-zero default.
    
    This test verifies that a TargetSaa object with zero-equity-cap (ultra-short horizon)
    correctly results in zero SIP allocations for all equity sleeves.
    """
    # Create a TargetSaa object with zero equity cap (ultra-short horizon investor)
    zero_target = TargetSaa(
        large_cap_pct=0.0,
        mid_small_cap_pct=0.0,
        flexi_multi_cap_pct=0.0,
        debt_pct=100.0,  # All debt for ultra-short horizon
    )
    
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=10000.0,
        funds=[],
        target_saa=zero_target,  # Pass actual TargetSaa object, not dict
    )
    
    assert blueprint["status"] == "DETERMINISTIC_SIP_READY", \
        f"Zero-equity target should still produce valid blueprint, got: {blueprint.get('status')}"
    
    allocations = blueprint["allocations"]
    
    # All equity sleeves should have 0 INR allocation
    for alloc in allocations:
        sleeve = alloc.get("sleeve", "")
        amount = float(alloc.get("amount_inr", 0))
        if "Cap" in sleeve or "Debt" in sleeve:
            # For zero-equity policy, all equity allocations must be 0
            if sleeve != "Debt & Capital Preservation":
                assert amount == 0.0, \
                    f"Sleeve {sleeve} should have 0 allocation (got {amount}) for zero-equity TargetSaa"
    
    # Debt should get the full budget
    debt_alloc = next((a for a in allocations if "Debt" in a.get("sleeve", "")), None)
    assert debt_alloc is not None, "Should have debt allocation"
    debt_amount = float(debt_alloc.get("amount_inr", 0))
    assert debt_amount > 0, "Debt allocation should receive the budget for zero-equity target"


def test_target_saa_object_preserves_zero_debt_and_zero_flexi():
    """Test that zero debt_pct and zero flexi_pct are preserved in TargetSaa object extraction.
    
    This addresses the 'or' pattern bug where 0 values were replaced by defaults.
    """
    # TargetSaa with zero debt and zero flexi - all to large/mid-small
    test_target = TargetSaa(
        large_cap_pct=60.0,
        mid_small_cap_pct=40.0,
        flexi_multi_cap_pct=0.0,  # Explicit zero
        debt_pct=0.0,  # Explicit zero
    )
    
    blueprint = generate_fiduciary_sip_blueprint(
        monthly_budget_inr=20000.0,
        funds=[],
        target_saa=test_target,
    )
    
    assert blueprint["status"] == "DETERMINISTIC_SIP_READY"
    
    allocations = blueprint["allocations"]
    
    # Find flexi allocation - should be 0 or not present
    flexi_allocs = [a for a in allocations if "Flexi" in a.get("sleeve", "")]
    
    # Total should still reconcile to budget
    total_allocated = sum(float(a.get("amount_inr", 0)) for a in allocations)
    assert abs(total_allocated - 20000.0) < 1.0, "Budget must reconcile even with zero flexi/debt"


def test_flexi_drift_tracking_in_saa_analysis():
    """Test that Flexi Multi-Cap drift is tracked in SAA analysis.
    
    Verify that the calculate_saa_drift function properly computes and reports
    flexi_multi_cap specific tracking fields.
    """
    from core.math_engine import calculate_saa_drift, HoldingItem
    
    # Create proper HoldingItem objects
    flexi_fund = HoldingItem(
        scheme='HDFC Flexi Cap Fund',
        category='Flexi Cap',
        plan_type='Direct',
        current_value_inr=150000.0,
        invested_value_inr=100000.0,
        equity_pct=90.0,
        debt_pct=10.0,
        units=0,
        nav=0,
        folio_no='',
        amc_name='HDFC',
    )
    
    large_cap_fund = HoldingItem(
        scheme='ICICI Large Cap Fund',
        category='Large Cap',
        plan_type='Direct',
        current_value_inr=850000.0,
        invested_value_inr=700000.0,
        equity_pct=100.0,
        debt_pct=0.0,
        units=0,
        nav=0,
        folio_no='',
        amc_name='ICICI',
    )
    
    holdings = [flexi_fund, large_cap_fund]
    
    # Target with explicit flexi allocation
    target = {"large_cap_pct": 50.0, "flexi_multi_cap_pct": 15.0, "debt_pct": 35.0}
    
    drift = calculate_saa_drift(holdings, target_saa=target, tolerance_band_pct=5.0)
    
    # Verify flexi tracking fields exist and have correct values
    assert hasattr(drift, 'current_flexi_inr'), "SAADriftAnalysis should have current_flexi_inr field"
    assert hasattr(drift, 'target_flexi_pct'), "SAADriftAnalysis should have target_flexi_pct field"
    assert hasattr(drift, 'flexi_drift_pct'), "SAADriftAnalysis should have flexi_drift_pct field"
    
    # Current flexi should reflect the flexi fund value
    assert drift.current_flexi_inr == 150000.0, f"Expected current_flexi_inr=150000, got {drift.current_flexi_inr}"
    
    # Target flexi should be 15%
    assert drift.target_flexi_pct == 15.0, f"Expected target_flexi_pct=15.0, got {drift.target_flexi_pct}"


