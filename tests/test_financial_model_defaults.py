import pytest
from pydantic import ValidationError

from core.models import (
    AssetClass,
    DeterministicSIPPlan,
    DeterministicLumpsumPlan,
    FeeBleedAnalysis,
    FiduciaryFactsPayload,
    HoldingItem,
    LookThroughStabilityBuffer,
    PlanType,
    ThematicExposureItem,
)
from core.math_engine import calculate_fee_bleed


def _holding(plan=PlanType.REGULAR):
    return HoldingItem(
        fund_id="scheme-1",
        scheme="Scheme Direct/Regular",
        fund_name="Scheme",
        folio="FOLIO-REDACTED",
        is_direct=plan == PlanType.DIRECT,
        plan=plan,
        asset_class=AssetClass.EQUITY,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=100000.0,
        invested_value_inr=90000.0,
        units=100.0,
        nav=1000.0,
    )


def test_missing_risk_and_validation_states_are_unknown_not_success_defaults():
    buffer = LookThroughStabilityBuffer()
    plan = DeterministicLumpsumPlan(
        total_lumpsum_inr=10000,
        is_big_ticket=False,
        stp_duration_months=0,
        immediate_amount_inr=0,
        stp_total_amount_inr=0,
        monthly_stp_total_inr=0,
        parking_vehicle="UNAVAILABLE",
    )
    assert buffer.meets_tier_target is None
    assert plan.cash_validation_passed is None


def test_missing_risk_profile_and_exposure_are_not_inferred():
    assert FiduciaryFactsPayload.model_fields["risk_tier_name"].default is None
    holding = _holding()
    assert holding.expense_ratio_pct is None
    thematic = ThematicExposureItem(theme_name="unknown")
    assert thematic.dedicated_funds_pct is None
    assert thematic.look_through_stocks_pct is None


def test_sip_plan_cannot_default_to_all_equity_when_split_is_omitted():
    with pytest.raises(ValidationError):
        DeterministicSIPPlan(total_monthly_budget_inr=10000)


def test_fee_analysis_does_not_infer_generic_commission_or_future_return():
    result = calculate_fee_bleed([_holding()])
    assert result.availability_status == "UNAVAILABLE"
    assert result.annual_commission_leakage_inr is None
    assert result.ten_year_compounded_loss_inr is None
    assert result.regular_funds_count == 1
    assert result.annual_bleed_inr is None
    assert result.regular_portfolio_value_inr is None


def test_fee_analysis_does_not_turn_zero_or_direct_plan_into_commission_fact():
    result = calculate_fee_bleed([_holding(PlanType.DIRECT)])
    assert result.regular_funds_count == 0
    assert result.annual_commission_leakage_inr is None
    assert result.ten_year_compounded_loss_inr is None
