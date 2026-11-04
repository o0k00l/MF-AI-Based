"""Regression tests for fiduciary P0 correctness defects."""
from datetime import date
from pathlib import Path

import pytest

_TEST_TAX_EVIDENCE_ROOT = Path(__file__).resolve().parent / "fixtures"
_TEST_TAX_EVIDENCE_SHA256 = "e3da5a5eb89824a20c0eb0b214fa5123548fada0976e7bb31c4d742d6efbe3fc"


def _synthetic_tax_evidence_kwargs():
    """Synthetic local file evidence: integrity only, never legal/source authenticity."""
    return {
        "equity_pct_source_sha256": _TEST_TAX_EVIDENCE_SHA256,
        "equity_pct_source_file": "synthetic_tax_evidence.txt",
        "equity_pct_evidence_root": str(_TEST_TAX_EVIDENCE_ROOT),
    }

from core.eligibility import _finite_number, _risk_tier_to_int, check_eligibility_gates
from types import SimpleNamespace
from core.math_engine import _parse_sebi_risk_tier, _sip_operational_constraint_violations, compute_candidate_portfolio_overlap, select_autonomous_blueprint_funds
from core.models import AssetAllocationTarget, DeterministicSIPPlan, DeterministicSIPRecommendation, RiskTier
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


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Conservative", 2),
        ("Moderate", 4),
        ("Aggressive", 6),
        ("Tier 3 (Moderate)", 3),
        ("Tier 4 (Moderately High)", 4),
    ],
)
def test_sip_builder_parser_distinguishes_investor_profiles_from_sebi_tiers(label, expected):
    assert _parse_sebi_risk_tier(label) == expected


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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_tax_classification_recomputes_source_document_digest_and_blocks_path_escape():
    lot = Lot(
        fund_id="fund-x",
        folio_name="folio-1",
        purchase_date=date(2024, 1, 1),
        units=10,
        nav=50,
        cost=500,
        source="cas",
        equity_pct=100.0,
        equity_pct_method="annual_average_monthly_opening_closing",
        equity_pct_fy_start=2026,
        equity_pct_source_url="https://example.test/synthetic-monthly-disclosure",
        equity_pct_source_reviewed=True,
        **_synthetic_tax_evidence_kwargs(),
    )
    rules = {"classification_test": {"equity_oriented_threshold_pct": 65.0}}
    assert classify_fund_for_tax(lot, rules, sale_date=date(2026, 11, 3)) == "equity_oriented"

    original_root = lot.equity_pct_evidence_root
    lot.equity_pct_evidence_root = None
    with pytest.raises(ValueError, match="source evidence root is required"):
        classify_fund_for_tax(lot, rules, sale_date=date(2026, 11, 3))
    lot.equity_pct_evidence_root = original_root

    lot.equity_pct_source_sha256 = "0" * 64
    with pytest.raises(ValueError, match="does not match local source bytes"):
        classify_fund_for_tax(lot, rules, sale_date=date(2026, 11, 3))

    lot.equity_pct_source_sha256 = _TEST_TAX_EVIDENCE_SHA256
    lot.equity_pct_source_file = "../synthetic_tax_evidence.txt"
    with pytest.raises(ValueError, match="cannot be safely verified"):
        classify_fund_for_tax(lot, rules, sale_date=date(2026, 11, 3))


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
        equity_pct_method="annual_average_monthly_opening_closing",
        equity_pct_fy_start=2026,
        equity_pct_source_url="https://example.test/monthly-portfolio-disclosure",
        **_synthetic_tax_evidence_kwargs(),
        equity_pct_source_reviewed=True,
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
        equity_pct_method="annual_average_monthly_opening_closing",
        equity_pct_fy_start=2026,
        equity_pct_source_url="https://example.test/verified-monthly-disclosure",
        **_synthetic_tax_evidence_kwargs(),
        equity_pct_source_reviewed=True,
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
        equity_pct_method="annual_average_monthly_opening_closing",
        equity_pct_fy_start=2026,
        equity_pct_source_url="https://example.test/verified-monthly-disclosure",
        **_synthetic_tax_evidence_kwargs(),
        equity_pct_source_reviewed=True,
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
        equity_pct_method="annual_average_monthly_opening_closing",
        equity_pct_fy_start=2026,
        equity_pct_source_url="https://example.test/verified-monthly-disclosure",
        **_synthetic_tax_evidence_kwargs(),
        equity_pct_source_reviewed=True,
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
    allocation = {
        "equity_pct": 100.0,
        "method": "annual_average_monthly_opening_closing",
        "financial_year_start": 2026,
        "source_url": "https://example.test/synthetic-monthly-disclosure",
        "source_document_sha256": _TEST_TAX_EVIDENCE_SHA256,
        "independently_verified": True,
        "source_file": "synthetic_tax_evidence.txt",
    }
    lots = load_transactions(
        tx_path,
        equity_allocation_by_fund={"Example Equity Direct Growth": allocation},
        evidence_root=_TEST_TAX_EVIDENCE_ROOT,
    )
    lot = lots["Example Equity Direct Growth"][0]
    assert lot.equity_pct == pytest.approx(100.0)
    assert lot.equity_pct_source_file == "synthetic_tax_evidence.txt"
    assert lot.equity_pct_evidence_root == str(_TEST_TAX_EVIDENCE_ROOT.resolve())


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
        equity_pct_method="annual_average_monthly_opening_closing",
        equity_pct_fy_start=2026,
        equity_pct_source_url="https://example.test/verified-monthly-disclosure",
        **_synthetic_tax_evidence_kwargs(),
        equity_pct_source_reviewed=True,
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
            "Slot 3: Small-Cap Growth Engine": {
                "scheme": "Example Small Fund", "fund_name": "Example Small Fund",
                "fund_id": "test-small", "allocation_pct": 15.0, "rationale": "Test",
            },
            "Slot 4: Large-Cap Bluechip Anchor": {
                "scheme": "Example Large Fund",
                "fund_name": "Example Large Fund",
                "fund_id": "test-large",
                "allocation_pct": 15.0,
                "rationale": "Test",
            },
            "Slot 5: Tactical Thematic Satellite": {
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
def test_eligibility_rejects_out_of_range_confidence_score(confidence, tmp_path):
    import hashlib
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
        "scheme_id": "TEST-SCHEME-X",
    }
    source_bytes = b"SYNTHETIC TEST ONLY: Example Large Cap Fund; Direct Plan - Growth Option"
    source_file = tmp_path / "scheme-master-source.txt"
    source_file.write_bytes(source_bytes)
    fund["direct_plan_evidence"] = {
        "source_file": source_file.name,
        "source_document_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_url": "https://example.test/synthetic-scheme-master",
        "source_type": "AMFI_SCHEME_MASTER",
        "reviewer_attested": True,
        "reviewed_at": date.today().isoformat(),
        "scheme_name": fund["fund_name"],
        "scheme_id": fund["scheme_id"],
        "isin": fund["isin"],
        "amc_name": fund["amc_name"],
        "plan": "Direct",
    }
    fund["_evidence_root"] = str(tmp_path.resolve())
    holdings = [
        {"amc_name": "EXAMPLE AMC", "current_value_inr": 200000.0},
        {"amc_name": "OTHER AMC", "current_value_inr": 800000.0},
    ]
    result = check_eligibility_gates(fund, portfolio_holdings=holdings)
    assert result.data_integrity_gate is False
    assert result.passed is False


def test_gate10_accepts_explicit_direct_plan_growth_option_classification(tmp_path):
    import hashlib
    from datetime import date

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
        "scheme_id": "TEST-SCHEME-001",
    }
    source_bytes = b"SYNTHETIC TEST ONLY: Example Large Cap Fund; Direct Plan - Growth Option"
    source_file = tmp_path / "scheme-master-source.txt"
    source_file.write_bytes(source_bytes)
    fund["direct_plan_evidence"] = {
        "source_file": source_file.name,
        "source_document_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "source_url": "https://example.test/synthetic-scheme-master",
        "source_type": "AMFI_SCHEME_MASTER",
        "reviewer_attested": True,
        "reviewed_at": date.today().isoformat(),
        "scheme_name": fund["fund_name"],
        "scheme_id": fund["scheme_id"],
        "isin": fund["isin"],
        "amc_name": fund["amc_name"],
        "plan": "Direct",
    }
    fund["_evidence_root"] = str(tmp_path.resolve())
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
        equity_pct_method="annual_average_monthly_opening_closing",
        equity_pct_fy_start=2026,
        equity_pct_source_url="https://example.test/verified-monthly-disclosure",
        **_synthetic_tax_evidence_kwargs(),
        equity_pct_source_reviewed=True,
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
def _daily_snapshots_for_fy(fy_start, fy_end, debt_pct, money_market_pct, equity_pct=10.0, fof_pct=None):
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
                fof_specified_mf_pct=fof_pct,
            )
        )
        current += timedelta(days=1)
    return snapshots


def _monthly_coverage_evidence(fy_start, snapshots):
    from core.math_engine import MonthlySnapshotCoverageEvidence

    return MonthlySnapshotCoverageEvidence(
        expected_months=tuple(snapshot.month for snapshot in snapshots),
        source_url="https://example.test/verified-monthly-calendar",
        source_document_sha256="c" * 64,
        reviewer_attested=True,
    )


def _monthly_snapshots_for_fy(fy_start, equity_pct=10.0, fof_units_pct=0.0, underlying_equity_pct=0.0):
    from core.math_engine import MonthlyPortfolioSnapshot

    rows = []
    for month in range(4, 13):
        rows.append(MonthlyPortfolioSnapshot(
            month=date(fy_start.year, month, 1),
            opening_equity_pct=equity_pct,
            closing_equity_pct=equity_pct,
            opening_fof_units_pct=fof_units_pct,
            closing_fof_units_pct=fof_units_pct,
            opening_underlying_equity_pct=underlying_equity_pct,
            closing_underlying_equity_pct=underlying_equity_pct,
        ))
    for month in range(1, 4):
        rows.append(MonthlyPortfolioSnapshot(
            month=date(fy_start.year + 1, month, 1),
            opening_equity_pct=equity_pct,
            closing_equity_pct=equity_pct,
            opening_fof_units_pct=fof_units_pct,
            closing_fof_units_pct=fof_units_pct,
            opening_underlying_equity_pct=underlying_equity_pct,
            closing_underlying_equity_pct=underlying_equity_pct,
        ))
    return rows


def _daily_coverage_evidence(snapshots):
    from core.math_engine import DailySnapshotCoverageEvidence

    return DailySnapshotCoverageEvidence(
        expected_dates=tuple(snapshot.date for snapshot in snapshots),
        source_url="https://example.test/verified-daily-calendar",
        source_document_sha256="b" * 64,
        reviewer_attested=True,
    )


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_section_50aa_original_equity_test_applies_through_fy_2025_26():
    from core.math_engine import classify_specified_mutual_fund

    fy_start, fy_end = date(2025, 4, 1), date(2026, 3, 31)
    daily = _daily_snapshots_for_fy(fy_start, fy_end, debt_pct=60.0, money_market_pct=5.0, equity_pct=35.0)
    monthly = _monthly_snapshots_for_fy(fy_start, equity_pct=35.0)
    result = classify_specified_mutual_fund(
        "Debt",
        equity_pct=35.0,
        debt_and_money_market_pct=65.0,
        acquisition_date=date(2023, 4, 1),
        transfer_date=date(2026, 3, 31),
        snapshots=daily,
        monthly_snapshots=monthly,
        monthly_coverage_evidence=_monthly_coverage_evidence(fy_start, monthly),
        fy_start=fy_start,
        fy_end=fy_end,
        snapshot_coverage_evidence=_daily_coverage_evidence(daily),
    )
    assert result["specified_50AA"]["qualifies"] is True
    assert result["specified_50AA"]["threshold"] == 35.0
    assert result["specified_50AA"]["source_data_status"] == "PROVISIONAL_DAILY_COVERAGE_RECONCILED"
    assert result["tax_treatment"] == "SECTION_50AA_DEEMED_STCG"

    not_qualifying = classify_specified_mutual_fund(
        "Hybrid",
        equity_pct=35.01,
        debt_and_money_market_pct=64.99,
        acquisition_date=date(2023, 4, 1),
        transfer_date=date(2026, 3, 31),
        snapshots=_daily_snapshots_for_fy(fy_start, fy_end, debt_pct=60.0, money_market_pct=5.0, equity_pct=35.01),
        monthly_snapshots=_monthly_snapshots_for_fy(fy_start, equity_pct=35.01),
        monthly_coverage_evidence=_monthly_coverage_evidence(fy_start, _monthly_snapshots_for_fy(fy_start, equity_pct=35.01)),
        fy_start=fy_start,
        fy_end=fy_end,
        snapshot_coverage_evidence=_daily_coverage_evidence(_daily_snapshots_for_fy(fy_start, fy_end, debt_pct=60.0, money_market_pct=5.0, equity_pct=35.01)),
    )
    assert not_qualifying["specified_50AA"]["qualifies"] is False


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_section_76_requires_acquisition_date_and_daily_series_coverage():
    from core.math_engine import classify_specified_mutual_fund
    from core.models import InsufficientDataError

    with pytest.raises(InsufficientDataError, match="acquisition date"):
        classify_specified_mutual_fund(
            "Debt",
            equity_pct=10.0,
            debt_and_money_market_pct=90.0,
            transfer_date=date(2026, 11, 3),
            monthly_snapshots=_monthly_snapshots_for_fy(date(2026, 4, 1), equity_pct=10.0),
            monthly_coverage_evidence=_monthly_coverage_evidence(date(2026, 4, 1), _monthly_snapshots_for_fy(date(2026, 4, 1), equity_pct=10.0)),
            fy_start=date(2026, 4, 1),
            fy_end=date(2027, 3, 31),
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
            monthly_snapshots=_monthly_snapshots_for_fy(date(2026, 4, 1), equity_pct=10.0),
            monthly_coverage_evidence=_monthly_coverage_evidence(date(2026, 4, 1), _monthly_snapshots_for_fy(date(2026, 4, 1), equity_pct=10.0)),
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
@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
        monthly_snapshots=_monthly_snapshots_for_fy(fy_start, equity_pct=10.0),
        monthly_coverage_evidence=_monthly_coverage_evidence(fy_start, _monthly_snapshots_for_fy(fy_start, equity_pct=10.0)),
        fy_start=fy_start,
        fy_end=fy_end,
        snapshot_coverage_evidence=_daily_coverage_evidence(snapshots),
    )
    assert result["specified_76"]["effective_debt_pct"] == pytest.approx(debt_pct + money_market_pct)
    assert result["specified_76"]["qualifies"] is expected
    assert result["specified_76"]["source_data_status"] == "PROVISIONAL_DAILY_COVERAGE_RECONCILED"
    assert result["tax_treatment"] == (
        "SECTION_76_DEEMED_STCG" if expected else "HYBRID_UNLISTED_OR_NORMAL"
    )


@pytest.mark.parametrize(
    ("fof_pct", "expected"),
    [(64.99, False), (65.0, True)],
)
@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_section_76_fund_of_funds_threshold_is_inclusive(fof_pct, expected):
    from core.math_engine import classify_specified_mutual_fund

    fy_start, fy_end = date(2026, 4, 1), date(2027, 3, 31)
    snapshots = _daily_snapshots_for_fy(
        fy_start, fy_end, debt_pct=0.0, money_market_pct=0.0, equity_pct=10.0, fof_pct=fof_pct
    )
    result = classify_specified_mutual_fund(
        "Fund of Funds",
        equity_pct=10.0,
        debt_and_money_market_pct=0.0,
        is_fund_of_funds=True,
        fof_debt_investing_pct=fof_pct,
        fof_underlying_traded_on_recognised_exchange=False,
        acquisition_date=date(2023, 4, 1),
        transfer_date=date(2026, 11, 3),
        snapshots=snapshots,
        monthly_snapshots=_monthly_snapshots_for_fy(fy_start, equity_pct=10.0, fof_units_pct=0.0, underlying_equity_pct=0.0),
        monthly_coverage_evidence=_monthly_coverage_evidence(fy_start, _monthly_snapshots_for_fy(fy_start, equity_pct=10.0, fof_units_pct=0.0, underlying_equity_pct=0.0)),
        fy_start=fy_start,
        fy_end=fy_end,
        snapshot_coverage_evidence=_daily_coverage_evidence(snapshots),
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


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
    # The public compatibility module must remain import-safe; policy
    # reconciliation belongs to the isolated legacy implementation.
    source = ast.parse((root / "legacy" / "advisor_lean_cli.py").read_text())
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
        equity_sip_routing_override=True,
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
    requires_ips = p["new_sip_allocation"].get("requires_explicit_ips_authorization", False)
    expected_equity = p["new_sip_allocation"]["equity_pct"]
    expected_debt = p["new_sip_allocation"]["debt_pct"]
    if requires_ips:
        # Without explicit IPS authorization, Tier 6 remains at its strategic allocation.
        expected_without_override = (
            100.0 - targets["debt_liquid_pct"],
            targets["debt_liquid_pct"],
        )
        assert calculate_universal_tier_split(tier) == expected_without_override
        assert calculate_universal_tier_split(
            tier, equity_sip_routing_override=True
        ) == (expected_equity, expected_debt)
    else:
        assert calculate_universal_tier_split(tier) == (expected_equity, expected_debt)
        threshold = max(0.0, targets["debt_liquid_pct"] - p["tolerance_band_pct"])
        if threshold > 0:
            assert calculate_universal_tier_split(tier, threshold - 0.01) == (expected_equity, expected_debt)
            assert calculate_universal_tier_split(tier, threshold) == (100.0, 0.0)


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
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
        reviewer_attested=True,
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
            monthly_snapshots=_monthly_snapshots_for_fy(fy_start, equity_pct=10.0),
            monthly_coverage_evidence=_monthly_coverage_evidence(fy_start, _monthly_snapshots_for_fy(fy_start, equity_pct=10.0)),
            fy_start=fy_start,
            fy_end=fy_end,
            snapshot_coverage_evidence=evidence,
        )


@pytest.mark.parametrize(
    ("fof_units_pct", "underlying_equity_pct", "expected"),
    [(90.0, 90.0, True), (89.99, 99.0, False), (99.0, 89.99, False)],
)
@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_section_198_fund_of_funds_requires_both_monthly_90_percent_limb_conditions(
    fof_units_pct, underlying_equity_pct, expected
):
    from core.math_engine import qualifies_as_equity_oriented_under_section_198

    fy_start, fy_end = date(2026, 4, 1), date(2027, 3, 31)
    monthly = _monthly_snapshots_for_fy(
        fy_start,
        equity_pct=0.0,
        fof_units_pct=fof_units_pct,
        underlying_equity_pct=underlying_equity_pct,
    )
    result = qualifies_as_equity_oriented_under_section_198(
        equity_pct=0.0,
        monthly_snapshots=monthly,
        monthly_coverage_evidence=_monthly_coverage_evidence(fy_start, monthly),
        fy_start=fy_start,
        fy_end=fy_end,
        is_fund_of_funds=True,
        fof_underlying_traded_on_recognised_exchange=True,
    )
    assert result.qualifies is expected
    assert result.source_data_status == "PROVISIONAL_MONTHLY_COVERAGE_RECONCILED"


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_section_198_uses_average_of_monthly_opening_and_closing_figures():
    from core.math_engine import MonthlyPortfolioSnapshot, compute_annual_average_monthly_opening_closing
    from core.models import InsufficientDataError

    fy_start, fy_end = date(2025, 4, 1), date(2026, 3, 31)
    rows = []
    for month in range(4, 13):
        rows.append(MonthlyPortfolioSnapshot(date(2025, month, 1), 64.0, 66.0))
    for month in range(1, 4):
        rows.append(MonthlyPortfolioSnapshot(date(2026, month, 1), 64.0, 66.0))
    assert compute_annual_average_monthly_opening_closing(rows, fy_start, fy_end) == pytest.approx(65.0)
    with pytest.raises(InsufficientDataError, match="all 12 financial-year months"):
        compute_annual_average_monthly_opening_closing(rows[:-1], fy_start, fy_end)


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_tax_planner_rejects_point_in_time_or_stale_equity_allocation_evidence():
    lot = Lot(
        fund_id="fund-x",
        folio_name="folio-1",
        purchase_date=date(2024, 1, 1),
        units=10,
        nav=50,
        cost=500,
        source="cas",
        equity_pct=70.0,
    )
    rules = {"classification_test": {"equity_oriented_threshold_pct": 65.0}}
    with pytest.raises(ValueError, match="annual-average monthly opening/closing"):
        classify_fund_for_tax(lot, rules, sale_date=date(2026, 11, 3))

    lot.equity_pct_method = "annual_average_monthly_opening_closing"
    lot.equity_pct_fy_start = 2025
    lot.equity_pct_source_url = "https://example.test/disclosure"
    lot.equity_pct_source_sha256 = _TEST_TAX_EVIDENCE_SHA256
    lot.equity_pct_source_file = "synthetic_tax_evidence.txt"
    lot.equity_pct_evidence_root = str(_TEST_TAX_EVIDENCE_ROOT)
    lot.equity_pct_source_reviewed = True
    with pytest.raises(ValueError, match="requires FY starting 2026"):
        classify_fund_for_tax(lot, rules, sale_date=date(2026, 11, 3))


def test_tier6_one_hundred_percent_equity_sip_requires_explicit_ips_override():
    from core.math_engine import calculate_universal_tier_split

    # Zero stability buffer used to pass the old zero-threshold comparison and
    # silently route all new cash to equity. It must not bypass investor consent.
    assert calculate_universal_tier_split(6, stability_buffer_pct=0.0) == (95.0, 5.0)
    assert calculate_universal_tier_split(6, stability_buffer_pct=7.54) == (95.0, 5.0)
    assert calculate_universal_tier_split(
        6,
        stability_buffer_pct=0.0,
        equity_sip_routing_override=True,
    ) == (100.0, 0.0)


def test_starter_routing_thresholds_and_weights_are_policy_driven():
    import json
    from pathlib import Path
    from core.math_engine import compute_deterministic_sip_blueprint

    policy = json.loads(
        (Path(__file__).resolve().parents[1] / "data/policy/asset_allocation.json").read_text()
    )["starter_portfolio_routing"]
    weights = policy["equity_sleeves_pct_of_equity_budget"]
    assert policy["classification"] == "RESEARCH_HEURISTIC"
    assert sum(weights.values()) == 100
    assert policy["thematic_satellite_default_pct_of_equity"] == 0

    starter = compute_deterministic_sip_blueprint(
        monthly_budget=20000.0,
        risk_tier="Tier 6 (Very High)",
        client_aum=policy["aum_threshold_inr"] - 1,
        equity_sip_routing_override=True,
    )
    roles = {item.category_role: item for item in starter.items}
    assert roles["Core Flexi-Cap Compounder"].allocation_pct == weights["flexi_cap"]
    assert roles["Mid-Cap Alpha Engine"].allocation_pct == pytest.approx(weights["mid_small_cap"] / 2)
    assert roles["Small-Cap Growth Engine"].allocation_pct == pytest.approx(weights["mid_small_cap"] / 2)
    assert "Large-Cap Bluechip Anchor" not in roles

    at_threshold = compute_deterministic_sip_blueprint(
        monthly_budget=policy["monthly_budget_threshold_inr"],
        risk_tier="Tier 6 (Very High)",
        client_aum=policy["aum_threshold_inr"],
        equity_sip_routing_override=True,
    )
    threshold_roles = {item.category_role: item for item in at_threshold.items}
    assert "Large-Cap Bluechip Anchor" in threshold_roles


def test_candidate_ingestion_never_hardcodes_direct_plan_status(tmp_path):
    import hashlib
    import json
    from datetime import date
    from core.eligibility import load_candidate_universe, check_eligibility_gates

    source_file = tmp_path / "direct-plan-source.txt"
    source_bytes = b"Synthetic test-only scheme master record: Synthetic Flexi Cap Growth; Plan=Direct"
    source_file.write_bytes(source_bytes)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    direct_evidence = {
        "source_file": source_file.name,
        "source_document_sha256": source_hash,
        "source_url": "https://example.test/synthetic-scheme-master",
        "source_type": "AMFI_SCHEME_MASTER",
        "reviewer_attested": True,
        "reviewed_at": date.today().isoformat(),
        "scheme_name": "Synthetic Flexi Cap Growth",
        "scheme_id": "SYNTH-SCHEME-001",
        "isin": "SYNTH-ISIN-001",
        "amc_name": "SYNTHETIC AMC",
        "plan": "Direct",
    }

    metrics_path = tmp_path / "fund_metrics.json"
    metrics_path.write_text(json.dumps({"funds": [
        {
            "id": "synthetic-direct-label-only",
            "name": "Synthetic Flexi Cap Direct Growth",
            "category": "Flexi Cap Equity",
        },
        {
            "id": "synthetic-source-classified-direct",
            "name": "Synthetic Flexi Cap Growth",
            "category": "Flexi Cap Equity",
            "scheme_id": "SYNTH-SCHEME-001",
            "isin": "SYNTH-ISIN-001",
            "amc_name": "SYNTHETIC AMC",
            "is_direct": True,
            "direct_plan_evidence": direct_evidence,
        },
        {
            "id": "synthetic-source-classified-regular",
            "name": "Synthetic Flexi Cap Growth",
            "category": "Flexi Cap Equity",
            "is_direct": False,
            "plan": "Regular",
        },
    ]}), encoding="utf-8")

    candidates = {c["fund_id"]: c for c in load_candidate_universe(metrics_path)}
    assert candidates["synthetic-direct-label-only"]["is_direct"] is None
    assert candidates["synthetic-source-classified-direct"]["is_direct"] is True
    assert candidates["synthetic-source-classified-direct"]["direct_plan_evidence_status"] == "REVIEWER_ATTESTED_HASH_MATCH"
    assert candidates["synthetic-source-classified-regular"]["is_direct"] is False

    missing_source_gate = check_eligibility_gates(candidates["synthetic-direct-label-only"], [])
    assert missing_source_gate.direct_plan_gate is False
    assert any("reviewer-attested source document" in item for item in missing_source_gate.failed_gates)

    direct_source_gate = check_eligibility_gates(candidates["synthetic-source-classified-direct"], [])
    assert direct_source_gate.direct_plan_gate is True

    # A stale digest or modified local source document must downgrade the plan
    # classification to unavailable, never leave an old True value in place.
    direct_evidence["source_document_sha256"] = "0" * 64
    metrics_path.write_text(json.dumps({"funds": [{
        "id": "synthetic-source-hash-mismatch",
        "name": "Synthetic Flexi Cap Growth",
        "category": "Flexi Cap Equity",
        "scheme_id": "SYNTH-SCHEME-001",
        "isin": "SYNTH-ISIN-001",
        "amc_name": "SYNTHETIC AMC",
        "is_direct": True,
        "direct_plan_evidence": direct_evidence,
    }]}), encoding="utf-8")
    mismatched = load_candidate_universe(metrics_path)[0]
    assert mismatched["is_direct"] is None
    assert mismatched["direct_plan_evidence_status"] == "INVALID"



def test_selector_slot_targets_are_policy_weighted_and_not_hardcoded(monkeypatch):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    import core.eligibility as eligibility
    import core.fund_classifier as classifier
    import core.math_engine as math_engine

    policy = json.loads(
        (Path(__file__).resolve().parents[1] / "data/policy/asset_allocation.json").read_text()
    )
    profile = policy["behavioral_risk_profiles"]["very_high"]
    saa = profile["saa_targets"]
    equity_parts = {
        "flexi": float(saa["flexi_multi_cap_pct"]),
        "mid": float(saa["mid_cap_pct"]),
        "small": float(saa["small_cap_pct"]),
        "large": float(saa["large_cap_pct"]),
    }
    equity_total = sum(equity_parts.values())
    expected = {
        "Slot 1: Core Flexi-Cap Compounder": round(100.0 * equity_parts["flexi"] / equity_total, 1),
        "Slot 2: Mid-Cap Alpha Engine": round(100.0 * equity_parts["mid"] / equity_total, 1),
        "Slot 3: Small-Cap Growth Engine": round(100.0 * equity_parts["small"] / equity_total, 1),
    }
    expected["Slot 4: Large-Cap Bluechip Anchor"] = round(
        100.0 - expected["Slot 1: Core Flexi-Cap Compounder"] - expected["Slot 2: Mid-Cap Alpha Engine"] - expected["Slot 3: Small-Cap Growth Engine"],
        1,
    )

    monkeypatch.setattr(
        eligibility, "_reviewed_direct_plan_evidence_status",
        lambda candidate: "REVIEWER_ATTESTED_HASH_MATCH",
    )
    monkeypatch.setattr(
        eligibility, "check_eligibility_gates",
        lambda *args, **kwargs: SimpleNamespace(passed=True),
    )
    monkeypatch.setattr(classifier, "classify_fund_category", lambda name, category, candidate=None: category)
    monkeypatch.setattr(classifier, "detect_fund_theme", lambda name, category: None)
    scored_categories = []
    monkeypatch.setattr(
        math_engine,
        "compute_multi_horizon_fiduciary_score",
        lambda candidate, category_key="Healthcare", portfolio_overlap_pct=0.0:
            scored_categories.append(category_key) or candidate["score"],
    )

    candidates = [
        {"fund_id": "flexi", "fund_name": "Synthetic Flexi", "category": "Flexi Cap Equity", "is_direct": True, "score": 3.0},
        {"fund_id": "mid", "fund_name": "Synthetic Mid", "category": "Mid Cap Equity", "is_direct": True, "score": 2.0},
        {"fund_id": "small", "fund_name": "Synthetic Small", "category": "Small Cap Equity", "is_direct": True, "score": 1.5},
        {"fund_id": "large", "fund_name": "Synthetic Large", "category": "Large Cap Equity", "is_direct": True, "score": 1.0},
        {"fund_id": "debt", "fund_name": "Synthetic Debt", "category": "Debt", "is_direct": True, "score": 1.0},
    ]
    candidates.extend(
        {
            "fund_id": f"universe-filler-{index}",
            "fund_name": f"Synthetic Filler {index}",
            "category": "Debt",
            "is_direct": True,
            "score": 0.0,
        }
        for index in range(26)
    )
    result = math_engine.select_autonomous_blueprint_funds(
        holdings=[],
        candidate_universe=candidates,
        client_risk_tier=6,
    )
    for slot_name, target in expected.items():
        assert result[slot_name]["allocation_pct"] == target
        assert result[slot_name]["gate_passed"] is True
        assert result[slot_name]["allocation_basis"] == "percent_of_equity_budget"
    assert result["High-Grade Debt Anchor"]["allocation_pct"] == 0.0
    assert result["High-Grade Debt Anchor"]["unallocated_pct"] == pytest.approx(float(saa["debt_liquid_pct"]))
    assert "no supported debt-specific ranking model" in result["High-Grade Debt Anchor"]["rationale"]
    assert result["High-Grade Debt Anchor"]["allocation_basis"] == "percent_of_total_portfolio"
    assert scored_categories == ["Flexi Cap", "Mid Cap", "Small Cap", "Large Cap"]
    assert result["High-Grade Debt Anchor"]["gate_passed"] is False
    assert str(result["High-Grade Debt Anchor"]["scheme"]).startswith("NO_ACTION")


def test_selector_does_not_select_candidate_using_direct_name_suffix_only():
    from core.math_engine import select_autonomous_blueprint_funds

    candidate = {
        "fund_id": "synthetic-flexi-unverified-plan",
        "fund_name": "Synthetic Flexi Cap Direct Growth",
        "category": "Flexi Cap Equity",
        # No is_direct value from a source record.
    }
    result = select_autonomous_blueprint_funds(
        holdings=[],
        candidate_universe=[candidate],
        client_risk_tier=6,
    )
    slot = result["Slot 1: Core Flexi-Cap Compounder"]
    assert slot["gate_passed"] is False
    assert slot["is_direct"] is None
    assert str(slot["scheme"]).startswith("NO_ACTION")
    assert slot["allocation_pct"] == 0.0
    assert slot["unallocated_pct"] > 0.0


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_section_198_direct_fund_threshold_is_at_least_65_percent():
    from core.math_engine import qualifies_as_equity_oriented_under_section_198

    fy_start, fy_end = date(2026, 4, 1), date(2027, 3, 31)
    monthly_below_threshold = _monthly_snapshots_for_fy(fy_start, equity_pct=64.99)
    result_below_threshold = qualifies_as_equity_oriented_under_section_198(
        equity_pct=64.99,
        monthly_snapshots=monthly_below_threshold,
        monthly_coverage_evidence=_monthly_coverage_evidence(fy_start, monthly_below_threshold),
        fy_start=fy_start,
        fy_end=fy_end,
    )
    assert result_below_threshold.qualifies is False

    monthly_at_threshold = _monthly_snapshots_for_fy(fy_start, equity_pct=65.0)
    result_at_threshold = qualifies_as_equity_oriented_under_section_198(
        equity_pct=65.0,
        monthly_snapshots=monthly_at_threshold,
        monthly_coverage_evidence=_monthly_coverage_evidence(fy_start, monthly_at_threshold),
        fy_start=fy_start,
        fy_end=fy_end,
    )
    assert result_at_threshold.qualifies is True

    monthly_above_threshold = _monthly_snapshots_for_fy(fy_start, equity_pct=65.01)
    result_above_threshold = qualifies_as_equity_oriented_under_section_198(
        equity_pct=65.01,
        monthly_snapshots=monthly_above_threshold,
        monthly_coverage_evidence=_monthly_coverage_evidence(fy_start, monthly_above_threshold),
        fy_start=fy_start,
        fy_end=fy_end,
    )
    assert result_above_threshold.qualifies is True


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_legacy_tax_classifier_never_defaults_unknown_or_non_equity_to_equity():
    from types import SimpleNamespace
    from core.math_engine import _classify_fund_for_tax

    rules = {"classification_test": {"equity_oriented_threshold_pct": 65.0}}
    with pytest.raises(ValueError, match="Verified annual-average equity allocation"):
        _classify_fund_for_tax(SimpleNamespace(equity_pct=None), rules)
    assert _classify_fund_for_tax(SimpleNamespace(equity_pct=65.0), rules) == "equity_oriented"
    with pytest.raises(NotImplementedError, match="Non-equity tax classification is not implemented"):
        _classify_fund_for_tax(SimpleNamespace(equity_pct=64.99), rules)


def test_tri_release_flag_fails_closed_while_fixture_is_provisional():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(root / "verify_tri_provenance.py"), "--require-alpha-release"],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "TRI alpha release eligibility: BLOCKED" in completed.stdout


@pytest.mark.skip(reason="Investor-facing tax/exit-load calculation is intentionally disabled pending independent approval; covered by fail-closed API tests.")
def test_tax_planner_equity_classification_uses_at_least_65_percent():
    lot = Lot(
        fund_id="synthetic-fund", folio_name="synthetic-folio",
        purchase_date=date(2024, 1, 1), units=1, nav=100, cost=100,
        source="synthetic", equity_pct=65.0,
        equity_pct_method="annual_average_monthly_opening_closing",
        equity_pct_fy_start=2026,
        equity_pct_source_url="https://example.test/synthetic-disclosure",
        **_synthetic_tax_evidence_kwargs(),
        equity_pct_source_reviewed=True,
    )
    rules = {"classification_test": {"equity_oriented_threshold_pct": 65.0}}
    assert classify_fund_for_tax(lot, rules, sale_date=date(2026, 11, 3)) == "equity_oriented"
    lot.equity_pct = 64.99
    assert classify_fund_for_tax(lot, rules, sale_date=date(2026, 11, 3)) == "non_equity_oriented"


def test_legacy_advisor_cli_import_is_safe_without_client_data(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    repository_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repository_root)
    env["MF_CLIENT_DATA_DIR"] = str(tmp_path / "deliberately-missing-client-data")
    completed = subprocess.run(
        [sys.executable, "-c", "import advisor_lean; print('import-safe')"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "import-safe" in completed.stdout
    assert not (tmp_path / "outputs").exists()


def test_tri_fixture_verifier_rejects_incorrect_declared_observation_count(tmp_path):
    import json
    from pathlib import Path
    from verify_tri_provenance import verify_fixture

    root = Path(__file__).resolve().parents[1]
    fixture = json.loads((root / "data/policy/benchmark_tri_series.json").read_text(encoding="utf-8"))
    fixture["coverage"]["nifty_500_tri"]["provided_data_points"] += 1
    corrupted = tmp_path / "incorrect-count.json"
    corrupted.write_text(json.dumps(fixture), encoding="utf-8")

    failures = verify_fixture(corrupted)
    assert any("does not match observed count" in failure for failure in failures)



def test_candidate_universe_rejects_repository_local_client_data(monkeypatch):
    from pathlib import Path
    from core.math_engine import select_autonomous_blueprint_funds

    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("MF_CLIENT_DATA_DIR", str(repository_root / "data"))
    with pytest.raises(ValueError, match="MF_CLIENT_DATA_DIR must be outside the Git repository"):
        select_autonomous_blueprint_funds(
            holdings=[],
            candidate_universe=None,
            client_risk_tier=6,
        )



def test_all_statutory_tax_classification_apis_fail_closed_pending_independent_review():
    import pytest
    from core import math_engine

    disabled_apis = [
        math_engine.get_statutory_tax_citation,
        math_engine.classify_specified_mutual_fund,
        math_engine.qualifies_as_equity_oriented_under_section_198,
        math_engine.qualifies_as_specified_mutual_fund_under_section_50AA,
        math_engine.qualifies_as_specified_mutual_fund_under_section_76,
        math_engine.compute_fifo_tax_lots,
        math_engine.build_fifo_tax_lots,
        math_engine._classify_fund_for_tax,
    ]
    for api in disabled_apis:
        with pytest.raises(math_engine.TaxClassificationDisabledError):
            api()



def test_candidate_scoring_rejects_unknown_category_instead_of_using_healthcare_anchors():
    from core.candidate_scoring import calculate_candidate_6_pillar_score

    candidate = {
        "alpha_3y": 2.0,
        "return_1y": 12.0,
        "sharpe_3y": 0.8,
        "ter_direct_pct": 0.7,
    }
    with pytest.raises(ValueError, match="Unsupported scoring category"):
        calculate_candidate_6_pillar_score(candidate, category_key="Debt")



def test_candidate_scoring_rejects_missing_core_evidence_instead_of_filling_defaults():
    from core.candidate_scoring import calculate_candidate_6_pillar_score

    candidate = {
        "alpha_3y": 2.0,
        "return_1y": 12.0,
        "sharpe_3y": 0.8,
        # Direct TER deliberately omitted.
    }
    with pytest.raises(ValueError, match="Missing required scoring metric: ter_direct_pct"):
        calculate_candidate_6_pillar_score(candidate, category_key="Flexi Cap")


def test_candidate_scoring_marks_absent_optional_pillars_neutral_not_as_observed_zero():
    from core.candidate_scoring import calculate_candidate_6_pillar_score

    candidate = {
        "alpha_3y": 2.0,
        "return_1y": 12.0,
        "sharpe_3y": 0.8,
        "ter_direct_pct": 0.7,
    }
    _, pillars = calculate_candidate_6_pillar_score(candidate, category_key="Flexi Cap")
    assert pillars["downside_buffer"] == 50.0
    assert pillars["geographic_moat"] == 50.0
    assert pillars["portfolio_overlap"] == 50.0



def test_sip_selector_holds_all_slots_when_candidate_universe_is_below_policy_minimum():
    from core.math_engine import select_autonomous_blueprint_funds

    candidates = [
        {"fund_id": f"candidate-{index}", "fund_name": f"Candidate {index}", "category": "Flexi Cap Equity"}
        for index in range(29)
    ]
    result = select_autonomous_blueprint_funds(
        holdings=[],
        candidate_universe=candidates,
        client_risk_tier=6,
    )
    for slot_name in (
        "Slot 1: Core Flexi-Cap Compounder",
        "Slot 2: Mid-Cap Alpha Engine",
        "Slot 3: Small-Cap Growth Engine",
        "Slot 4: Large-Cap Bluechip Anchor",
    ):
        slot = result[slot_name]
        assert slot["gate_passed"] is False
        assert slot["allocation_pct"] == 0.0
        assert slot["unallocated_pct"] > 0.0
        assert "candidate universe insufficient (29 < 30)" in slot["rationale"]



def _lookthrough_holding(fund_id, value, equity_pct, weights=None, coverage=100.0):
    return SimpleNamespace(
        fund_id=fund_id,
        current_value_inr=value,
        equity_pct=equity_pct,
        constituent_weights=weights,
        constituent_weights_coverage_pct=coverage if weights is not None else None,
    )


def test_candidate_portfolio_overlap_uses_actual_constituent_weights():
    holding = _lookthrough_holding("existing-1", 1000.0, 100.0, {"issuer-a": 60.0, "issuer-b": 40.0})
    candidate = {
        "constituent_weights": {"issuer-a": 30.0, "issuer-c": 70.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    assert compute_candidate_portfolio_overlap(candidate, [holding]) == 30.0


def test_candidate_portfolio_overlap_value_weights_multiple_existing_funds():
    holdings = [
        _lookthrough_holding("existing-1", 750.0, 100.0, {"issuer-a": 100.0}),
        _lookthrough_holding("existing-2", 250.0, 100.0, {"issuer-b": 100.0}),
    ]
    candidate = {
        "constituent_weights": {"issuer-a": 50.0, "issuer-b": 50.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    # Portfolio stock weights are 75% issuer-a and 25% issuer-b;
    # overlap is min(50,75) + min(50,25) = 75 percentage points.
    assert compute_candidate_portfolio_overlap(candidate, holdings) == 75.0


def test_candidate_portfolio_overlap_returns_unknown_for_missing_or_partial_evidence():
    candidate = {
        "constituent_weights": {"issuer-a": 100.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    assert compute_candidate_portfolio_overlap(candidate, None) is None
    assert compute_candidate_portfolio_overlap(candidate, [_lookthrough_holding("existing-1", 1000, 100, None)]) is None
    partial = _lookthrough_holding("existing-1", 1000, 100, {"issuer-a": 100.0}, coverage=80.0)
    assert compute_candidate_portfolio_overlap(candidate, [partial]) is None
    assert compute_candidate_portfolio_overlap({"constituent_weights": {"issuer-a": 100.0}}, [_lookthrough_holding("existing-1", 1000, 100, {"issuer-a": 100.0})]) is None


def test_candidate_portfolio_overlap_zero_is_only_confirmed_empty_or_disjoint():
    candidate = {
        "constituent_weights": {"issuer-a": 100.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    holding = _lookthrough_holding("existing-1", 1000.0, 100.0, {"issuer-b": 100.0})
    assert compute_candidate_portfolio_overlap(candidate, []) == 0.0
    assert compute_candidate_portfolio_overlap(candidate, [holding]) == 0.0


def test_portfolio_overlap_sensitivity_changes_with_actual_holdings_not_fund_labels():
    mid_cap_candidate = {
        "category": "Mid Cap",
        "constituent_weights": {"mid-issuer-a": 60.0, "mid-issuer-b": 40.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    large_cap_candidate = {
        "category": "Large Cap",
        "constituent_weights": {"large-issuer-a": 60.0, "large-issuer-b": 40.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    mid_heavy_portfolio = [
        _lookthrough_holding(
            "existing-mid-fund", 1000.0, 100.0,
            {"mid-issuer-a": 60.0, "mid-issuer-b": 40.0},
        )
    ]
    large_heavy_portfolio = [
        _lookthrough_holding(
            "existing-large-fund", 1000.0, 100.0,
            {"large-issuer-a": 60.0, "large-issuer-b": 40.0},
        )
    ]

    mid_candidate_overlap_mid_heavy = compute_candidate_portfolio_overlap(
        mid_cap_candidate, mid_heavy_portfolio
    )
    mid_candidate_overlap_large_heavy = compute_candidate_portfolio_overlap(
        mid_cap_candidate, large_heavy_portfolio
    )
    large_candidate_overlap_mid_heavy = compute_candidate_portfolio_overlap(
        large_cap_candidate, mid_heavy_portfolio
    )
    large_candidate_overlap_large_heavy = compute_candidate_portfolio_overlap(
        large_cap_candidate, large_heavy_portfolio
    )

    assert mid_candidate_overlap_mid_heavy == 100.0
    assert mid_candidate_overlap_large_heavy == 0.0
    assert large_candidate_overlap_mid_heavy == 0.0
    assert large_candidate_overlap_large_heavy == 100.0



def test_custom_investor_risk_profile_never_defaults_to_sebi_tier_six():
    with pytest.raises(ValueError, match="explicitly approved custom SAA"):
        select_autonomous_blueprint_funds(
            holdings=[],
            candidate_universe=[],
            client_risk_tier=RiskTier.CUSTOM,
        )


@pytest.mark.parametrize(
    ("risk_profile", "expected_tier"),
    [
        (RiskTier.CONSERVATIVE, 2),
        (RiskTier.MODERATE, 4),
        (RiskTier.AGGRESSIVE, 6),
    ],
)
def test_standard_investor_risk_profiles_have_explicit_policy_mapping(risk_profile, expected_tier):
    selected = select_autonomous_blueprint_funds(
        holdings=[],
        candidate_universe=[],
        client_risk_tier=risk_profile,
    )
    assert "Slot 1: Core Flexi-Cap Compounder" in selected


@pytest.mark.parametrize(
    "allocation",
    [
        {"equity_pct": 70.0, "debt_pct": 20.0, "cash_pct": 0.0},
        {"equity_pct": -1.0, "debt_pct": 101.0, "cash_pct": 0.0},
        {"equity_pct": float("inf"), "debt_pct": 0.0, "cash_pct": 0.0},
    ],
)
def test_custom_saa_rejects_non_reconciling_or_invalid_percentages(allocation):
    with pytest.raises(ValueError):
        AssetAllocationTarget(**allocation)


def test_custom_saa_accepts_reconciled_allocation():
    target = AssetAllocationTarget(equity_pct=75.0, debt_pct=20.0, cash_pct=5.0)
    assert target.equity_pct + target.debt_pct + target.cash_pct == 100.0


def test_sip_plan_requires_allocated_plus_unallocated_to_equal_budget():
    with pytest.raises(ValueError, match="must equal the monthly budget"):
        DeterministicSIPPlan(
            total_monthly_budget_inr=10000.0,
            unallocated_budget_inr=0.0,
            equity_sip_pct=100.0,
            debt_sip_pct=0.0,
            items=[],
        )


def test_sip_plan_accepts_fully_unallocated_budget_when_on_hold():
    plan = DeterministicSIPPlan(
        total_monthly_budget_inr=10000.0,
        unallocated_budget_inr=10000.0,
        equity_sip_pct=100.0,
        debt_sip_pct=0.0,
        items=[
            DeterministicSIPRecommendation(
                category_role="Core",
                scheme_name="NO_ACTION: candidate not verified",
                monthly_inr=0.0,
                allocation_pct=100.0,
                rational_code="CORE_COMPOUNDER",
                fiduciary_rationale="Held pending evidence",
            )
        ],
    )
    assert plan.unallocated_budget_inr == plan.total_monthly_budget_inr


def test_sip_plan_rejects_non_finite_budget():
    with pytest.raises(ValueError, match="must be finite"):
        DeterministicSIPPlan(
            total_monthly_budget_inr=float("nan"),
            unallocated_budget_inr=0.0,
            equity_sip_pct=100.0,
            debt_sip_pct=0.0,
            items=[],
        )


def _sip_policy_fixture():
    return {
        "max_fund_allocation_pct": 20.0,
        "min_sip_per_fund_inr": 1000.0,
        "sip_increment_inr": 500.0,
        "max_core_fund_count": 6,
    }


def _sip_item(role="Core Flexi-Cap", amount=1000.0, pct=10.0):
    return SimpleNamespace(category_role=role, monthly_inr=amount, allocation_pct=pct)


def test_sip_operational_constraints_accept_valid_line():
    assert _sip_operational_constraint_violations(
        [_sip_item(amount=1500.0, pct=15.0)], _sip_policy_fixture()
    ) == []


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (_sip_item(amount=2500.0, pct=25.0), "per-fund cap"),
        (_sip_item(amount=500.0, pct=5.0), "minimum ticket"),
        (_sip_item(amount=1250.0, pct=12.5), "SIP increment"),
    ],
)
def test_sip_operational_constraints_reject_invalid_lines(item, expected):
    violations = _sip_operational_constraint_violations([item], _sip_policy_fixture())
    assert any(expected in violation for violation in violations)


def test_sip_operational_constraints_enforce_core_fund_count():
    items = [_sip_item(role=f"Core {i}") for i in range(7)]
    violations = _sip_operational_constraint_violations(items, _sip_policy_fixture())
    assert any("maximum of 6" in violation for violation in violations)


def test_sip_operational_constraints_reject_invalid_policy():
    policy = _sip_policy_fixture()
    policy["sip_increment_inr"] = 0.0
    with pytest.raises(ValueError, match="finite and positive"):
        _sip_operational_constraint_violations([_sip_item()], policy)


def test_cas_parser_marks_stock_lookthrough_as_missing_not_zero(tmp_path):
    from openpyxl import Workbook
    from core.math_engine import parse_cas

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", "2026-10-31"])
    sheet.append(["Scheme Name", "Folio No.", "Current Value", "Invested Value"])
    sheet.append(["Example Equity Fund - Direct Growth", "12345", 150000.0, 120000.0])
    path = tmp_path / "cas.xlsx"
    workbook.save(path)

    as_of_date, holdings = parse_cas(path)

    assert as_of_date == "2026-10-31"
    assert len(holdings) == 1
    assert holdings[0]["constituent_weights"] is None
    assert holdings[0]["constituent_weights_coverage_pct"] is None
    assert holdings[0]["lookthrough_status"] == "MISSING"
    assert "do not contain stock-level" in holdings[0]["lookthrough_reason"]


def test_portfolio_disclosure_requires_hash_freshness_and_exact_scheme_id():
    import hashlib
    from datetime import date
    from ingestion.portfolio_disclosure import (
        validate_portfolio_disclosure,
        attach_verified_disclosures,
    )

    source = b"official monthly portfolio disclosure fixture"
    base = {
        "scheme_id": "SCHEME-001",
        "source_url": "https://amc.example/factsheet.pdf",
        "source_document_sha256": hashlib.sha256(source).hexdigest(),
        "reviewer_attested": True,
        "effective_date": "2026-10-15",
        "constituent_weights": {"INE000A01001": 60.0, "INE000A01002": 40.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    valid = validate_portfolio_disclosure(
        base, source, as_of=date(2026, 10, 31), max_age_days=45
    )
    assert valid["status"] == "VERIFIED"
    assert valid["constituent_weights"]["INE000A01001"] == 60.0

    bad_hash = dict(base, source_document_sha256="0" * 64)
    assert validate_portfolio_disclosure(
        bad_hash, source, as_of=date(2026, 10, 31), max_age_days=45
    )["status"] == "CONFLICTING"

    stale = dict(base, effective_date="2026-01-01")
    assert validate_portfolio_disclosure(
        stale, source, as_of=date(2026, 10, 31), max_age_days=45
    )["status"] == "STALE"

    attached = attach_verified_disclosures(
        [{"scheme": "Name only; no stable identifier", "current_value": 1000.0}],
        {"SCHEME-001": base},
        source_bytes_by_scheme_id={"SCHEME-001": source},
        as_of=date(2026, 10, 31),
        max_age_days=45,
    )
    assert attached[0]["lookthrough_status"] == "MISSING"
    assert attached[0]["constituent_weights"] is None


def test_primary_cas_ingestion_marks_constituent_lookthrough_missing(tmp_path):
    from openpyxl import Workbook
    from ingestion.cas_parser import parse_cas_xlsx

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", "31-Oct-2026"])
    sheet.append(["Scheme Name", "AMC Name", "Category", "Folio No.", "Invested Value", "Current Value"])
    sheet.append(["Example Equity Fund - Direct Growth", "Example AMC", "Equity", "FOLIO-1", 90000, 100000])
    path = tmp_path / "primary-cas.xlsx"
    workbook.save(path)

    parsed = parse_cas_xlsx(path)
    assert len(parsed["holdings"]) == 1
    holding = parsed["holdings"][0]
    assert holding["lookthrough_status"] == "MISSING"
    assert holding["constituent_weights"] is None
    assert holding["constituent_weights_coverage_pct"] is None


def test_candidate_universe_does_not_treat_metrics_as_constituent_evidence(tmp_path):
    import json
    from core.eligibility import load_candidate_universe

    metrics = tmp_path / "fund_metrics.json"
    metrics.write_text(json.dumps({"funds": [{
        "id": "FUND-001",
        "scheme_id": "SCHEME-001",
        "name": "Example Direct Growth",
        "category": "Mid Cap",
    }]}), encoding="utf-8")
    candidates = load_candidate_universe(metrics)

    assert len(candidates) == 1
    assert candidates[0]["scheme_id"] == "SCHEME-001"
    assert candidates[0]["lookthrough_status"] == "MISSING"
    assert candidates[0]["constituent_weights"] is None


def test_cas_scheme_identity_requires_verified_master_and_exact_scheme_amc(tmp_path):
    import hashlib
    from openpyxl import Workbook
    from ingestion.cas_parser import parse_cas_xlsx

    source_bytes = b"reviewed official scheme master"
    master = {
        "status": "VERIFIED",
        "reviewer_attested": True,
        "source_url": "https://amfiindia.com/scheme-master.xlsx",
        "source_document_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "schemes": [{
            "scheme_id": "SCHEME-ABC",
            "isin": "INF000A01000",
            "scheme_name": "Example Equity Fund - Direct Growth",
            "amc_name": "Example AMC",
        }],
    }
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", "31-Oct-2026"])
    sheet.append(["Scheme Name", "AMC Name", "Category", "Folio No.", "Invested Value", "Current Value"])
    sheet.append(["Example Equity Fund - Direct Growth", "Example AMC", "Equity", "FOLIO-1", 90000, 100000])
    path = tmp_path / "cas-identity.xlsx"
    workbook.save(path)

    parsed = parse_cas_xlsx(path, scheme_master=master, scheme_master_source_bytes=source_bytes)
    holding = parsed["holdings"][0]
    assert holding["scheme_identity_status"] == "VERIFIED"
    assert holding["scheme_id"] == "SCHEME-ABC"
    assert holding["isin"] == "INF000A01000"

    # A display-name near-match is not enough to resolve an identity.
    master["schemes"][0]["scheme_name"] = "Example Equity Fund"
    parsed = parse_cas_xlsx(path, scheme_master=master, scheme_master_source_bytes=source_bytes)
    assert parsed["holdings"][0]["scheme_identity_status"] == "MISSING"
    assert parsed["holdings"][0]["scheme_id"] is None



def test_tri_calculation_never_substitutes_nifty_500_for_missing_requested_benchmark(tmp_path):
    import json
    from core.math_engine import calculate_cashflow_matched_benchmark_xirr
    from core.models import TriProvenanceError

    tri_path = tmp_path / "tri.json"
    tx_path = tmp_path / "transactions.json"
    calendar_path = tmp_path / "calendar.json"
    tri_path.write_text(json.dumps({
        "provenance": {},
        "benchmarks": {
            "NIFTY 500 TRI": {"levels": {"2026-11-02": 100.0}}
        },
    }), encoding="utf-8")
    tx_path.write_text(json.dumps({"transactions": []}), encoding="utf-8")
    calendar_path.write_text("{}", encoding="utf-8")

    with pytest.raises(TriProvenanceError) as error:
        calculate_cashflow_matched_benchmark_xirr(
            transactions_path=tx_path,
            benchmark_key="NIFTY MIDCAP 150 TRI",
            benchmark_series_path=tri_path,
            trading_calendar_path=calendar_path,
        )

    assert error.value.validation_stage == "benchmark_missing"


def test_tri_calculation_rejects_unapproved_benchmark_without_checksum_contract(tmp_path):
    import hashlib
    import json
    from core.math_engine import calculate_cashflow_matched_benchmark_xirr
    from core.models import TriProvenanceError

    levels = {"2026-11-02": 100.0}
    checksum = hashlib.sha256(
        json.dumps(levels, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    tri_path = tmp_path / "tri.json"
    tx_path = tmp_path / "transactions.json"
    calendar_path = tmp_path / "calendar.json"
    tri_path.write_text(json.dumps({
        "provenance": {"checksum_sha256_unapproved_tri": checksum},
        "benchmarks": {"UNAPPROVED TRI": {"levels": levels}},
    }), encoding="utf-8")
    tx_path.write_text(json.dumps({"transactions": []}), encoding="utf-8")
    calendar_path.write_text("{}", encoding="utf-8")

    with pytest.raises(TriProvenanceError) as error:
        calculate_cashflow_matched_benchmark_xirr(
            transactions_path=tx_path,
            benchmark_key="UNAPPROVED TRI",
            benchmark_series_path=tri_path,
            trading_calendar_path=calendar_path,
        )

    assert error.value.validation_stage == "benchmark_not_approved"



@pytest.mark.parametrize(
    "statement_date, expected",
    [
        ("2026-09-09", date(2026, 9, 9)),
        ("09-Sep-2026", date(2026, 9, 9)),
        ("09/09/2026", date(2026, 9, 9)),
        ("09-09-2026", date(2026, 9, 9)),
    ],
)
def test_tri_audit_uses_explicit_cas_valuation_date(tmp_path, statement_date, expected):
    from openpyxl import Workbook
    from core.math_engine import _parse_cas_valuation_date

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", statement_date])
    path = tmp_path / "cas.xlsx"
    workbook.save(path)

    assert _parse_cas_valuation_date(path) == expected


def test_tri_audit_rejects_missing_or_ambiguous_cas_valuation_date(tmp_path):
    from openpyxl import Workbook
    from core.math_engine import _parse_cas_valuation_date

    workbook = Workbook()
    workbook.active.title = "Portfolio Details"
    path = tmp_path / "cas_missing_date.xlsx"
    workbook.save(path)

    with pytest.raises(ValueError, match="does not contain a valuation date"):
        _parse_cas_valuation_date(path)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", "not-a-date"])
    path = tmp_path / "cas_invalid_date.xlsx"
    workbook.save(path)

    with pytest.raises(ValueError, match="unsupported format"):
        _parse_cas_valuation_date(path)



def test_tri_release_gate_is_independent_of_process_working_directory(tmp_path, monkeypatch):
    from core.math_engine import _tri_alpha_release_blockers

    monkeypatch.chdir(tmp_path)
    blockers = _tri_alpha_release_blockers()

    assert blockers
    assert not any("high-coverage TRI fixture cannot be read" in item for item in blockers)
    assert any("independently sourced data/policy/nse_trading_calendar.json is absent" in item for item in blockers)
