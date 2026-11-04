import pytest
from pydantic import ValidationError

from core.models import (
    AssetClass,
    EligibilityGateResult,
    PersonalRedemptionPlan,
    RedemptionTrancheItem,
    SAADriftAnalysis,
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
        unallocated_amount_inr=10000,
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
    thematic = ThematicExposureItem(theme_name="unknown", coverage_status="UNKNOWN")
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


def test_duplicate_fee_bleed_module_does_not_emit_generic_commission_or_folio_data():
    from core.math.fee_bleed import calculate_fee_bleed as legacy_fee_bleed

    result = legacy_fee_bleed([_holding()])
    assert result.availability_status == "UNAVAILABLE"
    assert result.annual_bleed_inr is None
    assert result.ten_year_compounded_loss_inr is None
    assert result.regular_funds_count == 1
    assert result.regular_portfolio_value_inr == 100000.0
    assert result.details == []
    assert "generic estimate" in result.unavailable_reason


def test_eligibility_gates_cannot_default_to_pass():
    with pytest.raises(ValidationError, match="cannot pass"):
        EligibilityGateResult(
            fund_id="fund-1", fund_name="Fund 1", passed=True
        )


def test_eligibility_gates_allow_unknown_only_for_non_passing_result():
    result = EligibilityGateResult(
        fund_id="fund-1",
        fund_name="Fund 1",
        passed=False,
        failed_gates=["AMC gate unevaluated: source data missing"],
    )
    assert result.amc_concentration_gate is None
    assert result.direct_plan_gate is None
    assert result.passed is False


def test_eligibility_gates_require_all_explicit_true_for_pass():
    gates = {
        "amc_concentration_gate": True,
        "aum_stability_gate": True,
        "concentration_gate": True,
        "sharpe_alpha_gate": True,
        "liquidity_gate": True,
        "mandate_suitability_gate": True,
        "data_integrity_gate": True,
        "manager_tenure_gate": True,
        "thematic_satellite_gate": True,
        "direct_plan_gate": True,
    }
    result = EligibilityGateResult(
        fund_id="fund-1", fund_name="Fund 1", passed=True, **gates
    )
    assert result.passed is True
    assert all(
        getattr(result, field) is True
        for field in (
            "amc_concentration_gate", "aum_stability_gate", "concentration_gate",
            "sharpe_alpha_gate", "liquidity_gate", "mandate_suitability_gate",
            "data_integrity_gate", "manager_tenure_gate", "thematic_satellite_gate",
            "direct_plan_gate",
        )
    )

    with pytest.raises(ValidationError, match="cannot pass"):
        EligibilityGateResult(
            fund_id="fund-1",
            fund_name="Fund 1",
            passed=True,
            **{**gates, "direct_plan_gate": None},
        )
    with pytest.raises(ValidationError, match="cannot pass"):
        EligibilityGateResult(
            fund_id="fund-1",
            fund_name="Fund 1",
            passed=True,
            **{**gates, "direct_plan_gate": False},
        )


def test_saa_missing_lookthrough_and_redemption_tax_are_not_serialized_as_zero():
    saa = SAADriftAnalysis(
        current_equity_pct=0,
        current_debt_pct=0,
        current_cash_pct=0,
        current_equity_inr=0,
        current_debt_inr=0,
        target_equity_pct=75,
        target_debt_pct=25,
        rebalance_required=False,
        equity_gap_inr=0,
        debt_gap_inr=0,
    )
    assert saa.look_through_debt_inr is None
    assert saa.look_through_cash_inr is None
    assert saa.look_through_stability_buffer_pct is None

    redemption = PersonalRedemptionPlan(
        requested_amount_inr=10000,
        ticket_category="SMALL_TICKET",
        ticket_rationale="NO ACTION: tax evidence unavailable",
        is_net_cash_target=False,
        total_gross_redeemed_inr=0,
        total_net_cash_inr=0,
        funds_liquidated_count=0,
        full_folio_exits_count=0,
    )
    assert redemption.total_exit_load_inr is None
    assert redemption.total_stcg_tax_inr is None
    assert redemption.total_ltcg_tax_inr is None
    assert redemption.total_annual_commission_saved_inr is None

    tranche = RedemptionTrancheItem(
        fund_id="scheme-1",
        scheme_name="Scheme",
        folio="REDACTED",
        priority_tier=1,
        priority_label="NO ACTION",
        fiduciary_reason="No verified lots",
        gross_amount_inr=0,
        units_to_redeem=0,
        nav=0,
        action_step="NO ACTION",
    )
    assert tranche.is_long_term is None
    assert tranche.exit_load_inr is None
    assert tranche.net_tax_liability_inr is None


def test_public_saa_targets_are_derived_from_central_allocation_policy():
    import json
    from pathlib import Path
    from core.models import RiskTier, SAA_POLICY_MAP

    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    mapping = {
        RiskTier.CONSERVATIVE: "low_to_moderate",
        RiskTier.MODERATE: "moderately_high",
        RiskTier.AGGRESSIVE: "very_high",
    }
    for risk, profile_name in mapping.items():
        target = policy["behavioral_risk_profiles"][profile_name]["saa_targets"]
        expected_equity = sum(float(target[key]) for key in (
            "large_cap_pct", "mid_cap_pct", "small_cap_pct", "flexi_multi_cap_pct"
        ))
        actual = SAA_POLICY_MAP[risk]
        assert actual.equity_pct == expected_equity
        assert actual.debt_pct == float(target["debt_liquid_pct"])
        assert actual.cash_pct == float(target.get("cash_pct", 0.0))
