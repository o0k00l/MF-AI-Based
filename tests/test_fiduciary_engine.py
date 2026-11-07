"""Unit tests for services/fiduciary_engine.py."""
from __future__ import annotations

from decimal import Decimal
import pytest

from services.fiduciary_engine import (
    convert_cas_funds_to_holdings,
    evaluate_portfolio_saa_audit,
    generate_fiduciary_sip_blueprint,
    evaluate_fiduciary_lumpsum_blueprint,
)
from services.risk_profiler import TargetSaa


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


