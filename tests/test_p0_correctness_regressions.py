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


def test_tri_calculation_rejects_missing_terminal_cas_value(tmp_path):
    import hashlib
    import json
    from core.math_engine import calculate_cashflow_matched_benchmark_xirr
    from core.models import TriProvenanceError

    levels = {
        "2026-11-02": 100.0,
        "2026-11-03": 101.0,
        "2026-11-04": 102.0,
        "2026-11-05": 103.0,
        "2026-11-06": 104.0,
    }
    checksum = hashlib.sha256(
        json.dumps(levels, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    tri = {
        "provenance": {
            "checksum_sha256_nifty_500_tri": checksum,
            "frequency": "Daily",
            "historical_source_url": "https://example.invalid/historical-tri.csv",
            "source_document_sha256": "a" * 64,
        },
        "coverage": {
            "nifty_500_tri": {
                "expected_trading_days": 5,
                "provided_data_points": 5,
                "coverage_pct": 100.0,
            }
        },
        "benchmarks": {
            "NIFTY 500 TRI": {
                "name": "Test Nifty 500 TRI",
                "levels": levels,
            }
        },
    }
    transactions = {
        "transactions": [
            {"date": "2026-11-02", "amount": -1000.0, "type": "PURCHASE"}
        ]
    }
    tri_path = tmp_path / "tri.json"
    tx_path = tmp_path / "transactions.json"
    tri_path.write_text(json.dumps(tri), encoding="utf-8")
    tx_path.write_text(json.dumps(transactions), encoding="utf-8")

    with pytest.raises(TriProvenanceError, match="Current CAS valuation is missing"):
        calculate_cashflow_matched_benchmark_xirr(
            transactions_path=tx_path,
            as_of_date=date(2026, 11, 6),
            benchmark_key="NIFTY 500 TRI",
            benchmark_series_path=tri_path,
            cas_current=None,
        )


def test_tri_internal_switch_pair_is_netted_across_different_schemes(tmp_path):
    import hashlib
    import json
    from core.math_engine import calculate_cashflow_matched_benchmark_xirr

    levels = {
        "2026-11-02": 100.0,
        "2026-11-03": 101.0,
        "2026-11-04": 102.0,
        "2026-11-05": 103.0,
        "2026-11-06": 104.0,
    }
    checksum = hashlib.sha256(
        json.dumps(levels, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    tri = {
        "provenance": {
            "checksum_sha256_nifty_500_tri": checksum,
            "frequency": "Daily",
            "historical_source_url": "https://example.invalid/historical-tri.csv",
            "source_document_sha256": "a" * 64,
        },
        "coverage": {
            "nifty_500_tri": {
                "expected_trading_days": 5,
                "provided_data_points": 5,
                "coverage_pct": 100.0,
            }
        },
        "benchmarks": {"NIFTY 500 TRI": {"name": "Test TRI", "levels": levels}},
    }
    transactions = {
        "transactions": [
            {"date": "2026-11-03", "amount": 1000.0, "type": "SWITCH_OUT", "folio": "F1", "scheme": "Old Fund"},
            {"date": "2026-11-03", "amount": -1000.0, "type": "SWITCH_IN", "folio": "F1", "scheme": "New Fund"},
        ]
    }
    tri_path = tmp_path / "tri.json"
    tx_path = tmp_path / "transactions.json"
    tri_path.write_text(json.dumps(tri), encoding="utf-8")
    tx_path.write_text(json.dumps(transactions), encoding="utf-8")

    result = calculate_cashflow_matched_benchmark_xirr(
        transactions_path=tx_path,
        as_of_date=date(2026, 11, 6),
        benchmark_key="NIFTY 500 TRI",
        benchmark_series_path=tri_path,
        cas_current=1000.0,
    )
    assert result["cashflows_count"] == 0
    assert result["methodology"] == "Zero cashflows"


def test_tax_planner_respects_prior_ltcg_realized_in_current_fy():
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
                "long_term": {"rate_pct": 12.5, "exemption_limit_inr": 125000.0, "holding_period_months_gt": 12},
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
        prior_ltcg_this_fy=124900.0,
    )
    first_fy = 2026
    first_fy_rows = result[first_fy]
    assert sum(row["sheltered"] for row in first_fy_rows) == pytest.approx(100.0)
    assert sum(row["taxable"] for row in first_fy_rows) == pytest.approx(0.0)


def test_tax_planner_refuses_non_equity_tax_class_in_equity_exemption_path():
    lot = Lot(
        fund_id="fund-x",
        folio_name="folio-1",
        purchase_date=date(2024, 1, 1),
        units=10,
        nav=50,
        cost=500,
        source="cas",
        equity_pct=20.0,
    )
    plan = FundSellPlan(fund_id="fund-x", total_amount=1000.0, lots=[lot])
    with pytest.raises(ValueError, match="not supported by this equity-only exemption planner"):
        plan_fy_tranches(
            plans={"fund-x": plan},
            tax_rules={
                "ltcg_exemption": 125000.0,
                "lt_holding_months": 12,
                "exit_load_pct": 1.0,
                "classification_test": {"equity_oriented_threshold_pct": 65.0},
            },
            as_of=date(2026, 11, 3),
            current_navs={"fund-x": 100.0},
        )
