"""
tests/test_engine_bootstrap_and_lumpsum.py - Tests for engine bootstrap pipeline and portfolio-aware lumpsum decision workflow.
Addresses Issues #120 & #121:
- Issue #120: Make lump-sum decisions portfolio-aware and fail closed on incomplete investor evidence.
- Issue #121: Make engine bootstrap its own configuration and fund evidence; implement an operable promotion workflow.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import io
import json
from pathlib import Path
import openpyxl
import pytest

from services.engine_bootstrap import (
    EngineBootstrapPipeline,
    InvestorMandateInput,
    ValidationReport,
)
from services.lumpsum_recommendation import (
    evaluate_portfolio_aware_lumpsum,
    LumpsumDecisionResult,
)


def _create_synthetic_cas(tmp_path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Folio No.", "Units", "Current Value", "Invested Value"])
    ws.append(["SBI Bluechip Fund - Direct Plan - Growth", "12345/67", 100.0, 100000.0, 80000.0])
    ws.append(["SBI Small Cap Fund - Regular Plan - Growth", "98765/43", 50.0, 50000.0, 45000.0])
    cas_path = tmp_path / "synthetic_cas.xlsx"
    wb.save(cas_path)
    return cas_path


def test_mandate_rejects_free_text_aggressive_without_explicit_tier():
    # Issue #120 Observation 2: Risk comfort plus 5-7Y horizon does not authorize Tier 6
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=6.0,
        goal="Wealth Creation",
        lumpsum_budget_inr=Decimal("400000"),
        risk_comfort_text="Aggressive",
        explicit_authorized_risk_tier=None,  # Missing!
        bank_cash_inr=Decimal("600000"),
        emergency_reserve_inr=Decimal("150000"),
    )
    is_valid, errors = mandate.validate_for_lumpsum()
    assert is_valid is False
    assert any("Missing investor-authorized risk tier" in err for err in errors)


def test_mandate_rejects_missing_cash_or_reserve():
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=5.0,
        goal="Growth",
        lumpsum_budget_inr=Decimal("400000"),
        explicit_authorized_risk_tier="Tier 4",
        bank_cash_inr=None,  # Missing!
        emergency_reserve_inr=None,
    )
    is_valid, errors = mandate.validate_for_lumpsum()
    assert is_valid is False
    assert any("Verified bank cash evidence is missing" in err for err in errors)


def test_mandate_rejects_insufficient_deployable_surplus():
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=5.0,
        goal="Growth",
        lumpsum_budget_inr=Decimal("400000"),
        explicit_authorized_risk_tier="Tier 4",
        bank_cash_inr=Decimal("450000"),
        emergency_reserve_inr=Decimal("100000"),  # Deployable surplus is 350,000 < 400,000
    )
    is_valid, errors = mandate.validate_for_lumpsum()
    assert is_valid is False
    assert any("does not cover requested lump sum" in err for err in errors)


def test_engine_bootstrap_pipeline_validation_report(tmp_path):
    # Issue #121: Engine bootstraps evidence and produces deterministic validation report
    pipeline = EngineBootstrapPipeline()
    staging_dir = tmp_path / "staging"
    as_of = date.today()

    # Incomplete inputs should produce BLOCKED status
    report = pipeline.build_staging_bundle(
        staging_dir,
        as_of,
        hermetic_inputs={},  # Empty
        reviewer_attested=False,
    )
    assert report.status == "BLOCKED"
    assert report.can_provide_read_only_report is True
    assert report.unpromoted_reason is not None
    assert len(report.gates) >= 5
    assert not all(g.passed for g in report.gates)

    # Complete inputs should produce PROMOTABLE status
    report_valid = pipeline.build_staging_bundle(
        staging_dir,
        as_of,
        hermetic_inputs={
            "scheme_master": b"..." * 50,
            "daily_nav": b"..." * 50,
            "metrics": b"..." * 50,
            "metrics_json": b"..." * 50,
            "direct_evidence": {"s-1": b"%PDF-1.4 factsheet"},
            "disclosures": {"s-1": b"{\"constituents\": {}}"},
        },
        reviewer_attested=True,
    )
    assert report_valid.status == "PROMOTABLE"
    assert all(g.passed for g in report_valid.gates)


def test_evaluate_portfolio_aware_lumpsum_fails_closed_without_complete_evidence(tmp_path):
    cas_path = _create_synthetic_cas(tmp_path)
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=6.0,
        goal="Wealth Creation",
        lumpsum_budget_inr=Decimal("400000"),
        risk_comfort_text="Aggressive",
        explicit_authorized_risk_tier=None,  # Missing authorization
        bank_cash_inr=Decimal("600000"),
        emergency_reserve_inr=Decimal("150000"),
    )

    result = evaluate_portfolio_aware_lumpsum(cas_path, mandate)

    # Fail closed: Entire budget remains unallocated
    assert result.status == "HOLD"
    assert result.total_lumpsum_inr == Decimal("400000")
    assert result.allocated_amount_inr == Decimal("0")
    assert result.unallocated_amount_inr == Decimal("400000")
    assert result.parking_allocation_inr == Decimal("160000.00")  # 40% parking
    assert result.stp_allocation_inr == Decimal("240000.00")      # 60% STP
    assert result.parking_ratio_pct == 40.0
    assert result.stp_ratio_pct == 60.0
    assert result.stp_duration_months == 6
    assert result.policy_branch == "STANDARD_PARKING_STP_WATERFALL"
    assert result.is_execution_authorized is False
    assert len(result.missing_evidence) > 0
    assert any("Missing investor-authorized risk tier" in err for err in result.missing_evidence)


def test_evaluate_portfolio_aware_lumpsum_tier6_override(tmp_path):
    cas_path = _create_synthetic_cas(tmp_path)
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=8.0,
        goal="Wealth Creation",
        lumpsum_budget_inr=Decimal("400000"),
        explicit_authorized_risk_tier="Tier 6",
        tier6_equity_only_authorized=True,
        bank_cash_inr=Decimal("700000"),
        emergency_reserve_inr=Decimal("150000"),
    )

    result = evaluate_portfolio_aware_lumpsum(cas_path, mandate)
    # 20% parking / 80% STP for authorized Tier 6 with >= 7Y horizon
    assert result.policy_branch == "TIER6_AGGRESSIVE_STP_WATERFALL"
    assert result.parking_allocation_inr == Decimal("80000.00")
    assert result.stp_allocation_inr == Decimal("320000.00")
    assert result.parking_ratio_pct == 20.0
    assert result.stp_ratio_pct == 80.0
