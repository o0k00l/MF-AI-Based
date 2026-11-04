"""
core/redemption_engine.py — Redemption decision-support safety boundary.

The former heuristic waterfall is disabled. The prior implementation could
assume missing transaction lots were mature, treat generic maturity as a
zero-exit-load guarantee, apply fallback tax rates/exemptions, and prioritize
sectoral holdings using name-based heuristics. Those outputs are not safe for
investor-specific redemption planning.

Current behaviour: return NO ACTION until the tax framework has independent
legal approval, exact transaction lots are reconciled, and scheme/plan/lot-
specific exit-load evidence is available to a validated calculation engine.
No redemption order, tranche, tax estimate or realized saving is generated.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from core.models import (
    HoldingItem,
    PlanType,
    AssetClass,
    RedemptionPriorityTier,
    RedemptionTrancheItem,
    PersonalRedemptionPlan,
)
from tax.transition_planner import load_transactions, Lot, load_tax_rules


def classify_holding_liquidation_priority(
    holding: HoldingItem,
    metrics_data: Optional[Dict[str, Any]] = None,
    mature_gain_inr: float = 0.0,
) -> Tuple[RedemptionPriorityTier, str]:
    """
    Classifies a portfolio holding into one of 4 strict fiduciary priority tiers.
    """
    name_lower = (holding.scheme or holding.fund_name or "").lower()
    is_regular = (holding.plan == PlanType.REGULAR) or (not holding.is_direct) or ("regular" in name_lower)

    # Theme and Sectoral keywords indicating high valuation / concentration risk
    bubble_keywords = [
        "defence", "defense", "energy", "special opportunities",
        "manufacturing", "infrastructure", "thematic", "sectoral",
        "commodities", "natural resources", "psu"
    ]
    is_sectoral_or_thematic = any(kw in name_lower for kw in bubble_keywords)

    # Check top10 concentration if available
    top10_conc = 0.0
    if metrics_data:
        top10_conc = float(metrics_data.get("top10_concentration_pct", metrics_data.get("top10", 0.0)) or 0.0)
    elif holding.top_holdings and len(holding.top_holdings) <= 10:
        # If top_holdings provided, estimate
        pass

    # Priority 1: Toxic Sector Bubbles & Extreme Concentration Derisking
    # Sectoral/thematic funds (especially in Regular plans with bubble valuations like Defence/Energy)
    if is_sectoral_or_thematic:
        if is_regular:
            return (
                RedemptionPriorityTier.BUBBLE_DERISKING,
                "Priority 1: Toxic Sector Bubble Derisking & High Concentration Derisking (Regular Plan)"
            )
        else:
            return (
                RedemptionPriorityTier.BUBBLE_DERISKING,
                "Priority 1: Tactical Thematic Derisking (Direct Plan)"
            )

    # Priority 2: Fee Bleed Elimination (Regular Plans)
    if is_regular:
        if mature_gain_inr < 0:
            return (
                RedemptionPriorityTier.FEE_BLEED_ELIMINATION,
                "Priority 2: Fee Bleed Elimination + Sec 70 Capital Loss Harvesting (Zero Tax & Shields Other Gains)"
            )
        else:
            return (
                RedemptionPriorityTier.FEE_BLEED_ELIMINATION,
                "Priority 2: Regular Plan Intermediary Commission Bleed Elimination"
            )

    # Priority 3: SAA Rebalancing & Redundant Duplicates (Direct Plans)
    # Direct funds with duplicate overlap (multi-caps, large & mid cap duplicates)
    redundant_direct_keywords = ["multi cap", "multicap", "large and mid", "large & mid"]
    if any(kw in name_lower for kw in redundant_direct_keywords):
        return (
            RedemptionPriorityTier.SAA_REBALANCING,
            "Priority 3: Redundant Multi-Cap Overlap & SAA Rebalancing (Direct Plan)"
        )

    # Priority 4: Core Direct Compounding Anchors (Protected)
    return (
        RedemptionPriorityTier.CORE_CAPITAL_ANCHOR,
        "Priority 4: Core Direct Compounding Anchor (Protected Capital — Liquidation Shielded)"
    )


def match_fund_lots(
    holding: HoldingItem,
    lots_by_fund: Dict[str, List[Lot]]
) -> List[Lot]:
    """Match transaction lots only by exact scheme key; never use fuzzy substrings."""
    exact_keys = {
        str(holding.scheme or "").strip().casefold(),
        str(holding.fund_name or "").strip().casefold(),
    }
    exact_keys.discard("")
    for key, lots in lots_by_fund.items():
        if str(key).strip().casefold() in exact_keys:
            return lots
    return []


def get_holding_mature_profile(
    holding: HoldingItem,
    lots_by_fund: Dict[str, List[Lot]],
    as_of_date: date,
    annual_trail_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """Return only lot-backed maturity values; missing lots never imply maturity."""
    lots = match_fund_lots(holding, lots_by_fund)
    if not lots:
        return {
            "holding": holding,
            "nav": 0.0,
            "total_units": 0.0,
            "mature_units": 0.0,
            "mature_cost_inr": 0.0,
            "mature_value_inr": 0.0,
            "mature_gain_inr": 0.0,
            "annual_bleed_inr": 0.0,
            "is_regular": holding.plan == PlanType.REGULAR or not holding.is_direct,
            "data_verified": False,
            "unavailable_reason": "Exact transaction-lot match unavailable; no maturity or value inferred.",
        }

    total_units = sum(lot.units for lot in lots)
    nav = (
        holding.current_value_inr / total_units
        if total_units > 0
        else 0.0
    )
    mature_lots = [lot for lot in lots if lot.is_long_term(as_of_date)]
    mature_units = sum(lot.units for lot in mature_lots)
    mature_cost = sum(lot.cost for lot in mature_lots)
    mature_value = mature_units * nav
    mature_gain = mature_value - mature_cost

    is_regular = holding.plan == PlanType.REGULAR or not holding.is_direct
    trail_rate = 0.0
    if annual_trail_rate is not None:
        trail_rate = float(annual_trail_rate)
        if not 0.0 <= trail_rate <= 1.0:
            raise ValueError("Annual trail rate must be between 0 and 1.")

    return {
        "holding": holding,
        "nav": nav,
        "total_units": total_units,
        "mature_units": mature_units,
        "mature_cost_inr": mature_cost,
        "mature_value_inr": mature_value,
        "mature_gain_inr": mature_gain,
        "annual_bleed_inr": (mature_value * trail_rate) if is_regular else 0.0,
        "is_regular": is_regular,
        "data_verified": True,
        "unavailable_reason": None,
    }


def compute_personal_redemption_plan(
    requested_amount: float,
    holdings: List[HoldingItem],
    transactions_path: Optional[Path] = None,
    is_net_cash: bool = False,
    ltcg_exemption_remaining: Optional[float] = None,
    as_of_date: Optional[date] = None,
    client_risk_tier_num: int = 6,
    fund_metrics_dict: Optional[Dict[str, Any]] = None,
    tax_rules_path: Optional[Path] = None,
) -> PersonalRedemptionPlan:
    """Fail closed until tax and scheme-specific exit-load evidence is release-approved.

    The former implementation inferred maturity when lots were missing, assumed
    zero exit load for mature units, and applied generic tax defaults. Those
    assumptions are not safe for investor-specific redemption instructions.
    The current tax policy is explicitly provisional and generic exit-load
    schedules are not scheme/plan/lot evidence. Therefore no redemption amount,
    tax estimate, tranche or execution step is generated by this engine.
    """
    import math

    try:
        requested = float(requested_amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("Requested redemption amount must be numeric.") from exc
    if not math.isfinite(requested) or requested <= 0:
        raise ValueError("Requested redemption amount must be finite and positive.")

    if not holdings:
        category = "NO_HOLDINGS"
        reason = "NO ACTION: no holdings were supplied. The requested amount remains unallocated."
    else:
        category = "NO_ACTION_EVIDENCE"
        reason = (
            "NO ACTION: investor-specific redemption calculations are disabled. "
            "The checked-in tax rules are marked provisional, scheme/plan/lot-specific exit-load "
            "evidence is not consumed by this engine, and independent tax/legal approval is absent. "
            "Missing transaction lots must never be treated as mature. No tax, exit-load, redemption "
            "amount, fund priority or execution step has been inferred. "
            f"Requested INR {requested:,.2f} remains unallocated."
        )

    return PersonalRedemptionPlan(
        requested_amount_inr=round(requested, 2),
        ticket_category=category,
        ticket_rationale=reason,
        is_net_cash_target=is_net_cash,
        total_gross_redeemed_inr=0.0,
        total_exit_load_inr=0.0,
        total_realized_gain_loss_inr=0.0,
        total_stcg_tax_inr=0.0,
        total_ltcg_tax_inr=0.0,
        total_tax_sheltered_under_112a_inr=0.0,
        total_net_tax_inr=0.0,
        total_net_cash_inr=0.0,
        total_annual_commission_saved_inr=0.0,
        funds_liquidated_count=0,
        full_folio_exits_count=0,
        tranches=[],
        execution_steps=[reason],
        fiduciary_safeguards=[
            "Redemption outputs are disabled until statutory tax interpretation receives independent approval.",
            "Scheme/plan/lot-specific exit-load schedules and exact transaction lots are required.",
            "No missing holding period, tax rate, exemption, exit load or fund priority is inferred.",
        ],
    )
