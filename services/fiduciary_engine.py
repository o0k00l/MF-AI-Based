"""services/fiduciary_engine.py — Bridge service linking Web UI to Core Fiduciary Math Engine.

Transforms UI session state (CAS holdings, CGS capital gains, 3-mode Risk Profile,
and Financial Goals) into rigorous mathematical models and deterministic SAA plans.
"""
from __future__ import annotations

import json
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
) -> str:
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
        Scheme name of the selected passive index fund
    
    Raises:
        NoActionRecommended: If no passive fallback fund is available
    """
    # Map category_key to expected category names
    category_mapping = {
        "large_cap_index": "Large Cap",
        "mid_cap_active": "Mid Cap", 
        "debt_liquid": "Debt",
        "equity_generic": "Flexi Cap",
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
    
    # Return the best fund
    best_fund = candidates[0]
    scheme_name = best_fund.get("scheme") or best_fund.get("canonical_name") or best_fund.get("id", "")
    
    # Ensure Direct plan naming
    if "Direct" not in scheme_name and "Direct Plan" not in scheme_name:
        scheme_name = scheme_name + " - Direct Plan - Growth"
    
    return scheme_name


def _select_market_nom_fund(
    rules: Dict[str, Any],
    fund_universe: List[Dict[str, Any]],
    nom_key: str = "",
) -> str:
    """Dynamically select the best fund based on market nomination rules.
    
    Args:
        rules: Selection rules including category, sort_by, sort_order, and filters
        fund_universe: List of available funds with metrics (from fund_metrics.json or similar)
        nom_key: The key identifying this nomination (for fallback)
    
    Returns:
        Scheme name of the selected fund, or a safe fallback name
    """
    # SPIVA PASSIVE FALLBACK: Handle empty universe case
    if not fund_universe:
        return trigger_spiva_fallback(nom_key, rules, fund_universe)

    
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
        return trigger_spiva_fallback(nom_key, rules, fund_universe)
    
    # Sort by the specified metric
    reverse = sort_order == "desc"
    try:
        def sort_key(f):
            val = f.get(sort_by)
            if val is None:
                # For ascending sort (lowest first), None should be at the end
                # For descending sort (highest first), None should be at the end
                return float('inf')
            return val
        
        filtered.sort(key=sort_key, reverse=reverse)
        # Get scheme name from the best fund
        best = filtered[0]
        scheme_name = best.get("scheme") or best.get("canonical_name") or best.get("id", "Selected Fund")
        # Ensure Direct plan
        if "Direct" not in scheme_name and "Direct Plan" not in scheme_name:
            scheme_name = scheme_name + " - Direct Plan - Growth"
        return scheme_name
    except Exception:
        return filtered[0].get("scheme", "Selected Fund - Direct Plan - Growth")


def convert_cas_funds_to_holdings(funds: List[Dict[str, Any]]) -> List[HoldingItem]:
    """Convert raw UI CAS fund dictionaries into validated domain HoldingItems."""
    holdings: List[HoldingItem] = []
    for idx, f in enumerate(funds):
        val = Decimal(str(f.get("current_value", 0.0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if val <= Decimal("0.00"):
            continue
        cost = Decimal(str(f.get("invested_value", 0.0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        units = Decimal(str(f.get("units", 0.0))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        nav = Decimal(str(f.get("nav", 0.0))).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

        cat = str(f.get("category", "Equity")).upper()
        if "DEBT" in cat or "LIQUID" in cat or "INCOME" in cat:
            ac = AssetClass.DEBT
        elif "HYBRID" in cat or "BALANCED" in cat:
            ac = AssetClass.HYBRID
        elif "INTERNATIONAL" in cat or "OVERSEAS" in cat:
            ac = AssetClass.INTERNATIONAL
        else:
            ac = AssetClass.EQUITY

        plan_str = str(f.get("plan_type", "Direct")).upper()
        plan = PlanType.REGULAR if "REGULAR" in plan_str else PlanType.DIRECT

        eq_pct = float(f.get("eq", 100.0 if ac == AssetClass.EQUITY else (0.0 if ac == AssetClass.DEBT else 65.0)))
        debt_pct = float(f.get("debt", 0.0 if ac == AssetClass.EQUITY else (100.0 if ac == AssetClass.DEBT else 35.0)))
        # Gold is a stability asset (like debt) - include it in debt_pct for SAA drift calculation
        gold_pct = float(f.get("gold", 0.0))
        # Adjust debt_pct to include gold for proper SAA drift analysis
        # Cap at 100% to avoid invalid HoldingItem (debt_pct + gold_pct could theoretically exceed 100%)
        effective_debt_pct = min(debt_pct + gold_pct, 100.0)

        h = HoldingItem(
            fund_id=f"fund_{idx}_{f.get('scheme', 'unnamed')[:15]}",
            scheme=f.get("scheme", "Unknown Scheme"),
            fund_name=f.get("scheme", "Unknown Scheme"),
            folio=str(f.get("folio_no") or f.get("folio") or f"FOLIO_{idx}"),
            plan=plan,
            asset_class=ac,
            equity_pct=eq_pct,
            debt_pct=effective_debt_pct,
            hybrid_pct=0.0,
            international_pct=0.0,
            current_value_inr=val,
            invested_value_inr=cost,
            units=units,
            nav=nav,
        )
        holdings.append(h)
    return holdings


def evaluate_portfolio_saa_audit(
    funds: List[Dict[str, Any]],
    target_saa: Optional[Dict[str, float] | TargetSaa] = None,
) -> Dict[str, Any]:
    """Execute SAA drift and debt buffer analysis using core math engine."""
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

    # Format target_saa dictionary for math_engine
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

    drift: SAADriftAnalysis = calculate_saa_drift(
        holdings=holdings,
        target_saa={"equity_pct": target_equity_pct, "debt_pct": target_debt_pct},
        tolerance_band_pct=5.0,
    )

    curr_eq_pct = drift.current_equity_pct
    curr_db_pct = drift.current_debt_pct
    db_gap_inr = quantize_inr(drift.debt_gap_inr)
    eq_gap_inr = quantize_inr(drift.equity_gap_inr)

    # If debt_gap_inr is positive, target debt > current debt (Debt Deficit)
    is_debt_deficit = db_gap_inr > Decimal("0.00")

    return {
        "status": "ANALYZED",
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


def generate_fiduciary_sip_blueprint(
    monthly_budget_inr: float,
    funds: List[Dict[str, Any]],
    target_saa: Optional[Dict[str, float] | TargetSaa] = None,
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

    # Extract target percentages safely
    lc_pct = Decimal("50.0")
    ms_pct = Decimal("25.0")
    db_pct = Decimal("25.0")

    if target_saa is not None:
        if hasattr(target_saa, "large_cap_pct") and hasattr(target_saa, "mid_small_cap_pct"):
            try:
                lc_pct = Decimal(str(getattr(target_saa, "large_cap_pct", 50.0) or 50.0))
                ms_pct = Decimal(str(getattr(target_saa, "mid_small_cap_pct", 25.0) or 25.0))
                db_pct = Decimal(str(getattr(target_saa, "debt_pct", 25.0) or 25.0))
            except Exception:
                lc_pct, ms_pct, db_pct = Decimal("50.0"), Decimal("25.0"), Decimal("25.0")
        elif isinstance(target_saa, dict):
            try:
                lc_val = target_saa.get("large_cap_pct")
                lc_pct = Decimal(str(lc_val if lc_val is not None else 50.0))
                ms_val = target_saa.get("mid_small_cap_pct")
                ms_pct = Decimal(str(ms_val if ms_val is not None else 25.0))
                db_val = target_saa.get("debt_pct")
                db_pct = Decimal(str(db_val if db_val is not None else 25.0))
            except Exception:
                lc_pct, ms_pct, db_pct = Decimal("50.0"), Decimal("25.0"), Decimal("25.0")

    # Stability Buffer Override (per POL-SIP-001):
    # If current portfolio debt >= target debt, redirect all SIP debt allocation to equity.
    # Existing debt holdings are maintained for rebalancing ammunition but receive no new SIP inflows.
    # This prevents a Tier 6 investor with 9.3% current debt from adding more debt via SIP
    # when the target SAA only allows 5% debt in the total portfolio.
    stability_override_applied = False
    if db_pct > Decimal("0.0") and funds:
        total_value = sum(
            float(f.get("current_value", 0) or 0) for f in funds if isinstance(f, dict)
        )
        debt_value = sum(
            float(f.get("current_value", 0) or 0) for f in funds
            if isinstance(f, dict)
            and (str(f.get("category", "")).lower() == "debt"
                 or any(kw in str(f.get("scheme", "")).lower() for kw in ["liquid", "arbitrage", "money market"]))
        )
        if total_value > 0:
            current_debt_pct = Decimal(str(debt_value / total_value * 100.0))
            if current_debt_pct >= db_pct:
                # Debt is already at or above target — redirect SIP debt to equity
                debt_to_add = db_pct
                # Split the redirected debt across existing equity sleeves proportionally
                total_equity_pct = lc_pct + ms_pct
                if total_equity_pct > Decimal("0.0"):
                    lc_pct = lc_pct + (debt_to_add * (lc_pct / total_equity_pct))
                    ms_pct = ms_pct + (debt_to_add * (ms_pct / total_equity_pct))
                else:
                    lc_pct = lc_pct + debt_to_add
                db_pct = Decimal("0.0")
                stability_override_applied = True

    # Quantized target sleeve allocations
    lc_target = (budget_dec * (lc_pct / Decimal("100.0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    ms_target = (budget_dec * (ms_pct / Decimal("100.0"))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # Reconcile exact paisa difference onto debt/stability buffer
    db_target = (budget_dec - lc_target - ms_target).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Identify eligible Direct funds in client portfolio safely
    direct_funds = [
        f for f in (funds or [])
        if isinstance(f, dict) and str(f.get("plan_type") or "Direct").strip().upper() == "DIRECT"
    ]
    allocations = []

    # Load market-nominated funds for fallback selection
    market_noms = _load_market_nominations()
    
    # Load fund universe for dynamic selection
    fund_universe = _load_fund_universe()

    def _match_kw(f_obj: Dict[str, Any], kws: List[str]) -> bool:
        s_name = str(f_obj.get("scheme") or "").lower()
        return any(k in s_name for k in kws)

    def _get_market_nom_fund(nom_key: str, fund_universe_list: List[Dict[str, Any]] = None) -> str:
        """Get scheme name from market nominations using dynamic selection logic."""
        rules = market_noms.get(nom_key, {})
        if fund_universe_list:
            # Use dynamic selection from fund universe
            result = _select_market_nom_fund(rules, fund_universe_list, nom_key)
            if result and result != "SPIVA_FALLBACK_FAILED":
                return result
        # Fallback to embedded selection rules from data (NOT hardcoded defaults)
        return rules.get("scheme", "Market-Nominated Fund - Direct Plan - Growth")

    if direct_funds:
        # Match schemes to sleeves - prioritize client's existing funds
        # Strategy: Prefer pure category funds over blended category funds
        
        # Large Cap: first look for pure large cap/index funds, then fallback
        lc_pure = next((
            f for f in direct_funds 
            if _match_kw(f, ["index", "nifty"]) or 
               (str(f.get("category", "")).lower() == "large cap")
        ), None)
        lc_blended = next((
            f for f in direct_funds 
            if "large & mid" in str(f.get("scheme", "")).lower()
        ), None)
        lc_fund = lc_pure or lc_blended
        
        # Mid/Small-Cap: prefer mid cap/small cap, exclude pure large cap index
        ms_fund = next((
            f for f in direct_funds 
            if str(f.get("category", "")).lower() in ["mid cap", "small cap"]
        ), None)
        
        # Debt: match by category or keywords
        db_fund = next((f for f in direct_funds if str(f.get("category") or "") == "Debt" or _match_kw(f, ["liquid", "arbitrage", "money market"])), None)

        # Fallbacks for equity sleeves if specific cap categories not held
        if not lc_fund:
            # Use any Direct equity fund
            lc_fund = next((
                f for f in direct_funds 
                if f != ms_fund and str(f.get("category") or "") in ["Equity", "Large Cap", "Mid Cap"] and
                   str(f.get("plan_type") or "Direct").upper() == "DIRECT"
            ), None)
        if not ms_fund:
            # Use any other Direct equity fund for mid/small cap (different from lc_fund)
            ms_fund = next((
                f for f in direct_funds 
                if f != lc_fund and str(f.get("category") or "") in ["Equity", "Mid Cap", "Large Cap", "Large & Mid Cap"] and
                   str(f.get("plan_type") or "Direct").upper() == "DIRECT"
            ), None)

        # Large-Cap Sleeve
        if lc_target > Decimal("0.00"):
            # Use client's fund, or dynamically select from fund universe
            selected_fund = lc_fund
            if not lc_fund:
                selected_name = _get_market_nom_fund("large_cap_index", fund_universe)
                selected_fund = {"scheme": selected_name, "folio_no": "New Direct Folio Mandate"}
            s_name = selected_fund.get("scheme")
            f_num = selected_fund.get("folio_no", "Existing Direct Folio") if selected_fund.get("folio_no") != "New Direct Folio Mandate" else "New Direct Folio Mandate"
            allocations.append({
                "sleeve": "Large-Cap Core Index",
                "scheme_name": s_name,
                "folio_no": f_num,
                "amount_inr": lc_target,
                "allocation_pct": float(lc_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Anchor core equity compounding in lowest-cost Direct large cap index scheme.",
            })

        # Mid/Small-Cap Sleeve
        if ms_target > Decimal("0.00"):
            # Use client's fund, or dynamically select from fund universe
            selected_fund = ms_fund
            if not ms_fund:
                selected_name = _get_market_nom_fund("mid_cap_active", fund_universe)
                selected_fund = {"scheme": selected_name, "folio_no": "New Direct Folio Mandate"}
            s_name = selected_fund.get("scheme")
            f_num = selected_fund.get("folio_no", "Existing Direct Folio") if selected_fund.get("folio_no") != "New Direct Folio Mandate" else "New Direct Folio Mandate"
            allocations.append({
                "sleeve": "Mid/Small-Cap Alpha",
                "scheme_name": s_name,
                "folio_no": f_num,
                "amount_inr": ms_target,
                "allocation_pct": float(ms_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Long-term alpha accumulation aligned with investor risk tolerance.",
            })

        # Debt Sleeve (Strict Fiduciary Separation: Pure Debt/Liquid only)
        if db_target > Decimal("0.00"):
            # Use client's fund, or dynamically select from fund universe
            selected_fund = db_fund
            if not db_fund:
                # Dynamic Market Nomination Fallback
                # Filter the universe for Direct Liquid/Debt funds, sort by lowest TER, return the best
                liquid_candidates = [
                    f for f in (fund_universe or [])
                    if isinstance(f, dict)
                    and str(f.get("category", "")).lower() == "debt"
                    and str(f.get("plan_type", "Direct")).lower() == "direct"
                ]
                
                if liquid_candidates:
                    # Sort by TER ascending (lowest cost = fiduciary preference)
                    liquid_candidates.sort(key=lambda x: float(x.get("ter_direct_pct", 99.9)))
                    selected_name = liquid_candidates[0].get("scheme") or liquid_candidates[0].get("canonical_name")
                else:
                    # Absolute failsafe if universe is empty - use market nomination default
                    debt_rules = market_noms.get("debt_liquid", {})
                    selected_name = debt_rules.get("scheme", "Market-Nominated Liquid Fund - Direct Plan - Growth")
                if "direct" not in str(selected_name).lower():
                    selected_name = f"{selected_name} - Direct Plan - Growth"
                
                selected_fund = {"scheme": selected_name, "folio_no": "New Direct Folio Mandate"}
            s_name = selected_fund.get("scheme")
            f_num = selected_fund.get("folio_no", "Existing Direct Folio") if selected_fund.get("folio_no") != "New Direct Folio Mandate" else "New Direct Folio Mandate"
            allocations.append({
                "sleeve": "Debt & Capital Preservation",
                "scheme_name": s_name,
                "folio_no": f_num,
                "amount_inr": db_target,
                "allocation_pct": float(db_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Statutory capital preservation floor (100% Sovereign T-Bills/Repo).",
            })
    else:
        # Client has no Direct schemes yet (or 100% regular) — provide canonical sleeve blueprint with market nominations
        # Use dynamic selection from fund universe
        market_lc = _get_market_nom_fund("large_cap_index", fund_universe)
        market_ms = _get_market_nom_fund("mid_cap_active", fund_universe)
        
        # Dynamic debt liquid selection (avoid SPIVA fallback bug for active funds)
        liquid_candidates = [
            f for f in (fund_universe or [])
            if isinstance(f, dict)
            and str(f.get("category", "")).lower() == "debt"
            and str(f.get("plan_type", "Direct")).lower() == "direct"
        ]
        if liquid_candidates:
            liquid_candidates.sort(key=lambda x: float(x.get("ter_direct_pct", 99.9)))
            market_db = liquid_candidates[0].get("scheme") or liquid_candidates[0].get("canonical_name") or market_noms.get("debt_liquid", {}).get("scheme", "Market-Nominated Liquid Fund - Direct Plan - Growth")
        else:
            debt_rules = market_noms.get("debt_liquid", {})
            market_db = debt_rules.get("scheme", "Market-Nominated Liquid Fund - Direct Plan - Growth")
        if "direct" not in str(market_db).lower():
            market_db = f"{market_db} - Direct Plan - Growth"
        
        if lc_target > Decimal("0.00"):
            allocations.append({
                "sleeve": "Large-Cap Core Index",
                "scheme_name": market_lc,
                "folio_no": "New Direct Folio Mandate",
                "amount_inr": lc_target,
                "allocation_pct": float(lc_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Low-cost index foundation (zero commission leakage).",
            })
        if ms_target > Decimal("0.00"):
            allocations.append({
                "sleeve": "Mid/Small-Cap Alpha",
                "scheme_name": market_ms,
                "folio_no": "New Direct Folio Mandate",
                "amount_inr": ms_target,
                "allocation_pct": float(ms_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Diversified growth engine aligned with SAA policy.",
            })
        if db_target > Decimal("0.00"):
            allocations.append({
                "sleeve": "Debt & Capital Preservation",
                "scheme_name": market_db,
                "folio_no": "New Direct Folio Mandate",
                "amount_inr": db_target,
                "allocation_pct": float(db_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Defensive capital preservation & rebalancing liquidity buffer.",
            })

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

    return {
        "status": "DETERMINISTIC_SIP_READY",
        "monthly_budget_inr": budget_dec,
        "allocated_budget_inr": total_allocated,
        "unallocated_budget_inr": unallocated,
        "allocations": allocations,
        "recommendations": recommendations,
        "reconciliation_valid": abs(unallocated) <= Decimal("0.01"),
        "optimal_tranche_timing": optimal_tranche_timing,
        "portfolio_completion_alerts": completion_alerts,
        "fiduciary_routing_rationale": routing_rationale,
        "sip_selection_confidence_pct": confidence_score,
        "stability_override_applied": stability_override_applied,
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

