"""Regression tests for fiduciary P0 correctness defects."""
from datetime import date

import pytest

from core.eligibility import _finite_number, _risk_tier_to_int, check_eligibility_gates
from tax.transition_planner import Lot, FundSellPlan, plan_fy_tranches, classify_fund_for_tax


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Tier 1 (Low)", 1),
        ("Tier 2 (Low to Moderate)", 2),
        ("Tier 3 (Moderate)", 3),
        ("Tier 4 (Moderately High)", 4),
        ("Tier 5 (High)", 5),
        ("Tier 6 (Very High)", 6),
        ("Very High", 6),
        ("Aggressive", 6),
    ],
)
def test_risk_tier_parser_resolves_unambiguous_labels(label, expected):
    assert _risk_tier_to_int(label) == expected


@pytest.mark.parametrize("bad", [None, True, "", " ", "not-a-number", float("nan"), float("inf"), float("-inf")])
def test_finite_numeric_parser_rejects_missing_and_non_finite_values(bad):
    with pytest.raises(ValueError):
        _finite_number(bad, "test_value")


def test_eligibility_fails_closed_when_amc_and_portfolio_data_are_missing():
    result = check_eligibility_gates(
        fund_data={"fund_id": "fund-x", "fund_name": "Example Equity Fund", "category": "Large Cap"},
        portfolio_holdings=None,
    )
    assert result.passed is False
    assert any("Gate 1" in failure and "fail-closed" in failure for failure in result.failed_gates)
    assert result.direct_plan_gate is False


def test_tax_classification_requires_verified_equity_allocation():
    lot = Lot(
        fund_id="fund-x",
        folio_name="folio-1",
        purchase_date=date(2024, 1, 1),
        units=10,
        nav=50,
        cost=500,
        source="cas",
    )
    with pytest.raises(ValueError, match="equity_allocation_pct is required"):
        classify_fund_for_tax(lot, {"classification_test": {"equity_oriented_threshold_pct": 65.0}})


def test_tax_planner_allocates_each_lot_only_once():
    lot = Lot(
        fund_id="fund-x",
        folio_name="folio-1",
        purchase_date=date(2024, 1, 1),
        units=10,
        nav=50,
        cost=500,
        source="cas",
        equity_pct=100.0,
    )
    plan = FundSellPlan(fund_id="fund-x", total_amount=1000.0, lots=[lot])
    tax_rules = {
        "ltcg_exemption": 125000.0,
        "lt_holding_months": 12,
        "exit_load_pct": 1.0,
        "classification_test": {"equity_oriented_threshold_pct": 65.0},
        "classes": {
            "equity_oriented": {
                "long_term": {
                    "rate_pct": 12.5,
                    "exemption_limit_inr": 125000.0,
                    "holding_period_months_gt": 12,
                },
                "short_term": {"rate_pct": 20.0},
            }
        },
        "cess": {"health_education_cess_pct": 4.0},
        "exit_load_schedules": {},
    }
    result = plan_fy_tranches(
        plans={"fund-x": plan},
        tax_rules=tax_rules,
        as_of=date(2026, 11, 3),
        current_navs={"fund-x": 100.0},
    )
    tranches = [row for rows in result.values() for row in rows]
    assert sum(row["units_sold"] for row in tranches) == pytest.approx(10.0)
    assert len(tranches) == 1
