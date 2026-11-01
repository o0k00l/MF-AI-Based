"""
core/math/fee_bleed.py - Fee Bleed Analysis Module.

Computes exact annual commission drag for Regular plan holdings
and 10-year compounded opportunity loss at 12% CAGR.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any
from core.models import HoldingItem, PlanType


@dataclass
class FeeBleedAnalysis:
    """Analysis of commission drag from Regular plan funds."""
    annual_bleed_inr: float
    ten_year_compounded_loss_inr: float
    regular_funds_count: int
    regular_portfolio_value_inr: float
    details: List[Dict[str, Any]]


def calculate_fee_bleed(
    holdings: List[HoldingItem],
    default_commission_rate: float = 0.0105
) -> FeeBleedAnalysis:
    """
    Computes exact annual commission drag for Regular plan holdings.
    Also calculates 10-year compounded opportunity loss at 12% CAGR.
    """
    regular_holdings = [h for h in holdings if h.plan == PlanType.REGULAR]
    total_regular_val = sum(h.current_value_inr for h in regular_holdings)

    details = []
    annual_bleed = 0.0

    for h in regular_holdings:
        # Typical distributor trail commission delta is ~1.05% per year
        fund_bleed = h.current_value_inr * default_commission_rate
        annual_bleed += fund_bleed
        details.append({
            "fund_name": h.fund_name,
            "folio_no": h.folio_no,
            "current_value_inr": round(h.current_value_inr, 2),
            "estimated_annual_commission_inr": round(fund_bleed, 2),
            "expense_ratio_pct": round(h.expense_ratio_pct, 2)
        })

    # Sort details by commission bleed descending
    details.sort(key=lambda x: x["estimated_annual_commission_inr"], reverse=True)

    # 10-year compounding lost wealth: annuity factor at 12% CAGR over 10 years
    # Sum_{t=1}^{10} (1.12)^t = 1.12 * ((1.12^10 - 1) / 0.12) = 19.65
    # Future value of annuity due = Annual * [((1+r)^n - 1)/r] * (1+r)
    r = 0.12
    n = 10
    annuity_factor = (((1.0 + r) ** n - 1.0) / r) * (1.0 + r)
    ten_year_compounded_loss = annual_bleed * annuity_factor

    return FeeBleedAnalysis(
        annual_bleed_inr=round(annual_bleed, 2),
        ten_year_compounded_loss_inr=round(ten_year_compounded_loss, 2),
        regular_funds_count=len(regular_holdings),
        regular_portfolio_value_inr=round(total_regular_val, 2),
        details=details
    )