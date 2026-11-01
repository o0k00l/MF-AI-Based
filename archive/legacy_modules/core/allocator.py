# engine/allocation_builder.py
"""
Multi-decision fund selection & SIP allocation pipeline (GENERIC - any client).

Fund selection is not one decision. It is a chain of auditable decisions, each
with its own inputs, rules and gates. This module implements that chain:

  D1. Client profile validation
      Required: client_age, risk_tolerance, horizon_years, monthly_sip_budget,
      marginal_tax_rate_pct. The engine REFUSES to guess a missing profile
      (anti-fabrication): it asks the adviser instead.

  D2. Strategic Asset Allocation (SAA)
      - If the adviser declared target_allocation in config.json, it is the
        authority, but it is VALIDATED against the profile (coherence check).
      - If not declared, SAA is DERIVED from (risk_tolerance, horizon, age)
        using the documented glide-path matrix.

  D3. Portfolio gap analysis
      Look-through weights vs SAA, bucket by bucket (large / mid-small / debt).
      A1 HARD CONSTRAINT: while the portfolio breaches the mid/small horizon
      ceiling, the mid-small gap is forced to zero - no new money feeds the
      breach while the sell-down is in progress.

  D4. Bucket fund selection
      Per underweight bucket, candidates rank by MPB (confidence x (1-overlap))
      with caps: funds_per_bucket (default 2), overlap < threshold, verdict PASS
      (or accepted adviser override). Never a single-fund 100% allocation.

  D5. Budget split
      Budget splits across underweight buckets proportional to gaps, then
      across selected funds inside each bucket, enforcing max_fund_pct
      (default 20%) and AMC cap (default 30%). Sums to the budget.

  D6. Universe search (online candidates)
      When held funds cannot fill a bucket, search the AMFI catalogue
      (api.mfapi.in) by category keywords and fetch NAV-derived metrics.
      HONESTY GATE: NAV alone cannot supply AUM / TER / manager tenure /
      holdings, so candidates carry NAV status and CANNOT become
      BUY lines until the adviser verifies the fundamentals. They appear in
      the report as proposals requiring verification.

      NAV Status values (REVIEW-P2-1):
        - NAV_MISSING: No NAV data available
        - NAV_PROVISIONAL: NAV from AMFI but not verified against source
        - NAV_VERIFIED: NAV confirmed against authoritative source
        - NAV_STALE: NAV older than 180 days
        - NAV_CONFLICTING: Multiple sources report different NAVs
        - NAV_UNAVAILABLE: Source temporarily unreachable

  D7. INCONCLUSIVE / override gate
      A fund with an INCONCLUSIVE engine verdict may receive a BUY line only
      if config.json carries a signed adviser override for it
      (adviser_overrides: fund, engine_verdict, adviser_decision, rationale,
      signed_by, date). Otherwise the BUY is suppressed and a validation
      problem is recorded.

SEBI categorization references (Oct 2017 circular):
  Large Cap   >= 80% in top-100 by market cap
  Mid Cap     >= 65% in 101-250
  Small Cap   >= 65% in 251+
  Multi Cap   >= 25% each in large / mid / small
  Flexi Cap   >= 65% equity, any cap mix
  Aggressive Hybrid  65-80% equity
  Multi Asset >= 10% in each of >= 3 asset classes
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal

# ---------------------------------------------------------------------------
# D1. Client profile
# ---------------------------------------------------------------------------

RISK_TOLERANCES = ("conservative", "moderate", "aggressive")

REQUIRED_PROFILE_FIELDS: Dict[str, str] = {
    "client_age": "Client age in years (e.g. 35)",
    "risk_tolerance": "Risk tolerance: conservative | moderate | aggressive",
    "horizon_years": "Investment horizon in years (e.g. 10)",
    "monthly_sip_budget": "Monthly SIP budget in INR (e.g. 100000)",
    "marginal_tax_rate_pct": "Marginal tax rate in % (e.g. 30)",
}

_AGE_MIN, _AGE_MAX = 18, 100
_HORIZON_MIN, _HORIZON_MAX = 1, 60


def validate_profile(ips: dict) -> Tuple[bool, List[str]]:
    """Validate client profile against required fields and ranges.
    Raises ValueError if profile is invalid, or returns (True, []) when valid."""
    problems: List[str] = []
    if not isinstance(ips, dict):
        raise ValueError("Client profile must be a dictionary")

    for field, question in REQUIRED_PROFILE_FIELDS.items():
        value = ips.get(field)
        if field == "monthly_sip_budget":
            if value is None:
                problems.append(f"Missing '{field}': {question}")
            elif isinstance(value, (int, float)) and value < 0:
                problems.append(f"Invalid '{field}': monthly SIP budget cannot be negative ({value})")
            continue
        if value in (None, ""):
            problems.append(f"Missing '{field}': {question}")

    age = ips.get("client_age")
    if age not in (None, ""):
        if not isinstance(age, (int, float)) or isinstance(age, bool) or not (_AGE_MIN <= age <= _AGE_MAX):
            problems.append(f"Invalid client_age '{age}': expected {_AGE_MIN}-{_AGE_MAX}")

    rt = ips.get("risk_tolerance")
    if rt not in (None, ""):
        if str(rt).strip().lower() not in RISK_TOLERANCES:
            problems.append(f"Invalid risk_tolerance '{rt}': must be one of {', '.join(RISK_TOLERANCES)}")

    horizon = ips.get("horizon_years")
    if horizon not in (None, ""):
        if not isinstance(horizon, (int, float)) or isinstance(horizon, bool) or not (_HORIZON_MIN <= horizon <= _HORIZON_MAX):
            problems.append(f"Invalid horizon_years '{horizon}': expected {_HORIZON_MIN}-{_HORIZON_MAX}")

    if problems:
        raise ValueError("; ".join(problems))

    return (True, [])


# ---------------------------------------------------------------------------
# D2. Strategic Asset Allocation (SAA)
# ---------------------------------------------------------------------------

# Base SAA matrix: risk_tolerance -> (large, mid_small, debt) in %.
# Documented, transparent defaults. The adviser's declared target_allocation
# always wins; this matrix is only the derivation fallback (and the
# yardstick for the coherence check in validate_declared_allocation).
_SAA_BASE: Dict[str, Dict[str, float]] = {
    "conservative": {"large_cap_pct": 40.0, "mid_small_cap_pct": 10.0, "debt_global_pct": 50.0},
    "moderate":     {"large_cap_pct": 50.0, "mid_small_cap_pct": 25.0, "debt_global_pct": 25.0},
    "aggressive":   {"large_cap_pct": 50.0, "mid_small_cap_pct": 35.0, "debt_global_pct": 15.0},
}


def _horizon_equity_shift(horizon_years: float) -> float:
    """Equity sleeve shift (pp) by horizon. Short horizons need capital
    protection; very long horizons can carry more equity."""
    if horizon_years < 3:
        return -30.0
    if horizon_years < 7:
        return -10.0
    if horizon_years > 15:
        return +5.0
    return 0.0


def compute_saa(cfg_or_ips: dict) -> Dict[str, float]:
    """Strategic Asset Allocation (SAA) derivation & policy enforcement (GAP-110).
    
    1. If target_allocation is declared in config, it is the immutable authority.
    2. If not declared, SAA is derived from (risk_tolerance, horizon_years, client_age)
       using the policy matrix, bounded by horizon ceilings and age capacity.
    """
    # 1. Check for declared target_allocation
    if isinstance(cfg_or_ips, dict) and "target_allocation" in cfg_or_ips:
        target = cfg_or_ips["target_allocation"]
        if target and isinstance(target, dict):
            return {
                "large_cap_pct": float(target.get("large_cap_pct", 0.0)),
                "mid_small_cap_pct": float(target.get("mid_small_cap_pct", 0.0)),
                "debt_global_pct": float(target.get("debt_global_pct", 0.0)),
            }

    ips = cfg_or_ips.get("ips", cfg_or_ips) if isinstance(cfg_or_ips, dict) else {}
    
    risk = str(ips.get("risk_tolerance", "moderate") or "moderate").strip().lower()
    base = dict(_SAA_BASE.get(risk, _SAA_BASE["moderate"]))
    horizon = float(ips.get("horizon_years", 10) or 10)
    age = float(ips.get("client_age", 35) or 35)

    # Base allocations
    large = float(base["large_cap_pct"])
    mid_small = float(base["mid_small_cap_pct"])
    debt = float(base["debt_global_pct"])

    # Aggressive adjustment for long horizons / young age
    if risk == "aggressive":
        if horizon >= 15 and age <= 30:
            large, mid_small, debt = 50.0, 40.0, 10.0

    # Horizon Ceilings (A1 hard constraints)
    # Horizon < 3 yrs: max equity 40%, mid_small 0%
    if horizon < 3:
        mid_small = 0.0
        large = min(large, 40.0)
        debt = 100.0 - large
    elif horizon < 5:
        # Horizon 3-5 yrs: max mid_small 15%, max equity 60%
        mid_small = min(mid_small, 15.0)
        if large + mid_small > 60.0:
            large = 60.0 - mid_small
        debt = 100.0 - large - mid_small

    # Age Capacity Constraint:
    # Age >= 60: max equity 50%
    if age >= 60:
        max_eq = 50.0
        tot_eq = large + mid_small
        if tot_eq > max_eq:
            scale = max_eq / tot_eq
            large = round(large * scale, 2)
            mid_small = round(mid_small * scale, 2)
            debt = round(100.0 - large - mid_small, 2)
    elif age > 40:
        max_eq = max(100.0 - age, 30.0)
        tot_eq = large + mid_small
        if tot_eq > max_eq:
            scale = max_eq / tot_eq
            large = round(large * scale, 2)
            mid_small = round(mid_small * scale, 2)
            debt = round(100.0 - large - mid_small, 2)

    return {
        "large_cap_pct": round(large, 2),
        "mid_small_cap_pct": round(mid_small, 2),
        "debt_global_pct": round(debt, 2),
    }


derive_target_allocation = compute_saa


def validate_declared_allocation(target: dict, ips: dict) -> List[str]:
    """Coherence check of the adviser-declared SAA against the client profile.
    Warnings only - the adviser's declaration is authoritative. Returns a
    list of warning strings (empty = coherent)."""
    warnings: List[str] = []
    if not target:
        return warnings
    risk = str(ips.get("risk_tolerance", "") or "").strip().lower()
    if not risk:
        return warnings
    horizon = float(ips.get("horizon_years", 10) or 10)
    declared_ms = float(target.get("mid_small_cap_pct", 0) or 0)
    band = float(target.get("tolerance_band_pct", 5) or 5)
    ceiling_ms = declared_ms + band

    implied_max_ms = {"conservative": 15.0, "moderate": 35.0, "aggressive": 45.0}[risk]
    if horizon < 7:
        implied_max_ms = min(implied_max_ms, 20.0)
    if ceiling_ms > implied_max_ms:
        warnings.append(
            f"Declared mid/small allocation ({declared_ms:g}% + {band:g}% band = {ceiling_ms:g}% ceiling) "
            f"exceeds the {risk}-profile / {horizon:g}y-horizon convention (max ~{implied_max_ms:g}%). "
            "Adviser authority honoured; flagged for the record."
        )
    total = (float(target.get("large_cap_pct", 0) or 0)
             + float(target.get("mid_small_cap_pct", 0) or 0)
             + float(target.get("debt_global_pct", 0) or 0))
    if abs(total - 100.0) > 0.01:
        warnings.append(f"Declared allocation sums to {total:g}% (must be 100).")
    return warnings


# ---------------------------------------------------------------------------
# Valuation-Aware Tactical Asset Allocation: Reverse Fed Model (GAP-153)
# ---------------------------------------------------------------------------

def compute_reverse_fed_model(
    target_equity_pct: float,
    nifty_pe: float = 22.0,
    gsec_10y_yield: float = 7.10,
    min_equity_pct: float = 20.0,
    max_equity_pct: float = 85.0,
) -> Dict[str, Any]:
    """Logic 4.2 / GAP-153: Valuation-Aware Tactical Asset Allocation (The Reverse Fed Model).
    Calculates Earnings Yield = 100.0 / nifty_pe, Yield Gap = gsec_10y_yield - Earnings Yield.
    Tactical Allocation Bands:
      - Yield Gap > 2.0% or nifty_pe > 25.0: Overvaluation -> Equity trimmed by -5% to -10%
      - Yield Gap < 0.5% or nifty_pe < 18.0: Undervaluation -> Equity boosted by +5% to +10%
      - Fair Value: target equity maintained
    """
    if nifty_pe <= 0:
        ep_ratio = 0.0
    else:
        ep_ratio = round(100.0 / nifty_pe, 2)
    yield_gap = round(gsec_10y_yield - ep_ratio, 2)

    if yield_gap > 2.0 or nifty_pe > 25.0:
        regime = "OVERVALUED"
        tilt = -10.0 if (yield_gap > 2.5 or nifty_pe > 26.0) else -5.0
        tactical_equity = max(min_equity_pct, target_equity_pct + tilt)
        notes = (
            f"Reverse Fed Model indicates equity overvaluation (PE={nifty_pe:.1f}, "
            f"Yield Gap={yield_gap:.2f}%). Tactical equity trimmed by {abs(tilt):.1f}%."
        )
    elif yield_gap < 0.5 or nifty_pe < 18.0:
        regime = "UNDERVALUED"
        tilt = +10.0 if (yield_gap < 0.0 or nifty_pe < 16.0) else +5.0
        tactical_equity = min(max_equity_pct, target_equity_pct + tilt)
        notes = (
            f"Reverse Fed Model indicates equity undervaluation (PE={nifty_pe:.1f}, "
            f"Yield Gap={yield_gap:.2f}%). Tactical equity boosted by +{tilt:.1f}%."
        )
    else:
        regime = "FAIR_VALUE"
        tilt = 0.0
        tactical_equity = target_equity_pct
        notes = (
            f"Reverse Fed Model indicates fair valuation (PE={nifty_pe:.1f}, "
            f"Yield Gap={yield_gap:.2f}%). SAA targets maintained."
        )

    return {
        "nifty_pe": nifty_pe,
        "gsec_10y_yield": gsec_10y_yield,
        "earnings_yield_pct": ep_ratio,
        "yield_gap_pct": yield_gap,
        "valuation_regime": regime,
        "equity_tilt_pct": tilt,
        "target_equity_pct": target_equity_pct,
        "tactical_equity_pct": round(tactical_equity, 2),
        "notes": notes,
    }


def apply_reverse_fed_model(
    target_allocation: Dict[str, float],
    nifty_pe: float = 22.0,
    gsec_10y_yield: float = 7.10,
    min_equity_pct: float = 20.0,
    max_equity_pct: float = 85.0,
) -> Tuple[Dict[str, float], Dict[str, Any]]:
    """Apply the Reverse Fed Model tilt to a 3-way SAA dictionary
    (large_cap_pct, mid_small_cap_pct, debt_global_pct).
    Returns (tactical_allocation, fed_model_metrics).
    """
    large = target_allocation.get("large_cap_pct", 50.0)
    mid_small = target_allocation.get("mid_small_cap_pct", 25.0)
    debt = target_allocation.get("debt_global_pct", 25.0)
    current_equity = large + mid_small

    fed = compute_reverse_fed_model(
        target_equity_pct=current_equity,
        nifty_pe=nifty_pe,
        gsec_10y_yield=gsec_10y_yield,
        min_equity_pct=min_equity_pct,
        max_equity_pct=max_equity_pct,
    )
    tilt = fed["equity_tilt_pct"]
    if tilt == 0.0 or current_equity <= 0:
        return dict(target_allocation), fed

    tactical_equity = fed["tactical_equity_pct"]
    tactical_debt = round(100.0 - tactical_equity, 2)

    # In overvalued regimes, cap mid/small at 20% and steer towards large cap / debt
    if fed["valuation_regime"] == "OVERVALUED":
        tactical_mid_small = min(mid_small, 20.0)
        tactical_large = round(tactical_equity - tactical_mid_small, 2)
    elif fed["valuation_regime"] == "UNDERVALUED":
        # In undervalued regimes, mid/small can absorb the boost up to A1 ceiling
        boost = tactical_equity - current_equity
        tactical_mid_small = round(mid_small + boost * 0.5, 2)
        tactical_large = round(tactical_equity - tactical_mid_small, 2)
    else:
        scale = tactical_equity / current_equity
        tactical_large = round(large * scale, 2)
        tactical_mid_small = round(tactical_equity - tactical_large, 2)

    adj_alloc = {
        "large_cap_pct": tactical_large,
        "mid_small_cap_pct": tactical_mid_small,
        "debt_global_pct": tactical_debt,
    }
    return adj_alloc, fed



# ---------------------------------------------------------------------------
# D3. Portfolio gap analysis (with A1 enforcement)
# ---------------------------------------------------------------------------

def compute_bucket_gaps(
    current_weights: Dict[str, float],
    target: dict,
    a1_breached: bool = False,
) -> Tuple[Dict[str, float], List[str]]:
    """Gap per bucket = target - current (positive = underweight).
    
    GAP-116 (tax_steering): Direct fresh SIP capital into underweighted buckets
    to naturally restore asset allocation balance without triggering taxable sell events.
    A1 enforcement: while the portfolio breaches the mid/small horizon
    ceiling, the mid_small gap is forced to 0 (no new money into the breach)."""
    gaps: Dict[str, float] = {
        "large": float(target.get("large_cap_pct", 0) or 0) - float(current_weights.get("large_cap_pct", 0) or 0),
        "mid_small": float(target.get("mid_small_cap_pct", 0) or 0) - float(current_weights.get("mid_small_cap_pct", 0) or 0),
        "debt": float(target.get("debt_global_pct", 0) or 0) - float(current_weights.get("debt_global_pct", 0) or 0),
    }
    notes: List[str] = []
    if a1_breached and gaps["mid_small"] > 0:
        notes.append(
            "A1 ceiling breached: mid/small gap suppressed to 0 - the portfolio is ALREADY "
            "above its horizon ceiling; new money must not feed the breach while the "
            "sell-down is in progress."
        )
        gaps["mid_small"] = 0.0
    gaps = {k: max(v, 0.0) for k, v in gaps.items()}
    return gaps, notes



# ---------------------------------------------------------------------------
# D4/D5. Bucket fund selection and budget split
# ---------------------------------------------------------------------------

def decompose_hybrid_fund(metrics: dict) -> dict[str, float]:
    """
    Decompose Hybrid & Balanced Advantage Fund into look-through components (GAP-222).
    Standard SEBI asset allocation:
    - BAF / Dynamic Asset: ~65% equity (45% Large, 15% Mid, 5% Small) + 35% Debt
    - Arbitrage: ~65% equity + 35% Debt
    - Multi-Asset: ~40% Large, 15% Mid, 5% Small, 25% Debt
    """
    large = float(metrics.get("portfolio_large_cap_pct") or 0.0)
    mid = float(metrics.get("portfolio_mid_cap_pct") or 0.0)
    small = float(metrics.get("portfolio_small_cap_pct") or 0.0)
    debt = float(metrics.get("portfolio_debt_pct") or 0.0)
    
    if large == 0.0 and debt == 0.0:
        cat = str(metrics.get("category", "")).lower()
        if any(kw in cat for kw in ["balanced advantage", "dynamic asset", "baf"]):
            return {"large": 45.0, "mid": 15.0, "small": 5.0, "debt": 35.0}
        elif any(kw in cat for kw in ["arbitrage"]):
            return {"large": 65.0, "mid": 0.0, "small": 0.0, "debt": 35.0}
        elif any(kw in cat for kw in ["multi-asset", "multi asset"]):
            return {"large": 40.0, "mid": 15.0, "small": 5.0, "debt": 25.0}
        elif any(kw in cat for kw in ["conservative hybrid", "debt hybrid"]):
            return {"large": 20.0, "mid": 5.0, "small": 0.0, "debt": 75.0}
        elif any(kw in cat for kw in ["aggressive hybrid", "equity hybrid"]):
            return {"large": 50.0, "mid": 20.0, "small": 5.0, "debt": 25.0}

    return {"large": large, "mid": mid, "small": small, "debt": debt}


def classify_bucket(metrics: dict) -> Tuple[str, str]:
    """Classify a fund into a bucket based on its portfolio composition.
    
    Returns (bucket_key, target_class) where bucket_key is one of:
    'large', 'mid_small', 'debt'
    
    Logic:
    - If debt exposure > 50%: debt bucket
    - If hybrid/arbitrage/multi-asset: decompose via look-through and classify
    - If mid+small exposure > large exposure: mid_small bucket
    - Otherwise: large bucket
    """
    # Check for debt-heavy funds first
    debt_pct = float(metrics.get('portfolio_debt_pct', 0) or 0)
    if debt_pct > 50.0:
        return 'debt', 'Debt'
    
    # GAP-DEEP-07 FIX: Check for Hybrid/Arbitrage/Multi-Asset funds first.
    # These have ~35% debt + ~65% hedged equity and must NOT be classified
    # as Large Cap (which would direct SIP into zero-volatility assets).
    cat_name = str(metrics.get('category', '')).lower()
    if any(kw in cat_name for kw in ['arbitrage', 'hybrid', 'multi-asset', 'balanced advantage', 'dynamic asset']):
        # GAP-248 FIX: Decompose hybrid funds via look-through to determine actual allocation
        decomposed = decompose_hybrid_fund(metrics)
        # Use decomposed weights to classify
        large_pct = decomposed.get('large', 0.0)
        mid_pct = decomposed.get('mid', 0.0)
        small_pct = decomposed.get('small', 0.0)
        debt_pct_comp = decomposed.get('debt', 0.0)
        
        # Check if debt dominates after decomposition
        if debt_pct_comp > 50.0:
            return 'debt', 'Debt'
        
        # Determine equity composition
        ms_total = mid_pct + small_pct
        if ms_total > large_pct:
            return 'mid_small', 'Mid/Small Cap'
        else:
            return 'large', 'Large Cap'
    
    # Check equity composition
    large_pct = float(metrics.get('portfolio_large_cap_pct', 0) or 0)
    mid_pct = float(metrics.get('portfolio_mid_cap_pct', 0) or 0)
    small_pct = float(metrics.get('portfolio_small_cap_pct', 0) or 0)
    
    ms_total = mid_pct + small_pct
    
    if ms_total > large_pct:
        return 'mid_small', 'Mid/Small Cap'
    else:
        return 'large', 'Large Cap'

def select_funds_per_bucket(
    bucket: str,
    candidates: List[dict],
    funds_per_bucket: int = 2,
) -> List[dict]:
    """Select top funds for a bucket.

    Each candidate dict must carry:
      fid, mpb (score), verdict, overlap_pct, amc (optional)
    Eligibility: verdict contains PASS (or carries an accepted adviser
    override) and overlap below threshold. Ranked by MPB, capped at
    funds_per_bucket (AMC-diversity preferred: second pick from a different
    AMC when available).
    """
    def is_eligible(c):
        # Basic eligibility
        if c.get("bucket") != bucket:
            return False
        # FIX #1: Phantom Fund SIP Bug - Skip empty/unresolved fund identifiers
        fid = str(c.get("fid", "")).strip()
        if not fid or fid == "-" or fid == "N/A":
            return False
        if "PASS" not in str(c.get("verdict", "")):
            return False
        if float(c.get("overlap_pct", 0) or 0) >= float(c.get("overlap_threshold_pct", 40)):
            return False
        
        # GAP-SEBI-03: AMFI Liquidity Stress Test Gate
        # For Mid/Small Cap categories, disqualify if stress_test_days_50 > 15
        category = str(c.get("category", "")).lower()
        is_mid_small = "mid" in category or "small" in category
        stress_days = c.get("stress_test_days_50")
        if is_mid_small and stress_days is not None:
            try:
                if float(stress_days) > 15:
                    return False
            except (ValueError, TypeError):
                pass  # Invalid data, allow through
        
        return True
    
    eligible = [c for c in candidates if is_eligible(c)]
    eligible.sort(key=lambda c: (-float(c.get("mpb", 0) or 0), str(c.get("fid"))))
    picked: List[dict] = []
    amcs_seen: set = set()
    # First pass: prefer AMC diversity
    for c in eligible:
        if len(picked) >= funds_per_bucket:
            break
        amc = str(c.get("amc") or "").strip().lower()
        if amc and amc in amcs_seen:
            continue
        picked.append(c)
        if amc:
            amcs_seen.add(amc)
    # Second pass: fill remaining slots ignoring AMC diversity
    for c in eligible:
        if len(picked) >= funds_per_bucket:
            break
        if c not in picked:
            picked.append(c)
    return picked


def split_budget(
    budget: float,
    bucket_funds: Dict[str, List[dict]],
    gaps: Dict[str, float],
    max_fund_pct: float = 20.0,
    amc_cap_pct: float = 30.0,
    target_weights: Optional[Dict[str, float]] = None,
) -> Tuple[Dict[str, float], List[str]]:
    """Split the SIP budget across buckets proportional to positive gaps,
    then across the selected funds inside each bucket (equal split inside a
    bucket - MPB already chose WHICH funds; amount inside a bucket follows
    the simple core-satellite convention), enforcing:
      - max_fund_pct of the total budget per fund
      - amc_cap_pct of the total budget per AMC
    Returns (allocation {fid: amount}, notes).
    When gaps are zero or negative (portfolio balanced), allocates
    proportionally to target SAA weights when target_weights is provided."""
    notes: List[str] = []
    positive_gaps = {b: g for b, g in gaps.items() if g > 0.0 and bucket_funds.get(b)}
    total_gap = sum(positive_gaps.values())
    if budget <= 0:
        return {}, notes

    if total_gap <= 0:
        # GAP-143: When portfolio is balanced (total_gap <= 0), allocate
        # budget proportionally to target SAA weights if available
        if target_weights and bucket_funds:
            # Allocate proportionally to target weights
            total_target = sum(target_weights.get(b, 0.0) for b in bucket_funds if bucket_funds[b])
            if total_target > 0:
                allocation: Dict[str, float] = {}
                amc_totals: Dict[str, float] = {}
                max_fund_amt = budget * max_fund_pct / 100.0
                amc_cap_amt = budget * amc_cap_pct / 100.0

                for bucket, funds in bucket_funds.items():
                    if not funds:
                        continue
                    # Allocate: B_i = B * T_i (case 2 from ENGINE_LOGIC_SPECIFICATION 5.3)
                    bucket_target = target_weights.get(bucket, 0.0)
                    bucket_amt = budget * (bucket_target / total_target)
                    per_fund = bucket_amt / len(funds)
                    for f in funds:
                        amt = min(per_fund, max_fund_amt)
                        allocation[f["fid"]] = allocation.get(f["fid"], 0.0) + amt
                        amc = str(f.get("amc") or "").strip().lower()
                        if amc:
                            amc_totals[amc] = amc_totals.get(amc, 0.0) + amt

                # AMC cap enforcement
                for amc, total in list(amc_totals.items()):
                    if total > amc_cap_amt:
                        over = total - amc_cap_amt
                        contributors = [f for funds in bucket_funds.values() for f in funds
                                        if str(f.get("amc") or "").strip().lower() == amc]
                        for f in contributors:
                            fid = f["fid"]
                            if fid in allocation and over > 0:
                                cut = min(allocation[fid], over)
                                allocation[fid] -= cut
                                over -= cut
                        notes.append(f"AMC cap ({amc_cap_pct:g}%) enforced for '{amc}' family.")

                # GAP-100: Redistribute surplus respecting BOTH per-fund cap AND AMC concentration cap
                surplus = budget - sum(allocation.values())
                if surplus > 0.01:
                    fid_to_amc = {f["fid"]: str(f.get("amc") or "").strip().lower() for funds in bucket_funds.values() for f in funds}
                    room = {}
                    for fid, amt in allocation.items():
                        f_room = max(0.0, max_fund_amt - amt)
                        amc = fid_to_amc.get(fid, "")
                        amc_room = max(0.0, amc_cap_amt - amc_totals.get(amc, 0.0)) if amc else f_room
                        eff_room = min(f_room, amc_room)
                        if eff_room > 0.01:
                            room[fid] = eff_room

                    room_total = sum(room.values())
                    if room_total > 0:
                        for fid, r in room.items():
                            added = min(r, surplus * (r / room_total))
                            allocation[fid] += added
                            amc = fid_to_amc.get(fid, "")
                            if amc:
                                amc_totals[amc] = amc_totals.get(amc, 0.0) + added
                    else:
                        notes.append(f"Surplus Rs {surplus:,.0f} could not be redeployed without breaching caps; reduce caps or add funds_per_bucket.")
                for fid in allocation:
                    allocation[fid] = round(allocation[fid], 2)
                return allocation, notes
        # Backward compatibility: return empty dict when target_weights not provided
        return {}, notes

    allocation: Dict[str, float] = {}
    amc_totals: Dict[str, float] = {}
    max_fund_amt = budget * max_fund_pct / 100.0
    amc_cap_amt = budget * amc_cap_pct / 100.0

    for bucket, funds in bucket_funds.items():
        if not funds:
            continue
        bucket_amt = budget * (max(0.0, gaps.get(bucket, 0.0)) / total_gap)
        per_fund = bucket_amt / len(funds)
        for f in funds:
            amt = min(per_fund, max_fund_amt)
            allocation[f["fid"]] = allocation.get(f["fid"], 0.0) + amt
            amc = str(f.get("amc") or "").strip().lower()
            if amc:
                amc_totals[amc] = amc_totals.get(amc, 0.0) + amt

    # AMC cap enforcement
    for amc, total in list(amc_totals.items()):
        if total > amc_cap_amt:
            over = total - amc_cap_amt
            contributors = [f for funds in bucket_funds.values() for f in funds
                            if str(f.get("amc") or "").strip().lower() == amc]
            for f in contributors:
                fid = f["fid"]
                if fid in allocation and over > 0:
                    cut = min(allocation[fid], over)
                    allocation[fid] -= cut
                    over -= cut
            notes.append(f"AMC cap ({amc_cap_pct:g}%) enforced for '{amc}' family.")

    # GAP-100: Redistribute surplus respecting BOTH per-fund cap AND AMC concentration cap
    surplus = budget - sum(allocation.values())
    if surplus > 0.01:
        fid_to_amc = {f["fid"]: str(f.get("amc") or "").strip().lower() for funds in bucket_funds.values() for f in funds}
        room = {}
        for fid, amt in allocation.items():
            f_room = max(0.0, max_fund_amt - amt)
            amc = fid_to_amc.get(fid, "")
            amc_room = max(0.0, amc_cap_amt - amc_totals.get(amc, 0.0)) if amc else f_room
            eff_room = min(f_room, amc_room)
            if eff_room > 0.01:
                room[fid] = eff_room

        room_total = sum(room.values())
        if room_total > 0:
            for fid, r in room.items():
                added = min(r, surplus * (r / room_total))
                allocation[fid] += added
                amc = fid_to_amc.get(fid, "")
                if amc:
                    amc_totals[amc] = amc_totals.get(amc, 0.0) + added
        else:
            notes.append(f"UNALLOCATED budget: ₹{surplus:,.2f} could not be redeployed without breaching caps; reduce caps or add funds_per_bucket.")
    for fid in allocation:
        allocation[fid] = round(allocation[fid], 2)
    return allocation, notes


# ---------------------------------------------------------------------------
# D6. Universe search (online candidates)
# ---------------------------------------------------------------------------

# Category keyword probes per bucket. The catalogue is scanned for Direct-Growth
# variants whose name contains the probe. Proposals are NAV_PROVISIONAL: NAV
# metrics are real and sourced from api.mfapi.in; AUM/TER/manager/holdings are
# MISSING until the adviser verifies the fundamentals (human evidence overlay). They are
# report proposals, never BUY lines.
UNIVERSE_PROBES: Dict[str, List[str]] = {
    "large": ["Nifty 50 Index Fund", "Large Cap Fund"],
    "mid_small": ["Mid Cap Fund", "Nifty Midcap 150", "Small Cap Fund"],
    "debt": ["Liquid Fund", "Short Duration Fund", "Corporate Bond Fund"],
}


def search_universe(
    bucket: str,
    catalogue: List[dict],
    exclude_names: Optional[set] = None,
    max_results: int = 3,
    held_amc_concentration: Optional[Dict[str, float]] = None,
) -> List[dict]:
    """Search the AMFI catalogue (mfapi.in) for Direct-Growth schemes in the
    bucket's category. Returns proposals:
      {name, code, bucket, bucket, status: 'NAV_PROVISIONAL', missing: [...]}
    Deduplicated by AMC family so the proposal list is AMC-diverse.

    GAP-ENG-08 FIX: `held_amc_concentration` maps AMC name -> current portfolio
    weight %. AMCs already >= 30% of the portfolio are skipped to respect the
    AMC concentration ceiling."""
    probes = UNIVERSE_PROBES.get(bucket, [])
    exclude = {str(n).strip().lower() for n in (exclude_names or set())}
    # GAP-ENG-08: Build set of over-concentrated AMCs to skip
    over_concentrated_amcs = set()
    if held_amc_concentration:
        for amc, weight in held_amc_concentration.items():
            if weight >= 30.0:
                over_concentrated_amcs.add(str(amc).strip().lower())
    results: List[dict] = []
    seen_amc: set = set()

    def _amc_of(name: str) -> str:
        # AMC family heuristic: leading words before the category probe
        low = name.lower()
        for probe in probes:
            idx = low.find(probe.lower())
            if idx > 0:
                return name[:idx].strip(" -").strip().lower()
        return " ".join(name.split()[:2]).lower()

    for probe in probes:
        matches = []
        for item in catalogue:
            name = str(item.get("name") or item.get("schemeName") or "")
            code = str(item.get("code") or item.get("schemeCode") or "")
            if not name or not code:
                continue
            low = name.lower()
            if probe.lower() not in low:
                continue
            if "direct" not in low or "growth" not in low:
                continue
            if any(k in low for k in ("idcw", "dividend", "regular")):
                continue
            if name.strip().lower() in exclude:
                continue
            matches.append((name, code))
            if len(matches) >= 50:
                break
        for name, code in matches:
            amc = _amc_of(name)
            # GAP-ENG-08: Skip AMCs that would breach the 30% concentration ceiling
            if amc in over_concentrated_amcs:
                continue
            if amc in seen_amc:
                continue
            # FIX #1: Phantom Fund SIP Bug - Skip empty/unresolved fund identifiers
            if not name or name.strip() == "-" or name.strip() == "N/A" or not code or code.strip() == "-":
                continue
            seen_amc.add(amc)
            results.append({
                "name": name,
                "code": code,
                "bucket": bucket,
                "amc": amc,
                "status": "NAV_PROVISIONAL",
                "missing": ["aum_cr", "ter_direct_pct", "fund_manager_tenure_years",
                            "holdings", "category", "sector"],
            })
            if len(results) >= max_results:
                return results
    return results


# ---------------------------------------------------------------------------
# D7. Adviser override gate
# ---------------------------------------------------------------------------

def has_signed_override(cfg: dict, fund_name: str) -> Optional[dict]:
    """Look up a signed adviser override in config.adviser_overrides for the
    given fund name (case-insensitive containment match). Returns the override
    dict or None. An override must carry adviser_decision BUY + rationale +
    signed_by + date to be valid."""
    overrides = cfg.get("adviser_overrides") or []
    needle = str(fund_name).strip().lower()
    for ov in overrides:
        if not isinstance(ov, dict):
            continue
        target = str(ov.get("fund") or ov.get("fund_id") or "").strip().lower()
        if not target or (needle not in target and target not in needle):
            continue
        if str(ov.get("adviser_decision", "")).strip().upper() != "BUY":
            continue
        if not ov.get("rationale") or not ov.get("signed_by") or not ov.get("date"):
            return None  # present but not properly signed
        return ov
    return None
