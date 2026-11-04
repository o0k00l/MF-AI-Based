"""Fail-closed fee-drag analysis.

No universal distributor commission or future-return assumption is used.
Fee/commission amounts remain unavailable until matched plan-specific and
distributor-specific evidence plus approved scenario assumptions are supplied.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.models import HoldingItem, PlanType


@dataclass
class FeeBleedAnalysis:
    annual_bleed_inr: Optional[float]
    ten_year_compounded_loss_inr: Optional[float]
    regular_funds_count: int
    regular_portfolio_value_inr: Optional[float]
    details: List[Dict[str, Any]]
    availability_status: str = "UNAVAILABLE"
    unavailable_reason: str = (
        "Exact scheme/plan/distributor/effective-date commission evidence and approved "
        "future-return assumptions are required. No generic estimate is generated."
    )


def calculate_fee_bleed(holdings: List[HoldingItem]) -> FeeBleedAnalysis:
    """Return only the observed Regular-plan value; never infer commission drag."""
    regular_holdings = [holding for holding in holdings if holding.plan == PlanType.REGULAR]
    total_regular_value = sum(holding.current_value_inr for holding in regular_holdings)
    return FeeBleedAnalysis(
        annual_bleed_inr=None,
        ten_year_compounded_loss_inr=None,
        regular_funds_count=len(regular_holdings),
        regular_portfolio_value_inr=round(total_regular_value, 2) if regular_holdings else None,
        details=[],
        availability_status="UNAVAILABLE",
        unavailable_reason=(
            "Exact scheme/plan/distributor/effective-date commission evidence and approved "
            "future-return assumptions are required. No generic estimate is generated."
        ),
    )
