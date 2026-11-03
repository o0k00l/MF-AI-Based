"""Regression tests for fiduciary P0 correctness defects."""
from datetime import date

import pytest

from core.eligibility import _finite_number, _risk_tier_to_int, check_eligibility_gates
from tax.transition_planner import Lot, FundSellPlan, plan_fy_tranches, classify_fund_for_tax


def _write_test_nse_calendar(tmp_path, sessions):
    import hashlib
    import json

    sessions = sorted(sessions)
    sessions_sha256 = hashlib.sha256(
        json.dumps(sessions, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    calendar = {
        "exchange": "NSE",
        "status": "VERIFIED",
        "sessions": sessions,
        "provenance": {
            "source_url": "https://example.test/nse-calendar-fixture",
            "source_document_sha256": "b" * 64,
            "sessions_sha256": sessions_sha256,
        },
    }
    path = tmp_path / "nse_calendar.json"
    path.write_text(json.dumps(calendar), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Tier 1 (Low)", 1),
        ("Tier 2 (Low to Moderate)", 2),
        ("Tier 3 (Moderate)", 3),
        ("Tier 4 (Moderately High)", 4),
        ("Tier 5 (High)", 5),
        ("Tier 6 (Very High)", 6),
        ("Low to Moderate", 2),
        ("Moderately High", 4),
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
        prior_ltcg_this_fy=0.0,
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
    calendar_path = _write_test_nse_calendar(tmp_path, list(levels.keys()))

    with pytest.raises(TriProvenanceError, match="Current CAS valuation is missing"):
        calculate_cashflow_matched_benchmark_xirr(
            transactions_path=tx_path,
            as_of_date=date(2026, 11, 6),
            benchmark_key="NIFTY 500 TRI",
            benchmark_series_path=tri_path,
            cas_current=None,
            trading_calendar_path=calendar_path,
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
    calendar_path = _write_test_nse_calendar(tmp_path, list(levels.keys()))

    result = calculate_cashflow_matched_benchmark_xirr(
        transactions_path=tx_path,
        as_of_date=date(2026, 11, 6),
        benchmark_key="NIFTY 500 TRI",
        benchmark_series_path=tri_path,
        cas_current=1000.0,
        trading_calendar_path=calendar_path,
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
            prior_ltcg_this_fy=0.0,
        )


@pytest.mark.parametrize(
    "metrics",
    [
        {"top10_concentration_pct": float("nan")},
        {"top10_concentration_pct": float("inf")},
        {"downside_capture_ratio": float("nan"), "upside_capture_ratio": 100.0},
        {"downside_capture_ratio": 100.0, "upside_capture_ratio": float("inf")},
    ],
)
def test_eligibility_returns_fail_closed_for_non_finite_concentration_and_capture(metrics):
    base = {
        "fund_id": "fund-x",
        "fund_name": "Example Equity Direct Plan",
        "amc_name": "EXAMPLE AMC",
        "allocation_pct": 0.0,
        "aum_crore": 5000.0,
        "category": "Large Cap",
        "top10_concentration_pct": 30.0,
        "single_sector_weight_pct": 20.0,
        "sharpe_3y": 0.8,
        "alpha_3y": 2.0,
        "downside_capture_ratio": 80.0,
        "upside_capture_ratio": 110.0,
        "riskometer_score": 5,
        "confidence_score": 0.95,
        "data_complete": True,
        "manager_tenure_years": 4.0,
        "track_record_years": 5.0,
        "mandate_suitable": True,
        "aum_stable": True,
        "is_direct": True,
    }
    base.update(metrics)
    holdings = [
        {"amc_name": "EXAMPLE AMC", "current_value_inr": 200000.0},
        {"amc_name": "OTHER AMC", "current_value_inr": 800000.0},
    ]
    result = check_eligibility_gates(base, portfolio_holdings=holdings)
    assert result.passed is False
    assert any("Gate 3" in failure or "Gate 5" in failure for failure in result.failed_gates)


def test_daily_tri_calculation_uses_exact_observations_and_reports_unverified_source(tmp_path):
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
            "historical_source_url": "https://example.invalid/test-source.csv",
            "source_document_sha256": "d" * 64,
        },
        "benchmarks": {"NIFTY 500 TRI": {"name": "Test TRI", "levels": levels}},
    }
    transactions = {
        "transactions": [
            {"date": "2026-11-02", "amount": 1000.0, "type": "PURCHASE"}
        ]
    }
    tri_path = tmp_path / "tri.json"
    tx_path = tmp_path / "transactions.json"
    tri_path.write_text(json.dumps(tri), encoding="utf-8")
    tx_path.write_text(json.dumps(transactions), encoding="utf-8")
    calendar_path = _write_test_nse_calendar(tmp_path, list(levels.keys()))

    result = calculate_cashflow_matched_benchmark_xirr(
        transactions_path=tx_path,
        as_of_date=date(2026, 11, 6),
        benchmark_key="NIFTY 500 TRI",
        benchmark_series_path=tri_path,
        cas_current=1100.0,
        trading_calendar_path=calendar_path,
    )
    assert result["cashflows_count"] == 1
    assert result["benchmark_terminal_valuation_inr"] == pytest.approx(1040.0)
    assert result["portfolio_xirr_pct"] > result["benchmark_matched_xirr_pct"]
    assert result["provenance_audit"]["source_authenticity_verified"] is False


def test_tax_planner_rejects_missing_nav_and_insufficient_verified_lots():
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
    tax_rules = {
        "ltcg_exemption": 125000.0,
        "lt_holding_months": 12,
        "exit_load_pct": 1.0,
        "classes": {
            "equity_oriented": {
                "long_term": {"rate_pct": 12.5, "exemption_limit_inr": 125000.0, "holding_period_months_gt": 12},
                "short_term": {"rate_pct": 20.0},
            }
        },
        "exit_load_schedules": {},
    }
    with pytest.raises(ValueError, match="Missing or invalid current NAV"):
        plan_fy_tranches(
            plans={"fund-x": FundSellPlan(fund_id="fund-x", total_amount=1000.0, lots=[lot])},
            tax_rules=tax_rules,
            as_of=date(2026, 11, 3),
            current_navs={},
            prior_ltcg_this_fy=0.0,
        )
    with pytest.raises(ValueError, match="Insufficient verified lot value"):
        plan_fy_tranches(
            plans={"fund-x": FundSellPlan(fund_id="fund-x", total_amount=2000.0, lots=[lot])},
            tax_rules=tax_rules,
            as_of=date(2026, 11, 3),
            current_navs={"fund-x": 100.0},
            prior_ltcg_this_fy=0.0,
        )


def test_tax_planner_rejects_negative_sale_even_when_no_lots_exist():
    with pytest.raises(ValueError, match="Invalid sale amount"):
        plan_fy_tranches(
            plans={"fund-x": FundSellPlan(fund_id="fund-x", total_amount=-1.0, lots=[])},
            tax_rules={"ltcg_exemption": 125000.0},
            as_of=date(2026, 11, 3),
            current_navs={},
            prior_ltcg_this_fy=0.0,
        )


def test_non_thematic_eligibility_does_not_require_thematic_allocation_field():
    fund = {
        "fund_id": "fund-x",
        "fund_name": "Example Large Cap Direct Plan",
        "amc_name": "EXAMPLE AMC",
        "aum_crore": 5000.0,
        "category": "Large Cap",
        "top10_concentration_pct": 30.0,
        "single_sector_weight_pct": 20.0,
        "sharpe_3y": 0.8,
        "alpha_3y": 2.0,
        "downside_capture_ratio": 80.0,
        "upside_capture_ratio": 110.0,
        "riskometer_score": 5,
        "confidence_score": 0.95,
        "data_complete": True,
        "manager_tenure_years": 4.0,
        "track_record_years": 5.0,
        "mandate_suitable": True,
        "aum_stable": True,
        "is_direct": True,
    }
    holdings = [
        {"amc_name": "EXAMPLE AMC", "current_value_inr": 200000.0},
        {"amc_name": "OTHER AMC", "current_value_inr": 800000.0},
    ]
    result = check_eligibility_gates(fund, portfolio_holdings=holdings)
    assert result.thematic_satellite_gate is True


def test_fifo_tax_lot_loader_carries_verified_scheme_equity_allocation(tmp_path):
    import json
    from tax.transition_planner import load_transactions

    tx_path = tmp_path / "transactions.json"
    tx_path.write_text(
        json.dumps({
            "transactions": [{
                "scheme": "Example Equity Direct Growth",
                "date": "2024-01-01",
                "amount": 500.0,
                "units": 10.0,
                "nav": 50.0,
                "type": "PURCHASE",
            }]
        }),
        encoding="utf-8",
    )
    lots = load_transactions(
        tx_path,
        equity_allocation_by_fund={"Example Equity Direct Growth": 100.0},
    )
    assert lots["Example Equity Direct Growth"][0].equity_pct == pytest.approx(100.0)


def test_build_fifo_tax_lots_processes_all_rows_and_reconciles_units(tmp_path):
    import json
    from types import SimpleNamespace
    from core.math_engine import build_fifo_tax_lots

    tx_path = tmp_path / "transactions.json"
    tx_path.write_text(
        json.dumps({
            "transactions": [
                {"scheme": "Example Fund Direct Growth", "date": "2024-01-01", "amount": 1000.0, "units": 10.0, "nav": 100.0, "type": "PURCHASE"},
                {"scheme": "Example Fund Direct Growth", "date": "2024-02-01", "amount": 500.0, "units": 5.0, "nav": 100.0, "type": "SIP"},
                {"scheme": "Example Fund Direct Growth", "date": "2024-03-01", "amount": -450.0, "units": -4.0, "nav": 112.5, "type": "REDEMPTION"},
            ]
        }),
        encoding="utf-8",
    )
    holdings = [
        SimpleNamespace(
            fund_id="F1",
            scheme="Example Fund Direct Growth",
            fund_name="Example Fund Direct Growth",
            units=11.0,
            equity_pct=100.0,
        )
    ]
    lots = build_fifo_tax_lots(tx_path, holdings)
    assert sum(lot.units for lot in lots["F1"]) == pytest.approx(11.0)
    assert sum(lot.cost for lot in lots["F1"]) == pytest.approx(1100.0)
    assert len(lots["F1"]) == 2


def test_build_fifo_tax_lots_rejects_fuzzy_scheme_match_and_unreconciled_units(tmp_path):
    import json
    from types import SimpleNamespace
    from core.math_engine import build_fifo_tax_lots

    tx_path = tmp_path / "transactions.json"
    tx_path.write_text(
        json.dumps({
            "transactions": [
                {"scheme": "Example Fund Direct", "date": "2024-01-01", "amount": 1000.0, "units": 10.0, "nav": 100.0, "type": "PURCHASE"}
            ]
        }),
        encoding="utf-8",
    )
    holdings = [
        SimpleNamespace(
            fund_id="F1",
            scheme="Example Fund Direct Growth",
            fund_name="Example Fund Direct Growth",
            units=10.0,
            equity_pct=100.0,
        )
    ]
    with pytest.raises(ValueError, match="FIFO lot reconciliation failed"):
        build_fifo_tax_lots(tx_path, holdings)


def test_build_fifo_tax_lots_rejects_orphan_reversal(tmp_path):
    import json
    from types import SimpleNamespace
    from core.math_engine import build_fifo_tax_lots

    tx_path = tmp_path / "transactions.json"
    tx_path.write_text(
        json.dumps({
            "transactions": [
                {"scheme": "Example Fund", "date": "2024-01-01", "amount": 1000.0, "units": 10.0, "nav": 100.0, "type": "PURCHASE", "description": "Purchase"},
                {"scheme": "Example Fund", "date": "2024-01-02", "amount": 1000.0, "units": 10.0, "nav": 100.0, "type": "PURCHASE", "description": "Reversal of earlier transaction"},
            ]
        }),
        encoding="utf-8",
    )
    holdings = [
        SimpleNamespace(fund_id="F1", scheme="Example Fund", fund_name="Example Fund", units=10.0, equity_pct=100.0)
    ]
    with pytest.raises(ValueError, match="Orphan reversal"):
        build_fifo_tax_lots(tx_path, holdings)


def test_runtime_execution_requires_explicit_client_approved_state():
    from types import SimpleNamespace
    from core.math_engine import assert_mandate_execution_authorized
    from core.models import MandateExecutionState, MandateHoldViolationError

    with pytest.raises(MandateHoldViolationError):
        assert_mandate_execution_authorized(SimpleNamespace(
            mandate_state=MandateExecutionState.ADVISORY_PROPOSAL,
            is_execution_authorized=True,
        ))
    with pytest.raises(MandateHoldViolationError):
        assert_mandate_execution_authorized(SimpleNamespace(
            mandate_state=MandateExecutionState.HOLD_PENDING_TRI_VALIDATION,
            is_execution_authorized=True,
        ))
    assert_mandate_execution_authorized(SimpleNamespace(
        mandate_state=MandateExecutionState.CLIENT_APPROVED,
        is_execution_authorized=True,
    ))


@pytest.mark.parametrize(
    "transaction",
    [
        {"scheme": "Example Fund", "date": "2024-01-01", "amount": 100.0, "units": 1.0, "nav": 100.0, "type": "UNKNOWN"},
        {"scheme": "Example Fund", "date": "2024-01-01", "amount": 100.0, "units": 0.0, "nav": 100.0, "type": "PURCHASE"},
    ],
)
def test_transition_fifo_loader_rejects_unknown_or_incomplete_transaction_rows(tmp_path, transaction):
    import json
    from tax.transition_planner import load_transactions

    path = tmp_path / "transactions.json"
    path.write_text(json.dumps({"transactions": [transaction]}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_transactions(path)


@pytest.mark.parametrize(
    ("purchase_date", "expected_exit_load"),
    [
        (date(2025, 9, 1), 0.0),
        (date(2026, 5, 1), 9.0),
    ],
)
def test_current_fy_exit_load_uses_actual_planning_date(purchase_date, expected_exit_load):
    lot = Lot(
        fund_id="fund-x",
        folio_name="folio-1",
        purchase_date=purchase_date,
        units=10,
        nav=100,
        cost=1000,
        source="cas",
        equity_pct=100.0,
    )
    plan = FundSellPlan(fund_id="fund-x", total_amount=900.0, lots=[lot])
    result = plan_fy_tranches(
        plans={"fund-x": plan},
        tax_rules={
            "ltcg_exemption": 125000.0,
            "lt_holding_months": 12,
            "exit_load_pct": 1.0,
            "classification_test": {"equity_oriented_threshold_pct": 65.0},
            "exit_load_schedules": {},
        },
        as_of=date(2026, 11, 3),
        current_navs={"fund-x": 90.0},
        prior_ltcg_this_fy=0.0,
    )
    current_fy_rows = result[2026]
    assert sum(row["exit_load"] for row in current_fy_rows) == pytest.approx(expected_exit_load)


def test_direct_sip_validator_requires_explicit_flag_and_ignores_zero_orders():
    from types import SimpleNamespace
    from core.eligibility import validate_direct_sip_mandate

    valid = SimpleNamespace(items=[
        SimpleNamespace(scheme_name="Example Fund", monthly_inr=1000.0, is_direct=True)
    ])
    assert validate_direct_sip_mandate(valid) is True

    invalid = SimpleNamespace(items=[
        SimpleNamespace(scheme_name="Example Fund", monthly_inr=1000.0, is_direct=None)
    ])
    with pytest.raises(ValueError, match="lacks verified is_direct=True"):
        validate_direct_sip_mandate(invalid)

    no_order = SimpleNamespace(items=[
        SimpleNamespace(scheme_name="NO_ACTION: no candidate", monthly_inr=0.0, is_direct=None)
    ])
    assert validate_direct_sip_mandate(no_order) is True


def test_sip_builder_withholds_entire_budget_when_any_required_slot_is_unverified(monkeypatch):
    import core.math_engine as engine

    def fake_slots(**kwargs):
        return {
            "Slot 1: Core Flexi-Cap Compounder": {
                "scheme": "NO_ACTION: no eligible flexi",
                "fund_name": "NO_ACTION: no eligible flexi",
                "allocation_pct": 40.0,
                "rationale": "No eligible flexi candidate",
            },
            "Slot 2: Mid-Cap Alpha Engine": {
                "scheme": "Example Mid Fund",
                "fund_name": "Example Mid Fund",
                "fund_id": "test-mid",
                "allocation_pct": 30.0,
                "rationale": "Test",
            },
            "Slot 3: Large-Cap Bluechip Anchor": {
                "scheme": "Example Large Fund",
                "fund_name": "Example Large Fund",
                "fund_id": "test-large",
                "allocation_pct": 15.0,
                "rationale": "Test",
            },
            "Slot 4: Tactical Thematic Satellite": {
                "scheme": "NO_ACTION: no thematic allocation",
                "fund_name": "NO_ACTION: no thematic allocation",
                "allocation_pct": 0.0,
                "rationale": "No thematic selection",
            },
            "High-Grade Debt Anchor": {
                "scheme": "NO_ACTION: no debt candidate",
                "fund_name": "NO_ACTION: no debt candidate",
                "allocation_pct": 0.0,
                "rationale": "No debt selection",
            },
        }

    monkeypatch.setattr(engine, "select_autonomous_blueprint_funds", fake_slots)
    plan = engine.compute_deterministic_sip_blueprint(
        monthly_budget=100000.0,
        risk_tier="Tier 6 (Very High)",
        stability_buffer_pct=7.54,
        client_aum=5000000.0,
    )
    assert plan.total_monthly_budget_inr == pytest.approx(100000.0)
    assert plan.unallocated_budget_inr == pytest.approx(100000.0)
    assert sum(item.monthly_inr for item in plan.items) == pytest.approx(0.0)
    assert all(item.monthly_inr == 0.0 for item in plan.items)
    assert all("NO ACTION" in item.fiduciary_rationale for item in plan.items)


@pytest.mark.parametrize("confidence", [-0.1, 1.01, float("nan"), float("inf")])
def test_eligibility_rejects_out_of_range_confidence_score(confidence):
    fund = {
        "fund_id": "fund-x",
        "fund_name": "Example Large Cap Direct Plan",
        "amc_name": "EXAMPLE AMC",
        "aum_crore": 5000.0,
        "category": "Large Cap",
        "top10_concentration_pct": 30.0,
        "single_sector_weight_pct": 20.0,
        "sharpe_3y": 0.8,
        "alpha_3y": 2.0,
        "downside_capture_ratio": 80.0,
        "upside_capture_ratio": 110.0,
        "riskometer_score": 5,
        "confidence_score": confidence,
        "data_complete": True,
        "manager_tenure_years": 4.0,
        "track_record_years": 5.0,
        "mandate_suitable": True,
        "aum_stable": True,
        "is_direct": True,
        "plan": "Direct Plan - Growth Option",
        "isin": "TEST-ISIN",
    }
    holdings = [
        {"amc_name": "EXAMPLE AMC", "current_value_inr": 200000.0},
        {"amc_name": "OTHER AMC", "current_value_inr": 800000.0},
    ]
    result = check_eligibility_gates(fund, portfolio_holdings=holdings)
    assert result.data_integrity_gate is False
    assert result.passed is False


def test_gate10_accepts_explicit_direct_plan_growth_option_classification():
    fund = {
        "fund_id": "fund-x",
        "fund_name": "Example Large Cap Fund",
        "amc_name": "EXAMPLE AMC",
        "aum_crore": 5000.0,
        "category": "Large Cap",
        "top10_concentration_pct": 30.0,
        "single_sector_weight_pct": 20.0,
        "sharpe_3y": 0.8,
        "alpha_3y": 2.0,
        "downside_capture_ratio": 80.0,
        "upside_capture_ratio": 110.0,
        "riskometer_score": 5,
        "confidence_score": 0.95,
        "data_complete": True,
        "manager_tenure_years": 4.0,
        "track_record_years": 5.0,
        "mandate_suitable": True,
        "aum_stable": True,
        "is_direct": True,
        "plan": "Direct Plan - Growth Option",
        "isin": "TEST-ISIN",
    }
    holdings = [
        {"amc_name": "EXAMPLE AMC", "current_value_inr": 200000.0},
        {"amc_name": "OTHER AMC", "current_value_inr": 800000.0},
    ]
    result = check_eligibility_gates(fund, portfolio_holdings=holdings)
    assert result.direct_plan_gate is True


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Tier 1 (Capital Preservation)", 1),
        ("Tier 2 (Low to Moderate)", 2),
        ("Tier 3 (Moderate)", 3),
        ("Tier 4 (Moderately High)", 4),
        ("Tier 5 (High)", 5),
        ("Tier 6 (Very High)", 6),
        ("Aggressive", 6),
    ],
)
def test_engine_risk_tier_parser_is_unambiguous(label, expected):
    from core.math_engine import _parse_sebi_risk_tier
    assert _parse_sebi_risk_tier(label) == expected


@pytest.mark.parametrize("bad_tier", ["", "unknown", "risk 7", None])
def test_engine_risk_tier_parser_rejects_unrecognized_values(bad_tier):
    from core.math_engine import _parse_sebi_risk_tier
    with pytest.raises(ValueError):
        _parse_sebi_risk_tier(bad_tier)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"monthly_budget": -1.0},
        {"monthly_budget": float("nan")},
        {"client_aum": float("inf")},
        {"stability_buffer_pct": 101.0},
    ],
)
def test_sip_blueprint_rejects_invalid_numeric_inputs(monkeypatch, kwargs):
    import core.math_engine as engine
    args = {
        "monthly_budget": 10000.0,
        "risk_tier": "Tier 6 (Very High)",
        "stability_buffer_pct": 7.5,
        "client_aum": 1000000.0,
    }
    args.update(kwargs)
    # Invalid numeric inputs are rejected before the selection engine is called.
    monkeypatch.setattr(
        engine,
        "select_autonomous_blueprint_funds",
        lambda **_kwargs: {},
    )
    with pytest.raises(ValueError):
        engine.compute_deterministic_sip_blueprint(**args)


def test_tax_planner_requires_verified_prior_ltcg_headroom(tmp_path):
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
    with pytest.raises(ValueError, match="Verified prior_ltcg_this_fy is required"):
        plan_fy_tranches(
            plans={"fund-x": FundSellPlan(fund_id="fund-x", total_amount=1000.0, lots=[lot])},
            tax_rules={
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
                "exit_load_schedules": {},
            },
            as_of=date(2026, 11, 3),
            current_navs={"fund-x": 100.0},
        )


# Statutory regression coverage: Section 50AA / Section 76 effective dates and evidence gates.
def _daily_snapshots_for_fy(fy_start, fy_end, debt_pct, money_market_pct, equity_pct=10.0):
    from datetime import timedelta
    from core.math_engine import DailyPortfolioSnapshot

    snapshots = []
    current = fy_start
    while current <= fy_end:
        snapshots.append(
            DailyPortfolioSnapshot(
                date=current,
                equity_pct=equity_pct,
                debt_pct=debt_pct,
                money_market_pct=money_market_pct,
            )
        )
        current += timedelta(days=1)
    return snapshots


def test_section_50aa_original_equity_test_applies_through_fy_2025_26():
    from core.math_engine import classify_specified_mutual_fund

    result = classify_specified_mutual_fund(
        "Debt",
        equity_pct=35.0,
        debt_and_money_market_pct=60.0,
        acquisition_date=date(2023, 4, 1),
        transfer_date=date(2026, 3, 31),
    )
    assert result["specified_50AA"]["qualifies"] is True
    assert result["specified_50AA"]["threshold"] == 35.0
    assert result["tax_treatment"] == "SECTION_50AA_DEEMED_STCG"

    not_qualifying = classify_specified_mutual_fund(
        "Hybrid",
        equity_pct=35.01,
        debt_and_money_market_pct=64.99,
        acquisition_date=date(2023, 4, 1),
        transfer_date=date(2026, 3, 31),
    )
    assert not_qualifying["specified_50AA"]["qualifies"] is False


def test_section_50aa_mld_is_independent_of_unit_acquisition_date():
    from core.math_engine import classify_specified_mutual_fund

    result = classify_specified_mutual_fund(
        "MLD",
        equity_pct=0.0,
        debt_and_money_market_pct=0.0,
        acquisition_date=date(2020, 1, 1),
        transfer_date=date(2026, 3, 31),
        is_mld=True,
    )
    assert result["specified_50AA"]["qualifies"] is True
    assert "Market-Linked Debenture" in result["specified_50AA"]["provision"]


def test_section_76_requires_acquisition_date_and_daily_series_coverage():
    from core.math_engine import classify_specified_mutual_fund
    from core.models import InsufficientDataError

    with pytest.raises(InsufficientDataError, match="acquisition date"):
        classify_specified_mutual_fund(
            "Debt",
            equity_pct=10.0,
            debt_and_money_market_pct=90.0,
            transfer_date=date(2026, 11, 3),
        )

    snapshots = _daily_snapshots_for_fy(
        date(2026, 4, 1), date(2027, 3, 31), debt_pct=70.0, money_market_pct=10.0
    )
    with pytest.raises(InsufficientDataError, match="explicit expected-date coverage evidence"):
        classify_specified_mutual_fund(
            "Debt",
            equity_pct=10.0,
            debt_and_money_market_pct=90.0,
            acquisition_date=date(2023, 4, 1),
            transfer_date=date(2026, 11, 3),
            snapshots=snapshots,
            fy_start=date(2026, 4, 1),
            fy_end=date(2027, 3, 31),
            snapshot_coverage_evidence=None,
        )


@pytest.mark.parametrize(
    ("debt_pct", "money_market_pct", "expected"),
    [
        (64.5, 0.5, False),   # exactly 65% does not meet the strict >65% limb
        (64.51, 0.5, True),  # 65.01% qualifies
    ],
)
def test_section_76_strict_debt_plus_money_market_boundary(debt_pct, money_market_pct, expected):
    from core.math_engine import classify_specified_mutual_fund

    fy_start, fy_end = date(2026, 4, 1), date(2027, 3, 31)
    snapshots = _daily_snapshots_for_fy(fy_start, fy_end, debt_pct, money_market_pct)
    result = classify_specified_mutual_fund(
        "Debt",
        equity_pct=10.0,
        debt_and_money_market_pct=90.0,  # deliberately different; not used as a point-in-time proxy
        acquisition_date=date(2023, 4, 1),
        transfer_date=date(2026, 11, 3),
        snapshots=snapshots,
        fy_start=fy_start,
        fy_end=fy_end,
        snapshot_coverage_evidence=__import__("core.math_engine", fromlist=["DailySnapshotCoverageEvidence"]).DailySnapshotCoverageEvidence(
            expected_dates=tuple(snapshot.date for snapshot in snapshots),
            source_url="https://example.test/verified-daily-calendar",
            source_document_sha256="b" * 64,
            independently_verified=True,
        ),
    )
    assert result["specified_76"]["effective_debt_pct"] == pytest.approx(debt_pct + money_market_pct)
    assert result["specified_76"]["qualifies"] is expected
    assert result["tax_treatment"] == (
        "SECTION_76_DEEMED_STCG" if expected else "HYBRID_UNLISTED_OR_NORMAL"
    )


@pytest.mark.parametrize(
    ("fof_pct", "expected"),
    [(64.99, False), (65.0, True)],
)
def test_section_76_fund_of_funds_threshold_is_inclusive(fof_pct, expected):
    from core.math_engine import classify_specified_mutual_fund

    result = classify_specified_mutual_fund(
        "Fund of Funds",
        equity_pct=10.0,
        debt_and_money_market_pct=0.0,
        is_fund_of_funds=True,
        fof_debt_investing_pct=fof_pct,
        acquisition_date=date(2023, 4, 1),
        transfer_date=date(2026, 11, 3),
    )
    assert result["specified_76"]["qualifies"] is expected


def test_daily_average_rejects_duplicate_and_non_finite_composition_observations():
    from core.math_engine import DailyPortfolioSnapshot, compute_annual_average_daily_closing

    fy_start, fy_end = date(2026, 4, 1), date(2027, 3, 31)
    duplicate = [
        DailyPortfolioSnapshot(fy_start, 10.0, 80.0, 10.0),
        DailyPortfolioSnapshot(fy_start, 10.0, 80.0, 10.0),
    ]
    with pytest.raises(ValueError, match="Duplicate daily portfolio snapshot"):
        compute_annual_average_daily_closing(duplicate, fy_start, fy_end, "debt_pct")

    invalid = [DailyPortfolioSnapshot(fy_start, 10.0, float("nan"), 10.0)]
    with pytest.raises(ValueError, match="finite and between 0 and 100"):
        compute_annual_average_daily_closing(invalid, fy_start, fy_end, "debt_pct")


def test_tax_policy_has_separate_section_50aa_and_section_76_effective_dates():
    import json
    from pathlib import Path

    policy = json.loads((Path(__file__).resolve().parents[1] / "data/policy/tax_rules.json").read_text())
    regimes = policy["specified_mutual_fund_regimes"]
    old = regimes["section_50AA_1961"]
    new = regimes["section_76_2025"]
    assert old["transfer_effective_from"] == "2024-04-01"
    assert old["transfer_effective_to_exclusive"] == "2026-04-01"
    assert "not_more_than_35_percent" in old["mutual_fund_test"]
    assert new["transfer_effective_from"] == "2026-04-01"
    assert "more_than_65_percent" in new["mutual_fund_test"]
    assert "at_least_65_percent" in new["fund_of_funds_test"]
    assert "complete_daily_observation_coverage" in new["evidence_required"]
    assert policy["status"] == "provisional_statutory_review_required"


def test_thematic_category_does_not_create_automatic_redemption_instruction():
    import json
    from pathlib import Path

    policy = json.loads((Path(__file__).resolve().parents[1] / "data/policy/fund_screening.json").read_text())
    rule = policy["category_rules"]["thematic_sectoral_liquidation"]
    assert rule["action"] == "REVIEW_REQUIRED"
    assert "not a redemption instruction" in rule["rationale"]
    assert "Do not force liquidation" in rule["rationale"]


def test_standalone_advisor_saa_profiles_reconcile_to_central_policy():
    import ast
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    source = ast.parse((root / "advisor_lean.py").read_text())
    profile_node = next(
        node.value for node in source.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SEBI_RISKOMETER_PROFILES" for target in node.targets)
    )
    profiles = ast.literal_eval(profile_node)
    policy = json.loads((root / "data/policy/asset_allocation.json").read_text())
    keys = ["1_low", "2_low_to_moderate", "3_moderate", "4_moderately_high", "5_high", "6_very_high"]
    policy_keys = ["low", "low_to_moderate", "moderate", "moderately_high", "high", "very_high"]
    for key, policy_key in zip(keys, policy_keys):
        profile = profiles[key]
        targets = policy["behavioral_risk_profiles"][policy_key]["saa_targets"]
        expected = {
            "large": targets["large_cap_pct"] + targets["flexi_multi_cap_pct"],
            "mid_small": targets["mid_cap_pct"] + targets["small_cap_pct"],
            "debt": targets["debt_liquid_pct"],
        }
        assert {k: profile[k] for k in expected} == expected
        assert sum(expected.values()) == 100
        assert policy["behavioral_risk_profiles"][policy_key]["max_equity_pct"] == (
            targets["large_cap_pct"] + targets["mid_cap_pct"] + targets["small_cap_pct"] + targets["flexi_multi_cap_pct"]
        )
    compute_saa = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef) and node.name == "compute_saa"
    )
    params = {arg.arg for arg in compute_saa.args.args}
    assert {"current_exposure", "total_value"} <= params


def test_thematic_satellite_requires_explicit_authorization_and_is_carved_out():
    from core.math_engine import compute_deterministic_sip_blueprint

    with pytest.raises(ValueError, match="explicit IPS authorization"):
        compute_deterministic_sip_blueprint(
            monthly_budget=100000.0,
            risk_tier="Tier 6 (Very High)",
            stability_buffer_pct=7.54,
            client_aum=5000000.0,
            thematic_satellite_pct_of_equity=5.0,
        )

    plan = compute_deterministic_sip_blueprint(
        monthly_budget=100000.0,
        risk_tier="Tier 6 (Very High)",
        stability_buffer_pct=7.54,
        client_aum=5000000.0,
        thematic_satellite_pct_of_equity=5.0,
        thematic_satellite_authorized=True,
    )
    roles = {item.category_role: item for item in plan.items}
    assert roles["Tactical Thematic Satellite"].allocation_pct == 5.0
    assert sum(item.allocation_pct for item in plan.items) == pytest.approx(100.0)
    # With no verified candidate data, the engine must withhold the entire budget.
    if plan.unallocated_budget_inr > 0:
        assert all(item.monthly_inr == 0.0 for item in plan.items)


@pytest.mark.parametrize(
    ("tier", "profile"),
    [
        (1, "low"),
        (2, "low_to_moderate"),
        (3, "moderate"),
        (4, "moderately_high"),
        (5, "high"),
        (6, "very_high"),
    ],
)
def test_universal_tier_split_uses_policy_base_and_stability_threshold(tier, profile):
    import json
    from pathlib import Path
    from core.math_engine import calculate_universal_tier_split

    policy = json.loads(
        (Path(__file__).resolve().parents[1] / "data/policy/asset_allocation.json").read_text()
    )
    p = policy["behavioral_risk_profiles"][profile]
    targets = p["saa_targets"]
    assert sum(targets.values()) == 100
    expected_equity = p["new_sip_allocation"]["equity_pct"]
    expected_debt = p["new_sip_allocation"]["debt_pct"]
    assert calculate_universal_tier_split(tier) == (expected_equity, expected_debt)

    threshold = max(0.0, targets["debt_liquid_pct"] - p["tolerance_band_pct"])
    if threshold > 0:
        assert calculate_universal_tier_split(tier, threshold - 0.01) == (expected_equity, expected_debt)
    assert calculate_universal_tier_split(tier, threshold) == (100.0, 0.0)


def test_section_76_rejects_missing_dates_even_with_calendar_provenance():
    from core.math_engine import (
        DailySnapshotCoverageEvidence,
        classify_specified_mutual_fund,
    )
    from core.models import InsufficientDataError

    fy_start, fy_end = date(2026, 4, 1), date(2027, 3, 31)
    snapshots = _daily_snapshots_for_fy(fy_start, fy_end, debt_pct=70.0, money_market_pct=10.0)
    expected = tuple(snapshot.date for snapshot in snapshots)
    evidence = DailySnapshotCoverageEvidence(
        expected_dates=expected,
        source_url="https://example.test/verified-daily-calendar",
        source_document_sha256="c" * 64,
        independently_verified=True,
    )
    incomplete = snapshots[:-1]
    with pytest.raises(InsufficientDataError, match="do not exactly match"):
        classify_specified_mutual_fund(
            "Debt",
            equity_pct=10.0,
            debt_and_money_market_pct=90.0,
            acquisition_date=date(2023, 4, 1),
            transfer_date=date(2026, 11, 3),
            snapshots=incomplete,
            fy_start=fy_start,
            fy_end=fy_end,
            snapshot_coverage_evidence=evidence,
        )
