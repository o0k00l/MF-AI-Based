"""Unit tests for services/fiduciary_engine.py."""
from __future__ import annotations

from decimal import Decimal
import pytest

from services.fiduciary_engine import (
    convert_cas_funds_to_holdings,
    evaluate_portfolio_saa_audit,
    generate_fiduciary_sip_blueprint,
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

