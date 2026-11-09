"""Unit tests for services/risk_profiler.py.

Validates SEBI compliance, binding constraint enforcement, and SAA calculations.
"""
from __future__ import annotations

import pytest
from services.risk_profiler import (
    evaluate_fiduciary_profile,
    SebiRiskTier,
    TargetSaa,
    RiskProfileResult,
)


def test_user_scenario_five_percent_drop_hard_limiter():
    """Verify that a 5% max drop tolerance and 3-5y horizon results in appropriate tiering.

    Specifically tests the user's questionnaire answers:
    - Horizon: 4 years (3-5 years bracket)
    - Max drop tolerance: 5% or less
    - Emergency savings: 12+ months
    - Stable income, EMI < 20%
    """
    res = evaluate_fiduciary_profile(
        horizon_years=4.0,
        max_drawdown_tolerance_pct=5.0,
        emergency_fund_months=12.0,
        income_stability="stable",
        emi_burden_pct=15.0,
        experience_level="experienced",
    )

    # 1. Governing Tier must be Tier 2 (Low to Moderate), NOT Tier 4, 5, or 6
    assert res.governing_tier == SebiRiskTier.TIER_2_LOW

    # 2. Total Equity must be within Tier 2 bounds (max_equity_pct: 40)
    assert res.target_saa.total_equity_pct <= 40.0

    # 3. Mid/Small cap must be within Tier 2 policy bounds (max_mid_small_pct: 10)
    # Note: Actual result is 5.0% (mid_cap only, small_cap=0, flexi=5)
    assert res.target_saa.mid_small_cap_pct <= 10.0

    # 4. Debt/Capital preservation should be substantial
    assert res.target_saa.debt_pct >= 40.0

    # 5. SAA must sum to 100%
    total = res.target_saa.large_cap_pct + res.target_saa.mid_small_cap_pct + res.target_saa.debt_pct
    assert total == pytest.approx(100.0)


def test_ultra_short_horizon_prohibits_equity():
    """Ultra-short horizon (< 3 years) results in Tier 1 Capital Preservation.
    
    Tier 1 policy allows up to 20% equity (15% large_cap + 5% flexi_multi_cap).
    The debt allocation should be at least 80% for capital preservation.
    """
    res = evaluate_fiduciary_profile(
        horizon_years=2.0,
        max_drawdown_tolerance_pct=25.0,  # Aggressive tolerance
        emergency_fund_months=6.0,
    )
    assert res.governing_tier == SebiRiskTier.TIER_1_CAPITAL_PRESERVATION
    assert res.target_saa.total_equity_pct <= 20.0  # Tier 1 max_equity_pct: 20
    assert res.target_saa.debt_pct >= 80.0  # Tier 1 min_debt_pct: 80
    assert any("Preservation" in c or "Prohibited" in c or "horizon" in c.lower() for c in res.binding_constraints)


def test_long_horizon_and_high_tolerance_allows_aggressive():
    """10+ year horizon with high drawdown tolerance allows Tier 6 (Very High)."""
    res = evaluate_fiduciary_profile(
        horizon_years=12.0,
        max_drawdown_tolerance_pct=30.0,
        emergency_fund_months=12.0,
        income_stability="stable",
        emi_burden_pct=10.0,
    )
    assert res.governing_tier == SebiRiskTier.TIER_6_VERY_HIGH
    assert res.target_saa.total_equity_pct >= 90.0
    assert res.target_saa.mid_small_cap_pct >= 40.0


def test_weakest_link_binding_constraint():
    """Capacity vs Tolerance: Governing tier is always min(Capacity, Tolerance)."""
    # High capacity (10y horizon, 12m savings) but Low tolerance (8% drop)
    res = evaluate_fiduciary_profile(
        horizon_years=10.0,
        max_drawdown_tolerance_pct=8.0,
        emergency_fund_months=12.0,
    )
    assert res.capacity_tier >= SebiRiskTier.TIER_5_HIGH
    assert res.tolerance_tier == SebiRiskTier.TIER_3_MODERATE
    assert res.governing_tier == SebiRiskTier.TIER_3_MODERATE
    assert res.governing_tier == min(res.capacity_tier, res.tolerance_tier)


def test_all_target_saas_sum_to_100():
    """Every generated SAA target must sum to 100.0%."""
    test_cases = [
        (1.0, 5.0, 2.0),
        (3.0, 10.0, 6.0),
        (5.0, 15.0, 12.0),
        (7.0, 20.0, 6.0),
        (10.0, 35.0, 12.0),
    ]
    for h, d, e in test_cases:
        res = evaluate_fiduciary_profile(
            horizon_years=h,
            max_drawdown_tolerance_pct=d,
            emergency_fund_months=e,
        )
        total = res.target_saa.large_cap_pct + res.target_saa.mid_small_cap_pct + res.target_saa.debt_pct
        assert total == pytest.approx(100.0, abs=1e-5)



def test_evaluate_direct_tier():
    """Verify Mode 2 direct tier selection maps directly to regulatory SAA.
    
    Policy values (from data/policy/asset_allocation.json):
    - Tier 4 (Moderately High): large_cap=30, mid_small=45, debt=25
    - Tier 2 (Low): large_cap=25, mid_small=15, debt=60
    """
    from services.risk_profiler import evaluate_direct_tier

    res_t4 = evaluate_direct_tier(SebiRiskTier.TIER_4_MODERATE_HIGH)
    assert res_t4.governing_tier == SebiRiskTier.TIER_4_MODERATE_HIGH
    assert res_t4.target_saa.large_cap_pct == 30.0
    assert res_t4.target_saa.mid_small_cap_pct == 45.0
    assert res_t4.target_saa.debt_pct == 25.0
    assert res_t4.target_saa.total_equity_pct == 75.0

    res_t2 = evaluate_direct_tier(2)
    assert res_t2.governing_tier == SebiRiskTier.TIER_2_LOW
    assert res_t2.target_saa.debt_pct == 60.0


def test_evaluate_custom_saa():
    """Verify Mode 3 expert custom asset allocation validation."""
    from services.risk_profiler import evaluate_custom_saa

    res = evaluate_custom_saa(large_cap_pct=60.0, mid_small_cap_pct=20.0, debt_pct=20.0, rationale="HNI Core Portfolio")
    assert res.target_saa.large_cap_pct == 60.0
    assert res.target_saa.mid_small_cap_pct == 20.0
    assert res.target_saa.debt_pct == 20.0
    assert res.target_saa.total_equity_pct == 80.0
    assert res.governing_tier == SebiRiskTier.TIER_4_MODERATE_HIGH

    # Sum must be 100%
    with pytest.raises(ValueError, match="must sum to 100.0%"):
        evaluate_custom_saa(large_cap_pct=50.0, mid_small_cap_pct=30.0, debt_pct=10.0)
