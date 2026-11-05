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
