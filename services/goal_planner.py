"""services/goal_planner.py — Sensible, Fiduciary Financial Goal & Milestone Planning Engine.

Market Standard Features (SEBI RIA & CFA Wealth Management):
1. Integrates Existing Portfolio: Compounds existing invested corpus from CAS so users
   never start from artificial zero.
2. Smart Step-Up SIP: Models 5% - 10% annual salary step-up, making initial required
   monthly investments realistic rather than intimidating.
3. Realistic Inflation & Horizon-Aware Return Models:
   - Horizon < 5 years: ~8.5% conservative CAGR (Debt / Hybrid).
   - Horizon 5-10 years: ~11.0% moderate CAGR.
   - Horizon 10+ years: ~12.0% long-term compounding CAGR.
4. Constructive Feasibility Guidance: Provides clear trade-offs (step-up, horizon extension,
   or portfolio allocation) rather than discouraging raw shortfall numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GoalCalculationResult:
    """Complete, realistic financial goal projection."""
    goal_name: str
    horizon_years: int
    cost_today_inr: float
    future_target_inr: float
    existing_corpus_inr: float
    existing_corpus_future_val_inr: float
    net_corpus_needed_inr: float
    expected_cagr_pct: float
    inflation_rate_pct: float
    flat_monthly_sip_inr: float
    step_up_pct: float
    step_up_initial_sip_inr: float
    existing_corpus_coverage_pct: float
    feasibility_status: str
    actionable_advice: str


def compute_expected_cagr(horizon_years: int) -> float:
    """Return realistic market-standard portfolio CAGR based on horizon."""
    if horizon_years < 3:
        return 7.5   # Liquid / Arbitrage
    elif horizon_years <= 5:
        return 8.5   # Conservative / Hybrid
    elif horizon_years <= 8:
        return 10.5  # Balanced Advantage / Large Cap
    elif horizon_years <= 12:
        return 11.5  # Multi / Flexi Cap
    else:
        return 12.0  # Core Long-Term Equities


def calculate_future_value(present_value: float, annual_rate_pct: float, years: int) -> float:
    """Calculate inflation-adjusted or compounded future value."""
    if years <= 0 or present_value <= 0:
        return present_value
    return present_value * ((1.0 + (annual_rate_pct / 100.0)) ** years)


def calculate_flat_monthly_sip(future_value_needed: float, annual_cagr_pct: float, years: int) -> float:
    """Calculate required constant monthly SIP at given annual CAGR."""
    if future_value_needed <= 0 or years <= 0:
        return 0.0
    r_mo = (annual_cagr_pct / 100.0) / 12.0
    n_mo = years * 12
    # FV factor = ((1 + r)^n - 1) / r
    fv_factor = (((1.0 + r_mo) ** n_mo) - 1.0) / r_mo
    return future_value_needed / fv_factor


def calculate_step_up_initial_sip(
    future_value_needed: float,
    annual_cagr_pct: float,
    years: int,
    annual_step_up_pct: float = 10.0,
) -> float:
    """Calculate initial (Month 1) SIP required with an annual step-up percentage.

    With annual step-up, the SIP increases by `annual_step_up_pct` every 12 months.
    This solves for the starting monthly SIP.
    """
    if future_value_needed <= 0 or years <= 0:
        return 0.0
    if annual_step_up_pct <= 0:
        return calculate_flat_monthly_sip(future_value_needed, annual_cagr_pct, years)

    r_mo = (annual_cagr_pct / 100.0) / 12.0
    total_months = years * 12

    # Simulate accumulation of 1 Rupee initial SIP to find scaling multiplier
    accumulated_per_rupee = 0.0
    for m in range(total_months):
        year_idx = m // 12
        step_multiplier = (1.0 + (annual_step_up_pct / 100.0)) ** year_idx
        months_remaining = total_months - m
        compounded_growth = (1.0 + r_mo) ** months_remaining
        accumulated_per_rupee += step_multiplier * compounded_growth

    if accumulated_per_rupee <= 0:
        return calculate_flat_monthly_sip(future_value_needed, annual_cagr_pct, years)

    return future_value_needed / accumulated_per_rupee


def plan_goal(
    *,
    goal_name: str,
    cost_today_inr: float,
    horizon_years: int,
    existing_allocated_corpus_inr: float = 0.0,
    inflation_rate_pct: float = 6.0,
    annual_step_up_pct: float = 10.0,
    monthly_budget_capacity_inr: float | None = None,
) -> GoalCalculationResult:
    """Plan a realistic, sensible financial milestone goal.

    Arguments:
        goal_name: Description (e.g. 'Retirement', 'Child Higher Education', 'Home Down Payment').
        cost_today_inr: Estimated cost of the goal in today's rupees.
        horizon_years: Years until goal must be realized.
        existing_allocated_corpus_inr: Portion of existing portfolio allocated to this goal.
        inflation_rate_pct: Expected annual inflation for this specific goal category.
        annual_step_up_pct: Expected annual increase in SIP contribution (default 10%).
        monthly_budget_capacity_inr: Optional current monthly investment capacity for feasibility check.

    Returns:
        GoalCalculationResult with realistic compounding and actionable guidance.
    """
    horizon_years = max(1, int(horizon_years))
    cagr_pct = compute_expected_cagr(horizon_years)

    # 1. Future target value with inflation
    future_target = calculate_future_value(cost_today_inr, inflation_rate_pct, horizon_years)

    # 2. Future value of existing allocated portfolio
    existing_fv = calculate_future_value(existing_allocated_corpus_inr, cagr_pct, horizon_years)

    # 3. Net corpus required from fresh SIPs
    net_needed = max(0.0, future_target - existing_fv)

    # 4. Coverage percentage from existing assets
    coverage_pct = min(100.0, (existing_fv / future_target * 100.0)) if future_target > 0 else 100.0

    # 5. SIP sizing
    flat_sip = calculate_flat_monthly_sip(net_needed, cagr_pct, horizon_years)
    step_up_sip = calculate_step_up_initial_sip(net_needed, cagr_pct, horizon_years, annual_step_up_pct)

    # 6. Feasibility & Actionable Guidance
    advice_items: list[str] = []
    if coverage_pct >= 100.0:
        status = "Fully Funded by Existing Portfolio"
        advice_items.append(
            f"🎉 **Goal Already Secured:** Your allocated ₹{existing_allocated_corpus_inr:,.0f} existing portfolio "
            f"will compound to ₹{existing_fv:,.0f}, completely funding this goal without requiring any fresh SIP!"
        )
    else:
        if coverage_pct > 0.0:
            advice_items.append(
                f"🛡️ **Existing Portfolio Heavy Lifting:** Your existing ₹{existing_allocated_corpus_inr:,.0f} will grow "
                f"to ₹{existing_fv:,.0f}, covering **{coverage_pct:.1f}%** of your target future corpus."
            )

        advice_items.append(
            f"💡 **Smart Step-Up Advantage:** Starting with an annual {annual_step_up_pct:.0f}% step-up requires only "
            f"**₹{step_up_sip:,.0f}/month** initially (vs. a flat ₹{flat_sip:,.0f}/month fixed SIP) — saving "
            f"₹{flat_sip - step_up_sip:,.0f}/mo in initial cashflow."
        )

        if monthly_budget_capacity_inr is not None and monthly_budget_capacity_inr > 0:
            if monthly_budget_capacity_inr >= step_up_sip:
                status = "Comfortably Achievable"
                surplus = monthly_budget_capacity_inr - step_up_sip
                advice_items.append(
                    f"✅ **Fits Your Budget:** Your monthly capacity of ₹{monthly_budget_capacity_inr:,.0f} covers "
                    f"this goal with a monthly surplus of ₹{surplus:,.0f} available for other goals."
                )
            else:
                deficit = step_up_sip - monthly_budget_capacity_inr
                status = "Needs Horizon / Allocation Tuning"
                advice_items.append(
                    f"⚖️ **Optimization Options:** Gap of ₹{deficit:,.0f}/month. Consider extending the horizon by "
                    f"1–2 years or allocating an additional ₹{min(cost_today_inr, deficit * 24):,.0f} from existing investments."
                )
        else:
            status = "Planning Ready"

    return GoalCalculationResult(
        goal_name=goal_name,
        horizon_years=horizon_years,
        cost_today_inr=cost_today_inr,
        future_target_inr=future_target,
        existing_corpus_inr=existing_allocated_corpus_inr,
        existing_corpus_future_val_inr=existing_fv,
        net_corpus_needed_inr=net_needed,
        expected_cagr_pct=cagr_pct,
        inflation_rate_pct=inflation_rate_pct,
        flat_monthly_sip_inr=flat_sip,
        step_up_pct=annual_step_up_pct,
        step_up_initial_sip_inr=step_up_sip,
        existing_corpus_coverage_pct=coverage_pct,
        feasibility_status=status,
        actionable_advice="\n\n".join(advice_items),
    )

