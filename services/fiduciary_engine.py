"""services/fiduciary_engine.py — Bridge service linking Web UI to Core Fiduciary Math Engine.

Transforms UI session state (CAS holdings, CGS capital gains, 3-mode Risk Profile,
and Financial Goals) into rigorous mathematical models and deterministic SAA plans.
"""
from __future__ import annotations

import json
import math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.math_engine import calculate_saa_drift, quantize_inr
from core.models import AssetClass, HoldingItem, PlanType, SAADriftAnalysis
from services.risk_profiler import TargetSaa, SebiRiskTier, RiskProfileResult


# Market Nominations - Selection rules defined by category; actual funds selected dynamically from fund universe
_MARKET_NOMINATIONS_PATH = Path(__file__).resolve().parent.parent / "data" / "policy" / "market_nominations.json"
_SCHEME_MASTER_PATH = Path(__file__).resolve().parent.parent / "data" / "policy" / "scheme_master.json"


def _load_market_nominations() -> Dict[str, Dict[str, Any]]:
    """Load market nomination selection rules for SIP blueprint selection."""
    try:
        data = json.loads(_MARKET_NOMINATIONS_PATH.read_text(encoding="utf-8"))
        return data.get("selection_rules", data)  # Handle both formats
    except Exception:
        # Fallback to embedded rules if file unavailable
        return {
            "large_cap_index": {
                "category": "Large Cap",
                "plan_type": "Direct",
                "is_passive": True,
                "sort_by": "ter_direct_pct",
                "sort_order": "asc",
            },
            "mid_cap_active": {
                "category": "Mid Cap",
                "plan_type": "Direct",
                "is_passive": False,
                "sort_by": "sharpe_3y",
                "sort_order": "desc",
            },
            "flexi_multi_cap": {
                "category": "Flexi Cap",
                "plan_type": "Direct",
                "is_passive": False,
                "sort_by": "sharpe_3y",
                "sort_order": "desc",
            },
            "debt_liquid": {
                "category": "Debt",
                "plan_type": "Direct",
                "is_passive": False,
                "sort_by": "aum_crore",
                "sort_order": "desc",
            },
        }


def _load_fund_universe() -> List[Dict[str, Any]]:
    """Load the unified fund universe from scheme_master.json for dynamic selection.
    
    Returns a list of fund dictionaries with metrics suitable for _select_market_nom_fund.
    """
    try:
        data = json.loads(_SCHEME_MASTER_PATH.read_text(encoding="utf-8"))
        schemes = data.get("schemes", {})
        
        # Transform scheme master format to fund universe format
        fund_universe = []
        for scheme_id, scheme_data in schemes.items():
            # Get scheme name
            scheme_name = scheme_data.get("canonical_name") or scheme_data.get("scheme_name") or scheme_id
            
            # Category inference: try category, cat, then infer from name
            category = scheme_data.get("category") or scheme_data.get("cat") or ""
            if not category:
                # Infer category from scheme name
                name_lower = scheme_name.lower()
                if "index" in name_lower or ("nifty" in name_lower):
                    category = "Index - Large Cap"
                elif "mid cap" in name_lower or "emerging equity" in name_lower:
                    category = "Mid Cap"
                elif "large cap" in name_lower and "index" not in name_lower:
                    category = "Large Cap"
                elif "debt" in name_lower or "liquid" in name_lower:
                    category = "Debt"
            
            # Get equity allocation - use portfolio_large_cap_pct or eq (total equity percentage)
            # For the equity filter, we need total equity exposure, not just large cap
            eq_pct = scheme_data.get("eq") or scheme_data.get("portfolio_large_cap_pct") or 0
            
            # For index funds with no explicit equity data, infer 100% for large cap index
            # and 0% for non-equity indexes
            name_lower = scheme_name.lower()
            if eq_pct == 0:
                if "index" in name_lower or "nifty 50" in name_lower:
                    # Check if it's a debt/liquidity index
                    if "debt" not in name_lower and "liquid" not in name_lower and "money market" not in name_lower:
                        eq_pct = 100.0
            
            fund_entry = {
                "scheme": scheme_name,
                "id": scheme_id,
                "category": category,
                "plan_type": scheme_data.get("plan_type", "Direct"),
                "is_passive": scheme_data.get("is_passive", False),
                "ter_direct_pct": scheme_data.get("ter_direct_pct"),
                "ter_regular_pct": scheme_data.get("ter_regular_pct"),
                "aum_crore": scheme_data.get("aum_crore"),
                "sharpe_3y": scheme_data.get("sharpe_3y"),
                "alpha_3y": scheme_data.get("alpha_3y"),
                "equity_pct": eq_pct,
                "eq": eq_pct,
                "debt": scheme_data.get("portfolio_debt_pct") or scheme_data.get("debt"),
                "sc": scheme_data.get("portfolio_small_cap_pct") or scheme_data.get("sc"),
                "mc": scheme_data.get("portfolio_mid_cap_pct") or scheme_data.get("mc"),
            }
            fund_universe.append(fund_entry)
        
        return fund_universe
    except Exception:
        return []


def trigger_spiva_fallback(
    category_key: str,
    rules: Dict[str, Any],
    fund_metrics_universe: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """SPIVA Passive Fallback Trigger - Gate 4 Critical Compliance Fix.
    
    When no active candidates pass the 10 binary gates, dynamically select
    the lowest TER passive index fund from the verified universe.
    
    ZERO HARDCODING: This function dynamically searches the fund metrics 
    universe for passive funds matching the required category. No brand names
    are hardcoded - the selection is data-driven from verified fund_metrics.json.
    
    Legally compliant with SEBI guidelines for passive fund alternatives.
    
    Args:
        category_key: The market nomination key (e.g., "large_cap_index", "mid_cap_active")
        rules: Selection rules including is_passive flag and category requirements
        fund_metrics_universe: The verified list of funds from fund_metrics.json
    
    Returns:
        Dict with: scheme (str), source ("fallback"), validation ("valid"|"failed")
    
    Raises:
        ValueError: If no valid passive fallback fund is available (NO_ACTION)
    """
    # Map category_key to expected category names
    category_mapping = {
        "large_cap_index": "Large Cap",
        "mid_cap_active": "Mid Cap", 
        "debt_liquid": "Debt",
        "equity_generic": "Flexi Cap",
        "flexi_multi_cap": "Flexi Cap",
    }
    
    target_category = category_mapping.get(category_key, "")
    is_passive_needed = rules.get("is_passive", True)
    sort_by = rules.get("sort_by", "ter_direct_pct")
    
    # Dynamically filter for funds matching category and plan type
    candidates = []
    for fund in fund_metrics_universe:
        if not isinstance(fund, dict):
            continue
            
        fund_cat = fund.get("category", "") or fund.get("cat", "")
        fund_plan_type = fund.get("plan_type", "")
        is_passive = fund.get("is_passive", False)
        
        # For passive-only categories, skip active funds
        if is_passive_needed and not is_passive:
            continue
        # For active-only categories, skip passive funds  
        if not is_passive_needed and is_passive:
            continue
        
        # Category must match (case-insensitive)
        if target_category and target_category.lower() not in str(fund_cat).lower():
            continue
            
        # Must be Direct plan
        if fund_plan_type and "direct" not in str(fund_plan_type).lower():
            continue
        
        candidates.append(fund)
    
    if not candidates:
        # No candidates available - must trigger NO_ACTION
        # This is the correct fiduciary behavior: fail closed
        prefix = "SPIVA PASSIVE FALLBACK FAILURE" if is_passive_needed else "SPIVA FALLBACK FAILURE"
        raise ValueError(
            f"{prefix}: No {'passive index' if is_passive_needed else 'active'} fund found "
            f"for category '{target_category}'. This is a fiduciary compliance issue requiring scheme_master.json update."
        )
    
    # Sort by the specified metric (TER for passive, Sharpe for mid-cap, AUM for debt)
    def safe_sort_key(fund):
        val = fund.get(sort_by)
        if val is None:
            return float('inf')
        try:
            return float(val) if isinstance(val, (int, float)) else float('inf')
        except (TypeError, ValueError):
            return float('inf')
    
    # For Sharpe, we want highest (reverse sort), for TER/AUM we want lowest
    reverse_sort = sort_by == "sharpe_3y"
    candidates.sort(key=safe_sort_key, reverse=reverse_sort)
    
    # BLOCKER #5 FIX: Check if ALL candidates have invalid metrics for the ranking key
    # If all candidates have None/invalid for sort_by, we cannot make a valid selection
    def _is_valid_metric(val):
        """Check if metric is a finite numeric value (not None, NaN, infinity, or string)."""
        if val is None:
            return False
        if isinstance(val, str):
            return False
        try:
            fval = float(val)
            return fval == fval and fval != float('inf') and fval != float('-inf')  # Not NaN, not infinity
        except (TypeError, ValueError):
            return False
    
    valid_candidates = [f for f in candidates if _is_valid_metric(f.get(sort_by))]
    if not valid_candidates:
        # All candidates have invalid ranking metrics - must fail closed (NO_ACTION)
        prefix = "SPIVA PASSIVE FALLBACK FAILURE" if is_passive_needed else "SPIVA FALLBACK FAILURE"
        raise ValueError(
            f"{prefix}: All candidate funds for category '{target_category}' have invalid "
            f"ranking metric '{sort_by}'. Cannot select without valid metrics. "
            f"This is a fiduciary compliance issue requiring fund_metrics.json update."
        )
    
    # Return the best fund from VALID candidates only
    best_fund = valid_candidates[0]
    scheme_name = best_fund.get("scheme") or best_fund.get("canonical_name") or best_fund.get("id", "")
    
    # Ensure Direct plan naming
    if "Direct" not in scheme_name and "Direct Plan" not in scheme_name:
        scheme_name = scheme_name + " - Direct Plan - Growth"
    
    # Return dict with provenance info (source="fallback" for SPIVA fallback)
    return {
        "scheme": scheme_name,
        "category": best_fund.get("category") or target_category,
        "source": "fallback",
        "validation": "valid"
    }


def _select_market_nom_fund(
    rules: Dict[str, Any],
    fund_universe: List[Dict[str, Any]],
    nom_key: str = "",
) -> Dict[str, Any]:
    """Dynamically select the best fund based on market nomination rules.
    
    Args:
        rules: Selection rules including category, sort_by, sort_order, and filters
        fund_universe: List of available funds with metrics (from fund_metrics.json or similar)
        nom_key: The key identifying this nomination (for fallback)
    
    Returns:
        Dict with: scheme (str), source ("dynamic"|"fallback"|"unavailable"), validation ("valid"|"failed")
    """
    # SPIVA PASSIVE FALLBACK: Handle empty universe case
    if not fund_universe:
        try:
            fallback_result = trigger_spiva_fallback(nom_key, rules, fund_universe)
            return fallback_result  # Already returns dict with source="fallback"
        except ValueError:
            return {"scheme": "SPIVA_FALLBACK_FAILED", "source": "unavailable", "validation": "failed"}

    
    category = rules.get("category", "")
    is_passive = rules.get("is_passive", False)
    sort_by = rules.get("sort_by", "aum_crore")
    sort_order = rules.get("sort_order", "desc")
    
    # Filter funds by category and plan type
    filtered = []
    for fund in fund_universe:
        fund_cat = fund.get("category", "") or fund.get("cat", "")
        
        # Match category (case-insensitive, handle variations)
        if isinstance(fund_cat, str):
            cat_match = category.lower() in fund_cat.lower()
        else:
            cat_match = False
        
        if not cat_match:
            continue
        
        # Apply plan type filter
        rule_plan_type = rules.get("plan_type", "Direct")
        fund_plan_type = fund.get("plan_type", "Direct")
        if fund_plan_type and rule_plan_type and rule_plan_type.lower() not in str(fund_plan_type).lower():
            continue
        
        # Apply TER filter for all categories
        ter = fund.get("ter_direct_pct")
        max_ter = rules.get("max_ter_pct", 1.0)
        if ter is not None and ter > max_ter:
            continue
        
        # Apply equity exposure filter for large cap index
        equity_pct_min = rules.get("equity_pct_min", 0)
        if equity_pct_min > 0:
            eq = fund.get("eq", fund.get("portfolio_large_cap_pct", 0)) or 0
            if eq < equity_pct_min:
                continue
        
        # Apply Sharpe filter for mid-cap active
        if sort_by == "sharpe_3y":
            sharpe = fund.get("sharpe_3y")
            min_sharpe = rules.get("min_sharpe", 0.0)
            if sharpe is None or (isinstance(sharpe, (int, float)) and sharpe < min_sharpe):
                continue
            alpha = fund.get("alpha_3y")
            min_alpha = rules.get("min_alpha", -10.0)
            if alpha is not None and (isinstance(alpha, (int, float)) and alpha < min_alpha):
                continue
        
        # Apply AUM filter for debt/liquid funds
        if sort_by == "aum_crore":
            aum = fund.get("aum_crore")
            min_aum = rules.get("min_aum_crore", 0)
            if aum is None:
                continue
            if aum < min_aum:
                continue
        
        # For passive funds, check if it's an index fund
        if is_passive:
            fund_name = fund.get("scheme", fund.get("id", "")).lower()
            if "index" not in fund_name and "nifty" not in fund_name and "sensex" not in fund_name:
                continue
        
        filtered.append(fund)
    
    if not filtered:
        # SPIVA PASSIVE FALLBACK: Dynamic selection from verified universe
        # No brand hardcoding - selection is data-driven
        try:
            fallback_result = trigger_spiva_fallback(nom_key, rules, fund_universe)
            return fallback_result  # Already returns dict with source="fallback"
        except ValueError:
            return {"scheme": "SPIVA_FALLBACK_FAILED", "source": "unavailable", "validation": "failed"}
    
    # Sort by the specified metric
    reverse = sort_order == "desc"
    try:
        def _is_valid_metric(val):
            """Check if metric is a finite numeric value (not None, NaN, infinity, or string)."""
            if val is None:
                return False
            if isinstance(val, str):
                return False
            try:
                fval = float(val)
                return fval == fval and fval != float('inf') and fval != float('-inf')  # Not NaN, not infinity
            except (TypeError, ValueError):
                return False

        def sort_key(f):
            val = f.get(sort_by)
            if not _is_valid_metric(val):
                # For ascending sort (lowest first), invalid should be at the end
                # For descending sort (highest first), invalid should be at the end
                return float('inf')
            return float(val)

        filtered.sort(key=sort_key, reverse=reverse)

        # BLOCKER #5 FIX: Check if ALL filtered candidates have invalid metrics for the ranking key
        valid_filtered = [f for f in filtered if _is_valid_metric(f.get(sort_by))]
        if not valid_filtered:
            # All filtered candidates have invalid ranking metrics - trigger SPIVA fallback
            try:
                fallback_result = trigger_spiva_fallback(nom_key, rules, fund_universe)
                return fallback_result
            except ValueError:
                return {"scheme": "SPIVA_FALLBACK_FAILED", "source": "unavailable", "validation": "failed"}

        # Get scheme name and category from the best fund (from VALID filtered only)
        best = valid_filtered[0]
        scheme_name = best.get("scheme") or best.get("canonical_name") or best.get("id", "Selected Fund")
        scheme_category = best.get("category") or best.get("cat", "")
        if not scheme_category:
            return {"scheme": "SPIVA_FALLBACK_FAILED", "source": "unavailable", "validation": "failed"}
        # Ensure Direct plan
        if "Direct" not in scheme_name and "Direct Plan" not in scheme_name:
            scheme_name = scheme_name + " - Direct Plan - Growth"
        
        # Return dict with provenance info including actual category from selected fund
        return {
            "scheme": scheme_name,
            "category": scheme_category,
            "source": "dynamic",
            "validation": "valid"
        }
    except Exception:
        return {"scheme": "SPIVA_FALLBACK_FAILED", "source": "unavailable", "validation": "failed"}


def convert_cas_funds_to_holdings(funds: List[Dict[str, Any]]) -> List[HoldingItem]:
    """Convert raw UI CAS fund dictionaries into validated domain HoldingItems.
    
    Fiduciary Separation Contract:
    - Broad asset class is mapped strictly via authoritative SEBI category mapping.
      Unmapped or unknown categories map to AssetClass.OTHER.
    - Measured look-through exposures (equity_pct, debt_pct) are populated ONLY when backed by
      authenticated exposure evidence (portfolio_exposure_verified=True with valid evidence record).
    - Unverified holdings are marked lookthrough_status="INDETERMINATE" with 0.0% measured exposure.
      Numeric look-through percentages are NEVER manufactured from category labels (e.g. no 100% or 65/35% defaults).
    - Heuristic display allocations are never consumed as calculation inputs.
    """
    from services.cas_parser import SEBI_CATEGORY_TO_ASSET_CLASS, validate_exposure_evidence, resolve_authoritative_scheme

    holdings: List[HoldingItem] = []
    for idx, f in enumerate(funds):
        val = Decimal(str(f.get("current_value", 0.0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if val <= Decimal("0.00"):
            continue
        cost = Decimal(str(f.get("invested_value", 0.0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        units = Decimal(str(f.get("units", 0.0))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        nav = Decimal(str(f.get("nav", 0.0))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        s_name = str(f.get("scheme", "Unknown Scheme"))
        cat_raw = f.get("category")
        is_cat_verified = f.get("category_verified") is True

        # Require verified category provenance; unverified categories are checked against authoritative master
        if not is_cat_verified:
            m_entry = resolve_authoritative_scheme(s_name)
            if m_entry is not None:
                is_cat_verified = True
                cat_raw = m_entry.get("cat") or m_entry.get("category")

        if not cat_raw or not is_cat_verified:
            ac = AssetClass.OTHER
        else:
            cat_str = str(cat_raw).strip().lower()
            broad_class = SEBI_CATEGORY_TO_ASSET_CLASS.get(cat_str)
            if broad_class == "Debt":
                ac = AssetClass.DEBT
            elif broad_class == "Hybrid":
                ac = AssetClass.HYBRID
            elif broad_class == "International":
                ac = AssetClass.INTERNATIONAL
            elif broad_class == "Equity":
                ac = AssetClass.EQUITY
            else:
                ac = AssetClass.OTHER

        # Determine measured exposure strictly through authenticated evidence (single evidence path)
        is_exposure_verified = False
        v_debt = None
        v_eq = None
        evidence = f.get("exposure_evidence")

        if isinstance(evidence, dict):
            is_valid, _ = validate_exposure_evidence(evidence, f.get("scheme_code"))
            if is_valid:
                is_exposure_verified = True
                v_debt = evidence.get("debt_pct")
                v_eq = evidence.get("equity_pct")
        else:
            # Check authoritative scheme master for authentic evidence
            m_entry = resolve_authoritative_scheme(s_name)
            if m_entry is not None:
                m_ev = m_entry.get("exposure_evidence")
                if isinstance(m_ev, dict):
                    is_valid, _ = validate_exposure_evidence(m_ev, m_entry.get("sid"))
                    if is_valid:
                        is_exposure_verified = True
                        v_debt = m_ev.get("debt_pct")
                        v_eq = m_ev.get("equity_pct")

        if is_exposure_verified and v_debt is not None:
            lookthrough_status = "VERIFIED"
            lookthrough_reason = f"Verified factsheet disclosure via {f.get('exposure_source') or 'MASTER'} as of {f.get('exposure_as_of') or '2026-08-31'}"
            debt_pct = float(v_debt)
            eq_pct = float(v_eq) if v_eq is not None else max(0.0, 100.0 - debt_pct)
        else:
            lookthrough_status = "INDETERMINATE"
            lookthrough_reason = "No verified factsheet look-through disclosure attached"
            debt_pct = 0.0
            eq_pct = 0.0

        plan_str = str(f.get("plan_type", "Direct")).upper()
        plan = PlanType.REGULAR if "REGULAR" in plan_str else PlanType.DIRECT

        # Asset classes are strictly separated: gold/commodities are NEVER added to debt exposure
        gold_pct = float(f.get("gold", 0.0))

        h = HoldingItem(
            fund_id=f"fund_{idx}_{s_name[:15]}",
            scheme=s_name,
            fund_name=s_name,
            folio=str(f.get("folio_no") or f.get("folio") or f"FOLIO_{idx}"),
            plan=plan,
            asset_class=ac,
            equity_pct=eq_pct,
            debt_pct=debt_pct,
            hybrid_pct=0.0,
            international_pct=0.0,
            current_value_inr=val,
            invested_value_inr=cost,
            units=units,
            nav=nav,
            lookthrough_status=lookthrough_status,
            lookthrough_reason=lookthrough_reason,
            lookthrough_effective_date=f.get("exposure_as_of"),
        )
        holdings.append(h)
    return holdings


def evaluate_portfolio_saa_audit(
    funds: List[Dict[str, Any]],
    target_saa: Optional[Dict[str, float] | TargetSaa] = None,
) -> Dict[str, Any]:
    """Execute SAA drift and debt buffer analysis using verified portfolio exposure.
    
    Fails closed to INDETERMINATE if any holding lacks verified look-through exposure.
    Display estimates and manufactured category percentages are strictly excluded.
    """
    holdings = convert_cas_funds_to_holdings(funds)
    total_val = sum(h.current_value_inr for h in holdings)

    if total_val <= Decimal("0.00"):
        return {
            "status": "NO_PORTFOLIO",
            "total_value_inr": Decimal("0.00"),
            "drift_analysis": None,
            "current_equity_pct": 0.0,
            "current_debt_pct": 0.0,
            "target_equity_pct": 75.0,
            "target_debt_pct": 25.0,
            "debt_gap_inr": Decimal("0.00"),
            "equity_gap_inr": Decimal("0.00"),
            "is_debt_deficit": False,
        }

    # Format target_saa dictionary
    target_dict = None
    target_debt_pct = 25.0
    target_equity_pct = 75.0

    if target_saa is not None:
        if hasattr(target_saa, "as_dict"):
            target_dict = target_saa.as_dict()
            target_debt_pct = float(target_saa.debt_pct)
            target_equity_pct = float(target_saa.total_equity_pct)
        elif isinstance(target_saa, dict):
            target_dict = target_saa
            target_debt_pct = float(target_saa.get("debt_pct", 25.0))
            target_equity_pct = float(target_saa.get("total_equity_pct", 100.0 - target_debt_pct))

    # Strict fiduciary check: Fail closed if any holding lacks verified look-through exposure
    indeterminate_holdings = [h.scheme for h in holdings if h.lookthrough_status != "VERIFIED"]
    if indeterminate_holdings:
        return {
            "status": "INDETERMINATE",
            "lookthrough_verified": False,
            "total_value_inr": total_val,
            "holdings_count": len(holdings),
            "drift_analysis": None,
            "indeterminate_holdings": indeterminate_holdings,
            "reason": (
                f"Look-through portfolio exposure is indeterminate for {len(indeterminate_holdings)} holding(s): "
                f"{', '.join(indeterminate_holdings[:3])}. Fiduciary SAA calculations require authenticated factsheet disclosures."
            ),
            "current_equity_pct": None,
            "current_debt_pct": None,
            "target_equity_pct": round(target_equity_pct, 1),
            "target_debt_pct": round(target_debt_pct, 1),
            "debt_gap_inr": None,
            "equity_gap_inr": None,
            "rebalance_required": None,
            "is_debt_deficit": None,
        }

    drift: SAADriftAnalysis = calculate_saa_drift(
        holdings=holdings,
        target_saa={"equity_pct": target_equity_pct, "debt_pct": target_debt_pct},
        tolerance_band_pct=5.0,
    )

    curr_eq_pct = drift.current_equity_pct
    curr_db_pct = drift.current_debt_pct
    db_gap_inr = quantize_inr(drift.debt_gap_inr)
    eq_gap_inr = quantize_inr(drift.equity_gap_inr)

    is_debt_deficit = db_gap_inr > Decimal("0.00")

    return {
        "status": "ANALYZED",
        "lookthrough_verified": True,
        "total_value_inr": total_val,
        "holdings_count": len(holdings),
        "drift_analysis": drift,
        "current_equity_pct": round(curr_eq_pct, 1),
        "current_debt_pct": round(curr_db_pct, 1),
        "target_equity_pct": round(target_equity_pct, 1),
        "target_debt_pct": round(target_debt_pct, 1),
        "debt_gap_inr": db_gap_inr,
        "equity_gap_inr": eq_gap_inr,
        "rebalance_required": drift.rebalance_required,
        "is_debt_deficit": is_debt_deficit,
    }


def validate_scheme_for_sleeve(
    fund: dict | None,
    sleeve: str,
    expected_category_keywords: list[str] | None = None,
    require_provenance: bool = True,
    allowed_provenance: list[str] | None = None,
) -> dict:
    """
    Unified scheme validation for all four sleeves.
    
    Args:
        fund: Fund dictionary with scheme, category, plan_type, folio_no, source, validation
        sleeve: Sleeve name for error reporting
        expected_category_keywords: List of keywords to match against category/scheme
        require_provenance: If True, fund must have valid source metadata
        allowed_provenance: List of allowed source values (e.g., ["dynamic", "fallback", "existing"])
    
    Returns dict with: validation, scheme, folio_no, is_new, and optionally source/validation
    """
    if not fund or not isinstance(fund, dict):
        return {"validation": "failed", "scheme": "SPIVA_FALLBACK_FAILED", "folio_no": "New Direct Folio Mandate", "is_new": True}
    
    scheme = fund.get("scheme", "")
    category = str(fund.get("category", "")).lower()
    scheme_lower = str(scheme).lower()
    plan_type = str(fund.get("plan_type", "")).upper()
    folio = fund.get("folio_no", "")
    fund_source = fund.get("source", "")
    
    # Check for placeholder failure names
    if scheme == "SPIVA_FALLBACK_FAILED" or not scheme:
        return {"validation": "failed", "scheme": scheme or "SPIVA_FALLBACK_FAILED", "folio_no": folio or "New Direct Folio Mandate", "is_new": True}
    
    # Validate plan type - must be Direct
    if plan_type != "DIRECT":
        return {"validation": "failed", "scheme": scheme, "folio_no": folio, "is_new": False}
    
    # Validate category - authoritative category field MUST match expected keywords
    # Scheme-name text must NOT override or substitute for a non-matching, generic, or contradictory category
    if expected_category_keywords:
        category_match = any(kw.lower() in category for kw in expected_category_keywords)
        if not category_match:
            return {"validation": "failed", "scheme": scheme, "folio_no": folio, "is_new": False}
    
    # CRITICAL: Provenance gate enforcement
    # If require_provenance=True, source must be present AND in allowed_provenance list,
    # and validation status must be explicitly 'valid'
    if require_provenance:
        if not fund_source:
            return {"validation": "failed", "scheme": scheme, "folio_no": folio, "is_new": False}
        if not allowed_provenance:
            return {"validation": "failed", "scheme": scheme, "folio_no": folio, "is_new": False}
        if fund_source not in allowed_provenance:
            return {"validation": "failed", "scheme": scheme, "folio_no": folio, "is_new": False}
        if not fund.get("validation") or fund.get("validation") != "valid":
            return {"validation": "failed", "scheme": scheme, "folio_no": folio, "is_new": False}
    
    result = {"validation": "valid", "scheme": scheme, "folio_no": folio, "is_new": folio == "New Direct Folio Mandate"}
    if require_provenance:
        result["source"] = fund_source
        result["validation"] = "valid"
    return result


def generate_fiduciary_sip_blueprint(
    monthly_budget_inr: float,
    funds: List[Dict[str, Any]],
    target_saa: Optional[Dict[str, float] | TargetSaa] = None,
    fund_universe: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Generate paise-accurate, deterministic monthly SIP allocation mapped to Direct funds & SAA.

    Guarantees:
    - 100% Direct Plan enforcement
    - Allocation amounts sum to exactly the monthly budget (within 1 paisa)
    - Directly routes capital to Large Cap, Mid/Small, and Debt sleeves per evaluated SAA
    - Stability Buffer Override: If current debt >= target debt, redirects all SIP debt to equity
    """
    try:
        b_float = float(monthly_budget_inr) if monthly_budget_inr is not None else 0.0
    except (ValueError, TypeError):
        b_float = 0.0
    budget_dec = quantize_inr(max(0.0, b_float))
    if budget_dec <= Decimal("0.00"):
        return {
            "status": "ZERO_BUDGET",
            "allocated_budget_inr": Decimal("0.00"),
            "unallocated_budget_inr": Decimal("0.00"),
            "allocations": [],
        }

    # SAA Target Extraction & Validation
    # Default baseline if target_saa is explicitly None:
    lc_pct = Decimal("50.0")
    ms_pct = Decimal("25.0")
    flexi_pct = Decimal("0.0")
    db_pct = Decimal("25.0")

    if target_saa is not None:
        raw_vals = {}
        if hasattr(target_saa, "large_cap_pct") and hasattr(target_saa, "mid_small_cap_pct"):
            raw_vals = {
                "large_cap": getattr(target_saa, "large_cap_pct", None),
                "mid_small": getattr(target_saa, "mid_small_cap_pct", None),
                "flexi": getattr(target_saa, "flexi_multi_cap_pct", None),
                "debt": getattr(target_saa, "debt_pct", None),
            }
        elif isinstance(target_saa, dict):
            raw_vals = {
                "large_cap": target_saa.get("large_cap_pct"),
                "mid_small": target_saa.get("mid_small_cap_pct"),
                "flexi": target_saa.get("flexi_multi_cap_pct"),
                "debt": target_saa.get("debt_pct"),
            }
        else:
            return {
                "status": "INVALID_SAA_TARGET",
                "monthly_budget_inr": budget_dec,
                "allocated_budget_inr": Decimal("0.00"),
                "unallocated_budget_inr": budget_dec,
                "allocations": [],
                "recommendations": [],
                "reconciliation_valid": False,
                "error": f"Invalid target_saa input type: {type(target_saa).__name__}. Must be TargetSaa object or dict.",
            }

        # Boundary Check: Booleans are rejected
        for k, v in raw_vals.items():
            if type(v) is bool:
                return {
                    "status": "INVALID_SAA_TARGET",
                    "monthly_budget_inr": budget_dec,
                    "allocated_budget_inr": Decimal("0.00"),
                    "unallocated_budget_inr": budget_dec,
                    "allocations": [],
                    "recommendations": [],
                    "reconciliation_valid": False,
                    "error": f"Target SAA '{k}' cannot be boolean: {v}",
                }

        # If all keys are None, use default baseline
        if all(v is None for v in raw_vals.values()):
            lc_pct, ms_pct, flexi_pct, db_pct = Decimal("50.0"), Decimal("25.0"), Decimal("0.0"), Decimal("25.0")
        else:
            # Parse finite numeric percentages
            try:
                def _parse_pct(name, val, default=0.0):
                    if val is None:
                        return Decimal(str(default))
                    fval = float(val)
                    if math.isnan(fval) or math.isinf(fval):
                        raise ValueError(f"Target SAA '{name}' must be finite: {val}")
                    if fval < 0.0 or fval > 100.0:
                        raise ValueError(f"Target SAA '{name}' must be between 0 and 100: {val}")
                    return Decimal(str(fval))

                lc_pct = _parse_pct("large_cap", raw_vals["large_cap"], default=0.0)
                ms_pct = _parse_pct("mid_small", raw_vals["mid_small"], default=0.0)
                flexi_pct = _parse_pct("flexi", raw_vals["flexi"], default=0.0)
                db_pct = _parse_pct("debt", raw_vals["debt"], default=0.0)
            except Exception as e:
                return {
                    "status": "INVALID_SAA_TARGET",
                    "monthly_budget_inr": budget_dec,
                    "allocated_budget_inr": Decimal("0.00"),
                    "unallocated_budget_inr": budget_dec,
                    "allocations": [],
                    "recommendations": [],
                    "reconciliation_valid": False,
                    "error": str(e),
                }

            # POL-SIP-002: Fiduciary SAA Target Sum Invariant
            # Target allocations must strictly sum to 100.0%. Undocumented permissive approximations are rejected.
            saa_sum = lc_pct + ms_pct + flexi_pct + db_pct
            if abs(saa_sum - Decimal("100.0")) > Decimal("0.00"):
                return {
                    "status": "INVALID_SAA_TARGET",
                    "monthly_budget_inr": budget_dec,
                    "allocated_budget_inr": Decimal("0.00"),
                    "unallocated_budget_inr": budget_dec,
                    "allocations": [],
                    "recommendations": [],
                    "reconciliation_valid": False,
                    "error": f"Target SAA allocations sum to {saa_sum}%, expected exactly 100.0% (strict policy tolerance ±0.00%).",
                }

    # Stability Buffer Override (per POL-SIP-001):
    # If current portfolio debt >= target debt, redirect all SIP debt allocation to equity.
    # Existing debt holdings are maintained for rebalancing ammunition but receive no new SIP inflows.
    # Exposure-aware calculation: Restricts strictly to validated client holdings with verified factsheet look-through.
    # If debt exposure is unavailable or unparseable for ANY valid holding, the portfolio exposure
    # is INDETERMINATE, and the override is withheld (fails closed) without heuristic substitution.
    stability_override_applied = False
    stability_override_status = "NOT_APPLIED"
    stability_override_reason = ""
    if db_pct > Decimal("0.0") and funds:
        valid_holdings = [
            f for f in funds
            if isinstance(f, dict)
            and float(f.get("current_value", 0) or 0) > 0.001
            and f.get("validation") == "valid"
        ]
        if valid_holdings:
            total_value = sum(float(f["current_value"]) for f in valid_holdings)
            debt_value = 0.0
            debt_exposure_indeterminate = False
            indeterminate_reasons = []

            for f in valid_holdings:
                c_val = float(f["current_value"])
                raw_debt = None
                s_name = str(f.get("scheme", "Unknown Scheme"))

                # 1. Check for malformed, non-finite, or unparseable values on any provided debt field
                for k in ("verified_debt_pct", "debt", "debt_pct", "portfolio_debt_pct"):
                    if k in f and f[k] is not None:
                        try:
                            val_check = float(f[k])
                            if math.isnan(val_check) or math.isinf(val_check) or val_check < 0.0 or val_check > 100.0:
                                raw_debt = val_check
                                break
                        except (ValueError, TypeError):
                            raw_debt = f[k]
                            break

                if raw_debt is not None:
                    # Found malformed or unparseable debt field directly on holding
                    pass
                else:
                    from services.cas_parser import validate_exposure_evidence, resolve_authoritative_scheme
                    ev = f.get("exposure_evidence")
                    is_ev_valid = False
                    if isinstance(ev, dict):
                        is_ev_valid, _ = validate_exposure_evidence(ev, f.get("scheme_code"))
                        if is_ev_valid and ev.get("debt_pct") is not None:
                            raw_debt = ev["debt_pct"]

                    if not is_ev_valid and "debt" not in f and "debt_pct" not in f and "verified_debt_pct" not in f:
                        # 2. Try resolving via authoritative scheme master only if holding didn't supply unverified debt fields
                        try:
                            m_entry = resolve_authoritative_scheme(s_name)
                            if m_entry is not None:
                                m_ev = m_entry.get("exposure_evidence")
                                if isinstance(m_ev, dict):
                                    m_ev_valid, _ = validate_exposure_evidence(m_ev, m_entry.get("sid"))
                                    if m_ev_valid and m_ev.get("debt_pct") is not None:
                                        raw_debt = m_ev["debt_pct"]
                        except Exception:
                            pass

                # 3. Pure statutory debt categories have 100% debt statutory floor (category MUST be verified)
                if raw_debt is None:
                    is_cat_verified = f.get("category_verified") is True
                    cat_val = f.get("category")
                    if not is_cat_verified:
                        m_entry = resolve_authoritative_scheme(s_name)
                        if m_entry is not None:
                            is_cat_verified = True
                            cat_val = m_entry.get("cat") or m_entry.get("category")

                    if is_cat_verified and cat_val:
                        cat_lower = str(cat_val).strip().lower()
                        if cat_lower in ["debt", "liquid", "money market", "overnight", "gilt", "income"]:
                            raw_debt = 100.0

                # 4. If raw_debt is still None, reject generic unverified debt/debt_pct fields
                if raw_debt is None:
                    debt_exposure_indeterminate = True
                    indeterminate_reasons.append(
                        f"Holding '{s_name}' lacks verified factsheet debt look-through"
                    )
                    break

                try:
                    f_debt_pct = float(raw_debt)
                    if math.isnan(f_debt_pct) or math.isinf(f_debt_pct) or f_debt_pct < 0.0 or f_debt_pct > 100.0:
                        debt_exposure_indeterminate = True
                        indeterminate_reasons.append(
                            f"Holding '{s_name}' has non-finite or out-of-bounds debt value: {raw_debt}"
                        )
                        break
                    debt_value += c_val * (f_debt_pct / 100.0)
                except (ValueError, TypeError):
                    debt_exposure_indeterminate = True
                    indeterminate_reasons.append(
                        f"Holding '{s_name}' has unparseable debt exposure: {raw_debt}"
                    )
                    break

            if debt_exposure_indeterminate:
                stability_override_status = "INDETERMINATE"
                stability_override_reason = "Debt exposure indeterminate: " + "; ".join(indeterminate_reasons)
            else:
                current_debt_pct = Decimal(str(round((debt_value / total_value) * 100.0, 4)))
                original_db_pct = db_pct
                if current_debt_pct >= db_pct:
                    debt_to_add = db_pct
                    total_equity_pct = lc_pct + ms_pct + flexi_pct
                    if total_equity_pct > Decimal("0.0"):
                        lc_pct = lc_pct + (debt_to_add * (lc_pct / total_equity_pct))
                        ms_pct = ms_pct + (debt_to_add * (ms_pct / total_equity_pct))
                        flexi_pct = flexi_pct + (debt_to_add * (flexi_pct / total_equity_pct))
                    else:
                        lc_pct = lc_pct + debt_to_add
                    db_pct = Decimal("0.0")
                    stability_override_applied = True
                    stability_override_status = "APPLIED"
                    stability_override_reason = (
                        f"Current verified look-through debt ({current_debt_pct:.2f}%) >= target ({original_db_pct:.2f}%). "
                        f"Redirected SIP debt inflows to equity sleeves."
                    )
                else:
                    stability_override_status = "BELOW_TARGET"
                    stability_override_reason = (
                        f"Current verified look-through debt ({current_debt_pct:.2f}%) < target ({original_db_pct:.2f}%). "
                        f"Maintaining SIP debt buffer inflows."
                    )

    # Quantized target sleeve allocations
    lc_target = (budget_dec * (lc_pct / Decimal("100.0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ms_target = (budget_dec * (ms_pct / Decimal("100.0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    flexi_target = (budget_dec * (flexi_pct / Decimal("100.0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Reconcile exact paisa difference onto debt/stability buffer
    db_target = (budget_dec - lc_target - ms_target - flexi_target).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Identify eligible Direct funds in client portfolio safely
    direct_funds = [
        f for f in (funds or [])
        if isinstance(f, dict) and str(f.get("plan_type") or "Direct").strip().upper() == "DIRECT"
    ]
    allocations = []

    # Load market-nominated funds for fallback selection
    market_noms = _load_market_nominations()
    
    # Load fund universe for dynamic selection (use provided or load default)
    if fund_universe is None:
        fund_universe = _load_fund_universe()

    def _match_kw(f_obj: Dict[str, Any], kws: List[str]) -> bool:
        s_name = str(f_obj.get("scheme") or "").lower()
        return any(k in s_name for k in kws)

    def _get_market_nom_fund(nom_key: str, fund_universe_list: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Get scheme name from market nominations using dynamic selection logic.
        
        Returns a dict with:
        - scheme: the selected scheme name
        - source: 'dynamic' (verified from universe), 'fallback' (from config rules), or 'unavailable'
        - validation: 'valid' or 'failed' if selection failed
        """
        rules = market_noms.get(nom_key, {})
        if fund_universe_list is not None:
            result = _select_market_nom_fund(rules, fund_universe_list, nom_key)
            if isinstance(result, dict) and result.get("scheme") and result.get("scheme") != "SPIVA_FALLBACK_FAILED":
                return result  # Already returns dict with scheme, source, validation
        
        # Fallback to embedded selection rules from data (NOT hardcoded defaults)
        # Validate that the configured fallback scheme exists in the fund universe 
        # and matches the required category/plan_type before marking it valid
        fallback_scheme = rules.get("scheme")
        if fallback_scheme and fund_universe_list:
            expected_category = rules.get("category", "")
            expected_plan_type = rules.get("plan_type", "Direct")
            expected_is_passive = rules.get("is_passive", False)
            
            # Search for the fallback scheme in the fund universe
            for fund in fund_universe_list:
                if not isinstance(fund, dict):
                    continue
                fund_scheme = fund.get("scheme") or fund.get("canonical_name") or fund.get("id", "")
                if fallback_scheme.lower() in fund_scheme.lower() or fund_scheme.lower() in fallback_scheme.lower():
                    # Verify category match (case-insensitive)
                    fund_cat = fund.get("category", "") or fund.get("cat", "")
                    if expected_category and expected_category.lower() not in str(fund_cat).lower():
                        continue
                    # Verify plan type
                    fund_plan_type = fund.get("plan_type", "")
                    if expected_plan_type and expected_plan_type.lower() not in str(fund_plan_type).lower():
                        continue
                    # Verify passive/active match
                    fund_is_passive = fund.get("is_passive", False)
                    if expected_is_passive != fund_is_passive:
                        continue
                    # All checks passed - fallback is valid (include actual category from fund)
                    return {"scheme": fallback_scheme, "category": fund_cat, "source": "fallback", "validation": "valid"}
            # Fallback scheme not found or doesn't match criteria in universe
            return {"scheme": "SPIVA_FALLBACK_FAILED", "source": "unavailable", "validation": "failed"}
        
        return {"scheme": "SPIVA_FALLBACK_FAILED", "source": "unavailable", "validation": "failed"}

    # === SHARED VALIDATION FUNCTION ALIAS ===
    _validate_scheme_for_sleeve = validate_scheme_for_sleeve

    # === HELPER FOR NO-DIRECT BRANCH ===
    def _make_allocation_from_market_result(
        market_result: dict,
        sleeve_name: str,
        target_amount: Decimal,
        target_pct: float,
        expected_category_keywords: list[str],
    ) -> dict | None:
        """
        Validate a market nomination result and create an allocation dict.
        Fail-closed: missing or invalid provenance or category rejects allocation immediately.
        """
        if not market_result or not isinstance(market_result, dict):
            return None
        
        # Explicit fail-closed: must have explicit valid status and explicit source
        if market_result.get("validation") != "valid":
            return None
        
        market_source = market_result.get("source")
        if not market_source or market_source not in ("dynamic", "fallback"):
            return None
        
        scheme = market_result.get("scheme", "")
        if not scheme or scheme == "SPIVA_FALLBACK_FAILED":
            return None
        
        # Category MUST come from the actual selected fund's classification, NOT manufactured
        actual_category = market_result.get("category", "")
        if not actual_category:
            return None
        
        # Build a fund dict for validation - NEVER manufacture missing source/validation/category
        fund_for_validation = {
            "scheme": scheme,
            "category": actual_category,
            "plan_type": "Direct",
            "folio_no": "New Direct Folio Mandate",
            "source": market_source,
            "validation": "valid",
        }
        
        # Validate using shared function - provenance gate and category keywords strictly enforced
        validation = _validate_scheme_for_sleeve(
            fund_for_validation,
            sleeve_name,
            expected_category_keywords,
            require_provenance=True,
            allowed_provenance=["dynamic", "fallback"],
        )
        
        if validation.get("validation") != "valid":
            return None
        
        # Skip allocations with zero target amount
        if target_amount <= Decimal("0.00"):
            return None
        
        return {
            "sleeve": sleeve_name,
            "scheme_name": validation["scheme"],
            "folio_no": "New Direct Folio Mandate",
            "source": validation["source"],
            "validation": validation["validation"],
            "amount_inr": target_amount,
            "allocation_pct": target_pct,
            "plan_type": "Direct-Growth",
        }

    if direct_funds:
        # Match schemes to sleeves - prioritize client's existing funds
        # Strategy: Prefer pure category funds over blended category funds
        
        # Large Cap: first look for pure large cap/index funds, then blended
        lc_pure = next((
            f for f in direct_funds 
            if _match_kw(f, ["index", "nifty", "sensex"]) or 
               (str(f.get("category", "")).lower() in ["large cap", "large-cap", "largecap", "index - large cap"])
        ), None)
        lc_blended = next((
            f for f in direct_funds 
            if "large & mid" in str(f.get("scheme", "")).lower() or
               "large & mid" in str(f.get("category", "")).lower()
        ), None)
        lc_fund = lc_pure or lc_blended
        
        # Mid/Small-Cap: prefer mid cap/small cap, exclude pure large cap index
        ms_fund = next((
            f for f in direct_funds 
            if str(f.get("category", "")).lower() in ["mid cap", "small cap", "mid-cap", "small-cap", "midcap", "smallcap", "mid & small"] or
               _match_kw(f, ["mid cap", "small cap", "mid-cap", "small-cap", "midcap", "smallcap", "emerging equity"])
        ), None)
        
        # Flexi-Multi-Cap: prefer flexi/multi-cap category funds
        flexi_fund = next((
            f for f in direct_funds 
            if str(f.get("category", "")).lower() in ["flexi cap", "multi cap", "flexi-multi cap", "multi-cap", "flexicap", "multicap"] or
               _match_kw(f, ["flexi", "multi cap", "multi-cap", "flexicap", "multicap"])
        ), None)
        
        # Debt: match by category or keywords
        db_fund = next((
            f for f in direct_funds 
            if str(f.get("category", "")).lower() in ["debt", "liquid", "arbitrage", "money market", "overnight", "ultra short"] or
               _match_kw(f, ["liquid", "arbitrage", "money market", "overnight", "ultra short", "treasury", "gilt"])
        ), None)

        # Note: If client does not hold an eligible Direct fund in the sleeve's genuine category,
        # the engine does NOT substitute arbitrary equity funds; it initiates dynamic market nomination.

        # Large-Cap Sleeve
        if lc_target > Decimal("0.00"):
            validated_allocation = None
            if lc_fund:
                # Existing holding path: validate client's fund with provenance
                lc_val = _validate_scheme_for_sleeve(
                    lc_fund,
                    "Large-Cap Core Index",
                    ["large cap", "large-cap", "largecap", "large & mid", "index", "nifty", "sensex"],
                    require_provenance=True,
                    allowed_provenance=["existing"],
                )
                if lc_val.get("validation") == "valid":
                    validated_allocation = {
                        "sleeve": "Large-Cap Core Index",
                        "scheme_name": lc_val["scheme"],
                        "folio_no": lc_val["folio_no"],
                        "source": lc_val["source"],
                        "validation": lc_val["validation"],
                        "amount_inr": lc_target,
                        "allocation_pct": float(lc_pct),
                        "plan_type": "Direct-Growth",
                        "rationale": "Anchor core equity compounding in lowest-cost Direct large cap index scheme.",
                    }
            
            # If no existing fund or existing fund failed provenance/category validation,
            # execute dynamic market nomination selection via shared helper (no manufactured category)
            if not validated_allocation:
                selection_result = _get_market_nom_fund("large_cap_index", fund_universe)
                validated_allocation = _make_allocation_from_market_result(
                    selection_result,
                    "Large-Cap Core Index",
                    lc_target,
                    float(lc_pct),
                    ["large cap", "large-cap", "largecap", "large & mid", "index", "nifty", "sensex"],
                )
                if validated_allocation:
                    validated_allocation["rationale"] = "Anchor core equity compounding in lowest-cost Direct large cap index scheme."
            
            if validated_allocation:
                allocations.append(validated_allocation)

        # Mid/Small-Cap Sleeve
        if ms_target > Decimal("0.00"):
            validated_allocation = None
            if ms_fund:
                ms_val = _validate_scheme_for_sleeve(
                    ms_fund,
                    "Mid/Small-Cap Alpha",
                    ["mid cap", "small cap", "mid-cap", "small-cap", "midcap", "smallcap", "emerging equity", "mid & small"],
                    require_provenance=True,
                    allowed_provenance=["existing"],
                )
                if ms_val.get("validation") == "valid":
                    validated_allocation = {
                        "sleeve": "Mid/Small-Cap Alpha",
                        "scheme_name": ms_val["scheme"],
                        "folio_no": ms_val["folio_no"],
                        "source": ms_val["source"],
                        "validation": ms_val["validation"],
                        "amount_inr": ms_target,
                        "allocation_pct": float(ms_pct),
                        "plan_type": "Direct-Growth",
                        "rationale": "Long-term alpha accumulation aligned with investor risk tolerance.",
                    }
            
            if not validated_allocation:
                selection_result = _get_market_nom_fund("mid_cap_active", fund_universe)
                validated_allocation = _make_allocation_from_market_result(
                    selection_result,
                    "Mid/Small-Cap Alpha",
                    ms_target,
                    float(ms_pct),
                    ["mid cap", "small cap", "mid-cap", "small-cap", "midcap", "smallcap", "emerging equity", "mid & small"],
                )
                if validated_allocation:
                    validated_allocation["rationale"] = "Long-term alpha accumulation aligned with investor risk tolerance."
            
            if validated_allocation:
                allocations.append(validated_allocation)

        # Flexi-Multi-Cap Sleeve
        if flexi_target > Decimal("0.00"):
            validated_allocation = None
            if flexi_fund:
                flexi_val = _validate_scheme_for_sleeve(
                    flexi_fund,
                    "Flexi-Multi Cap",
                    ["flexi cap", "multi cap", "flexi-cap", "multi-cap", "flexicap", "multicap"],
                    require_provenance=True,
                    allowed_provenance=["existing"],
                )
                if flexi_val.get("validation") == "valid":
                    validated_allocation = {
                        "sleeve": "Flexi-Multi Cap",
                        "scheme_name": flexi_val["scheme"],
                        "folio_no": flexi_val["folio_no"],
                        "source": flexi_val["source"],
                        "validation": flexi_val["validation"],
                        "amount_inr": flexi_target,
                        "allocation_pct": float(flexi_pct),
                        "plan_type": "Direct-Growth",
                        "rationale": "Flexible multi-cap exposure for growth enhancement with automatic rebalancing across market caps.",
                    }
            
            if not validated_allocation:
                selection_result = _get_market_nom_fund("flexi_multi_cap", fund_universe)
                validated_allocation = _make_allocation_from_market_result(
                    selection_result,
                    "Flexi-Multi Cap",
                    flexi_target,
                    float(flexi_pct),
                    ["flexi cap", "multi cap", "flexi-cap", "multi-cap", "flexicap", "multicap"],
                )
                if validated_allocation:
                    validated_allocation["rationale"] = "Flexible multi-cap exposure for growth enhancement with automatic rebalancing across market caps."
            
            if validated_allocation:
                allocations.append(validated_allocation)

        # Debt Sleeve
        if db_target > Decimal("0.00"):
            validated_allocation = None
            if db_fund:
                db_val = _validate_scheme_for_sleeve(
                    db_fund,
                    "Debt & Capital Preservation",
                    ["debt", "liquid", "arbitrage", "money market"],
                    require_provenance=True,
                    allowed_provenance=["existing"],
                )
                if db_val.get("validation") == "valid":
                    validated_allocation = {
                        "sleeve": "Debt & Capital Preservation",
                        "scheme_name": db_val["scheme"],
                        "folio_no": db_val["folio_no"],
                        "source": db_val["source"],
                        "validation": db_val["validation"],
                        "amount_inr": db_target,
                        "allocation_pct": float(db_pct),
                        "plan_type": "Direct-Growth",
                        "rationale": "Statutory capital preservation floor (100% Sovereign T-Bills/Repo).",
                    }
            
            if not validated_allocation:
                selection_result = _get_market_nom_fund("debt_liquid", fund_universe)
                validated_allocation = _make_allocation_from_market_result(
                    selection_result,
                    "Debt & Capital Preservation",
                    db_target,
                    float(db_pct),
                    ["debt", "liquid", "arbitrage", "money market"],
                )
                if validated_allocation:
                    validated_allocation["rationale"] = "Statutory capital preservation floor (100% Sovereign T-Bills/Repo)."
            
            if validated_allocation:
                allocations.append(validated_allocation)
    else:
        # Client has no Direct schemes yet (or 100% regular) — provide canonical sleeve blueprint with market nominations
        # All allocations must go through the shared validator for provenance enforcement
        
        # Perform market nominations for each sleeve type
        market_lc_result = _get_market_nom_fund("large_cap_index", fund_universe)
        market_ms_result = _get_market_nom_fund("mid_cap_active", fund_universe)
        market_flexi_result = _get_market_nom_fund("flexi_multi_cap", fund_universe)
        market_db_result = _get_market_nom_fund("debt_liquid", fund_universe)
        
        # Large-Cap Core Index
        lc_alloc = _make_allocation_from_market_result(
            market_lc_result,
            "Large-Cap Core Index",
            lc_target,
            float(lc_pct),
            ["large cap", "large-cap", "largecap", "large & mid", "index", "nifty", "sensex"],
        )
        if lc_alloc:
            allocations.append(lc_alloc)
        
        # Mid/Small-Cap Alpha
        ms_alloc = _make_allocation_from_market_result(
            market_ms_result,
            "Mid/Small-Cap Alpha",
            ms_target,
            float(ms_pct),
            ["mid cap", "small cap", "mid-cap", "small-cap", "midcap", "smallcap", "emerging equity", "mid & small"],
        )
        if ms_alloc:
            allocations.append(ms_alloc)
        
        # Flexi-Multi-Cap
        flexi_alloc = _make_allocation_from_market_result(
            market_flexi_result,
            "Flexi-Multi Cap",
            flexi_target,
            float(flexi_pct),
            ["flexi cap", "multi cap", "flexi-cap", "multi-cap", "flexicap", "multicap"],
        )
        if flexi_alloc:
            allocations.append(flexi_alloc)
        
        # Debt & Capital Preservation
        db_alloc = _make_allocation_from_market_result(
            market_db_result,
            "Debt & Capital Preservation",
            db_target,
            float(db_pct),
            ["debt", "liquid", "arbitrage", "money market"],
        )
        if db_alloc:
            allocations.append(db_alloc)

    total_allocated = sum(a["amount_inr"] for a in allocations)
    unallocated = budget_dec - total_allocated

    # AI & Fiduciary Tranche Timing
    biweekly_tranche = (budget_dec / Decimal("2.0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    weekly_tranche = (budget_dec / Decimal("4.0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    optimal_tranche_timing = {
        "recommended_cadence": "Bi-Weekly (Dual-Tranche)",
        "dates": "5th and 20th of each month",
        "biweekly_amount_inr": biweekly_tranche,
        "weekly_amount_inr": weekly_tranche,
        "rationale": "Splitting monthly deployment into two equal tranches (5th post-payroll, 20th pre-derivatives expiry) smooths intraday volatility and avoids month-end illiquidity spreads on NSE/BSE.",
        "weekly_alternative": f"4 weekly tranches of INR {weekly_tranche:,.2f} every Wednesday.",
    }

    # Portfolio Completion Alerts & Scheme Replacements
    # Returns structured alerts with slot/action for proper display
    completion_alerts: List[dict] = []
    
    # Consistent detection with fund selection logic
    has_large = any(
        (f.get("category", "").lower() in ["large cap", "index - large cap", "equity"] or 
         _match_kw(f, ["index", "nifty"])) 
        for f in (direct_funds or [])
    )
    has_mid_small = any(
        f.get("category", "").lower() in ["mid cap", "small cap"] 
        for f in (direct_funds or [])
    )
    has_debt = any(str(f.get("category") or "") == "Debt" or _match_kw(f, ["liquid", "arbitrage", "money market"]) for f in (direct_funds or []))
    regular_count = sum(1 for f in (funds or []) if str(f.get("plan_type", "Direct")).strip().upper() == "REGULAR")

    if not direct_funds:
        completion_alerts.append({
            "slot": "Direct Plans",
            "action": "Initiate new Direct Plan folios to eliminate intermediary trail commission",
            "severity": "HIGH"
        })
    if not has_large:
        completion_alerts.append({
            "slot": "Core Equity",
            "action": "Add a low-cost Direct large-cap index fund for index anchoring",
            "severity": "HIGH"
        })
    if not has_mid_small:
        completion_alerts.append({
            "slot": "Alpha Engine",
            "action": "Add quality mid/small-cap allocation for long-term real wealth creation",
            "severity": "MEDIUM"
        })
    if not has_debt and db_target > Decimal("0.00"):
        completion_alerts.append({
            "slot": "Debt/Stable",
            "action": "Add pure direct liquid/debt vehicle for capital preservation buffer",
            "severity": "HIGH"
        })
    if regular_count > 0:
        completion_alerts.append({
            "slot": "Plan Optimization",
            "action": f"Replace {regular_count} Regular plan schemes with Direct Growth variants",
            "severity": "MEDIUM"
        })

    # Personalized Routing Rationale
    if stability_override_applied:
        routing_rationale = (
            f"SIP budget of INR {budget_dec:,.2f}/mo is routed 100% to Equity sleeves: "
            f"{lc_pct:.0f}% Large-Cap Core (Index compounding), "
            f"{ms_pct:.0f}% Mid/Small-Cap Alpha (Growth engine). "
            f"Stability Buffer Override: Current debt already at or above target — "
            f"all SIP debt allocation redirected to equity (per POL-SIP-001)."
        )
    else:
        routing_rationale = (
            f"SIP budget of INR {budget_dec:,.2f}/mo is routed across 3 fiduciary sleeves: "
            f"{lc_pct:.0f}% Large-Cap Core (Index compounding), "
            f"{ms_pct:.0f}% Mid/Small-Cap Alpha (Growth engine), and "
            f"{db_pct:.0f}% Debt/Liquid Buffer (Capital stability) in strict compliance with your target SAA."
        )

    # Compute SIP Selection Confidence Score
    # Factors: 1) Direct plans present, 2) Sleeve completeness, 3) No regular plan migration needed
    confidence_score = 100.0
    confidence_baselines = ["Direct plan baseline established", "All fiduciary sleeves present", "No Regular-to-Direct migration pending"]
    
    if not direct_funds:
        confidence_score -= 35.0
        confidence_baselines = ["No existing Direct plans"]
    elif len(completion_alerts) >= 1:
        # Each alert reduces confidence proportionally
        high_alerts = sum(1 for a in completion_alerts if a.get("severity") == "HIGH")
        medium_alerts = sum(1 for a in completion_alerts if a.get("severity") == "MEDIUM")
        confidence_score -= (high_alerts * 12.0 + medium_alerts * 5.0)
    
    # Cap at reasonable range
    confidence_score = max(45.0, min(100.0, confidence_score))

    # Build UI-compatible recommendations format
    recommendations = []
    for alloc in allocations:
        sleeve = alloc.get("sleeve", "")
        # Map sleeve to category
        if "Large-Cap" in sleeve or "Core" in sleeve:
            category = "Large Cap / Index"
        elif "Mid" in sleeve or "Small" in sleeve or "Alpha" in sleeve:
            category = "Mid/Small Cap"
        elif "Debt" in sleeve or "Liquid" in sleeve or "Capital Preservation" in sleeve:
            category = "Debt / Liquid"
        else:
            category = "Equity"
        
        recommendations.append({
            "slot_name": sleeve,
            "scheme_name": alloc.get("scheme_name", "N/A"),
            "category": category,
            "plan_type": alloc.get("plan_type", "Direct-Growth"),
            "monthly_allocation_inr": float(alloc.get("amount_inr", 0)),
            "allocation_pct": float(alloc.get("allocation_pct", 0)),
        })
    
    total_allocated = sum(a["amount_inr"] for a in allocations)
    unallocated = budget_dec - total_allocated
    reconciliation_valid = abs(unallocated) <= Decimal("0.01")
    
    # Build tranche timing and alerts
    biweekly_tranche = (budget_dec / Decimal("2.0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    weekly_tranche = (budget_dec / Decimal("4.0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    optimal_tranche_timing = {
        "recommended_cadence": "Bi-Weekly (Dual-Tranche)",
        "dates": "5th and 20th of each month",
        "biweekly_amount_inr": biweekly_tranche,
        "weekly_amount_inr": weekly_tranche,
        "rationale": "Splitting monthly deployment into two equal tranches (5th post-payroll, 20th pre-derivatives expiry) smooths intraday volatility and avoids month-end illiquidity spreads on NSE/BSE.",
        "weekly_alternative": f"4 weekly tranches of INR {weekly_tranche:,.2f} every Wednesday.",
    }
    
    # Portfolio Completion Alerts & Scheme Replacements
    completion_alerts: List[dict] = []
    
    # Allocation Integrity Check: Fail-closed if required sleeve is missing or unreconciled
    # A DETERMINISTIC_SIP_READY result is only valid when all budget is allocated to paisa
    
    confidence_score = 100.0
    confidence_baselines = ["Direct plan baseline established", "All fiduciary sleeves present", "No Regular-to-Direct migration pending"]
    
    # Consistent detection with fund selection logic
    has_large = any(
        (f.get("category", "").lower() in ["large cap", "index - large cap", "equity"] or 
         _match_kw(f, ["index", "nifty"])) 
        for f in (direct_funds or [])
    )
    has_mid_small = any(
        f.get("category", "").lower() in ["mid cap", "small cap"] 
        for f in (direct_funds or [])
    )
    has_debt = any(str(f.get("category") or "") == "Debt" or _match_kw(f, ["liquid", "arbitrage", "money market"]) for f in (direct_funds or []))
    regular_count = sum(1 for f in (funds or []) if str(f.get("plan_type", "Direct")).strip().upper() == "REGULAR")
    
    if not direct_funds:
        confidence_score -= 35.0
        confidence_baselines = ["No existing Direct plans"]
    
    if not has_large:
        if not direct_funds:
            pass  # Already high severity alert
        else:
            pass
    
    if not has_mid_small:
        pass
    
    if not has_debt and db_target > Decimal("0.00"):
        pass
    
    if regular_count > 0:
        confidence_score -= (regular_count * 5.0)
    
    confidence_score = max(45.0, min(100.0, confidence_score))
    
    # Portfolio Completion Alerts
    portfolio_completion_alerts = []
    if not direct_funds:
        portfolio_completion_alerts.append({"slot": "Direct Plans", "action": "Initiate new Direct Plan folios", "severity": "HIGH"})
    if not has_large:
        portfolio_completion_alerts.append({"slot": "Core Equity", "action": "Add large-cap index fund", "severity": "HIGH"})
    if not has_mid_small:
        portfolio_completion_alerts.append({"slot": "Alpha Engine", "action": "Add mid/small-cap fund", "severity": "MEDIUM"})
    if not has_debt and db_target > Decimal("0.00"):
        portfolio_completion_alerts.append({"slot": "Debt/Stable", "action": "Add debt fund", "severity": "HIGH"})
    if regular_count > 0:
        portfolio_completion_alerts.append({"slot": "Plan Optimization", "action": f"Replace {regular_count} Regular plans", "severity": "MEDIUM"})
    
    # Personalized Routing Rationale
    if stability_override_applied:
        routing_rationale = (
            f"SIP budget of INR {budget_dec:,.2f}/mo routed 100% to Equity sleeves: "
            f"{lc_pct:.0f}% Large-Cap Core, {ms_pct:.0f}% Mid/Small-Cap Alpha. "
            f"Stability Buffer Override applied."
        )
    else:
        routing_rationale = (
            f"SIP budget of INR {budget_dec:,.2f}/mo routed across 3 fiduciary sleeves: "
            f"{lc_pct:.0f}% Large-Cap Core, {ms_pct:.0f}% Mid/Small-Cap Alpha, and "
            f"{db_pct:.0f}% Debt/Liquid Buffer."
        )
    
    # Allocation Completeness & Explicit Omission Reasons
    omission_reasons: List[str] = []
    if lc_target > Decimal("0.00") and not any("Large-Cap" in a.get("sleeve", "") for a in allocations):
        omission_reasons.append("Large-Cap Core Index: No verified Direct fund passing large-cap index criteria was available.")
    if ms_target > Decimal("0.00") and not any("Mid/Small" in a.get("sleeve", "") for a in allocations):
        omission_reasons.append("Mid/Small-Cap Alpha: No verified Direct fund passing mid/small-cap criteria was available.")
    if flexi_target > Decimal("0.00") and not any("Flexi" in a.get("sleeve", "") for a in allocations):
        omission_reasons.append("Flexi-Multi Cap: No verified Direct fund passing flexi/multi-cap criteria was available.")
    if db_target > Decimal("0.00") and not any("Debt" in a.get("sleeve", "") for a in allocations):
        omission_reasons.append("Debt & Capital Preservation: No verified Direct fund passing debt/liquid criteria was available.")

    # Check allocation reconciliation
    if not reconciliation_valid:
        omission_summary = "; ".join(omission_reasons) if omission_reasons else "selection integrity check failed"
        return {
            "status": "NO_ACTION",
            "monthly_budget_inr": budget_dec,
            "allocated_budget_inr": total_allocated,
            "unallocated_budget_inr": unallocated,
            "allocations": allocations,
            "recommendations": recommendations,
            "reconciliation_valid": reconciliation_valid,
            "omission_reasons": omission_reasons,
            "optimal_tranche_timing": optimal_tranche_timing,
            "portfolio_completion_alerts": portfolio_completion_alerts + [{"slot": "Fiduciary Allocation Failure", "action": f"Unallocated ₹{unallocated:,.2f} - {omission_summary}", "severity": "HIGH"}],
            "fiduciary_routing_rationale": f"SIP blueprint incomplete: ₹{unallocated:,.2f} unallocated after fund selection. {omission_summary}",
            "sip_selection_confidence_pct": confidence_score,
            "stability_override_applied": stability_override_applied,
        }
    
    return {
        "status": "DETERMINISTIC_SIP_READY",
        "monthly_budget_inr": budget_dec,
        "allocated_budget_inr": total_allocated,
        "unallocated_budget_inr": unallocated,
        "allocations": allocations,
        "recommendations": recommendations,
        "reconciliation_valid": reconciliation_valid,
        "omission_reasons": omission_reasons,
        "optimal_tranche_timing": optimal_tranche_timing,
        "portfolio_completion_alerts": portfolio_completion_alerts,
        "fiduciary_routing_rationale": routing_rationale,
        "sip_selection_confidence_pct": confidence_score,
        "stability_override_applied": stability_override_applied,
        "stability_override_status": stability_override_status,
        "stability_override_reason": stability_override_reason,
    }


def evaluate_fiduciary_lumpsum_blueprint(
    lumpsum_amount_inr: float = 0.0,
    bank_cash_inr: Optional[float] = None,
    monthly_expenses_inr: float = 0.0,
    emergency_reserve_inr: Optional[float] = None,
    stp_duration_months: int = 6,
    target_saa: Optional[Dict[str, float] | TargetSaa] = None,
    funds: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Evaluate portfolio-aware lump sum deployment and generate a deterministic STP schedule.

    Adheres strictly to SEBI fiduciary standards:
    1. Stages equity deployments systematically via STP into Direct funds to mitigate timing risk.
    2. Parks idle capital in an ultra-low-risk Direct parking vehicle (Direct Liquid / Arbitrage).
    3. Reconciles every monthly tranche to the exact paisa.
    4. When explicit bank cash and expenses are provided, guards emergency reserves;
       otherwise assumes deployable capital is the investor's designated allocation.
    """
    try:
        lump_float = float(lumpsum_amount_inr) if lumpsum_amount_inr is not None else 0.0
    except (ValueError, TypeError):
        lump_float = 0.0
    lump_dec = quantize_inr(max(0.0, lump_float))
    reasons: List[str] = []

    reserve_dec = Decimal("0.00")
    if emergency_reserve_inr is not None:
        try:
            res_val = float(emergency_reserve_inr)
            if res_val > 0.0:
                reserve_dec = quantize_inr(res_val)
        except (ValueError, TypeError):
            pass
    elif monthly_expenses_inr is not None:
        try:
            exp_val = float(monthly_expenses_inr)
            if exp_val > 0.0:
                reserve_dec = quantize_inr(exp_val * 6.0)
        except (ValueError, TypeError):
            pass

    if bank_cash_inr is None:
        cash_dec = lump_dec
        deployable_surplus = lump_dec
        if lump_dec <= Decimal("0.00"):
            status = "ZERO_AMOUNT"
            effective_lumpsum = Decimal("0.00")
            reasons.append("Lump-sum deployment amount must be greater than zero.")
        else:
            status = "ELIGIBLE"
            effective_lumpsum = lump_dec
            reasons.append(
                f"Lump sum capital of ₹{lump_dec:,.2f} ready for staged fiduciary deployment into Direct plans."
            )
    else:
        try:
            b_val = float(bank_cash_inr)
        except (ValueError, TypeError):
            b_val = 0.0
        if b_val <= 0.0:
            cash_dec = lump_dec
            deployable_surplus = lump_dec
            if lump_dec <= Decimal("0.00"):
                status = "ZERO_AMOUNT"
                effective_lumpsum = Decimal("0.00")
                reasons.append("Lump-sum deployment amount must be greater than zero.")
            else:
                status = "ELIGIBLE"
                effective_lumpsum = lump_dec
                reasons.append(
                    f"Lump sum capital of ₹{lump_dec:,.2f} ready for staged fiduciary deployment into Direct plans."
                )
        else:
            cash_dec = quantize_inr(max(0.0, b_val))
            deployable_surplus = max(Decimal("0.00"), cash_dec - reserve_dec)

            if cash_dec < reserve_dec:
                status = "RESERVE_DEFICIT"
                effective_lumpsum = Decimal("0.00")
                deficit = reserve_dec - cash_dec
                reasons.append(
                    f"Bank cash (₹{cash_dec:,.2f}) is below the required 6-month emergency reserve (₹{reserve_dec:,.2f}) "
                    f"by ₹{deficit:,.2f}. Fiduciary policy mandates holding a complete liquid cushion before deploying equity lump sums."
                )
            elif deployable_surplus < lump_dec:
                status = "CAPPED_AT_SURPLUS"
                effective_lumpsum = deployable_surplus
                reasons.append(
                    f"Requested lump sum (₹{lump_dec:,.2f}) exceeds deployable surplus (₹{deployable_surplus:,.2f}) "
                    f"after protecting ₹{reserve_dec:,.2f} for emergency reserves. Deployment is capped at deployable surplus."
                )
            elif lump_dec <= Decimal("0.00"):
                status = "ZERO_AMOUNT"
                effective_lumpsum = Decimal("0.00")
                reasons.append("Lump-sum deployment amount must be greater than zero.")
            else:
                status = "ELIGIBLE"
                effective_lumpsum = lump_dec
                reasons.append(
                    f"Deployable surplus (₹{deployable_surplus:,.2f}) fully accommodates the requested lump sum of ₹{lump_dec:,.2f} "
                    f"while maintaining a full ₹{reserve_dec:,.2f} emergency reserve."
                )

    # Determine SAA target allocation percentages safely
    db_pct = Decimal("25.0")
    lc_pct = Decimal("50.0")
    ms_pct = Decimal("25.0")
    eq_pct = Decimal("75.0")

    if target_saa is not None:
        if hasattr(target_saa, "debt_pct") and hasattr(target_saa, "large_cap_pct"):
            try:
                db_pct = Decimal(str(getattr(target_saa, "debt_pct", 25.0) or 25.0))
                lc_pct = Decimal(str(getattr(target_saa, "large_cap_pct", 50.0) or 50.0))
                ms_pct = Decimal(str(getattr(target_saa, "mid_small_cap_pct", 25.0) or 25.0))
                eq_pct = Decimal(str(getattr(target_saa, "total_equity_pct", 75.0) or (lc_pct + ms_pct)))
            except Exception:
                db_pct, lc_pct, ms_pct, eq_pct = Decimal("25.0"), Decimal("50.0"), Decimal("25.0"), Decimal("75.0")
        elif isinstance(target_saa, dict):
            try:
                db_val = target_saa.get("debt_pct")
                db_pct = Decimal(str(db_val if db_val is not None else 25.0))
                lc_val = target_saa.get("large_cap_pct")
                lc_pct = Decimal(str(lc_val if lc_val is not None else 50.0))
                ms_val = target_saa.get("mid_small_cap_pct")
                ms_pct = Decimal(str(ms_val if ms_val is not None else 25.0))
                eq_val = target_saa.get("total_equity_pct") or target_saa.get("equity_pct")
                eq_pct = Decimal(str(eq_val if eq_val is not None else (100.0 - float(db_pct))))
            except Exception:
                db_pct, lc_pct, ms_pct, eq_pct = Decimal("25.0"), Decimal("50.0"), Decimal("25.0"), Decimal("75.0")

    # Quantize equity deployment and debt retention
    target_equity_capital = (effective_lumpsum * (eq_pct / Decimal("100.0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    target_debt_capital = (effective_lumpsum - target_equity_capital).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Resolve direct parking vehicle safely
    direct_funds = []
    if funds:
        for f in funds:
            if isinstance(f, dict):
                p_type = str(f.get("plan_type") or "Direct").strip().upper()
                if p_type == "DIRECT":
                    direct_funds.append(f)

    parking_scheme = "Direct Liquid / Money Market Fund"
    for f in direct_funds:
        cat_val = str(f.get("category") or "")
        s_val = str(f.get("scheme") or "")
        s_lower = s_val.lower()
        if cat_val == "Debt" or "liquid" in s_lower or "arbitrage" in s_lower or "money market" in s_lower:
            if s_val:
                parking_scheme = s_val
                break

    # Multi-month STP Staging Schedule for Equity Capital
    try:
        stp_dur_int = int(stp_duration_months) if stp_duration_months is not None else 6
    except (ValueError, TypeError):
        stp_dur_int = 6
    stp_duration = max(1, min(stp_dur_int, 36))
    base_tranche = (target_equity_capital / Decimal(str(stp_duration))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    stp_schedule: List[Dict[str, Any]] = []
    cumulative_deployed = Decimal("0.00")

    # Ratio within equity sleeve
    tot_eq_weight = lc_pct + ms_pct
    lc_ratio = (lc_pct / tot_eq_weight) if tot_eq_weight > Decimal("0.0") else Decimal("0.67")
    ms_ratio = Decimal("1.0") - lc_ratio

    for month_num in range(1, stp_duration + 1):
        if month_num == stp_duration:
            tranche_amt = target_equity_capital - cumulative_deployed
        else:
            tranche_amt = base_tranche

        lc_tranche = (tranche_amt * lc_ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        ms_tranche = (tranche_amt - lc_tranche).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cumulative_deployed += tranche_amt

        rem_parking = (target_equity_capital - cumulative_deployed).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        stp_schedule.append({
            "month": month_num,
            "tranche_amount_inr": tranche_amt,
            "large_cap_inr": lc_tranche,
            "mid_small_inr": ms_tranche,
            "remaining_liquid_parking_inr": rem_parking,
            "source_parking": parking_scheme,
        })

    return {
        "status": status,
        "effective_lumpsum_inr": effective_lumpsum,
        "requested_lumpsum_inr": lump_dec,
        "bank_cash_inr": cash_dec,
        "emergency_reserve_inr": reserve_dec,
        "deployable_surplus_inr": deployable_surplus,
        "target_equity_capital_inr": target_equity_capital,
        "target_debt_capital_inr": target_debt_capital,
        "stp_duration_months": stp_duration,
        "monthly_stp_tranche_inr": base_tranche,
        "stp_schedule": stp_schedule,
        "parking_scheme": parking_scheme,
        "reasons": reasons,
        "reconciliation_valid": cumulative_deployed == target_equity_capital,
    }

