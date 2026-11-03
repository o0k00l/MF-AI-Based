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


def _reviewed_direct_plan_evidence_status(fund_data: dict) -> str:
    """
    Verify the bytes of a local plan-source document and require a current human
    attestation. This verifies file integrity and records reviewer assurance;
    it does not cryptographically authenticate the publisher or reviewer.
    """
    import hashlib
    import re
    from datetime import date

    evidence = fund_data.get("direct_plan_evidence")
    evidence_root_value = fund_data.get("_evidence_root")
    if not isinstance(evidence, dict) or not evidence_root_value:
        return "MISSING"
    try:
        root = Path(evidence_root_value).expanduser().resolve()
        relative_source = evidence.get("source_file")
        if not isinstance(relative_source, str) or not relative_source.strip():
            return "MISSING"
        relative_path = Path(relative_source)
        if relative_path.is_absolute():
            return "INVALID"
        source_path = (root / relative_path).resolve()
        source_path.relative_to(root)
        if not source_path.is_file():
            return "MISSING"
        actual_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except (OSError, ValueError, RuntimeError):
        return "INVALID"

    declared_sha = evidence.get("source_document_sha256")
    source_url = evidence.get("source_url")
    source_type = evidence.get("source_type")
    reviewed_at_raw = evidence.get("reviewed_at")
    scheme_name = fund_data.get("fund_name") or fund_data.get("name")
    if (
        not isinstance(declared_sha, str)
        or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_sha)
        or actual_sha.lower() != declared_sha.lower()
        or not isinstance(source_url, str)
        or not source_url.startswith("https://")
        or source_type not in {"AMC_FACTSHEET", "AMFI_SCHEME_MASTER", "REGISTRAR_SCHEME_MASTER"}
        or evidence.get("reviewer_attested") is not True
        or evidence.get("plan") != "Direct"
        or evidence.get("scheme_name") != scheme_name
        or not isinstance(reviewed_at_raw, str)
    ):
        return "INVALID"
    try:
        reviewed_at = date.fromisoformat(reviewed_at_raw)
    except ValueError:
        return "INVALID"
    age_days = (date.today() - reviewed_at).days
    if age_days < 0 or age_days > 180:
        return "STALE"
    return "REVIEWER_ATTESTED_HASH_MATCH"



def _resolve_field(fund_data: dict, *names, default=None):
    """Resolve a field from either expanded or abbreviated names.
    
    Checks expanded names first, then abbreviated forms.
    Returns (value, source_name) or (default, None) if not found.
    """
    for name in names:
        if name in fund_data:
            return fund_data[name], name
    return default, None


def _require_field(fund_data: dict, gate: str, *names):
    """Require a field; append failure message if missing. Returns (value, is_missing)."""
    val, source = _resolve_field(fund_data, *names)
    if source is None:
        return None, True
    return val, False


def _risk_tier_to_int(tier: Any) -> int:
    """Parse a SEBI riskometer tier without ambiguous substring matching."""
    if isinstance(tier, bool):
        raise ValueError("Risk tier must be an integer from 1 to 6, not boolean")
    if isinstance(tier, int):
        if 1 <= tier <= 6:
            return tier
        raise ValueError(f"Risk tier out of range: {tier}")
    if isinstance(tier, RiskTier):
        if tier == RiskTier.CUSTOM:
            raise ValueError("RiskTier.CUSTOM requires an explicit custom suitability policy")
        mapping = {
            RiskTier.CONSERVATIVE: 2,
            RiskTier.MODERATE: 4,
            RiskTier.AGGRESSIVE: 6,
        }
        return mapping[tier]
    tier_str = str(tier).strip().lower()
    import re
    match = re.search(r"\btier\s*([1-6])\b", tier_str)
    if match:
        return int(match.group(1))
    # Match the most specific labels first.
    if "very high" in tier_str or "aggressive" in tier_str:
        return 6
    if "moderately high" in tier_str:
        return 4
    if tier_str in {"high", "5_high"} or tier_str.endswith("_high"):
        return 5
    if "low to moderate" in tier_str:
        return 2
    if "moderate" in tier_str:
        return 3
    if tier_str in {"low", "preservation"}:
        return 1
    raise ValueError(f"Unrecognized risk tier: {tier!r}")


def _finite_number(value: Any, field: str) -> float:
    """Convert a required numeric input; reject booleans, blanks and non-finite values."""
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{field} is missing or malformed")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} is not numeric: {value!r}") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result

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
    fund_name = str(fund_data.get("fund_name", fund_data.get("name", fund_id)) or "")
    category = str(fund_data.get("category", fund_data.get("cat", "")) or "")

    # --- Gate 1: AMC Concentration Gate ---
    # Never infer an AMC from the first token of a scheme name: many AMCs have
    # multi-word names and unrelated schemes can share the same first token.
    amc_name = str(fund_data.get("amc_name", "") or "").strip()
    amc_exposure_pct = None
    amc_ok = False
    if not amc_name:
        failed.append("Gate 1 [AMC Concentration]: explicit amc_name missing — cannot verify (fail-closed)")
    elif not portfolio_holdings:
        failed.append("Gate 1 [AMC Concentration]: portfolio holdings missing — cannot verify (fail-closed)")
    else:
        try:
            holding_values = []
            amc_values = []
            target_amc = amc_name.casefold()
            for holding in portfolio_holdings:
                raw_value = holding.get("value", holding.get("current_value_inr")) if isinstance(holding, dict) else getattr(holding, "current_value_inr", None)
                raw_amc = holding.get("amc_name", holding.get("amc")) if isinstance(holding, dict) else getattr(holding, "amc_name", None)
                value = _finite_number(raw_value, "portfolio holding value")
                if value < 0:
                    raise ValueError("portfolio holding value cannot be negative")
                if not raw_amc:
                    raise ValueError("portfolio holding AMC metadata missing")
                holding_values.append(value)
                if str(raw_amc).strip().casefold() == target_amc:
                    amc_values.append(value)
            total_val = sum(holding_values)
            if total_val <= 0:
                raise ValueError("portfolio total value must be positive")
            amc_exposure_pct = sum(amc_values) / total_val * 100.0
            amc_ok = amc_exposure_pct < amc_max_limit_pct
            if not amc_ok:
                failed.append(f"Gate 1 [AMC Concentration]: AMC {amc_name} exposure {amc_exposure_pct:.1f}% >= {amc_max_limit_pct}% ceiling")
        except (TypeError, ValueError) as exc:
            failed.append(f"Gate 1 [AMC Concentration]: invalid holdings/AMC data ({exc}) — fail-closed")
    details["amc_name"] = amc_name or None
    details["amc_exposure_pct"] = amc_exposure_pct

    # --- Gate 2: Liquidity & AUM Stability Gate ---
    try:
        aum = _finite_number(fund_data.get("aum_crore", fund_data.get("aum_cr")), "AUM")
        if aum < 0:
            raise ValueError("AUM cannot be negative")
    except ValueError as exc:
        aum = 0.0
        failed.append(f"Gate 2 [AUM]: {exc} — fail-closed")
    aum_min_ok = aum >= min_aum_crore
    if not aum_min_ok:
        failed.append(f"Gate 2 [Liquidity/AUM]: AUM ₹{aum:,.0f} Cr < ₹{min_aum_crore:,.0f} Cr minimum")

    cat_cap = CATEGORY_AUM_CAPS.get(category)
    aum_cap_ok = True
    if cat_cap and aum > cat_cap:
        aum_cap_ok = False
        failed.append(f"Gate 2 [AUM Size Drag]: AUM ₹{aum:,.0f} Cr exceeds {category} ceiling ₹{cat_cap:,.0f} Cr")

    aum_stable = fund_data.get("aum_stable")
    if aum_stable is None:
        failed.append("Gate 2 [AUM Stability]: aum_stable field missing — cannot verify liquidity (fail-closed)")
    elif not aum_stable:
        failed.append("Gate 2 [AUM Stability]: Outflows detected compromising liquidity")

    liquidity_and_aum_ok = aum_min_ok and aum_cap_ok and (aum_stable is True)
    details["aum_crore"] = aum

    # --- Gate 3: Top-10 Concentration Gate ---
    top10_raw = fund_data.get("top10_concentration_pct", fund_data.get("concentration_top10_pct", fund_data.get("top10")))
    if top10_raw is None:
        failed.append("Gate 3 [Top-10 Concentration]: top10_concentration_pct field missing — cannot verify (fail-closed)")
        top10 = 0.0
        top10_ok = False
    else:
        try:
            top10 = _finite_number(top10_raw, "top-10 concentration")
            if not 0.0 <= top10 <= 100.0:
                raise ValueError("top-10 concentration must be between 0 and 100")
            top10_ok = top10 <= max_top10_concentration_pct
        except ValueError as exc:
            top10 = None
            top10_ok = False
            failed.append(f"Gate 3 [Top-10 Concentration]: {exc} — fail-closed")
        if not top10_ok and top10 is not None:
            failed.append(f"Gate 3 [Top-10 Concentration]: Top 10 holdings {top10:.1f}% > {max_top10_concentration_pct:.1f}%")
    details["top10_concentration_pct"] = top10

    # Sector concentration check
    # Dedicated thematic/sectoral funds are governed by Gate 9 portfolio allocation limits.
    is_thematic = any(kw in category.lower() or kw in fund_name.lower() for kw in ("thematic", "sectoral", "defence", "energy", "pharma", "health", "tech"))
    sector_raw = fund_data.get("single_sector_weight_pct", fund_data.get("max_sector_concentration_pct", fund_data.get("fin")))
    sector_conc = None
    if not is_thematic:
        try:
            sector_conc = _finite_number(sector_raw, "single-sector concentration")
            if not 0.0 <= sector_conc <= 100.0:
                raise ValueError("single-sector concentration must be between 0 and 100")
        except ValueError as exc:
            failed.append(f"Gate 3 [Sector Concentration]: {exc} — fail-closed")
    elif sector_raw is not None:
        try:
            sector_conc = _finite_number(sector_raw, "single-sector concentration")
        except ValueError:
            sector_conc = None
    if not is_thematic and sector_conc is not None and sector_conc > max_sector_concentration_pct:
        failed.append(f"Gate 3 [Sector Concentration]: Sector weight {sector_conc:.1f}% > {max_sector_concentration_pct:.1f}%")
    details["sector_concentration_pct"] = sector_conc

    # --- Gate 4: Risk-Adjusted Sharpe & Alpha Gate (STRICTLY FAIL-CLOSED) ---
    from core.fund_classifier import is_verified_passive_scheme
    from core.models import InsufficientDataError
    sharpe = fund_data.get("sharpe_3y", fund_data.get("sharpe", None))
    alpha = fund_data.get("alpha_3y", fund_data.get("alpha", None))
    f_name = fund_data.get("fund_name", fund_data.get("name", ""))
    
    # Gate 4: Check if this is a verified passive scheme
    # If ISIN/scheme master unavailable for active fund, Default to False (not passive)
    # Passive verification failure due to missing ISIN should NOT cause gate failure for active funds
    is_passive_cand = False
    try:
        is_passive_cand = is_verified_passive_scheme(fund_data, fund_name=f_name, category=category, require_scheme_master=True)
    except InsufficientDataError:
        # No ISIN/scheme master available - cannot verify passive status
        # For active funds, this is fine - we'll check Sharpe and Alpha below
        # Only fail if fund was explicitly marked as passive but can't be verified
        if fund_data.get("is_passive") is True:
            failed.append(f"Gate 4 [Passive Verification]: Cannot verify passive status - missing scheme master")
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
        try:
            downside_capture = _finite_number(downside_capture, "downside capture")
            upside_capture = _finite_number(upside_capture, "upside capture")
            if not (0.0 <= downside_capture <= 500.0 and 0.0 <= upside_capture <= 500.0):
                raise ValueError("capture ratios must be between 0 and 500")
            downside_ok = True
        except ValueError as exc:
            failed.append(f"Gate 5 [Capture Ratio]: {exc} — fail-closed")
            downside_ok = False
            downside_capture = upside_capture = None
        # Capture Ratio Asymmetry Gate: Fund fails if downside capture > 100% AND upside < downside
        if downside_capture is not None and upside_capture is not None and downside_capture > 100.0 and upside_capture < downside_capture:
            downside_ok = False
            failed.append(f"Gate 5 [Inverted Capture Asymmetry]: Downside capture {downside_capture:.1f}% > 100% AND Upside {upside_capture:.1f}% < Downside {downside_capture:.1f}%")
    
    details["downside_capture"] = downside_capture
    details["upside_capture"] = upside_capture

    # --- Gate 6: Mandate Suitability Gate ---
    riskometer_raw = fund_data.get("riskometer_score")
    if riskometer_raw is None:
        failed.append("Gate 6 [Riskometer]: riskometer_score field missing - cannot verify suitability (fail-closed)")
        riskometer_score = 6
        mandate_ok = False
    else:
        try:
            riskometer_num = _finite_number(riskometer_raw, "riskometer_score")
            if not riskometer_num.is_integer() or not 1 <= riskometer_num <= 6:
                raise ValueError("riskometer_score must be an integer from 1 to 6")
            riskometer_score = int(riskometer_num)
            mandate_ok = True
        except ValueError as exc:
            riskometer_score = 6
            mandate_ok = False
            failed.append(f"Gate 6 [Riskometer]: {exc} — fail-closed")
    mandate_suitable_raw = fund_data.get("mandate_suitable")
    if mandate_suitable_raw is None:
        failed.append("Gate 6 [Mandate Suitability]: mandate_suitable field missing - cannot verify (fail-closed)")
        mandate_ok = False
    elif not mandate_suitable_raw:
        mandate_ok = False
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
    # Top-level confidence_score overrides _provenance.confidence_score
    confidence_score = None
    if "confidence_score" in fund_data:
        try:
            confidence_score = _finite_number(fund_data.get("confidence_score"), "confidence_score")
        except ValueError as exc:
            confidence_score = None
            failed.append(f"Gate 7 [Data Integrity]: {exc} — fail-closed")
    elif "confidence_score" in provenance:
        try:
            confidence_score = _finite_number(provenance.get("confidence_score"), "_provenance.confidence_score")
        except ValueError as exc:
            confidence_score = None
            failed.append(f"Gate 7 [Data Integrity]: {exc} — fail-closed")
    
    if confidence_score is not None and not 0.0 <= confidence_score <= 1.0:
        failed.append("Gate 7 [Data Integrity]: confidence_score must be between 0 and 1 — fail-closed")
        confidence_score = None

    if confidence_score is None:
        failed.append("Gate 7 [Data Integrity]: confidence_score missing, malformed or out of range — cannot verify (fail-closed)")
        data_ok = False
    else:
        data_ok = confidence_score >= min_confidence_score
        if not data_ok:
            failed.append(f"Gate 7 [Data Integrity]: Confidence score {confidence_score:.2f} < {min_confidence_score:.2f}")
    
    if "data_complete" not in fund_data:
        failed.append("Gate 7 [Data Integrity]: data_complete field missing - cannot verify (fail-closed)")
        data_ok = False
    elif not fund_data.get("data_complete", False):
        failed.append("Gate 7 [Data Integrity]: data_complete is False - factsheet incomplete")
        data_ok = False
    details["confidence_score"] = confidence_score

    # --- Gate 8: Manager Tenure & Process Continuity Gate ---
    # Evaluates scheme operational history (>= 3.0 yrs) and manager continuity (tenure >= min_manager_tenure_years, default 2.0 yrs).
    # Process-driven index and arbitrage funds are exempted from individual manager tenure.
    if "manager_tenure_years" not in fund_data and "tenure" not in fund_data:
        failed.append("Gate 8 [Manager Tenure]: manager_tenure_years field missing - cannot verify (fail-closed)")
        tenure = 0.0
    else:
        try:
            tenure = _finite_number(fund_data.get("manager_tenure_years", fund_data.get("tenure")), "manager_tenure_years")
            if tenure < 0: raise ValueError("manager tenure cannot be negative")
        except ValueError as exc:
            tenure = 0.0
            failed.append(f"Gate 8 [Manager Tenure]: {exc} — fail-closed")
    if "track_record_years" not in fund_data and "track_record" not in fund_data:
        failed.append("Gate 8 [Track Record]: track_record_years field missing - cannot verify (fail-closed)")
        scheme_track_record = 0.0
    else:
        try:
            scheme_track_record = _finite_number(fund_data.get("track_record_years", fund_data.get("track_record")), "track_record_years")
            if scheme_track_record < 0: raise ValueError("track record cannot be negative")
        except ValueError as exc:
            scheme_track_record = 0.0
            failed.append(f"Gate 8 [Track Record]: {exc} — fail-closed")
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
    alloc_pct = 0.0
    if is_thematic:
        try:
            alloc_pct = _finite_number(fund_data.get("allocation_pct"), "allocation_pct")
            if not 0.0 <= alloc_pct <= 100.0:
                raise ValueError("allocation_pct must be between 0 and 100")
        except ValueError as exc:
            thematic_ok = False
            failed.append(f"Gate 9 [Thematic Cap]: {exc} — fail-closed")
    if is_thematic and thematic_ok:
        if is_starter and alloc_pct > 0.0:
            thematic_ok = False
            failed.append("Gate 9 [Thematic Cap]: Thematic satellite must be 0% for starter portfolios")
        elif alloc_pct > 15.0:
            thematic_ok = False
            failed.append(f"Gate 9 [Thematic Cap]: Thematic satellite {alloc_pct:.1f}% exceeds 15% maximum")
    details["thematic_ok"] = thematic_ok

    # --- Gate 10: 100% Direct Plan Mandate Gate ---
    plan_value = str(fund_data.get("plan", "") or "").strip().casefold()
    direct_flag = fund_data.get("is_direct")
    # Recompute the local evidence digest at the decision boundary; never trust
    # a copied/caller-supplied status string as proof of Direct-plan identity.
    direct_evidence_status = _reviewed_direct_plan_evidence_status(fund_data)
    if "regular" in plan_value or "distributor" in plan_value or "regular" in fund_name.casefold():
        is_direct = False
    elif (
        direct_flag is True
        and plan_value.startswith("direct")
        and direct_evidence_status == "REVIEWER_ATTESTED_HASH_MATCH"
    ):
        is_direct = True
    else:
        is_direct = False
        failed.append(
            "Gate 10 [Direct Plan Mandate]: current reviewer-attested source document with matching hash and explicit Direct plan classification is required"
        )
    if not is_direct:
        failed.append("Gate 10 [Direct Plan Mandate]: Scheme is not verified as a Direct plan")
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
        # Preserve missing values as None — eligibility gates will fail closed
        aum_crore = m.get("aum_crore", m.get("aum_cr"))
        top10_raw = m.get("top10_concentration_pct", m.get("concentration_top10", m.get("top10")))
        sector_raw = m.get("single_sector_weight_pct", m.get("max_sector_concentration", m.get("fin")))
        sharpe_3y_raw = m.get("sharpe_3y", m.get("sharpe"))
        sharpe_1y_raw = m.get("sharpe_1y")
        alpha_3y_raw = m.get("alpha_3y", m.get("alpha"))
        return_1y_raw = m.get("return_1y", m.get("ret_1y"))
        return_6m_raw = m.get("return_6m", m.get("ret_6m"))
        return_3y_raw = m.get("return_3y", m.get("ret_3y"))
        ter_raw = m.get("ter_direct_pct", m.get("er"))
        er_raw = m.get("er", m.get("ter_direct_pct"))
        riskometer_raw = m.get("riskometer_score")
        manager_tenure_raw = m.get("manager_tenure_years")
        track_record_raw = m.get("track_record_years")
        composite_raw = m.get("composite_score")
        downside_raw = m.get("downside_capture_ratio", m.get("downside_capture"))
        upside_raw = m.get("upside_capture_ratio", m.get("upside_capture"))
        riskometer_raw = m.get("riskometer_score")
        is_passive_raw = m.get("is_passive")
        provenance_raw = m.get("_provenance")

        cand = {
            "fund_id": m.get("id", ""),
            "fund_name": m.get("name", m.get("scheme_name", m.get("id", ""))),
            "aum_crore": float(aum_crore) if aum_crore is not None else None,
            "aum_stable": m.get("aum_stable"),  # None if missing — gate will fail closed
            "category": m.get("category", m.get("cat", "")),
            "top10_concentration_pct": float(top10_raw) if top10_raw is not None else None,
            "single_sector_weight_pct": float(sector_raw) if sector_raw is not None else None,
            "sharpe_3y": float(sharpe_3y_raw) if sharpe_3y_raw is not None else None,
            "sharpe_1y": float(sharpe_1y_raw) if sharpe_1y_raw is not None else None,
            "alpha_3y": float(alpha_3y_raw) if alpha_3y_raw is not None else None,
            "return_1y": float(return_1y_raw) if return_1y_raw is not None else None,
            "return_6m": float(return_6m_raw) if return_6m_raw is not None else None,
            "return_3y": float(return_3y_raw) if return_3y_raw is not None else None,
            "ter_direct_pct": float(ter_raw) if ter_raw is not None else None,
            "er": float(er_raw) if er_raw is not None else None,
            "downside_capture_ratio": downside_raw,
            "upside_capture_ratio": upside_raw,
            "riskometer_score": int(riskometer_raw) if riskometer_raw is not None else None,
            "mandate_suitable": m.get("mandate_suitable"),  # None if missing — gate will fail closed
            "data_complete": m.get("data_complete"),  # None if missing — gate will fail closed
            "manager_tenure_years": float(manager_tenure_raw) if manager_tenure_raw is not None else None,
            "track_record_years": float(track_record_raw) if track_record_raw is not None else None,
            "composite_score": float(composite_raw) if composite_raw is not None else None,
            # Never synthesize Direct-plan status. Require the source document
            # to be present locally, hash-matched and reviewer-attested.
            "direct_plan_evidence": m.get("direct_plan_evidence"),
            "_evidence_root": str(Path(metrics_path).resolve().parent),
            "direct_plan_evidence_status": _reviewed_direct_plan_evidence_status({
                "direct_plan_evidence": m.get("direct_plan_evidence"),
                "_evidence_root": str(Path(metrics_path).resolve().parent),
                "fund_name": m.get("name", m.get("scheme_name", m.get("id", ""))),
            }),
            "is_direct": (
                m.get("is_direct")
                if isinstance(m.get("is_direct"), bool)
                and _reviewed_direct_plan_evidence_status({
                    "direct_plan_evidence": m.get("direct_plan_evidence"),
                    "_evidence_root": str(Path(metrics_path).resolve().parent),
                    "fund_name": m.get("name", m.get("scheme_name", m.get("id", ""))),
                }) == "REVIEWER_ATTESTED_HASH_MATCH"
                else None
            ),
            "plan": (
                m.get("direct_plan_evidence", {}).get("plan", "")
                if isinstance(m.get("direct_plan_evidence"), dict)
                else ""
            ),
            "is_passive": is_passive_raw if is_passive_raw is not None else False,
            "_provenance": provenance_raw if provenance_raw is not None else {},
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
    """Require explicit Direct-plan metadata for every positive SIP allocation."""
    if not hasattr(sip_plan, "items"):
        raise ValueError("SIP plan is missing recommendation items; Direct-plan status cannot be verified")

    for item in sip_plan.items:
        amount = getattr(item, "monthly_inr", None)
        scheme = str(getattr(item, "scheme_name", "") or "")
        is_direct = getattr(item, "is_direct", None)
        if amount is None or isinstance(amount, bool):
            raise ValueError(f"Invalid SIP amount for recommendation {scheme!r}")
        try:
            amount_value = float(amount)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid SIP amount for recommendation {scheme!r}") from exc
        if not math.isfinite(amount_value) or amount_value < 0:
            raise ValueError(f"SIP amount must be finite and non-negative for {scheme!r}")
        if amount_value == 0:
            continue
        if is_direct is not True:
            raise ValueError(
                f"Fiduciary Gate 10 Violation: '{scheme}' lacks verified is_direct=True metadata."
            )
        if "regular" in scheme.casefold():
            raise ValueError(
                f"Fiduciary Gate 10 Violation: Fresh SIP recommendation '{scheme}' is a Regular plan."
            )
    return True
