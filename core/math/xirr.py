"""
core/math/xirr.py - XIRR Calculation Module.

Calculates Extended Internal Rate of Return for irregular cash flows
using Newton-Raphson with secant method fallback.
"""

from __future__ import annotations
from datetime import date, datetime
import math
from typing import List, Tuple, Optional


def calculate_xirr(cashflows: List[Tuple[date, float]]) -> Optional[float]:
    """
    Calculate XIRR (Extended Internal Rate of Return) for irregular cash flows.

    Args:
        cashflows: List of (date, amount) tuples where negative = investment, positive = return

    Returns:
        Annualized XIRR as decimal (e.g., 0.134 for 13.4%), or None if cannot converge
    """
    if not cashflows or len(cashflows) < 2:
        return None

    # Strict domain and type validation on all cashflows
    clean_flows = []
    for cf in cashflows:
        if not isinstance(cf, (tuple, list)) or len(cf) != 2:
            return None
        cf_date, amount = cf
        if not isinstance(cf_date, date) or isinstance(cf_date, datetime):
            return None
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            return None
        amount_float = float(amount)
        if not math.isfinite(amount_float):
            return None
        clean_flows.append((cf_date, amount_float))

    # Sort by date
    clean_flows.sort(key=lambda x: x[0])

    # Check if we have both positive and negative flows
    has_negative = any(cf[1] < 0 for cf in clean_flows)
    has_positive = any(cf[1] > 0 for cf in clean_flows)
    if not (has_negative and has_positive):
        return None

    def npv(rate: float) -> float:
        if rate <= -1.0:
            return float("nan")
        total = 0.0
        base_date = clean_flows[0][0]
        for cf_date, amount in clean_flows:
            days = (cf_date - base_date).days
            try:
                term = (1.0 + rate) ** (days / 365.0)
                if term == 0.0:
                    return float("nan")
                total += amount / term
            except (OverflowError, ZeroDivisionError, ValueError):
                return float("nan")
        return total

    def npv_derivative(rate: float) -> float:
        if rate <= -1.0:
            return float("nan")
        total = 0.0
        base_date = clean_flows[0][0]
        for cf_date, amount in clean_flows:
            days = (cf_date - base_date).days
            try:
                denom = (1.0 + rate) ** (days / 365.0 + 1.0)
                if denom == 0.0:
                    return float("nan")
                total += -amount * (days / 365.0) / denom
            except (OverflowError, ZeroDivisionError, ValueError):
                return float("nan")
        return total

    # Initial guess
    total_invested = sum(abs(cf[1]) for cf in clean_flows if cf[1] < 0)
    total_returned = sum(cf[1] for cf in clean_flows if cf[1] > 0)
    if total_invested > 0:
        guess = (total_returned - total_invested) / total_invested
        guess = max(-0.99, min(10.0, guess))
    else:
        guess = 0.1

    # Newton-Raphson iteration
    rate = guess
    for _ in range(100):
        if rate <= -0.999:
            break
        npv_val = npv(rate)
        if not math.isfinite(npv_val):
            break
        if abs(npv_val) < 1e-6:
            return rate
        deriv = npv_derivative(rate)
        if not math.isfinite(deriv) or abs(deriv) < 1e-10:
            break
        rate_new = rate - npv_val / deriv
        if rate_new <= -0.999:
            rate_new = -0.99
        if abs(rate_new - rate) < 1e-8:
            new_npv = npv(rate_new)
            if math.isfinite(new_npv) and abs(new_npv) < 1e-4:
                return rate_new
            break
        rate = rate_new

    # Fallback: secant / bisection method
    rate_low, rate_high = -0.99, 10.0
    npv_low, npv_high = npv(rate_low), npv(rate_high)
    if not (math.isfinite(npv_low) and math.isfinite(npv_high)) or npv_low * npv_high > 0:
        return None
    for _ in range(100):
        rate_mid = (rate_low + rate_high) / 2.0
        npv_mid = npv(rate_mid)
        if not math.isfinite(npv_mid):
            return None
        if abs(npv_mid) < 1e-6:
            return rate_mid
        if npv_low * npv_mid <= 0:
            rate_high, npv_high = rate_mid, npv_mid
        else:
            rate_low, npv_low = rate_mid, npv_mid

    final_rate = (rate_low + rate_high) / 2.0
    final_npv = npv(final_rate)
    if math.isfinite(final_npv) and abs(final_npv) < 1e-4:
        return final_rate
    return None
