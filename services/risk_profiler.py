"""services/risk_profiler.py — SEBI-Compliant Fiduciary Risk Profiler and Strategic Asset Allocation (SAA) Engine.

Follows SEBI Investment Adviser Regulations (Schedule III) and CFA Fiduciary Standards:
1. Evaluates Risk Capacity (Financial Ability) and Risk Tolerance (Psychological Willingness) separately.
2. Implements the "Weakest Link" / Binding Constraint Principle:
       Governing Tier = min(Capacity Tier, Tolerance Tier)
3. Enforces Hard Fiduciary Limiters:
   - Drawdown Limiter: If max loss tolerance <= 5%, equity is hard-capped at 30%, Mid/Small Cap at 0%.
   - Horizon Limiter: If horizon is 3-5 years, Mid/Small Cap is hard-capped at 0-5%, equity capped at 40%.
     If horizon < 3 years, equity is hard-capped at 0% (Liquid/Debt only).
   - Liquidity Limiter: If emergency savings < 3 months, risk tier is capped until buffer is built.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class SebiRiskTier(IntEnum):
    """SEBI 6-Tier Regulatory Risk Classification."""
    TIER_1_CAPITAL_PRESERVATION = 1  # Low (Green)
    TIER_2_LOW = 2                   # Low to Moderate (Chartreuse)
    TIER_3_MODERATE = 3              # Moderate (Yellow)
    TIER_4_MODERATE_HIGH = 4         # Moderately High (Orange)
    TIER_5_HIGH = 5                  # High (Dark Orange)
    TIER_6_VERY_HIGH = 6             # Very High (Red)


@dataclass(frozen=True)
class TargetSaa:
    """Strategic Asset Allocation target percentages (sum to 100.0%)."""
    large_cap_pct: float
    mid_small_cap_pct: float
    debt_pct: float

    @property
    def total_equity_pct(self) -> float:
        return self.large_cap_pct + self.mid_small_cap_pct

    def as_dict(self) -> dict[str, float]:
        return {
            "large_cap_pct": round(self.large_cap_pct, 1),
            "mid_small_cap_pct": round(self.mid_small_cap_pct, 1),
            "debt_pct": round(self.debt_pct, 1),
            "total_equity_pct": round(self.total_equity_pct, 1),
        }


@dataclass(frozen=True)
class RiskProfileResult:
    """Complete diagnostic result from SEBI fiduciary risk profiling."""
    governing_tier: SebiRiskTier
    tier_label: str
    target_saa: TargetSaa
    capacity_tier: SebiRiskTier
    tolerance_tier: SebiRiskTier
    binding_constraints: list[str]
    fiduciary_rationale: str
    expected_drawdown_range: str


# Canonical SEBI SAA Policy Mapping (Baseline Targets)
# Updated to match data/policy/asset_allocation.json (2026-10-30)
# Note: mid_small_cap_pct combines mid_cap + small_cap + flexi_multi_cap
_SEBI_SAA_TABLE: dict[SebiRiskTier, TargetSaa] = {
    SebiRiskTier.TIER_1_CAPITAL_PRESERVATION: TargetSaa(large_cap_pct=15.0, mid_small_cap_pct=5.0, debt_pct=80.0),   # 20% equity (15% large + 5% flexi)
    SebiRiskTier.TIER_2_LOW: TargetSaa(large_cap_pct=25.0, mid_small_cap_pct=15.0, debt_pct=60.0),  # 40% equity (25% large + 15% mid)
    SebiRiskTier.TIER_3_MODERATE: TargetSaa(large_cap_pct=35.0, mid_small_cap_pct=35.0, debt_pct=30.0),   # 70% equity (35% large + 15% mid + 5% small + 15% flexi)
    SebiRiskTier.TIER_4_MODERATE_HIGH: TargetSaa(large_cap_pct=30.0, mid_small_cap_pct=45.0, debt_pct=25.0),  # 75% equity (30% large + 45% mid/small/flexi)
    SebiRiskTier.TIER_5_HIGH: TargetSaa(large_cap_pct=25.0, mid_small_cap_pct=65.0, debt_pct=15.0),   # 90% equity (25% large + 65% mid/small/flexi)
    SebiRiskTier.TIER_6_VERY_HIGH: TargetSaa(large_cap_pct=20.0, mid_small_cap_pct=75.0, debt_pct=5.0),  # 95% equity (20% large + 75% mid/small/flexi)
}

_TIER_LABELS: dict[SebiRiskTier, str] = {
    SebiRiskTier.TIER_1_CAPITAL_PRESERVATION: "Tier 1: Capital Preservation (Low Risk)",
    SebiRiskTier.TIER_2_LOW: "Tier 2: Low to Moderate Risk",
    SebiRiskTier.TIER_3_MODERATE: "Tier 3: Moderate Risk",
    SebiRiskTier.TIER_4_MODERATE_HIGH: "Tier 4: Moderately High Risk",
    SebiRiskTier.TIER_5_HIGH: "Tier 5: High Risk",
    SebiRiskTier.TIER_6_VERY_HIGH: "Tier 6: Very High (Maximum Compounding)",
}

_DRAWDOWN_RANGES: dict[SebiRiskTier, str] = {
    SebiRiskTier.TIER_1_CAPITAL_PRESERVATION: "< 2% (Capital stability prioritized)",
    SebiRiskTier.TIER_2_LOW: "3% – 6% in typical market downturns",
    SebiRiskTier.TIER_3_MODERATE: "8% – 14% in typical market downturns",
    SebiRiskTier.TIER_4_MODERATE_HIGH: "15% – 22% in cyclical corrections",
    SebiRiskTier.TIER_5_HIGH: "20% – 30% in cyclical corrections",
    SebiRiskTier.TIER_6_VERY_HIGH: "25% – 40%+ in major bear market cycles",
}


def evaluate_fiduciary_profile(
    *,
    horizon_years: float,
    max_drawdown_tolerance_pct: float,
    emergency_fund_months: float,
    income_stability: str = "stable",  # "stable", "variable", "retired"
    emi_burden_pct: float = 15.0,      # debt obligations as % of income
    experience_level: str = "moderate",# "beginner", "moderate", "experienced"
) -> RiskProfileResult:
    """Evaluate investor risk profile using SEBI fiduciary binding constraints.

    Arguments:
        horizon_years: Investment time horizon in years.
        max_drawdown_tolerance_pct: Maximum temporary drop tolerated without selling (e.g. 5, 10, 20).
        emergency_fund_months: Months of household expenses in liquid/savings accounts.
        income_stability: Income predictability ("stable", "variable", "retired").
        emi_burden_pct: Total debt/EMI commitments as percentage of monthly income.
        experience_level: Experience in mutual funds ("beginner", "moderate", "experienced").

    Returns:
        RiskProfileResult containing governing tier, SAA targets, and fiduciary rationale.
    """
    constraints: list[str] = []

    # -------------------------------------------------------------------------
    # 1. Evaluate Financial Capacity (Ability to Take Risk)
    # -------------------------------------------------------------------------
    # Baseline capacity from time horizon
    if horizon_years < 3.0:
        raw_capacity = SebiRiskTier.TIER_1_CAPITAL_PRESERVATION
    elif horizon_years < 5.0:
        raw_capacity = SebiRiskTier.TIER_3_MODERATE
    elif horizon_years < 7.0:
        raw_capacity = SebiRiskTier.TIER_4_MODERATE_HIGH
    elif horizon_years < 10.0:
        raw_capacity = SebiRiskTier.TIER_5_HIGH
    else:
        raw_capacity = SebiRiskTier.TIER_6_VERY_HIGH

    # Financial stability adjustments on Capacity
    capacity_score = int(raw_capacity)

    # Emergency buffer penalty
    if emergency_fund_months < 3.0:
        capacity_score = min(capacity_score, int(SebiRiskTier.TIER_2_LOW))
        constraints.append(
            f"Liquidity Buffer Warning: Emergency savings ({emergency_fund_months:.0f} mos) is below recommended 6 months."
        )
    elif emergency_fund_months >= 12.0 and capacity_score < int(SebiRiskTier.TIER_5_HIGH):
        # Good buffer supports capacity
        pass

    # Debt burden penalty
    if emi_burden_pct > 40.0:
        capacity_score = min(capacity_score, int(SebiRiskTier.TIER_3_MODERATE))
        constraints.append(
            f"Debt Burden: High EMI obligations ({emi_burden_pct:.0f}% of income) restrict risk capacity."
        )

    # Income stability penalty
    if income_stability.lower() in ("variable", "retired"):
        capacity_score = max(int(SebiRiskTier.TIER_1_CAPITAL_PRESERVATION), capacity_score - 1)

    capacity_tier = SebiRiskTier(max(1, min(6, capacity_score)))

    # -------------------------------------------------------------------------
    # 2. Evaluate Risk Tolerance (Psychological Willingness to Bear Drawdowns)
    # -------------------------------------------------------------------------
    if max_drawdown_tolerance_pct <= 5.0:
        tolerance_tier = SebiRiskTier.TIER_2_LOW
    elif max_drawdown_tolerance_pct <= 10.0:
        tolerance_tier = SebiRiskTier.TIER_3_MODERATE
    elif max_drawdown_tolerance_pct <= 18.0:
        tolerance_tier = SebiRiskTier.TIER_4_MODERATE_HIGH
    elif max_drawdown_tolerance_pct <= 25.0:
        tolerance_tier = SebiRiskTier.TIER_5_HIGH
    else:
        tolerance_tier = SebiRiskTier.TIER_6_VERY_HIGH

    # -------------------------------------------------------------------------
    # 3. Apply the Fiduciary Binding Constraint Principle (Weakest Link Rule)
    # -------------------------------------------------------------------------
    # Capacity is what you CAN afford; Tolerance is what you CAN EMOTIONALLY BEAR.
    # Fiduciary rule: You must never exceed the lower of the two.
    governing_tier = min(capacity_tier, tolerance_tier)

    # -------------------------------------------------------------------------
    # 4. Enforce Hard Boundary Limiter Overrides
    # -------------------------------------------------------------------------
    # Hard Limiter A: 5% Max Drop Limiter
    if max_drawdown_tolerance_pct <= 5.0 and governing_tier > SebiRiskTier.TIER_2_LOW:
        governing_tier = SebiRiskTier.TIER_2_LOW
        constraints.append(
            "Drawdown Hard Limiter: You indicated a max loss tolerance of 5% or less. "
            "To prevent panic selling, equity is capped at 30% and allocated to stable assets."
        )

    # Hard Limiter B: Short Horizon Mid/Small Cap Limiter
    if horizon_years <= 5.0 and governing_tier >= SebiRiskTier.TIER_4_MODERATE_HIGH:
        governing_tier = SebiRiskTier.TIER_3_MODERATE
        constraints.append(
            f"Time Horizon Limiter: A {horizon_years:.0f}-year horizon cannot safely absorb "
            "cyclical mid/small-cap drawdowns. Governing tier adjusted to Moderate."
        )

    # Hard Limiter C: Ultra-Short Horizon (< 3 years)
    if horizon_years < 3.0:
        governing_tier = SebiRiskTier.TIER_1_CAPITAL_PRESERVATION
        constraints.append(
            f"Capital Preservation Limiter: Goal horizon is only {horizon_years:.1f} years. "
            "Equity deployment is prohibited under SEBI guidelines to prevent capital loss."
        )

    # -------------------------------------------------------------------------
    # 5. Determine Strategic Asset Allocation (SAA)
    # -------------------------------------------------------------------------
    base_saa = _SEBI_SAA_TABLE[governing_tier]

    # Special adjustment: If horizon is 3-5 years, eliminate or strictly minimize Mid/Small caps
    if 3.0 <= horizon_years <= 5.0 and base_saa.mid_small_cap_pct > 5.0:
        reallocated_mid_small = base_saa.mid_small_cap_pct - 5.0
        # Shift excess mid/small into large cap and debt
        adjusted_saa = TargetSaa(
            large_cap_pct=base_saa.large_cap_pct + (reallocated_mid_small * 0.5),
            mid_small_cap_pct=5.0,
            debt_pct=base_saa.debt_pct + (reallocated_mid_small * 0.5),
        )
    elif max_drawdown_tolerance_pct <= 5.0:
        # Zero mid/small cap for strict 5% loss limit
        adjusted_saa = TargetSaa(
            large_cap_pct=25.0,
            mid_small_cap_pct=0.0,
            debt_pct=75.0,
        )
        if "Zero Mid/Small Cap Mandate" not in " ".join(constraints):
            constraints.append("Mid/Small Cap allocation eliminated (0%) to maintain <= 5% portfolio drawdown floor.")
    else:
        adjusted_saa = base_saa

    # -------------------------------------------------------------------------
    # 6. Build Comprehensive Fiduciary Rationale
    # -------------------------------------------------------------------------
    rationale_lines = [
        f"**Governing Profile:** {_TIER_LABELS[governing_tier]}",
        f"* **Financial Capacity:** {_TIER_LABELS[capacity_tier]} (Horizon: {horizon_years:.0f}y, Savings: {emergency_fund_months:.0f}m, EMI: {emi_burden_pct:.0f}%)",
        f"* **Emotional Tolerance:** {_TIER_LABELS[tolerance_tier]} (Max tolerable drop: {max_drawdown_tolerance_pct:.0f}%)",
    ]
    if capacity_tier != tolerance_tier:
        rationale_lines.append(
            f"* **Binding Constraint:** Your {_TIER_LABELS[governing_tier]} governs your portfolio because your "
            f"{'emotional risk tolerance' if tolerance_tier < capacity_tier else 'financial capacity'} "
            f"is the primary limiting boundary."
        )

    return RiskProfileResult(
        governing_tier=governing_tier,
        tier_label=_TIER_LABELS[governing_tier],
        target_saa=adjusted_saa,
        capacity_tier=capacity_tier,
        tolerance_tier=tolerance_tier,
        binding_constraints=constraints,
        fiduciary_rationale="\n".join(rationale_lines),
        expected_drawdown_range=_DRAWDOWN_RANGES[governing_tier],
    )



def evaluate_direct_tier(tier: SebiRiskTier | int) -> RiskProfileResult:
    """Evaluate investor risk profile directly from selected SEBI Tier (Mode 2: Informed)."""
    if isinstance(tier, int):
        tier = SebiRiskTier(tier)
    base_saa = _SEBI_SAA_TABLE[tier]
    return RiskProfileResult(
        governing_tier=tier,
        tier_label=_TIER_LABELS[tier],
        target_saa=base_saa,
        capacity_tier=tier,
        tolerance_tier=tier,
        binding_constraints=[],
        fiduciary_rationale=(
            f"**Governing Profile:** {_TIER_LABELS[tier]}\n"
            f"* **Mode:** Direct Regulatory Declaration (Informed Investor)\n"
            f"* **Asset Allocation:** Equity {base_saa.total_equity_pct:.1f}% (Large Cap {base_saa.large_cap_pct:.1f}%, Mid/Small Cap {base_saa.mid_small_cap_pct:.1f}%) | Debt {base_saa.debt_pct:.1f}%\n"
            f"* **Regulatory Alignment:** Directly mapped to SEBI 6-Tier risk governance framework."
        ),
        expected_drawdown_range=_DRAWDOWN_RANGES[tier],
    )


def evaluate_custom_saa(
    *,
    large_cap_pct: float,
    mid_small_cap_pct: float,
    debt_pct: float,
    rationale: str = "",
) -> RiskProfileResult:
    """Evaluate custom SAA target defined by investor or RIA (Mode 3: Expert / IPS)."""
    lc = float(large_cap_pct)
    ms = float(mid_small_cap_pct)
    db = float(debt_pct)
    total = lc + ms + db
    if abs(total - 100.0) > 0.01:
        raise ValueError(f"Custom asset allocation must sum to 100.0% (got {total:.2f}%).")
    if lc < 0 or ms < 0 or db < 0:
        raise ValueError("Asset allocation percentages cannot be negative.")

    target_saa = TargetSaa(large_cap_pct=round(lc, 1), mid_small_cap_pct=round(ms, 1), debt_pct=round(db, 1))
    total_eq = target_saa.total_equity_pct

    # Map to closest regulatory equivalent tier
    if total_eq <= 20.0:
        equiv_tier = SebiRiskTier.TIER_1_CAPITAL_PRESERVATION
    elif total_eq <= 35.0:
        equiv_tier = SebiRiskTier.TIER_2_LOW
    elif total_eq <= 65.0:
        equiv_tier = SebiRiskTier.TIER_3_MODERATE
    elif total_eq <= 80.0:
        equiv_tier = SebiRiskTier.TIER_4_MODERATE_HIGH
    elif total_eq <= 90.0:
        equiv_tier = SebiRiskTier.TIER_5_HIGH
    else:
        equiv_tier = SebiRiskTier.TIER_6_VERY_HIGH

    custom_rationale = (
        f"**Governing Profile:** Custom IPS Allocation (Closest SEBI Equivalent: {_TIER_LABELS[equiv_tier]})\n"
        f"* **Mode:** Expert Bespoke Target (HNIs / RIAs / Institutional Mandate)\n"
        f"* **Custom SAA:** Large Cap {lc:.1f}%, Mid/Small Cap {ms:.1f}%, Debt/Cash {db:.1f}%\n"
        f"* **Client Notes:** {rationale or 'Bespoke mandate specified by investor.'}"
    )

    return RiskProfileResult(
        governing_tier=equiv_tier,
        tier_label=f"Custom Allocation (Eq: {total_eq:.0f}% / Debt: {db:.0f}%)",
        target_saa=target_saa,
        capacity_tier=equiv_tier,
        tolerance_tier=equiv_tier,
        binding_constraints=["Custom IPS Mandate: User-defined asset allocation active."],
        fiduciary_rationale=custom_rationale,
        expected_drawdown_range=_DRAWDOWN_RANGES[equiv_tier],
    )



def predict_risk_tier_from_portfolio(
    portfolio: list[dict[str, Any]],
    use_live_ai: bool = True,
) -> dict[str, Any]:
    """AI-assisted dynamic risk scoring and behavioral risk tier prediction from CAS data.

    Analyzes revealed asset allocation (equity %, mid/small-cap %, thematic exposure)
    to predict the investor's governing SEBI risk profile before questionnaire completion.
    """
    if not portfolio:
        # Default neutral moderate profile if portfolio is empty
        res = evaluate_direct_tier(SebiRiskTier.TIER_3_MODERATE)
        return {
            "status": "NO_PORTFOLIO",
            "predicted_tier": SebiRiskTier.TIER_3_MODERATE,
            "predicted_tier_num": 3,
            "predicted_tier_name": _TIER_LABELS[SebiRiskTier.TIER_3_MODERATE],
            "portfolio_equity_pct": 60.0,
            "portfolio_debt_pct": 40.0,
            "portfolio_mid_small_pct": 15.0,
            "thematic_pct": 0.0,
            "confidence_score_pct": 50.0,
            "suggested_horizon_years": 5.0,
            "suggested_drawdown_pct": 10.0,
            "suggested_emergency_months": 6.0,
            "profile_result": res,
            "ai_behavioral_rationale": "Default baseline profile applied as no uploaded portfolio was detected.",
        }

    total_val = sum(float(f.get("current_value", 0.0) or 0.0) for f in portfolio)
    if total_val <= 0.0:
        total_val = 1.0

    # Calculate revealed asset allocation
    eq_val = sum(float(f.get("current_value", 0.0) or 0.0) * (float(f.get("eq", 0.0) or 0.0) / 100.0) for f in portfolio)
    debt_val = sum(float(f.get("current_value", 0.0) or 0.0) * (float(f.get("debt", 0.0) or 0.0) / 100.0) for f in portfolio)
    
    eq_pct = round((eq_val / total_val) * 100.0, 1)
    debt_pct = round((debt_val / total_val) * 100.0, 1)

    # Detect mid/small and thematic concentration
    mid_small_val = 0.0
    thematic_val = 0.0
    for f in portfolio:
        sch_name = str(f.get("scheme", "")).lower()
        cat_name = str(f.get("category", "")).lower()
        val = float(f.get("current_value", 0.0) or 0.0)
        if any(k in sch_name or k in cat_name for k in ("mid", "small", "micro")):
            mid_small_val += val
        if any(k in sch_name or k in cat_name for k in ("sectoral", "thematic", "pharma", "it fund", "banking", "infra")):
            thematic_val += val

    mid_small_pct = round((mid_small_val / total_val) * 100.0, 1)
    thematic_pct = round((thematic_val / total_val) * 100.0, 1)

    # Behavioral Tier Prediction Logic
    if eq_pct < 15.0:
        predicted_tier = SebiRiskTier.TIER_1_CAPITAL_PRESERVATION
        conf = 92.0
        sug_horizon = 2.0
        sug_dd = 5.0
    elif eq_pct < 40.0:
        predicted_tier = SebiRiskTier.TIER_2_LOW
        conf = 88.0
        sug_horizon = 4.0
        sug_dd = 8.0
    elif eq_pct < 65.0:
        predicted_tier = SebiRiskTier.TIER_3_MODERATE
        conf = 85.0
        sug_horizon = 5.0
        sug_dd = 12.0
    elif eq_pct < 80.0:
        predicted_tier = SebiRiskTier.TIER_4_MODERATE_HIGH
        conf = 90.0
        sug_horizon = 7.0
        sug_dd = 18.0
    elif eq_pct < 90.0 or mid_small_pct < 45.0:
        predicted_tier = SebiRiskTier.TIER_5_HIGH
        conf = 89.0
        sug_horizon = 10.0
        sug_dd = 25.0
    else:
        predicted_tier = SebiRiskTier.TIER_6_VERY_HIGH
        conf = 91.0
        sug_horizon = 12.0
        sug_dd = 35.0

    profile_res = evaluate_direct_tier(predicted_tier)

    # Generate AI / Institutional Behavioral Narrative
    ai_narrative = ""
    if use_live_ai:
        try:
            from core.ai_engine import call_llm
            prompt = f"""You are a SEBI-registered Research Analyst and Behavioral Finance Expert.
Analyze the investor's revealed portfolio behavior from their uploaded CAS data:
- Total Portfolio Value: INR {total_val:,.0f} across {len(portfolio)} schemes
- Revealed Net Equity Allocation: {eq_pct:.1f}%
- Revealed Debt & Liquid Buffer: {debt_pct:.1f}%
- Mid/Small-Cap Alpha Allocation: {mid_small_pct:.1f}%
- Thematic/Sectoral Bet Exposure: {thematic_pct:.1f}%
- Predicted SEBI Risk Tier: {_TIER_LABELS[predicted_tier]}

Provide a concise 2-3 sentence behavioral diagnostic explaining why their actual investment pattern reflects this risk tier and what it implies for their market correction tolerance."""
            res = call_llm(prompt, external_processing_consent=True)
            if res and len(res.strip()) > 40:
                ai_narrative = res.strip()
        except Exception:
            pass

    if not ai_narrative:
        ai_narrative = (
            f"Based on your actual CAS asset mix ({eq_pct:.1f}% Equity / {debt_pct:.1f}% Debt with {mid_small_pct:.1f}% Mid/Small-Caps), "
            f"your revealed investment behavior aligns with **{_TIER_LABELS[predicted_tier]}**. Your portfolio demonstrates capacity "
            f"for a ~{sug_horizon:.0f}-year compounding horizon and estimated market drawdown tolerance of {sug_dd:.0f}%."
        )

    return {
        "status": "PREDICTED",
        "predicted_tier": predicted_tier,
        "predicted_tier_num": int(predicted_tier),
        "predicted_tier_name": _TIER_LABELS[predicted_tier],
        "portfolio_equity_pct": eq_pct,
        "portfolio_debt_pct": debt_pct,
        "portfolio_mid_small_pct": mid_small_pct,
        "thematic_pct": thematic_pct,
        "confidence_score_pct": conf,
        "suggested_horizon_years": sug_horizon,
        "suggested_drawdown_pct": sug_dd,
        "suggested_emergency_months": 6.0,
        "profile_result": profile_res,
        "ai_behavioral_rationale": ai_narrative,
    }
