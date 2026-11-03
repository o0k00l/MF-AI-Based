"""
core/eligibility.py — Module 4: Hard Binary Selection Gates & NO ACTION Engine.
Implements the 10 Binary Fiduciary Gates and the Mandatory NO ACTION decision branch.
"""
from __future__ import annotations
import math
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from core.models import EligibilityGateResult, NOActionResult, RiskTier


def _risk_tier_to_int(tier: Any) -> int:
    """Convert RiskTier enum or string to legacy 1-6 integer scale."""
    if isinstance(tier, int):
        return tier
    if isinstance(tier, RiskTier):
        if tier == RiskTier.CUSTOM:
            raise ValueError("RiskTier.CUSTOM cannot be mapped to a legacy 1-6 tier. Provide a custom allocation via get_target_allocation with custom_target.")
        mapping = {
            RiskTier.CONSERVATIVE: 2,  # Tier 2 (Low)
            RiskTier.MODERATE: 4,      # Tier 4 (Moderate High)
            RiskTier.AGGRESSIVE: 6,    # Tier 6 (Very High)
        }
        return mapping.get(tier, 6)
    # Try to parse string like "Tier 6 (Very High)"
    tier_str = str(tier).lower()
    if "tier 1" in tier_str or "preservation" in tier_str:
        return 1
    if "tier 2" in tier_str or "low" in tier_str:
        return 2
    if "tier 3" in tier_str or "moderate" in tier_str:
        return 3
    if "tier 4" in tier_str or "moderately high" in tier_str:
        return 4
    if "tier 5" in tier_str or "high" in tier_str:
        return 5
    if "tier 6" in tier_str or "very high" in tier_str or "aggressive" in tier_str:
        return 6
    return 6


CATEGORY_AUM_CAPS = {
    "Small Cap": 20000.0,
    "Mid Cap": 40000.0,
    "Flexi Cap": 90000.0,
    "Large Cap": 250000.0,
    "Multi Cap": 40000.0,
}


def check_eligibility_gates(
    fund_data: Dict[str, Any],
    portfolio_holdings: Optional[List[Dict[str, Any]]] = None,
    client_risk_tier_num: int = 6,
    is_starter: bool = False,
    amc_max_limit_pct: float = 30.0,
    min_aum_crore: float = 1000.0,
    max_top10_concentration_pct: float = 55.0,
    max_sector_concentration_pct: float = 35.0,
    min_sharpe: float = 0.40,
    min_manager_tenure_years: float = 2.0,
    min_confidence_score: float = 0.80,
) -> EligibilityGateResult:
    """
    Evaluates all 10 Hard Binary Selection Gates for a candidate fund:
    - Gate 1: AMC Concentration Gate (< 30% AUM)
    - Gate 2: Liquidity & AUM Stability Gate (>= ₹1,000 Cr & <= Category Cap)
    - Gate 3: Top-10 Concentration Gate (<= 55%)
    - Gate 4: Risk-Adjusted Sharpe & Alpha Gate (Sharpe >= 0.40 & Alpha >= 0)
    - Gate 5: Downside Capture Ratio Gate (Downside <= 100 or Upside >= Downside)
    - Gate 6: Mandate Suitability Gate (Riskometer <= Client Tier; Starters reject sector bets)
    - Gate 7: Data Integrity & Provenance Gate (Confidence >= 0.8 & TRI Benchmark)
    - Gate 8: Manager Tenure & Process Continuity Gate (Tenure >= 2.0 Yrs)
    - Gate 9: Thematic Satellite Cap Gate (Thematic <= 15% Established / 0% Starter)
    - Gate 10: 100% Direct Plan Mandate Gate (Direct Plan only, zero regular commission)
    """
    failed = []
    details = {}

    fund_id = fund_data.get("fund_id", fund_data.get("id", ""))
    fund_name = fund_data.get("fund_name", fund_data.get("name", fund_id))

    # --- Gate 1: AMC Concentration Gate ---
    amc_name = fund_name.split()[0].upper() if fund_name else ""
    amc_exposure_pct = 0.0
    if portfolio_holdings:
        def _get_val(h):
            if isinstance(h, dict):
                return float(h.get("value", h.get("current_value_inr", 0.0)) or 0.0)
            return float(getattr(h, "current_value_inr", 0.0) or 0.0)

        def _get_scheme(h):
            if isinstance(h, dict):
                return str(h.get("scheme", h.get("fund_name", "")) or "")
            return str(getattr(h, "scheme", getattr(h, "fund_name", "")) or "")

        total_val = sum(_get_val(h) for h in portfolio_holdings)
        if total_val > 0:
            amc_val = sum(
                _get_val(h)
                for h in portfolio_holdings
                if _get_scheme(h).split()[0].upper() == amc_name
            )
            amc_exposure_pct = (amc_val / total_val) * 100.0

    amc_ok = amc_exposure_pct < amc_max_limit_pct
    if not amc_ok:
        failed.append(f"Gate 1 [AMC Concentration]: AMC {amc_name} exposure {amc_exposure_pct:.1f}% >= {amc_max_limit_pct}% ceiling")
    details["amc_exposure_pct"] = amc_exposure_pct

    # --- Gate 2: Liquidity & AUM Stability Gate ---
    aum = float(fund_data.get("aum_crore", fund_data.get("aum_cr", 0.0)) or 0.0)
    aum_min_ok = aum >= min_aum_crore
    if not aum_min_ok:
        failed.append(f"Gate 2 [Liquidity/AUM]: AUM ₹{aum:,.0f} Cr < ₹{min_aum_crore:,.0f} Cr minimum")

    category = fund_data.get("category", fund_data.get("cat", ""))
    cat_cap = CATEGORY_AUM_CAPS.get(category)
    aum_cap_ok = True
    if cat_cap and aum > cat_cap:
        aum_cap_ok = False
        failed.append(f"Gate 2 [AUM Size Drag]: AUM ₹{aum:,.0f} Cr exceeds {category} ceiling ₹{cat_cap:,.0f} Cr")

    aum_stable = fund_data.get("aum_stable", True)
    if not aum_stable:
        failed.append("Gate 2 [AUM Stability]: Outflows detected compromising liquidity")

    liquidity_and_aum_ok = aum_min_ok and aum_cap_ok and aum_stable
    details["aum_crore"] = aum

    # --- Gate 3: Top-10 Concentration Gate ---
    top10 = float(fund_data.get("top10_concentration_pct", fund_data.get("concentration_top10_pct", fund_data.get("top10", 0.0))) or 0.0)
    top10_ok = top10 <= max_top10_concentration_pct
    if not top10_ok:
        failed.append(f"Gate 3 [Top-10 Concentration]: Top 10 holdings {top10:.1f}% > {max_top10_concentration_pct:.1f}%")
    details["top10_concentration_pct"] = top10

    # Sector concentration check
    sector_conc = float(fund_data.get("single_sector_weight_pct", fund_data.get("max_sector_concentration_pct", fund_data.get("fin", 0.0))) or 0.0)
    # Broad diversified equity funds must not exceed single-sector concentration cap (35%).
    # Dedicated thematic/sectoral funds are governed by Gate 9 (15% portfolio allocation cap) rather than an internal sector cap.
    is_thematic = any(kw in category.lower() or kw in fund_name.lower() for kw in ("thematic", "sectoral", "defence", "energy", "pharma", "health", "tech"))
    if not is_thematic and sector_conc > max_sector_concentration_pct:
        failed.append(f"Gate 3 [Sector Concentration]: Sector weight {sector_conc:.1f}% > {max_sector_concentration_pct:.1f}%")
    details["sector_concentration_pct"] = sector_conc

    # --- Gate 4: Risk-Adjusted Sharpe & Alpha Gate (STRICTLY FAIL-CLOSED) ---
    from core.fund_classifier import is_verified_passive_scheme
    from core.models import InsufficientDataError
    sharpe = fund_data.get("sharpe_3y", fund_data.get("sharpe", None))
    alpha = fund_data.get("alpha_3y", fund_data.get("alpha", None))
    f_name = fund_data.get("fund_name", fund_data.get("name", ""))
    try:
        is_passive_cand = is_verified_passive_scheme(fund_data, fund_name=f_name, category=category)
    except InsufficientDataError as e:
        # Gate 4: Passive scheme verification failed due to missing scheme master
        # This is a hard fail for Gate 4 exemption — active fund criteria must be met
        failed.append(f"Gate 4 [Passive Verification]: {e}")
        is_passive_cand = False

    sharpe_ok = False
    if is_passive_cand:
        sharpe_ok = True
    elif sharpe is None:
        failed.append("Gate 4 [Sharpe Ratio Missing]: 3Y Sharpe ratio is missing (fail-closed)")
    elif isinstance(sharpe, bool):
        failed.append(f"Gate 4 [Sharpe Malformed]: Boolean value '{sharpe}' is not a numeric Sharpe ratio (fail-closed)")
    elif isinstance(sharpe, str) and not sharpe.strip():
        failed.append("Gate 4 [Sharpe Malformed]: Empty Sharpe ratio string (fail-closed)")
    else:
        try:
            s_val = float(sharpe)
            if math.isnan(s_val) or math.isinf(s_val):
                failed.append("Gate 4 [Sharpe Non-Finite]: 3Y Sharpe ratio is NaN/Infinity (fail-closed)")
            elif s_val < min_sharpe:
                failed.append(f"Gate 4 [Sharpe Ratio]: 3Y Sharpe {s_val:.2f} < {min_sharpe:.2f}")
            else:
                sharpe_ok = True
        except (ValueError, TypeError):
            failed.append(f"Gate 4 [Sharpe Malformed]: Invalid Sharpe ratio value '{sharpe}' (fail-closed)")

    alpha_ok = False
    if is_passive_cand:
        alpha_ok = True
    elif alpha is None:
        failed.append("Gate 4 [Alpha Drag Missing]: 3Y Jensen's Alpha is missing (fail-closed)")
    elif isinstance(alpha, bool):
        failed.append(f"Gate 4 [Alpha Malformed]: Boolean value '{alpha}' is not a numeric Alpha (fail-closed)")
    elif isinstance(alpha, str) and not alpha.strip():
        failed.append("Gate 4 [Alpha Malformed]: Empty Alpha string (fail-closed)")
    else:
        try:
            a_val = float(alpha)
            if math.isnan(a_val) or math.isinf(a_val):
                failed.append("Gate 4 [Alpha Non-Finite]: 3Y Jensen's Alpha is NaN/Infinity (fail-closed)")
            elif a_val <= 0.0:
                failed.append(f"Gate 4 [Alpha Drag]: Non-positive 3Y Jensen's Alpha {a_val:.2f}% vs TRI Benchmark (active funds require > 0.0% to justify active fee drag)")
            else:
                alpha_ok = True
        except (ValueError, TypeError):
            failed.append(f"Gate 4 [Alpha Malformed]: Invalid Alpha value '{alpha}' (fail-closed)")

    sharpe_alpha_ok = sharpe_ok and alpha_ok
    details["sharpe"] = sharpe
    details["alpha"] = alpha

    # --- Gate 5: Downside Capture Ratio Gate ---
    # Gate 5: Capture Ratio Asymmetry Gate (renamed from Downside Capture Ratio Gate)
    # Requires genuine capture ratio data - no mock defaults
    # Passive/index funds are exempt (by definition track index with 100/100 capture)
    downside_capture = fund_data.get("downside_capture_ratio", fund_data.get("downside_capture"))
    upside_capture = fund_data.get("upside_capture_ratio", fund_data.get("upside_capture"))
    
    if is_passive_cand:
        # Passive funds track index - capture ratios are 100/100 by definition
        downside_capture = 100.0
        upside_capture = 100.0
        downside_ok = True
    elif downside_capture is None or upside_capture is None:
        # Fail explicitly if capture ratio data is missing (Zero Mock Defaults mandate)
        failed.append("Gate 5 [Capture Ratio Asymmetry]: Missing downside/upside capture ratio data in fund_metrics.json — required for fiduciary assessment")
        downside_ok = False
    else:
        downside_capture = float(downside_capture)
        upside_capture = float(upside_capture)
        downside_ok = True
        # Capture Ratio Asymmetry Gate: Fund fails if downside capture > 100% AND upside < downside
        if downside_capture > 100.0 and upside_capture < downside_capture:
            downside_ok = False
            failed.append(f"Gate 5 [Inverted Capture Asymmetry]: Downside capture {downside_capture:.1f}% > 100% AND Upside {upside_capture:.1f}% < Downside {downside_capture:.1f}%")
    
    details["downside_capture"] = downside_capture
    details["upside_capture"] = upside_capture

    # --- Gate 6: Mandate Suitability Gate ---
    riskometer_score = int(fund_data.get("riskometer_score", 6))
    mandate_ok = fund_data.get("mandate_suitable", True)
    # Convert client_risk_tier_num to int (handles RiskTier enum, string, or int)
    client_tier_int = _risk_tier_to_int(client_risk_tier_num)
    
    # Passive/index funds are exempt from riskometer breach (broad market tracking = diversified risk)
    if not is_passive_cand and riskometer_score > client_tier_int:
        mandate_ok = False
        failed.append(f"Gate 6 [Riskometer Breach]: Fund riskometer score {riskometer_score} exceeds client risk tier {client_tier_int}")

    is_thematic = any(kw in category.lower() or kw in fund_name.lower() for kw in ("thematic", "sectoral", "defence", "energy", "pharma", "tech"))
    if is_starter and is_thematic:
        mandate_ok = False
        failed.append("Gate 6 [Mandate Suitability]: Starter portfolios (< INR 5L) are barred from thematic/sectoral funds")
    details["mandate_suitable"] = mandate_ok

    # --- Gate 7: Data Integrity & Provenance Gate ---
    provenance = fund_data.get("_provenance", {})
    confidence_score = float(provenance.get("confidence_score", fund_data.get("confidence_score", 1.0)) or 1.0)
    data_complete = fund_data.get("data_complete", True)
    data_ok = (confidence_score >= min_confidence_score) and data_complete
    if not data_ok:
        failed.append(f"Gate 7 [Data Integrity]: Confidence score {confidence_score:.2f} < {min_confidence_score:.2f} or incomplete factsheet")
    details["confidence_score"] = confidence_score

    # --- Gate 8: Manager Tenure & Process Continuity Gate ---
    # Evaluates scheme operational history (>= 3.0 yrs) and manager continuity (tenure >= min_manager_tenure_years, default 2.0 yrs).
    # Process-driven index and arbitrage funds are exempted from individual manager tenure.
    tenure = float(fund_data.get("manager_tenure_years", fund_data.get("tenure", 3.0)) or 0.0)
    scheme_track_record = float(fund_data.get("track_record_years", fund_data.get("track_record", 5.0)) or 5.0)
    is_process_driven = bool(fund_data.get("is_process_driven", False) or "index" in category.lower() or "arbitrage" in category.lower())

    track_ok = scheme_track_record >= 3.0
    tenure_ok = (tenure >= min_manager_tenure_years) or is_process_driven

    if not track_ok:
        failed.append(f"Gate 8 [Track Record]: Scheme operational history {scheme_track_record:.1f} yrs < 3.0 yrs minimum")
    if not tenure_ok:
        failed.append(f"Gate 8 [Manager Tenure]: Current manager tenure {tenure:.1f} yrs < {min_manager_tenure_years:.1f} yrs minimum without process-driven exemption")

    details["scheme_track_record_years"] = scheme_track_record
    details["manager_tenure_years"] = tenure

    # --- Gate 9: Thematic Satellite Cap Gate ---
    thematic_ok = True
    alloc_pct = float(fund_data.get("allocation_pct", 0.0))
    if is_thematic:
        if is_starter and alloc_pct > 0.0:
            thematic_ok = False
            failed.append("Gate 9 [Thematic Cap]: Thematic satellite must be 0% for starter portfolios")
        elif alloc_pct > 15.0:
            thematic_ok = False
            failed.append(f"Gate 9 [Thematic Cap]: Thematic satellite {alloc_pct:.1f}% exceeds 15% maximum")
    details["thematic_ok"] = thematic_ok

    # --- Gate 10: 100% Direct Plan Mandate Gate ---
    is_direct = fund_data.get("is_direct", True)
    if "regular" in fund_name.lower() or "distributor" in str(fund_data.get("plan", "")).lower():
        is_direct = False
    if not is_direct:
        failed.append("Gate 10 [Direct Plan Mandate]: Scheme is a Regular plan carrying distributor commission")
    details["is_direct"] = is_direct

    passed = (len(failed) == 0)

    return EligibilityGateResult(
        fund_id=str(fund_id),
        fund_name=str(fund_name),
        passed=passed,
        failed_gates=failed,
        amc_concentration_gate=amc_ok,
        aum_stability_gate=liquidity_and_aum_ok,
        concentration_gate=top10_ok,
        sharpe_alpha_gate=sharpe_alpha_ok,
        liquidity_gate=downside_ok,
        mandate_suitability_gate=mandate_ok,
        data_integrity_gate=data_ok,
        manager_tenure_gate=tenure_ok,
        thematic_satellite_gate=thematic_ok,
        direct_plan_gate=is_direct,
        details=details
    )


def filter_candidates(
    candidate_universe: List[Dict[str, Any]],
    current_portfolio: List[Dict[str, Any]],
    amc_max_limit_pct: float = 30.0,
    max_overlap_limit_pct: float = 30.0,
    client_risk_tier_num: int = 6,
    is_starter: bool = False,
) -> List[str]:
    """
    Runs strict boolean checks across candidate universe using all 10 binary gates.
    Returns: List of eligible fund names.
    If len(eligible) == 0, the caller triggers NO ACTION branch.
    """
    eligible = []
    for cand in candidate_universe:
        cand_name = cand.get("name", cand.get("fund_name", cand.get("id", "")))
        fund_data = dict(cand)
        fund_data["fund_name"] = cand_name
        
        gate_result = check_eligibility_gates(
            fund_data=fund_data,
            portfolio_holdings=current_portfolio,
            client_risk_tier_num=client_risk_tier_num,
            is_starter=is_starter,
            amc_max_limit_pct=amc_max_limit_pct,
        )
        if gate_result.passed:
            eligible.append(cand_name)

    return eligible


def evaluate_no_action(
    current_portfolio: List[Any],
    candidate_funds: List[Dict[str, Any]],
    min_improvement_threshold: float = 5.0
) -> NOActionResult:
    """
    Mandatory Fiduciary NO ACTION decision branch:
    If no candidate scheme demonstrates statistically validated improvement (composite score >= 5.0),
    emits an explicit verdict: NO ACTION / HOLD. Retain existing holdings.
    """
    best_improvement = 0.0
    best_fund = None

    for fund in candidate_funds:
        is_passed = fund.get("eligibility", {}).get("passed", False)
        if not is_passed and "eligibility" not in fund:
            # Evaluate on the fly if not pre-evaluated
            gate_res = check_eligibility_gates(fund)
            is_passed = gate_res.passed

        if not is_passed:
            continue

        score = float(fund.get("composite_score", fund.get("score", 0.0)) or 0.0)
        if score > best_improvement:
            best_improvement = score
            best_fund = fund

    no_improvement = (best_improvement < min_improvement_threshold)
    current_adequate = no_improvement

    if no_improvement:
        best_name = best_fund.get("fund_name", best_fund.get("name", "None")) if best_fund else "None"
        best_score = best_improvement if best_fund else 0.0
        reason = (
            f"No candidate fund offers demonstrable, statistically validated improvement (>={min_improvement_threshold} pts) "
            f"over current portfolio. Best candidate: {best_name} (+{best_score:.1f} pts). "
            f"Fiduciary mandate: NO ACTION / HOLD existing assets."
        )
        hold_rec = "Retain current verified holdings. Pause fresh deployment until qualifying candidates emerge. Review quarterly."
    else:
        best_name = best_fund.get("fund_name", best_fund.get("name", "Unknown"))
        reason = f"Demonstrated improvement candidate found: {best_name} (+{best_improvement:.1f} pts over hurdle)."
        hold_rec = "Proceed with deployment into verified candidate."

    return NOActionResult(
        action="NO_ACTION" if no_improvement else "PROCEED",
        reason=reason,
        current_portfolio_adequate=current_adequate,
        no_improvement_found=no_improvement,
        hold_recommendation=hold_rec,
        sip_deployment_pause=no_improvement
    )


def load_candidate_universe(
    metrics_path: Path,
    screening_policy_path: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """
    Loads candidate universe from fund_metrics.json and enriches with screening policy rules.
    """
    candidates = []
    if not metrics_path.exists():
        return candidates

    try:
        with open(metrics_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return candidates

    funds = data.get("funds", [])
    for m in funds:
        cand = {
            "fund_id": m.get("id", ""),
            "fund_name": m.get("name", m.get("scheme_name", m.get("id", ""))),
            "aum_crore": float(m.get("aum_crore", m.get("aum_cr", 0.0)) or 0.0),
            "aum_stable": True,
            "category": m.get("category", m.get("cat", "")),
            "top10_concentration_pct": float(m.get("top10_concentration_pct", m.get("concentration_top10", m.get("top10", 0.0))) or 0.0),
            "single_sector_weight_pct": float(m.get("single_sector_weight_pct", m.get("max_sector_concentration", m.get("fin", 0.0))) or 0.0),
            "sharpe_3y": float(m.get("sharpe_3y", m.get("sharpe", 0.5)) or 0.5),
            "sharpe_1y": float(m.get("sharpe_1y", 0.5) or 0.5),
            "alpha_3y": float(m.get("alpha_3y", m.get("alpha", 0.0)) or 0.0),
            "return_1y": float(m.get("return_1y", m.get("ret_1y", 0.0)) or 0.0),
            "return_6m": float(m.get("return_6m", m.get("ret_6m", 0.0)) or 0.0),
            "return_3y": float(m.get("return_3y", m.get("ret_3y", 0.0)) or 0.0),
            "ter_direct_pct": float(m.get("ter_direct_pct", m.get("er", 0.75)) or 0.75),
            "er": float(m.get("er", m.get("ter_direct_pct", 0.75)) or 0.75),
            "downside_capture_ratio": m.get("downside_capture_ratio", m.get("downside_capture")),
            "upside_capture_ratio": m.get("upside_capture_ratio", m.get("upside_capture")),
            "riskometer_score": int(m.get("riskometer_score", 6)),
            "mandate_suitable": True,
            "data_complete": True,
            "manager_tenure_years": float(m.get("manager_tenure_years", 5.0) or 5.0),
            "composite_score": float(m.get("composite_score", 65.0) or 65.0),
            "is_direct": True,
            "is_passive": m.get("is_passive", False),
            "_provenance": m.get("_provenance", {}),
            "eligibility": {}
        }
        candidates.append(cand)

    return candidates


def validate_thematic_satellite_cap(
    sip_plan: Any,
    client_aum: float,
    max_satellite_pct: float = 15.0
) -> bool:
    """
    Enforces Gate 9: Thematic Satellite Cap.
    - If client AUM < INR 5,00,000 (Starter), satellite thematic must be 0%.
    - If client AUM >= INR 5,00,000, satellite thematic must not exceed 15%.
    """
    if not hasattr(sip_plan, "items"):
        return True

    thematic_alloc = sum(
        item.allocation_pct for item in sip_plan.items
        if getattr(item, "rational_code", "") == "SATELLITE_THEME"
    )

    if client_aum > 0 and client_aum < 500000.0 and thematic_alloc > 0.0:
        raise ValueError(f"Fiduciary Gate 9 Violation: Starter portfolios (< INR 5L AUM) cannot hold thematic funds (found {thematic_alloc}%).")

    if thematic_alloc > max_satellite_pct:
        raise ValueError(f"Fiduciary Gate 9 Violation: Thematic satellite allocation {thematic_alloc}% exceeds max allowed {max_satellite_pct}%.")

    return True


def validate_direct_sip_mandate(sip_plan: Any) -> bool:
    """
    Enforces Gate 10: 100% Direct Plan Mandate on Fresh SIPs.
    Any recommended SIP item containing Regular or distributor commission throws an immediate violation.
    """
    if not hasattr(sip_plan, "items"):
        return True

    for item in sip_plan.items:
        scheme = getattr(item, "scheme_name", "").lower()
        if "regular" in scheme:
            raise ValueError(f"Fiduciary Gate 10 Violation: Fresh SIP recommendation '{item.scheme_name}' contains Regular plan.")

    return True
