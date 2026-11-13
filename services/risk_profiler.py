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
from pathlib import Path
import json
import math


class SebiRiskTier(IntEnum):
    """SEBI 6-Tier Regulatory Risk Classification."""
    TIER_1_CAPITAL_PRESERVATION = 1  # Low (Green)
    TIER_2_LOW = 2                   # Low to Moderate (Chartreuse)
    TIER_3_MODERATE = 3              # Moderate (Yellow)
    TIER_4_MODERATE_HIGH = 4         # Moderately High (Orange)
    TIER_5_HIGH = 5                  # High (Dark Orange)
    TIER_6_VERY_HIGH = 6             # Very High (Red)

# Tier name mapping for policy lookup
_TIER_NAME_MAP = {
    SebiRiskTier.TIER_1_CAPITAL_PRESERVATION: "low",
    SebiRiskTier.TIER_2_LOW: "low_to_moderate",
    SebiRiskTier.TIER_3_MODERATE: "moderate",
    SebiRiskTier.TIER_4_MODERATE_HIGH: "moderately_high",
    SebiRiskTier.TIER_5_HIGH: "high",
    SebiRiskTier.TIER_6_VERY_HIGH: "very_high",
}


@dataclass(frozen=True)
class TargetSaa:
    """Strategic Asset Allocation target percentages (sum to 100.0%).

    Note: flexi_multi_cap_pct is tracked separately from mid_small_cap_pct because:
    - Flexi-multi-cap funds are a distinct asset class (can hold large, mid, or small cap)
    - mid_small_cap_pct represents pure mid-cap + small-cap exposure only
    - Total equity = large_cap_pct + mid_small_cap_pct + flexi_multi_cap_pct
    - Risk limiters (max_mid_small_pct) apply only to true mid/small exposure
    """
    large_cap_pct: float
    mid_small_cap_pct: float
    debt_pct: float
    flexi_multi_cap_pct: float = 0.0

    @property
    def total_equity_pct(self) -> float:
        return self.large_cap_pct + self.mid_small_cap_pct + self.flexi_multi_cap_pct

    def as_dict(self) -> dict[str, float]:
        return {
            "large_cap_pct": round(self.large_cap_pct, 1),
            "mid_small_cap_pct": round(self.mid_small_cap_pct, 1),
            "flexi_multi_cap_pct": round(self.flexi_multi_cap_pct, 1),
            "debt_pct": round(self.debt_pct, 1),
            "total_equity_pct": round(self.total_equity_pct, 1),
        }


# Canonical SEBI SAA Policy Mapping - loaded from policy file at runtime
# No hardcoding: values come from data/policy/asset_allocation.json
_POLICY_PATH = Path(__file__).parent.parent / "data" / "policy" / "asset_allocation.json"

def _load_saa_from_policy() -> dict[SebiRiskTier, TargetSaa]:
    """Load SAA targets from the authoritative policy file.

    Raises:
        FileNotFoundError: If policy file is missing
        ValueError: If policy is malformed, incomplete, or contains invalid values
    """
    if not _POLICY_PATH.exists():
        raise FileNotFoundError(
            f"SAA policy file not found at {_POLICY_PATH}. "
            "Cannot compute asset allocation without policy."
        )

    with open(_POLICY_PATH, 'r', encoding='utf-8') as f:
        policy = json.load(f)

    if not isinstance(policy, dict):
        raise ValueError("SAA policy root must be a JSON object")
    profiles = policy.get('behavioral_risk_profiles')
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("Policy file missing 'behavioral_risk_profiles' section")

    saa_table = {}
    for tier, tier_name in _TIER_NAME_MAP.items():
        profile = profiles.get(tier_name)
        if not isinstance(profile, dict):
            raise ValueError(f"Policy missing profile for tier '{tier_name}'")

        saa_targets = profile.get('saa_targets')
        if not isinstance(saa_targets, dict) or not saa_targets:
            raise ValueError(f"Policy tier '{tier_name}' missing 'saa_targets' section")

        # Extract and validate required fields
        required_fields = ['large_cap_pct', 'mid_cap_pct', 'small_cap_pct',
                          'flexi_multi_cap_pct', 'debt_liquid_pct']
        missing_fields = [f for f in required_fields if f not in saa_targets]
        if missing_fields:
            raise ValueError(
                f"Policy tier '{tier_name}' saa_targets missing required fields: {missing_fields}"
            )

        # Validate all values are non-negative, finite numbers
        for field in required_fields:
            value = saa_targets[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"Policy tier '{tier_name}' field '{field}' must be numeric, got {type(value).__name__}"
                )
            if value < 0:
                raise ValueError(
                    f"Policy tier '{tier_name}' field '{field}' must be non-negative, got {value}"
                )
            if not math.isfinite(float(value)):  # Reject NaN and infinities
                raise ValueError(
                    f"Policy tier '{tier_name}' field '{field}' must be finite, got {value}"
                )

        # Calculate derived values - separate mid/small from flexi-multi-cap
        mid_cap = float(saa_targets['mid_cap_pct'])
        small_cap = float(saa_targets['small_cap_pct'])
        flexi_cap = float(saa_targets['flexi_multi_cap_pct'])
        mid_small_total = mid_cap + small_cap  # Only mid + small, NOT flexi

        large_cap = float(saa_targets['large_cap_pct'])
        debt_pct = float(saa_targets['debt_liquid_pct'])

        # Validate allocation totals sum to 100%
        total = large_cap + mid_small_total + flexi_cap + debt_pct
        if abs(total - 100.0) > 0.1:  # Inclusive 0.1 percentage-point tolerance
            raise ValueError(
                f"Policy tier '{tier_name}' allocations sum to {total:.1f}%, should be 100%"
            )

        saa_table[tier] = TargetSaa(
            large_cap_pct=large_cap,
            mid_small_cap_pct=mid_small_total,  # Pure mid + small cap only
            flexi_multi_cap_pct=flexi_cap,  # Separate flexi-multi-cap tracking
            debt_pct=debt_pct,
        )

    return saa_table


def _load_risk_profile_limiters() -> dict[str, dict[str, float]]:
    """Load and validate hard risk constraints from the authoritative policy."""
    with open(_POLICY_PATH, "r", encoding="utf-8") as policy_file:
        policy = json.load(policy_file)
    if not isinstance(policy, dict):
        raise ValueError("Risk policy root must be a JSON object")
    limiters = policy.get("risk_profile_limiters")
    if not isinstance(limiters, dict):
        raise ValueError("Policy missing 'risk_profile_limiters' object")

    required = {
        "drawdown_5pct": {"max_tolerated_drawdown_pct", "max_equity_pct", "max_mid_small_pct"},
        "ultra_short_horizon": {"max_horizon_years_exclusive", "max_equity_pct", "max_mid_small_pct"},
        "short_horizon": {
            "min_horizon_years", "max_horizon_years",
            "max_equity_pct", "max_mid_small_pct",
        },
    }
    validated: dict[str, dict[str, float]] = {}
    for limiter_name, fields in required.items():
        config = limiters.get(limiter_name)
        if not isinstance(config, dict):
            raise ValueError(f"Policy risk_profile_limiters.{limiter_name} must be an object")
        missing = fields.difference(config)
        if missing:
            raise ValueError(
                f"Policy risk_profile_limiters.{limiter_name} missing fields: {sorted(missing)}"
            )
        validated_config: dict[str, float] = {}
        for field_name in fields:
            value = config[field_name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"Policy risk_profile_limiters.{limiter_name}.{field_name} must be numeric"
                )
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError(
                    f"Policy risk_profile_limiters.{limiter_name}.{field_name} must be finite"
                )
            if field_name.endswith("_pct") and not 0.0 <= numeric <= 100.0:
                raise ValueError(
                    f"Policy risk_profile_limiters.{limiter_name}.{field_name} must be between 0 and 100"
                )
            validated_config[field_name] = numeric
        if limiter_name == "short_horizon":
            if validated_config["min_horizon_years"] < 0.0:
                raise ValueError("Policy short_horizon minimum cannot be negative")
            if validated_config["min_horizon_years"] >= validated_config["max_horizon_years"]:
                raise ValueError("Policy short_horizon minimum must be below its maximum")
        else:
            horizon_key = "max_horizon_years_exclusive" if limiter_name == "ultra_short_horizon" else None
            if horizon_key and validated_config[horizon_key] <= 0.0:
                raise ValueError("Policy ultra-short horizon threshold must be positive")
        if validated_config["max_mid_small_pct"] > validated_config["max_equity_pct"]:
            raise ValueError(
                f"Policy risk_profile_limiters.{limiter_name} mid/small cap cannot exceed total equity cap"
            )
        validated[limiter_name] = validated_config
    return validated


def _apply_saa_caps(
    base_saa: TargetSaa,
    *,
    max_equity_pct: float | None = None,
    max_mid_small_pct: float | None = None,
) -> TargetSaa:
    """Apply binding allocation caps by transferring excess exposure to debt.

    Note: mid_small_cap_pct and flexi_multi_cap_pct are capped independently.
    max_mid_small_pct applies only to true mid/small exposure, NOT flexi-multi-cap.
    Flexi-multi-cap funds are a distinct asset class that can hold any market cap segment.

    When total equity exceeds max_equity_pct, all equity sleeves are reduced proportionally
    to maintain the cap. This ensures flexi-multi-cap is not exempt from equity limits.
    """
    large = base_saa.large_cap_pct
    mid_small = base_saa.mid_small_cap_pct
    flexi = base_saa.flexi_multi_cap_pct

    # Apply mid/small cap limiter only to mid_small, NOT flexi
    if max_mid_small_pct is not None:
        mid_small = min(mid_small, max_mid_small_pct)

    # Apply total equity cap to all equity (large + mid_small + flexi)
    total_eq = large + mid_small + flexi
    if max_equity_pct is not None and total_eq > max_equity_pct:
        if total_eq > 0:
            # Scale all equity sleeves proportionally to meet the cap
            scale = max_equity_pct / total_eq
            large = large * scale
            mid_small = mid_small * scale
            flexi = flexi * scale
        else:
            large = mid_small = flexi = 0.0

    return TargetSaa(
        large_cap_pct=round(large, 6),
        mid_small_cap_pct=round(mid_small, 6),
        flexi_multi_cap_pct=round(flexi, 6),
        debt_pct=round(100.0 - large - mid_small - flexi, 6),
    )


_RISK_PROFILE_LIMITERS = _load_risk_profile_limiters()


# Load SAA table from policy at module import time
# Application fails fast if policy is missing/malformed
_SEBI_SAA_TABLE: dict[SebiRiskTier, TargetSaa] = _load_saa_from_policy()


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
    drawdown_limiter = _RISK_PROFILE_LIMITERS["drawdown_5pct"]
    if max_drawdown_tolerance_pct <= drawdown_limiter["max_tolerated_drawdown_pct"]:
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
    # Hard limiters determine the governing tier; allocation caps are applied
    # independently below so one limiter can never bypass another.
    if max_drawdown_tolerance_pct <= drawdown_limiter["max_tolerated_drawdown_pct"]:
        if governing_tier > SebiRiskTier.TIER_2_LOW:
            governing_tier = SebiRiskTier.TIER_2_LOW
        constraints.append(
            "Drawdown Hard Limiter: Maximum tolerated loss is 5% or less; "
            "the policy-defined equity and mid/small allocation caps apply."
        )

    short_horizon = _RISK_PROFILE_LIMITERS["short_horizon"]
    if (short_horizon["min_horizon_years"] <= horizon_years
            <= short_horizon["max_horizon_years"]
            and governing_tier >= SebiRiskTier.TIER_4_MODERATE_HIGH):
        governing_tier = SebiRiskTier.TIER_3_MODERATE
        constraints.append(
            f"Time Horizon Limiter: A {horizon_years:.0f}-year horizon cannot safely absorb "
            "cyclical mid/small-cap drawdowns. Governing tier adjusted to Moderate."
        )

    ultra_short = _RISK_PROFILE_LIMITERS["ultra_short_horizon"]
    if horizon_years < ultra_short["max_horizon_years_exclusive"]:
        governing_tier = SebiRiskTier.TIER_1_CAPITAL_PRESERVATION
        constraints.append(
            f"Capital Preservation Limiter: Goal horizon is only {horizon_years:.1f} years. "
            "The policy prohibits equity deployment for this horizon."
        )

    # -------------------------------------------------------------------------
    # 5. Determine Strategic Asset Allocation (SAA)
    # -------------------------------------------------------------------------
    base_saa = _SEBI_SAA_TABLE[governing_tier]
    applicable_caps: list[dict[str, float]] = []
    if horizon_years < ultra_short["max_horizon_years_exclusive"]:
        applicable_caps.append(ultra_short)
    elif (short_horizon["min_horizon_years"] <= horizon_years
          <= short_horizon["max_horizon_years"]):
        applicable_caps.append(short_horizon)
    if max_drawdown_tolerance_pct <= drawdown_limiter["max_tolerated_drawdown_pct"]:
        applicable_caps.append(drawdown_limiter)

    adjusted_saa = _apply_saa_caps(
        base_saa,
        max_equity_pct=min(cap["max_equity_pct"] for cap in applicable_caps)
            if applicable_caps else None,
        max_mid_small_pct=min(cap["max_mid_small_pct"] for cap in applicable_caps)
            if applicable_caps else None,
    )
    if max_drawdown_tolerance_pct <= drawdown_limiter["max_tolerated_drawdown_pct"]:
        constraints.append(
            "Mid/Small Cap allocation eliminated by the 5% drawdown policy limiter."
        )

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
            f"* **Asset Allocation:** Equity {base_saa.total_equity_pct:.1f}% (Large Cap {base_saa.large_cap_pct:.1f}%, Mid/Small Cap {base_saa.mid_small_cap_pct:.1f}%, Flexi-Multi Cap {base_saa.flexi_multi_cap_pct:.1f}%) | Debt {base_saa.debt_pct:.1f}%\n"
            f"* **Regulatory Alignment:** Directly mapped to SEBI 6-Tier risk governance framework."
        ),
        expected_drawdown_range=_DRAWDOWN_RANGES[tier],
    )


def evaluate_custom_saa(
    *,
    large_cap_pct: float,
    mid_small_cap_pct: float,
    debt_pct: float,
    flexi_multi_cap_pct: float = 0.0,
    rationale: str = "",
) -> RiskProfileResult:
    """Evaluate custom SAA target defined by investor or RIA (Mode 3: Expert / IPS)."""
    # Validate inputs: reject booleans, NaN, Infinity
    for name, val in [
        ("large_cap_pct", large_cap_pct),
        ("mid_small_cap_pct", mid_small_cap_pct),
        ("debt_pct", debt_pct),
        ("flexi_multi_cap_pct", flexi_multi_cap_pct),
    ]:
        if isinstance(val, bool):
            raise ValueError(f"{name} cannot be a boolean value")
        if not isinstance(val, (int, float)):
            raise ValueError(f"{name} must be a numeric value")
        if not math.isfinite(val):
            raise ValueError(f"{name} must be finite (no NaN or Infinity)")
        if not 0.0 <= val <= 100.0:
            raise ValueError(f"{name} must be between 0 and 100 (got {val})")

    lc = float(large_cap_pct)
    ms = float(mid_small_cap_pct)
    db = float(debt_pct)
    flexi = float(flexi_multi_cap_pct)
    total = lc + ms + flexi + db
    if abs(total - 100.0) > 0.01:
        raise ValueError(f"Custom asset allocation must sum to 100.0% (got {total:.2f}%).")
    if lc < 0 or ms < 0 or db < 0 or flexi < 0:
        raise ValueError("Asset allocation percentages cannot be negative.")

    target_saa = TargetSaa(
        large_cap_pct=round(lc, 1),
        mid_small_cap_pct=round(ms, 1),
        flexi_multi_cap_pct=round(flexi, 1),
        debt_pct=round(db, 1),
    )
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
        f"* **Custom SAA:** Large Cap {lc:.1f}%, Mid/Small Cap {ms:.1f}%, Flexi-Multi Cap {flexi:.1f}%, Debt/Cash {db:.1f}%\n"
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
    use_live_ai: bool = False,
    external_processing_consent: bool = False,
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
    if use_live_ai and external_processing_consent is True:
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
            from core.prompt_advisor import collect_sensitive_identifiers, sanitize_prompt_for_privacy
            minimized_prompt = sanitize_prompt_for_privacy(
                prompt,
                sensitive_identifiers=collect_sensitive_identifiers(portfolio),
            )
            res = call_llm(
                minimized_prompt,
                external_processing_consent=external_processing_consent,
                use_cache=False,
            )
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
