"""
Unit tests for emergency reserve verification and liquidity runway.
Addresses Issue #31: Verify emergency reserve, liquidity runway and near-term cash obligations before SIP deployment.
"""
from __future__ import annotations

import math
import pytest
from types import SimpleNamespace

from core.math_engine import (
    _validated_ips_numeric_inputs,
    compute_liquidity_waterfall,
    calculate_cash_deployment,
    calculate_lookthrough_stability_buffer,
)
from core.models import AssetClass, HoldingItem, PlanType


def test_validated_ips_numeric_inputs_rejects_missing_emergency_months():
    ips = {"monthly_sip_budget": 10000.0}
    with pytest.raises(ValueError, match="Explicit ips.emergency_months is required"):
        _validated_ips_numeric_inputs(ips)


def test_validated_ips_numeric_inputs_rejects_invalid_emergency_months():
    ips_bool = {"monthly_sip_budget": 10000.0, "emergency_months": True}
    with pytest.raises(ValueError, match="must not be booleans"):
        _validated_ips_numeric_inputs(ips_bool)

    ips_negative = {"monthly_sip_budget": 10000.0, "emergency_months": -1.0}
    with pytest.raises(ValueError, match="finite and non-negative"):
        _validated_ips_numeric_inputs(ips_negative)

    ips_nan = {"monthly_sip_budget": 10000.0, "emergency_months": float("nan")}
    with pytest.raises(ValueError, match="finite and non-negative"):
        _validated_ips_numeric_inputs(ips_nan)


def test_validated_ips_numeric_inputs_accepts_explicit_policy_months():
    ips = {"monthly_sip_budget": 15000.0, "emergency_months": 12.0, "lumpsum_budget": 50000.0}
    sip, lumpsum, months = _validated_ips_numeric_inputs(ips)
    assert sip == 15000.0
    assert lumpsum == 50000.0
    assert months == 12.0


def test_compute_liquidity_waterfall_requires_explicit_months():
    with pytest.raises(TypeError):
        compute_liquidity_waterfall(500000.0, 50000.0)  # missing months_reserve

    reserve, deployable = compute_liquidity_waterfall(500000.0, 50000.0, 6.0)
    assert reserve == 300000.0
    assert deployable == 200000.0

    # Negative or non-finite inputs fail closed
    with pytest.raises(ValueError, match="finite non-negative numbers"):
        compute_liquidity_waterfall(-100.0, 50000.0, 6.0)


def test_calculate_cash_deployment_fails_closed_when_evidence_missing():
    # When cash or emergency buffer or months are None, status is EVIDENCE_MISSING and deployable is None
    plan = calculate_cash_deployment(bank_cash_inr=None, emergency_buffer_inr=None, emergency_months=None)
    assert plan.status == "EVIDENCE_MISSING"
    assert plan.total_cash_inr is None
    assert plan.emergency_reserve_inr is None
    assert plan.deployable_surplus_inr is None
    assert "Missing source-backed bank cash" in plan.unavailable_reason

    # Missing bank cash cannot be coerced to 0.0 deployable surplus
    plan2 = calculate_cash_deployment(bank_cash_inr=None, emergency_buffer_inr=100000.0, emergency_months=6.0)
    assert plan2.status == "EVIDENCE_MISSING"
    assert plan2.deployable_surplus_inr is None


def test_calculate_cash_deployment_with_verified_evidence():
    plan = calculate_cash_deployment(
        bank_cash_inr=500000.0,
        emergency_buffer_inr=300000.0,
        emergency_months=6.0,
        stp_months=6,
        as_of_date="2026-11-01",
        evidence_source="BANK_STATEMENT_CGS_LINKED"
    )
    assert plan.status == "AVAILABLE"
    assert plan.total_cash_inr == 500000.0
    assert plan.emergency_reserve_inr == 300000.0
    assert plan.emergency_months == 6.0
    assert plan.deployable_surplus_inr == 200000.0
    assert plan.stp_monthly_amount_inr == round(200000.0 / 6, 2)


def test_lookthrough_stability_buffer_reports_missing_cash_evidence():
    holding = HoldingItem(
        fund_id="fund-1",
        scheme="Debt Fund Direct",
        fund_name="Debt Fund Direct",
        folio="12345",
        is_direct=True,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.DEBT,
        equity_pct=0.0,
        debt_pct=100.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=100000.0,
        invested_value_inr=90000.0,
        units=100.0,
        nav=1000.0,
    )
    # When bank cash or emergency buffer is None
    buf = calculate_lookthrough_stability_buffer(
        holdings=[holding],
        bank_cash_inr=None,
        emergency_reserve_inr=None,
    )
    assert buf.cash_evidence_status == "EVIDENCE_MISSING"
    assert buf.bank_deployable_cash_inr is None
    assert buf.emergency_reserve_inr is None
    # Only embedded debt is counted in total stability buffer
    assert buf.embedded_debt_inr == 100000.0
    assert buf.total_stability_buffer_inr == 100000.0
