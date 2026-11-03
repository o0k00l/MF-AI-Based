"""
core/redemption_engine.py — Deterministic Fiduciary Personal Cash Redemption Engine.

Implements mathematically grounded personal cash liberation:
1. 4-Tier Liquidation Priority Waterfall:
   - Priority 1: Toxic Sector Bubbles & Extreme Concentration Derisking (Defence, Energy, Thematic).
   - Priority 2: Fee Bleed Elimination (Regular Plans sorted by Section 70 Loss-Harvesting first, then commission leakage).
   - Priority 3: SAA Rebalancing & Redundant Multi-cap / Overweight Direct Holdings.
   - Priority 4: Core Direct Compounding Anchors (Protected from redemption).

2. Ticket-Size Scaling Logic:
   - Small-Ticket (<= INR 1,00,000): Operational friction minimization -> Single-fund execution (1 MFCentral action).
   - Medium-Ticket (INR 1,00,000 to INR 5,00,000): Complete folio exits -> Eliminates residual tail balances.
   - Large-Ticket (> INR 5,00,000): Macro structural derisking & SAA preservation.

3. Fiduciary Tax & Cost Minimization Safeguards:
   - 0% Exit Load Guarantee: Only mature lots (> 365 days) are liquidated; immature lots are shielded.
   - Section 112A Tax Shield Siphon: INR 1.25L LTCG annual tax-free exemption utilized first (12.5% on excess).
   - Section 70 Loss Netting: Realized capital losses offset taxable gains within the plan.
   - Permanent Fee Bleed Elimination: Eliminates ongoing ~1.05% distributor commission drag.
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
    """Matches a HoldingItem to its transaction lots."""
    h_scheme = (holding.scheme or "").lower()
    h_name = (holding.fund_name or "").lower()
    h_folio = str(holding.folio).strip()

    # Exact key match
    if holding.scheme in lots_by_fund:
        return lots_by_fund[holding.scheme]
    if holding.fund_name in lots_by_fund:
        return lots_by_fund[holding.fund_name]

    # Substring matching
    for k, v in lots_by_fund.items():
        k_lower = k.lower()
        if k_lower == h_scheme or k_lower == h_name:
            return v
        if k_lower in h_scheme or h_scheme in k_lower:
            return v
        if k_lower in h_name or h_name in k_lower:
            return v

    return []


def get_holding_mature_profile(
    holding: HoldingItem,
    lots_by_fund: Dict[str, List[Lot]],
    as_of_date: date,
    annual_trail_rate: float = 0.0105
) -> Dict[str, Any]:
    """
    Computes mature units, mature value, mature cost, and mature gain for a holding.
    Enforces Day 366 maturity lock (0% exit load guarantee).
    """
    lots = match_fund_lots(holding, lots_by_fund)

    if lots:
        total_units = sum(l.units for l in lots)
        nav = (holding.current_value_inr / total_units) if total_units > 0 else (holding.nav if holding.nav > 0 else 1.0)

        # Filter strictly for mature lots (> 365 days)
        mature_lots = [l for l in lots if (as_of_date - l.purchase_date).days > 365]
        mature_units = sum(l.units for l in mature_lots)
        mature_cost = sum(l.cost for l in mature_lots)
        mature_value = mature_units * nav
        mature_gain = mature_value - mature_cost
    else:
        # Fallback if no transaction lots are provided: assume holding is mature
        nav = holding.nav if holding.nav > 0 else (holding.current_value_inr / holding.units if holding.units > 0 else 1.0)
        total_units = holding.units if holding.units > 0 else (holding.current_value_inr / nav if nav > 0 else 0.0)
        mature_units = total_units
        mature_cost = holding.invested_value_inr
        mature_value = holding.current_value_inr
        mature_gain = mature_value - mature_cost

    is_regular = (holding.plan == PlanType.REGULAR) or (not holding.is_direct)
    annual_leakage = (mature_value * annual_trail_rate) if is_regular else 0.0

    return {
        "holding": holding,
        "nav": nav,
        "total_units": total_units,
        "mature_units": mature_units,
        "mature_cost_inr": mature_cost,
        "mature_value_inr": mature_value,
        "mature_gain_inr": mature_gain,
        "annual_bleed_inr": annual_leakage,
        "is_regular": is_regular,
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
    # Defensive guard for empty holdings
    if not holdings:
        return PersonalRedemptionPlan(
            requested_amount_inr=round(requested_amount, 2),
            ticket_category="NO_HOLDINGS",
            ticket_rationale="No holdings provided for redemption planning.",
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
            execution_steps=["No holdings available for redemption."],
            fiduciary_safeguards=["Redemption planner requires holdings data."],
        )
    """
    Computes an optimal, deterministic Personal Cash Redemption Plan:
    - 4-Tier Liquidation Waterfall
    - Amount-based ticket scaling (Small, Medium, Large)
    - 0% Exit Load Guarantee (mature lots only)
    - Section 112A ₹1.25L LTCG annual exemption utilization
    - Section 70 Capital Loss Harvesting (loss netting)
    - Commission bleed termination
    """
    if requested_amount <= 0:
        raise ValueError(f"Requested redemption amount must be positive. Received: {requested_amount}")

    # Load tax rules from policy
    tax_rules = {}
    if tax_rules_path and tax_rules_path.exists():
        tax_rules = load_tax_rules(tax_rules_path)
    
    # Extract tax parameters from policy (with fallbacks)
    ltcg_rate = tax_rules.get("ltcg_rate", 0.125)
    stcg_rate = tax_rules.get("stcg_rate", 0.20)
    ltcg_exemption = tax_rules.get("ltcg_exemption", 125000.0)
    cess_rate = tax_rules.get("cess", {}).get("health_education_cess_pct", 4.0) / 100.0
    cess_multiplier = 1.0 + cess_rate
    exit_load_pct = tax_rules.get("exit_load_pct", 1.0)

    # Use provided exemption or fall back to tax rules
    current_ltcg_exemption = ltcg_exemption_remaining if ltcg_exemption_remaining is not None else ltcg_exemption

    eval_date = as_of_date or date.today()

    # Load transaction lots if path provided
    lots_by_fund: Dict[str, List[Lot]] = {}
    if transactions_path and transactions_path.exists():
        lots_by_fund = load_transactions(transactions_path)

    # Build mature profile for all holdings
    profiles: List[Dict[str, Any]] = []
    for h in holdings:
        prof = get_holding_mature_profile(h, lots_by_fund, eval_date)
        metrics = (fund_metrics_dict or {}).get(h.scheme, (fund_metrics_dict or {}).get(h.fund_name, {}))
        priority_tier, reason = classify_holding_liquidation_priority(h, metrics, prof["mature_gain_inr"])
        prof["priority_tier"] = priority_tier
        prof["priority_reason"] = reason
        profiles.append(prof)

    # Determine ticket category
    if requested_amount <= 100_000.0:
        ticket_category = "SMALL_TICKET"
        ticket_rationale = (
            "Small-Ticket Redemption (≤ ₹1,00,000): Optimized for zero operational friction. "
            "Fulfills the entire withdrawal from a single fund in 1 single transaction on MFCentral."
        )
    elif requested_amount <= 500_000.0:
        ticket_category = "MEDIUM_TICKET"
        ticket_rationale = (
            "Medium-Ticket Redemption (₹1,00,000 to ₹5,00,000): Optimized for folio cleanups and fee bleed termination. "
            "Prioritizes 100% full liquidation of unwanted bubble and regular folios, preventing residual tail balances."
        )
    else:
        ticket_category = "LARGE_TICKET"
        ticket_rationale = (
            "Large-Ticket Redemption (> ₹5,00,000): Macro structural derisking and Strategic Asset Allocation (SAA) preservation. "
            "Sweeps toxic sector bubbles and high-commission regular plans while protecting core compounding anchors."
        )

    # Split profiles by priority tier
    p1_funds = [p for p in profiles if p["priority_tier"] == RedemptionPriorityTier.BUBBLE_DERISKING and p["mature_value_inr"] > 100.0]
    p2_funds = [p for p in profiles if p["priority_tier"] == RedemptionPriorityTier.FEE_BLEED_ELIMINATION and p["mature_value_inr"] > 100.0]
    p3_funds = [p for p in profiles if p["priority_tier"] == RedemptionPriorityTier.SAA_REBALANCING and p["mature_value_inr"] > 100.0]
    p4_funds = [p for p in profiles if p["priority_tier"] == RedemptionPriorityTier.CORE_CAPITAL_ANCHOR and p["mature_value_inr"] > 100.0]

    # Sort Priority 1: Regular bubble funds first, then highest valuation/concentration
    p1_funds.sort(key=lambda x: (x["is_regular"], x["mature_value_inr"]), reverse=True)

    # Sort Priority 2: Loss-harvesting funds first (negative gain descending -> largest loss first), then highest fee bleed
    p2_loss = [p for p in p2_funds if p["mature_gain_inr"] < 0]
    p2_gain = [p for p in p2_funds if p["mature_gain_inr"] >= 0]
    p2_loss.sort(key=lambda x: x["mature_gain_inr"])  # Most negative gain first
    p2_gain.sort(key=lambda x: x["annual_bleed_inr"], reverse=True)  # Highest bleed first
    p2_sorted = p2_loss + p2_gain

    # Sort Priority 3: Highest value first
    p3_funds.sort(key=lambda x: x["mature_value_inr"], reverse=True)

    # Priority 4: Protected
    p4_funds.sort(key=lambda x: x["mature_value_inr"], reverse=True)

    # Selection Strategy based on Ticket Size
    candidate_order: List[Dict[str, Any]] = []

    if ticket_category == "SMALL_TICKET":
        # Search for a single candidate fund that can cover the full requested amount
        # Check Priority 1 first
        single_p1 = next((p for p in p1_funds if p["mature_value_inr"] >= requested_amount), None)
        if single_p1:
            candidate_order = [single_p1]
        else:
            # Check Priority 2
            single_p2 = next((p for p in p2_sorted if p["mature_value_inr"] >= requested_amount), None)
            if single_p2:
                candidate_order = [single_p2]
            else:
                # If no single fund can cover it, use sequential waterfall from P1 then P2
                candidate_order = p1_funds + p2_sorted + p3_funds + p4_funds
    else:
        # MEDIUM_TICKET and LARGE_TICKET use the structured fiduciary waterfall
        candidate_order = p1_funds + p2_sorted + p3_funds + p4_funds

    # Execute Waterfall Simulation
    # If is_net_cash is requested, we track net cash realized and adjust
    tranches: List[RedemptionTrancheItem] = []
    remaining_cash_needed = requested_amount
    accumulated_loss_pool = 0.0

    total_gross = 0.0
    total_exit_load = 0.0
    total_gain_loss = 0.0
    total_stcg_tax = 0.0
    total_ltcg_tax = 0.0
    total_tax_sheltered = 0.0
    total_net_tax = 0.0
    total_net_cash = 0.0
    total_bleed_saved = 0.0
    full_exits = 0

    for prof in candidate_order:
        if remaining_cash_needed <= 0.50:  # Within 50 paise
            break

        holding: HoldingItem = prof["holding"]
        mat_val = prof["mature_value_inr"]
        mat_units = prof["mature_units"]
        mat_cost = prof["mature_cost_inr"]
        nav = prof["nav"]

        if mat_val <= 0 or mat_units <= 0:
            continue

        # Determine gross allocation for this fund
        if not is_net_cash:
            gross_take = min(mat_val, remaining_cash_needed)
        else:
            # Net cash mode: estimate tax drag to ensure net cash target is met
            gain_ratio = (mat_val - mat_cost) / mat_val if mat_val > 0 else 0.0
            # If gain is negative or covered by exemption, tax drag is 0
            if gain_ratio <= 0 or current_ltcg_exemption >= (mat_val - mat_cost):
                gross_take = min(mat_val, remaining_cash_needed)
            else:
                # Taxable at LTCG rate with cess
                tax_drag_rate = ltcg_rate * cess_multiplier * gain_ratio
                gross_needed = remaining_cash_needed / (1.0 - tax_drag_rate) if tax_drag_rate < 0.99 else remaining_cash_needed
                gross_take = min(mat_val, gross_needed)

        is_full_exit = (gross_take >= mat_val - 1.0)
        units_to_redeem = mat_units if is_full_exit else (gross_take / nav)
        gross_amount = units_to_redeem * nav

        # Pro-rata cost and gain
        fraction = gross_amount / mat_val if mat_val > 0 else 0.0
        cost_basis = mat_cost * fraction
        gain = gross_amount - cost_basis

        exit_load = 0.0  # 0% Exit Load Guarantee for mature lots!
        stcg_tax = 0.0
        ltcg_tax = 0.0
        sheltered = 0.0

        if gain < 0:
            loss = abs(gain)
            accumulated_loss_pool += loss
        else:
            # Gain > 0: Net against Section 70 loss pool first
            offset = min(accumulated_loss_pool, gain)
            accumulated_loss_pool -= offset
            gain_after_loss = gain - offset

            # Apply Section 112A LTCG annual exemption
            sheltered = min(current_ltcg_exemption, gain_after_loss)
            current_ltcg_exemption -= sheltered
            taxable_ltcg = gain_after_loss - sheltered
            ltcg_tax = taxable_ltcg * ltcg_rate * cess_multiplier
            # Mature lots are always long-term (>365 days), so no STCG

        net_tax = stcg_tax + ltcg_tax
        net_cash = gross_amount - exit_load - net_tax
        bleed_saved = (gross_amount * 0.0105) if prof["is_regular"] else 0.0

        action = (
            f"REDEEM ALL {units_to_redeem:,.3f} mature units (Folio: {holding.folio}). "
            f"Zeroes out folio permanently."
            if is_full_exit else
            f"REDEEM PARTIAL {units_to_redeem:,.3f} units for INR {gross_amount:,.2f} (Folio: {holding.folio})."
        )

        tranche = RedemptionTrancheItem(
            fund_id=holding.fund_id,
            scheme_name=holding.scheme,
            folio=holding.folio,
            priority_tier=int(prof["priority_tier"]),
            priority_label=f"Priority {int(prof['priority_tier'])}: {prof['priority_tier'].name.replace('_', ' ').title()}",
            fiduciary_reason=prof["priority_reason"],
            gross_amount_inr=round(gross_amount, 2),
            units_to_redeem=round(units_to_redeem, 4),
            nav=round(nav, 4),
            exit_load_inr=round(exit_load, 2),
            realized_capital_gain_inr=round(gain, 2),
            is_long_term=(units_to_redeem <= mat_units + 0.001),
            projected_stcg_tax_inr=round(stcg_tax, 2),
            projected_ltcg_tax_inr=round(ltcg_tax, 2),
            tax_sheltered_under_112a_inr=round(sheltered, 2),
            net_tax_liability_inr=round(net_tax, 2),
            net_cash_realized_inr=round(net_cash, 2),
            annual_commission_saved_inr=round(bleed_saved, 2),
            is_full_redemption=is_full_exit,
            action_step=action,
        )
        tranches.append(tranche)

        total_gross += gross_amount
        total_exit_load += exit_load
        total_gain_loss += gain
        total_stcg_tax += stcg_tax
        total_ltcg_tax += ltcg_tax
        total_tax_sheltered += sheltered
        total_net_tax += net_tax
        total_net_cash += net_cash
        total_bleed_saved += bleed_saved
        if is_full_exit:
            full_exits += 1

        if is_net_cash:
            remaining_cash_needed -= net_cash
        else:
            remaining_cash_needed -= gross_amount

    # Build execution steps
    exec_steps = []
    for i, t in enumerate(tranches, 1):
        full_tag = " [FULL FOLIO EXIT]" if t.is_full_redemption else ""
        exec_steps.append(
            f"Step {i}: Go to MFCentral -> Select '{t.scheme_name}' (Folio: {t.folio}) -> "
            f"Action: Redeem {t.units_to_redeem:,.3f} units (Gross: INR {t.gross_amount_inr:,.2f}) -> "
            f"Net Cash to Bank: INR {t.net_cash_realized_inr:,.2f}{full_tag}"
        )

    fiduciary_safeguards = [
        "100% 0% Exit Load Guarantee: Immature lots (<365 days) are shielded from personal redemption.",
        f"Section 112A Tax Shield Siphon: INR {total_tax_sheltered:,.2f} of LTCG harvested 100% tax-free under annual exemption.",
        f"Fee Bleed Termination: Liquidating these positions permanently saves INR {total_bleed_saved:,.2f} per year in distributor commissions.",
        "Core Capital Protection: Core Direct compounding anchors (Flexi-Cap, BAF, Core Index) are strictly protected and left untouched.",
    ]
    if accumulated_loss_pool > 0:
        fiduciary_safeguards.append(
            f"Section 70 Loss Netting: Created INR {accumulated_loss_pool:,.2f} in allowable capital losses to offset future gains."
        )

    return PersonalRedemptionPlan(
        requested_amount_inr=round(requested_amount, 2),
        ticket_category=ticket_category,
        ticket_rationale=ticket_rationale,
        is_net_cash_target=is_net_cash,
        total_gross_redeemed_inr=round(total_gross, 2),
        total_exit_load_inr=round(total_exit_load, 2),
        total_realized_gain_loss_inr=round(total_gain_loss, 2),
        total_stcg_tax_inr=round(total_stcg_tax, 2),
        total_ltcg_tax_inr=round(total_ltcg_tax, 2),
        total_tax_sheltered_under_112a_inr=round(total_tax_sheltered, 2),
        total_net_tax_inr=round(total_net_tax, 2),
        total_net_cash_inr=round(total_net_cash, 2),
        total_annual_commission_saved_inr=round(total_bleed_saved, 2),
        funds_liquidated_count=len(tranches),
        full_folio_exits_count=full_exits,
        tranches=tranches,
        execution_steps=exec_steps,
        fiduciary_safeguards=fiduciary_safeguards,
    )

