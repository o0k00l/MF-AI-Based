"""
Unit tests for exact Decimal money contract and budget reconciliation.
Addresses Issue #55: Enforce the documented Decimal money contract across ingestion, calculations and outputs.
"""
from __future__ import annotations

from decimal import Decimal
import pytest

from core.models import (
    AssetClass,
    DeterministicSIPPlan,
    DeterministicSIPRecommendation,
    HoldingItem,
    PlanType,
    quantize_inr,
)


def test_quantize_inr_exact_paise():
    assert quantize_inr(Decimal("100.555")) == Decimal("100.56")
    assert quantize_inr(Decimal("100.554")) == Decimal("100.55")
    assert quantize_inr("123456789.99") == Decimal("123456789.99")
    assert quantize_inr(1000.5) == Decimal("1000.50")


def test_holding_item_preserves_decimal_precision():
    curr_val = Decimal("150000.75")
    inv_val = Decimal("120000.25")
    units = Decimal("100.1234")
    nav = Decimal("1498.1582")

    item = HoldingItem(
        fund_id="fund-001",
        scheme="Bluechip Fund Direct",
        fund_name="Bluechip Fund Direct",
        folio="12345",
        is_direct=True,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.EQUITY,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=curr_val,
        invested_value_inr=inv_val,
        units=units,
        nav=nav,
    )

    assert item.current_value_inr == curr_val
    assert isinstance(item.current_value_inr, Decimal)
    assert item.invested_value_inr == inv_val
    assert isinstance(item.invested_value_inr, Decimal)


def test_deterministic_sip_plan_exact_decimal_budget_reconciliation():
    budget = Decimal("15000.00")
    item1 = DeterministicSIPRecommendation(
        category_role="Core Flexi-Cap",
        scheme_name="Flexi Direct Growth",
        monthly_inr=Decimal("9000.00"),
        allocation_pct=60.0,
        rational_code="CORE",
        fiduciary_rationale="Core compounder",
    )
    item2 = DeterministicSIPRecommendation(
        category_role="Mid-Cap Alpha",
        scheme_name="Mid Direct Growth",
        monthly_inr=Decimal("6000.00"),
        allocation_pct=40.0,
        rational_code="ALPHA",
        fiduciary_rationale="Alpha engine",
    )

    # Exactly reconciled: 9000.00 + 6000.00 + 0.00 = 15000.00
    plan = DeterministicSIPPlan(
        total_monthly_budget_inr=budget,
        unallocated_budget_inr=Decimal("0.00"),
        equity_sip_pct=100.0,
        debt_sip_pct=0.0,
        items=[item1, item2],
    )
    assert plan.total_monthly_budget_inr == budget

    # Discrepancy by 5 paise -> fail closed
    with pytest.raises(ValueError, match="Allocated SIP amounts"):
        DeterministicSIPPlan(
            total_monthly_budget_inr=budget,
            unallocated_budget_inr=Decimal("0.05"),
            equity_sip_pct=100.0,
            debt_sip_pct=0.0,
            items=[item1, item2],
        )

def test_holding_item_coerces_float_to_exact_decimal():
    item = HoldingItem(
        fund_id="fund-002",
        scheme="Flexi Direct",
        fund_name="Flexi Direct",
        folio="998877",
        is_direct=True,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.EQUITY,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=150000.75,   # Float input
        invested_value_inr=120000.25,  # Float input
        units=100.1234,                # Float input
        nav=1498.1582,                 # Float input
    )
    assert isinstance(item.current_value_inr, Decimal)
    assert item.current_value_inr == Decimal("150000.75")
    assert isinstance(item.invested_value_inr, Decimal)
    assert item.invested_value_inr == Decimal("120000.25")
    assert isinstance(item.units, Decimal)
    assert isinstance(item.nav, Decimal)


def test_deterministic_lumpsum_plan_exact_decimal_budget_reconciliation():
    from core.models import DeterministicLumpsumPlan, LumpsumTrancheItem

    tranche1 = LumpsumTrancheItem(
        role="Parking Vehicle",
        scheme_name="Arbitrage Direct Growth",
        amount_inr=160000.00,  # Float input coerced to Decimal
        allocation_pct=40.0,
        timing="IMMEDIATE",
        source_vehicle="Bank Account",
        fiduciary_rationale="Arbitrage parking",
    )
    assert isinstance(tranche1.amount_inr, Decimal)
    assert tranche1.amount_inr == Decimal("160000.00")

    plan = DeterministicLumpsumPlan(
        total_lumpsum_inr=Decimal("400000.00"),
        unallocated_amount_inr=Decimal("240000.00"),
        is_big_ticket=False,
        stp_duration_months=6,
        immediate_amount_inr=Decimal("160000.00"),
        stp_total_amount_inr=Decimal("240000.00"),
        monthly_stp_total_inr=Decimal("40000.00"),
        parking_vehicle="Arbitrage Direct",
        tranches=[tranche1],
    )
    assert isinstance(plan.total_lumpsum_inr, Decimal)
    assert isinstance(plan.unallocated_amount_inr, Decimal)
    assert plan.total_lumpsum_inr == tranche1.amount_inr + plan.unallocated_amount_inr

    # Discrepancy by 1 paisa -> fail closed
    with pytest.raises(ValueError, match="Allocated lumpsum amounts"):
        DeterministicLumpsumPlan(
            total_lumpsum_inr=Decimal("400000.00"),
            unallocated_amount_inr=Decimal("240000.01"),
            is_big_ticket=False,
            stp_duration_months=6,
            immediate_amount_inr=Decimal("160000.00"),
            stp_total_amount_inr=Decimal("240000.00"),
            monthly_stp_total_inr=Decimal("40000.00"),
            parking_vehicle="Arbitrage Direct",
            tranches=[tranche1],
        )


def test_sip_plan_rejects_one_paise_budget_mismatch():
    item = DeterministicSIPRecommendation(
        category_role="Core",
        scheme_name="Core Direct Growth",
        monthly_inr=Decimal("9999.99"),
        allocation_pct=100.0,
        rational_code="CORE",
        fiduciary_rationale="Exact Decimal reconciliation",
    )
    with pytest.raises(ValueError, match="must equal the monthly budget exactly"):
        DeterministicSIPPlan(
            total_monthly_budget_inr=Decimal("10000.00"),
            unallocated_budget_inr=Decimal("0.00"),
            equity_sip_pct=100.0,
            debt_sip_pct=0.0,
            items=[item],
        )


@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), float("nan"), float("inf"), True])
def test_quantize_inr_rejects_non_finite_and_boolean_inputs(value):
    with pytest.raises(ValueError):
        quantize_inr(value)


@pytest.mark.parametrize("field", ["units", "nav"])
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-0.0001"), True])
def test_holding_item_rejects_invalid_unit_and_nav_values(field, value):
    data = {
        "fund_id": "fund-invalid",
        "scheme": "Invalid precision fund",
        "fund_name": "Invalid precision fund",
        "folio": "F-1",
        "is_direct": True,
        "plan": PlanType.DIRECT,
        "asset_class": AssetClass.EQUITY,
        "equity_pct": 100.0,
        "debt_pct": 0.0,
        "hybrid_pct": 0.0,
        "international_pct": 0.0,
        "current_value_inr": Decimal("100.00"),
        "invested_value_inr": Decimal("90.00"),
        "units": Decimal("1.123456"),
        "nav": Decimal("89.012345"),
    }
    data[field] = value
    with pytest.raises((ValueError, TypeError)):
        HoldingItem(**data)
