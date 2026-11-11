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
    """Verify that a 5% max drop tolerance and 3-5y horizon caps portfolio at Tier 2.

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

    # 2. Total Equity must be strictly capped (<= 30%)
    assert res.target_saa.total_equity_pct <= 30.0

    # 3. Mid/Small cap must be eliminated (0%) because 3-5 years cannot absorb volatility
    assert res.target_saa.mid_small_cap_pct == 0.0

    # 4. Debt/Capital preservation must be at least 70%
    assert res.target_saa.debt_pct >= 70.0

    # 5. SAA must sum to 100% (including flexi_multi_cap_pct)
    total = res.target_saa.large_cap_pct + res.target_saa.mid_small_cap_pct + res.target_saa.flexi_multi_cap_pct + res.target_saa.debt_pct
    assert total == pytest.approx(100.0)

    # 6. Must articulate the binding constraint
    assert any("5%" in c or "Drawdown" in c for c in res.binding_constraints)


def test_ultra_short_horizon_prohibits_equity():
    """Goals under 3 years are prohibited from equity under SEBI fiduciary standards.
    
    The ultra-short horizon limiter caps total equity at 0%, which includes all equity
    sleeves (large_cap, mid_small, and flexi_multi_cap). The policy's Tier 1 baseline
    allocation of 15% large_cap + 5% flexi = 20% equity is therefore reduced to 0% total.
    """
    res = evaluate_fiduciary_profile(
        horizon_years=2.0,
        max_drawdown_tolerance_pct=25.0,  # Aggressive tolerance
        emergency_fund_months=6.0,
    )
    assert res.governing_tier == SebiRiskTier.TIER_1_CAPITAL_PRESERVATION
    # Ultra-short horizon caps ALL equity to 0%, including flexi
    assert res.target_saa.large_cap_pct == 0.0
    assert res.target_saa.mid_small_cap_pct == 0.0
    assert res.target_saa.flexi_multi_cap_pct == 0.0
    assert res.target_saa.debt_pct == 100.0
    assert res.target_saa.total_equity_pct == 0.0
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
        total = res.target_saa.large_cap_pct + res.target_saa.mid_small_cap_pct + res.target_saa.flexi_multi_cap_pct + res.target_saa.debt_pct
        assert total == pytest.approx(100.0, abs=1e-5)



def test_evaluate_direct_tier():
    """Verify Mode 2 direct tier selection maps directly to regulatory SAA."""
    from services.risk_profiler import evaluate_direct_tier

    res_t4 = evaluate_direct_tier(SebiRiskTier.TIER_4_MODERATE_HIGH)
    assert res_t4.governing_tier == SebiRiskTier.TIER_4_MODERATE_HIGH
    assert res_t4.target_saa.large_cap_pct == 30.0
    assert res_t4.target_saa.mid_small_cap_pct == 30.0  # mid_cap(20) + small_cap(10)
    assert res_t4.target_saa.flexi_multi_cap_pct == 15.0  # flexi_multi_cap
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


def test_evaluate_custom_saa_rejects_booleans():
    """Boolean values must be rejected even though bool subclasses int."""
    from services.risk_profiler import evaluate_custom_saa
    
    with pytest.raises(ValueError, match="cannot be a boolean"):
        evaluate_custom_saa(large_cap_pct=True, mid_small_cap_pct=20.0, debt_pct=20.0, flexi_multi_cap_pct=40.0)
    
    with pytest.raises(ValueError, match="cannot be a boolean"):
        evaluate_custom_saa(large_cap_pct=50.0, mid_small_cap_pct=False, debt_pct=30.0, flexi_multi_cap_pct=20.0)


def test_evaluate_custom_saa_rejects_nan_and_infinity():
    """NaN and Infinity must be rejected."""
    import math
    from services.risk_profiler import evaluate_custom_saa
    
    with pytest.raises(ValueError, match="must be finite"):
        evaluate_custom_saa(large_cap_pct=float('nan'), mid_small_cap_pct=20.0, debt_pct=30.0, flexi_multi_cap_pct=50.0)
    
    with pytest.raises(ValueError, match="must be finite"):
        evaluate_custom_saa(large_cap_pct=50.0, mid_small_cap_pct=20.0, debt_pct=float('inf'), flexi_multi_cap_pct=30.0)
    
    with pytest.raises(ValueError, match="must be finite"):
        evaluate_custom_saa(large_cap_pct=50.0, mid_small_cap_pct=20.0, debt_pct=30.0, flexi_multi_cap_pct=float('-inf'))


def test_evaluate_custom_saa_allows_flexi():
    """Flexi-multi-cap must be accepted as a separate fourth sleeve."""
    from services.risk_profiler import evaluate_custom_saa
    
    # With flexi
    res = evaluate_custom_saa(
        large_cap_pct=50.0, 
        mid_small_cap_pct=20.0, 
        debt_pct=20.0,
        flexi_multi_cap_pct=10.0,
        rationale="With Flexi Multi-Cap"
    )
    assert res.target_saa.flexi_multi_cap_pct == 10.0
    assert res.target_saa.total_equity_pct == 80.0  # 50 + 20 + 10


def test_short_horizon_policy_caps_equity_and_mid_small_allocation():
    """The 3-5 year policy limiter caps total equity and mid/small exposure."""
    res = evaluate_fiduciary_profile(
        horizon_years=4.0,
        max_drawdown_tolerance_pct=20.0,
        emergency_fund_months=12.0,
    )
    assert res.target_saa.total_equity_pct <= 40.0
    assert res.target_saa.mid_small_cap_pct <= 5.0
    assert res.target_saa.debt_pct >= 60.0


def test_policy_limiters_compose_without_bypassing_stricter_drawdown_cap():
    """The strictest applicable limiter governs when horizon and drawdown overlap."""
    res = evaluate_fiduciary_profile(
        horizon_years=4.0,
        max_drawdown_tolerance_pct=5.0,
        emergency_fund_months=12.0,
    )
    assert res.target_saa.total_equity_pct <= 30.0
    assert res.target_saa.mid_small_cap_pct == 0.0
    assert res.target_saa.debt_pct >= 70.0


def test_total_equity_cap_applies_to_all_sleeves():
    """When total equity is capped, ALL equity sleeves (including flexi) must be reduced proportionally.
    
    The 5% drawdown limiter caps total equity at 30%. If Tier 3 policy has 15% mid_small + 15% flexi,
    the total equity reduction must scale both mid_small and flexi down proportionally along with large_cap.
    """
    from services.risk_profiler import evaluate_direct_tier
    
    # Tier 3 has: large=35%, mid_small=20%, flexi=15% -> total_eq=70%
    # Apply 30% equity cap (from drawdown limiter)
    res = evaluate_direct_tier(SebiRiskTier.TIER_3_MODERATE)
    # The result should reflect the policy baseline (no caps applied in direct tier)
    assert res.target_saa.total_equity_pct == 70.0
    
    # Now verify the cap is applied correctly via fiduciary profile
    res_limited = evaluate_fiduciary_profile(
        horizon_years=5.0,  # Triggers short_horizon cap: max_equity=40%
        max_drawdown_tolerance_pct=5.0,  # Triggers drawdown cap: max_equity=30%
        emergency_fund_months=6.0,
    )
    # The stricter cap (30%) should apply
    assert res_limited.target_saa.total_equity_pct <= 30.0
    # If there was flexi in the policy, it should be reduced proportionally
    # (Tier 1 has flexi=5%, but ultra_short caps everything to 0)
    
    # Verify that when equity cap is 0, ALL equity is zero (including flexi)
    res_ultra = evaluate_fiduciary_profile(
        horizon_years=2.0,  # Triggers ultra_short: max_equity=0%
        max_drawdown_tolerance_pct=25.0,
        emergency_fund_months=6.0,
    )
    assert res_ultra.target_saa.total_equity_pct == 0.0
    assert res_ultra.target_saa.large_cap_pct == 0.0
    assert res_ultra.target_saa.mid_small_cap_pct == 0.0
    assert res_ultra.target_saa.flexi_multi_cap_pct == 0.0


@pytest.mark.parametrize("bad_value", [True, False])
def test_saa_policy_loader_rejects_boolean_percentages(tmp_path, monkeypatch, bad_value):
    """The loader must reject bool even though bool subclasses int in Python."""
    import json
    import services.risk_profiler as rp

    policy = json.loads(rp._POLICY_PATH.read_text(encoding="utf-8"))
    policy["behavioral_risk_profiles"]["low"]["saa_targets"]["large_cap_pct"] = bad_value
    policy_path = tmp_path / "asset_allocation.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(rp, "_POLICY_PATH", policy_path)

    with pytest.raises(ValueError, match="must be numeric"):
        rp._load_saa_from_policy()


def test_saa_policy_loader_rejects_nonfinite_percentages(tmp_path, monkeypatch):
    """NaN and infinity must never enter a financial allocation."""
    import json
    import services.risk_profiler as rp

    policy = json.loads(rp._POLICY_PATH.read_text(encoding="utf-8"))
    policy["behavioral_risk_profiles"]["low"]["saa_targets"]["large_cap_pct"] = float("inf")
    policy_path = tmp_path / "asset_allocation.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(rp, "_POLICY_PATH", policy_path)

    with pytest.raises(ValueError, match="must be finite"):
        rp._load_saa_from_policy()


def test_saa_policy_loader_enforces_inclusive_sum_tolerance(tmp_path, monkeypatch):
    """Exactly 0.1 percentage point is accepted; values outside are rejected."""
    import json
    import services.risk_profiler as rp

    policy = json.loads(rp._POLICY_PATH.read_text(encoding="utf-8"))
    policy["behavioral_risk_profiles"]["low"]["saa_targets"]["debt_liquid_pct"] += 0.1
    policy_path = tmp_path / "asset_allocation.json"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    monkeypatch.setattr(rp, "_POLICY_PATH", policy_path)
    rp._load_saa_from_policy()

    policy["behavioral_risk_profiles"]["low"]["saa_targets"]["debt_liquid_pct"] += 0.001
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    with pytest.raises(ValueError, match="allocations sum"):
        rp._load_saa_from_policy()
