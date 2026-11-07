"""services/fiduciary_engine.py — Bridge service linking Web UI to Core Fiduciary Math Engine.

Transforms UI session state (CAS holdings, CGS capital gains, 3-mode Risk Profile,
and Financial Goals) into rigorous mathematical models and deterministic SAA plans.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from core.math_engine import calculate_saa_drift, quantize_inr
from core.models import AssetClass, HoldingItem, PlanType, SAADriftAnalysis
from services.risk_profiler import TargetSaa, SebiRiskTier, RiskProfileResult


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

    def _match_kw(f_obj: Dict[str, Any], kws: List[str]) -> bool:
        s_name = str(f_obj.get("scheme") or "").lower()
        return any(k in s_name for k in kws)

    if direct_funds:
        # Match schemes to sleeves
        lc_fund = next((f for f in direct_funds if _match_kw(f, ["large", "index", "nifty"])), None)
        ms_fund = next((f for f in direct_funds if _match_kw(f, ["mid", "small"])), None)
        db_fund = next((f for f in direct_funds if str(f.get("category") or "") == "Debt" or _match_kw(f, ["liquid", "arbitrage", "money market"])), None)

        # Fallbacks for equity sleeves if specific cap categories not held
        if not lc_fund:
            lc_fund = next((f for f in direct_funds if str(f.get("category") or "") == "Equity"), None)
        if not ms_fund:
            ms_fund = next((f for f in direct_funds if f != lc_fund and str(f.get("category") or "") == "Equity"), None)

        # Large-Cap Sleeve
        if lc_target > Decimal("0.00"):
            s_name = lc_fund.get("scheme") if lc_fund else "Nifty 50 Index Fund (Direct - Growth)"
            f_num = lc_fund.get("folio_no", "Existing Direct Folio") if lc_fund else "New Direct Folio Mandate"
            allocations.append({
                "sleeve": "Large-Cap Core Index",
                "scheme_name": s_name,
                "folio_no": f_num,
                "amount_inr": lc_target,
                "allocation_pct": float(lc_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Anchor core equity compounding in lowest-cost Direct large cap index scheme (0.20% TER).",
            })

        # Mid/Small-Cap Sleeve
        if ms_target > Decimal("0.00"):
            s_name = ms_fund.get("scheme") if ms_fund else "Active Quality Mid/Small Cap Fund (Direct - Growth)"
            f_num = ms_fund.get("folio_no", "Existing Direct Folio") if ms_fund else "New Direct Folio Mandate"
            allocations.append({
                "sleeve": "Mid/Small-Cap Alpha",
                "scheme_name": s_name,
                "folio_no": f_num,
                "amount_inr": ms_target,
                "allocation_pct": float(ms_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Long-term alpha accumulation aligned with investor risk tolerance without distributor trail drag.",
            })

        # Debt Sleeve (Strict Fiduciary Separation: Pure Debt/Liquid only, NEVER route debt into hybrid equity)
        if db_target > Decimal("0.00"):
            s_name = db_fund.get("scheme") if db_fund else "Liquid / Capital Preservation Fund (Direct - Growth)"
            f_num = db_fund.get("folio_no", "Existing Direct Folio") if db_fund else "New Direct Folio Mandate"
            allocations.append({
                "sleeve": "Debt & Capital Preservation",
                "scheme_name": s_name,
                "folio_no": f_num,
                "amount_inr": db_target,
                "allocation_pct": float(db_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Statutory capital preservation floor (100% Sovereign T-Bills/Repo). Dedicated liquid buffer separate from equities.",
            })
    else:
        # Client has no Direct schemes yet (or 100% regular) — provide canonical sleeve blueprint
        if lc_target > Decimal("0.00"):
            allocations.append({
                "sleeve": "Large-Cap Core Index",
                "scheme_name": "Nifty 50 Index Fund (Direct - Growth)",
                "folio_no": "New Direct Folio Mandate",
                "amount_inr": lc_target,
                "allocation_pct": float(lc_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Low-cost index foundation (zero commission leakage).",
            })
        if ms_target > Decimal("0.00"):
            allocations.append({
                "sleeve": "Mid/Small-Cap Alpha",
                "scheme_name": "Active Quality Mid/Small Cap Fund (Direct - Growth)",
                "folio_no": "New Direct Folio Mandate",
                "amount_inr": ms_target,
                "allocation_pct": float(ms_pct),
                "plan_type": "Direct-Growth",
                "rationale": "Diversified growth engine aligned with SAA policy.",
            })
        if db_target > Decimal("0.00"):
            allocations.append({
                "sleeve": "Debt & Capital Preservation",
                "scheme_name": "Liquid / Money Market Fund (Direct - Growth)",
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
    has_large = any(_match_kw(f, ["large", "index", "nifty"]) for f in (direct_funds or []))
    has_mid_small = any(_match_kw(f, ["mid", "small"]) for f in (direct_funds or []))
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
    routing_rationale = (
        f"SIP budget of INR {budget_dec:,.2f}/mo is routed across 3 fiduciary sleeves: "
        f"{lc_pct:.0f}% Large-Cap Core (Index compounding), "
        f"{ms_pct:.0f}% Mid/Small-Cap Alpha (Growth engine), and "
        f"{db_pct:.0f}% Debt/Liquid Buffer (Capital stability) in strict compliance with your target SAA."
    )

    return {
        "status": "DETERMINISTIC_SIP_READY",
        "monthly_budget_inr": budget_dec,
        "allocated_budget_inr": total_allocated,
        "unallocated_budget_inr": unallocated,
        "allocations": allocations,
        "reconciliation_valid": abs(unallocated) <= Decimal("0.01"),
        "optimal_tranche_timing": optimal_tranche_timing,
        "portfolio_completion_alerts": completion_alerts,
        "fiduciary_routing_rationale": routing_rationale,
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

