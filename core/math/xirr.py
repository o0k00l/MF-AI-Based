"""
core/math/xirr.py - XIRR Calculation Module.

Calculates Extended Internal Rate of Return for irregular cash flows
using Newton-Raphson with secant method fallback.
"""

from __future__ import annotations
from datetime import date
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

    # Sort by date
    cashflows = sorted(cashflows, key=lambda x: x[0])

    # Check if we have both positive and negative flows
    has_negative = any(cf[1] < 0 for cf in cashflows)
    has_positive = any(cf[1] > 0 for cf in cashflows)
    if not (has_negative and has_positive):
        return None

    # Use Newton-Raphson method to solve for IRR
    # NPV(rate) = sum(cf / (1+rate)^(days/365)) = 0

    def npv(rate: float) -> float:
        total = 0.0
        base_date = cashflows[0][0]
        for cf_date, amount in cashflows:
            days = (cf_date - base_date).days
            total += amount / ((1 + rate) ** (days / 365.0))
        return total

    def npv_derivative(rate: float) -> float:
        total = 0.0
        base_date = cashflows[0][0]
        for cf_date, amount in cashflows:
            days = (cf_date - base_date).days
            total += -amount * (days / 365.0) / ((1 + rate) ** (days / 365.0 + 1))
        return total

    # Initial guess: simple approximation
    total_invested = sum(abs(cf[1]) for cf in cashflows if cf[1] < 0)
    total_returned = sum(cf[1] for cf in cashflows if cf[1] > 0)
    if total_invested > 0:
        guess = (total_returned - total_invested) / total_invested
        guess = max(-0.99, min(10.0, guess))  # Clamp between -99% and 1000%
    else:
        guess = 0.1

    # Newton-Raphson iteration
    rate = guess
    for _ in range(100):
        npv_val = npv(rate)
        if abs(npv_val) < 1e-6:
            return rate
        deriv = npv_derivative(rate)
        if abs(deriv) < 1e-10:
            break
        rate_new = rate - npv_val / deriv
        if abs(rate_new - rate) < 1e-8:
            return rate_new
        rate = rate_new

    # Fallback: secant method
    rate_low, rate_high = -0.99, 10.0
    npv_low, npv_high = npv(rate_low), npv(rate_high)
    if npv_low * npv_high > 0:
        return None
    for _ in range(50):
        rate_mid = (rate_low + rate_high) / 2
        npv_mid = npv(rate_mid)
        if abs(npv_mid) < 1e-6:
            return rate_mid
        if npv_low * npv_mid <= 0:
            rate_high, npv_high = rate_mid, npv_mid
        else:
            rate_low, npv_low = rate_mid, npv_mid
    return (rate_low + rate_high) / 2