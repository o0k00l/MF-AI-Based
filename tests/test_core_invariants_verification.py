"""Dedicated verification suite for Indian Mutual Fund Decision-Support Engine fiduciary invariants.

Tests:
1. TestDecimalPrecisionInvariants (5 tests)
2. TestFailClosedBehavior (5 tests)
3. TestSaaBoundsEnforcement (5 tests)
4. TestGateLogicBlocking (3 tests)

Total: 18 authoritative tests.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import pytest

from core.models import (
    AssetClass,
    DeterministicSIPPlan,
    EligibilityGateResult,
    HoldingItem,
    RiskTier,
    SAA_POLICY_MAP,
    AssetAllocationTarget,
    quantize_inr,
    INR_PAISE,
    NOActionResult,
)
from core.math_engine import compute_deterministic_sip_blueprint
from core.eligibility import check_eligibility_gates, validate_direct_sip_mandate


# =============================================================================
# 1. TestDecimalPrecisionInvariants (5 tests)
# =============================================================================
class TestDecimalPrecisionInvariants:
    """Verifies monetary decimal precision and paise rounding rules."""

    def test_inr_quantization_round_half_up_paise(self):
        """Verifies INR quantization uses ROUND_HALF_UP to 2 decimal places (paise)."""
        val_up = Decimal("100.555")
        val_down = Decimal("100.554")
        assert quantize_inr(val_up) == Decimal("100.56")
        assert quantize_inr(val_down) == Decimal("100.55")

    def test_float_precision_error_handling(self):
        """Tests float precision error handling and safe coercion to Decimal paise."""
        f_val = 0.1 + 0.2
        d_val = quantize_inr(Decimal(str(round(f_val, 4))))
        assert d_val == Decimal("0.30")
        assert str(d_val) == "0.30"

    def test_sip_plan_budget_reconciliation(self):
        """Validates SIP plan budget reconciliation: total == allocated + unallocated."""
        plan = compute_deterministic_sip_blueprint(
            monthly_budget=15000.0,
            risk_tier="Tier 3 (Moderate)",
            client_aum=5000000.0,
            client_aum_verified=True,
            candidate_universe=[],
        )
        assert plan.total_monthly_budget_inr == Decimal("15000.00")
        allocated = sum((item.monthly_inr for item in plan.items), Decimal("0.00"))
        assert plan.total_monthly_budget_inr == allocated + plan.unallocated_budget_inr
        assert allocated == Decimal("0.00")
        assert plan.unallocated_budget_inr == Decimal("15000.00")

    def test_holding_item_preserves_decimal_precision(self):
        """Confirms HoldingItem preserves decimal precision for units and financial values."""
        item = HoldingItem(
            fund_id="HDFC_FLEXI",
            scheme="HDFC Flexi Cap Fund Direct Growth",
            fund_name="HDFC Flexi Cap Fund",
            amc_name="HDFC Mutual Fund",
            folio="12345/67",
            units=Decimal("150.123"),
            nav=Decimal("1200.4567"),
            current_value_inr=Decimal("180216.56"),
            invested_value_inr=Decimal("150000.00"),
            asset_class=AssetClass.EQUITY,
            equity_pct=100.0,
            debt_pct=0.0,
            hybrid_pct=0.0,
            international_pct=0.0,
        )
        assert isinstance(item.units, Decimal)
        assert item.units == Decimal("150.123")
        assert isinstance(item.current_value_inr, Decimal)
        assert item.current_value_inr == Decimal("180216.56")
        assert isinstance(item.nav, Decimal)
        assert item.nav == Decimal("1200.4567")

    def test_decimal_paise_rounding_boundary(self):
        """Tests exact paise half-way boundary cases."""
        assert quantize_inr(Decimal("0.005")) == Decimal("0.01")
        assert quantize_inr(Decimal("0.0049")) == Decimal("0.00")
        assert quantize_inr(Decimal("12345.675")) == Decimal("12345.68")
        assert quantize_inr(Decimal("12345.6749")) == Decimal("12345.67")


# =============================================================================
# 2. TestFailClosedBehavior (5 tests)
# =============================================================================
class TestFailClosedBehavior:
    """Verifies fail-closed behavior when data or evidence is missing."""

    def test_empty_candidate_universe_returns_hold_no_action(self):
        """Tests empty candidate universe returns HOLD/NO_ACTION."""
        plan = compute_deterministic_sip_blueprint(
            monthly_budget=10000.0,
            risk_tier="Tier 3 (Moderate)",
            client_aum=5000000.0,
            client_aum_verified=True,
            candidate_universe=[],
        )
        assert "HOLD" in plan.execution_status
        assert plan.is_actionable_order is False
        assert all(item.monthly_inr == Decimal("0.00") for item in plan.items)
        assert all("NO_ACTION" in item.scheme_name for item in plan.items)
        assert plan.unallocated_budget_inr == Decimal("10000.00")

    def test_missing_scheme_master_fails_closed(self):
        """Verifies candidate with missing scheme master verification fails closed."""
        unverified_candidate = {
            "fund_id": "unverified-001",
            "fund_name": "Unverified Scheme Fund",
            "category": "Flexi Cap",
            "is_direct": True,
        }
        plan = compute_deterministic_sip_blueprint(
            monthly_budget=10000.0,
            risk_tier="Tier 3 (Moderate)",
            client_aum=5000000.0,
            client_aum_verified=True,
            candidate_universe=[unverified_candidate],
        )
        assert "HOLD" in plan.execution_status
        assert plan.is_actionable_order is False
        assert all(item.monthly_inr == Decimal("0.00") for item in plan.items)
        assert all("NO_ACTION" in item.scheme_name for item in plan.items)
        assert plan.unallocated_budget_inr == Decimal("10000.00")

    def test_eligibility_gates_fail_when_portfolio_data_is_missing(self):
        """Confirms eligibility gates fail when candidate portfolio data is missing."""
        incomplete = {
            "fund_id": "test-incomplete",
            "fund_name": "Test Incomplete Fund",
            "plan_type": "Direct",
        }
        res = check_eligibility_gates(incomplete)
        assert res.passed is False
        assert len(res.failed_gates) > 0

    def test_missing_scheme_identity_fails_the_gate(self):
        """Tests missing scheme identity (Regular designation) fails Gate 10."""
        cand_regular = {
            "fund_id": "reg-fund",
            "fund_name": "Regular Plan Fund",
            "plan_type": "Regular",
            "is_direct": False,
        }
        res = check_eligibility_gates(cand_regular)
        assert res.passed is False
        assert any("Gate 10" in g or "Direct" in g for g in res.failed_gates)

    def test_no_action_result_structure(self):
        """Validates NO_ACTION result structure and fields."""
        no_action = NOActionResult(
            action="NO_ACTION",
            reason="Unverified scheme candidates",
            current_portfolio_adequate=True,
            no_improvement_found=True,
            hold_recommendation="HOLD",
        )
        assert no_action.action == "NO_ACTION"
        assert "Unverified" in no_action.reason
        assert no_action.hold_recommendation == "HOLD"
        assert no_action.sip_deployment_pause is True


# =============================================================================
# 3. TestSaaBoundsEnforcement (5 tests)
# =============================================================================
class TestSaaBoundsEnforcement:
    """Verifies SAA policy bounds and risk tier asset allocation enforcement."""

    def test_all_risk_profile_saa_targets_sum_to_100(self):
        """Verifies all risk profile SAA targets sum to 100%."""
        for tier, target in SAA_POLICY_MAP.items():
            total = target.equity_pct + target.debt_pct
            assert total == pytest.approx(100.0, abs=1e-5), f"{tier} does not sum to 100%"

    def test_equity_plus_debt_percentages_do_not_exceed_100(self):
        """Confirms equity + debt percentages do not exceed 100%."""
        for tier, target in SAA_POLICY_MAP.items():
            assert target.equity_pct >= 0.0
            assert target.debt_pct >= 0.0
            assert target.equity_pct + target.debt_pct <= 100.0

    def test_tier_6_saa_target_structure(self):
        """Tests Tier 6 SAA target structure (95% equity, 5% debt base)."""
        target = SAA_POLICY_MAP[RiskTier.AGGRESSIVE]
        assert target.equity_pct == 95.0
        assert target.debt_pct == 5.0
        assert target.equity_pct + target.debt_pct == 100.0

    def test_tier_6_95_percent_equity_sip_routing_without_ips_override(self):
        """Validates 95% equity SIP routing without IPS override."""
        plan = compute_deterministic_sip_blueprint(
            monthly_budget=50000.0,
            risk_tier="Tier 6 (Very High)",
            client_aum=5000000.0,
            client_aum_verified=True,
            equity_sip_routing_override=False,
            candidate_universe=[],
        )
        assert plan.equity_sip_pct == 95.0
        assert plan.debt_sip_pct == 5.0
        assert "HOLD" in plan.execution_status

    def test_tier_6_100_percent_equity_sip_routing_with_ips_override(self):
        """Validates 100% equity SIP routing with explicit IPS override."""
        plan = compute_deterministic_sip_blueprint(
            monthly_budget=50000.0,
            risk_tier="Tier 6 (Very High)",
            client_aum=5000000.0,
            client_aum_verified=True,
            equity_sip_routing_override=True,
            candidate_universe=[],
        )
        assert plan.equity_sip_pct == 100.0
        assert plan.debt_sip_pct == 0.0
        assert "HOLD" in plan.execution_status


# =============================================================================
# 4. TestGateLogicBlocking (3 tests)
# =============================================================================
class TestGateLogicBlocking:
    """Tests AMC concentration, Direct-only mandate, and gate model integrity."""

    def test_gate_1_amc_concentration_logic(self):
        """Tests Gate 1 AMC concentration logic blocks excessive AMC exposure."""
        # Portfolio with 40% in HDFC AMC (above 30% policy ceiling)
        portfolio = [
            {"current_value_inr": 40000.0, "amc_name": "HDFC Mutual Fund"},
            {"current_value_inr": 60000.0, "amc_name": "ICICI Mutual Fund"},
        ]
        cand = {
            "fund_id": "hdfc_mid",
            "fund_name": "HDFC Mid-Cap Opportunities Fund Direct Growth",
            "amc_name": "HDFC Mutual Fund",
            "plan_type": "Direct",
            "is_direct": True,
            "aum_crore": 50000,
        }
        res = check_eligibility_gates(cand, portfolio_holdings=portfolio)
        assert isinstance(res, EligibilityGateResult)
        assert any("Gate 1" in f and "Concentration" in f for f in res.failed_gates)

    def test_gate_10_direct_plan_requirement(self):
        """Tests Gate 10 Direct Plan requirement blocks any regular plan in SIP mandate."""
        class MockItem:
            scheme_name = "SBI Bluechip Fund Regular Growth"
            is_direct = False
            monthly_inr = Decimal("5000.00")

        class MockPlan:
            items = [MockItem()]

        with pytest.raises(ValueError, match="Fiduciary Gate 10 Violation"):
            validate_direct_sip_mandate(MockPlan())

    def test_eligibility_gate_result_model_integrity(self):
        """Validates EligibilityGateResult model integrity and diagnostic properties."""
        all_passed_kwargs = {
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
        gate_res = EligibilityGateResult(
            fund_id="SCHEME_999",
            fund_name="Parag Parikh Flexi Cap Direct",
            passed=True,
            failed_gates=[],
            details={"Gate 10": "Direct Plan Verified"},
            **all_passed_kwargs,
        )
        assert gate_res.passed is True
        assert len(gate_res.failed_gates) == 0

        # Validates that passing cannot have any unevaluated / false gate
        with pytest.raises(ValueError, match="Eligibility cannot pass"):
            EligibilityGateResult(
                fund_id="SCHEME_999",
                fund_name="Parag Parikh Flexi Cap Direct",
                passed=True,
                failed_gates=[],
            )
