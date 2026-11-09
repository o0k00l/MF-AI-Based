"""
core/math/tax_lots.py - FIFO Tax Lot Builder & §112A Staging Module.

Builds FIFO tax lots from transaction history, computes LTCG/STCG
splits, and stages redemptions across financial years to maximize
the ₹1.25L LTCG exemption per FY.
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
import re
from datetime import datetime


@dataclass
class TaxLot:
    """A single purchase lot of a fund."""
    fund_id: str
    scheme_name: str
    folio: str
    purchase_date: date
    units: float
    nav: float
    cost: float
    source: str  # "transactions" or "manual"

    def holding_days(self, as_of: date) -> int:
        return (as_of - self.purchase_date).days

    def is_long_term(self, as_of: date, holding_months: int = 12) -> bool:
        """LTCG if holding period > 12 months (strict: > 12 months, not >=)."""
        return (as_of - self.purchase_date).days > 365

    def is_short_term(self, as_of: date) -> bool:
        return not self.is_long_term(as_of)


@dataclass
class TaxLotSummary:
    """Aggregated tax lot summary for a fund."""
    fund_id: str
    scheme_name: str
    total_units: float
    total_cost: float
    current_value: float
    unrealized_gain: float
    ltcg_units: float
    ltcg_gain: float
    stcg_units: float
    stcg_gain: float
    ltcg_tax: float
    stcg_tax: float
    ltcg_exemption_used: float
    stcg_exemption_used: float


def _fifo_redeem(lots: List[TaxLot], units_to_remove: float) -> List[TaxLot]:
    """
    Remove units from lot pool using FIFO method.
    
    NOTE: This legacy helper is disabled pending regulatory approval.
    DO NOT USE for tax classification purposes.
    Use approved tax-engine pathways for statutory compliance.
    """
    from core.math_engine import TaxClassificationDisabledError
    
    raise TaxClassificationDisabledError(
        "Legacy FIFO redemption helper is disabled. Use approved tax-engine pathways "
        "for statutory compliance. Direct tax-lot maturity classification requires "
        "independent Indian tax/legal approval."
    )

def _tax_lot_maturity_classification_disabled(*args, **kwargs):
    from core.math_engine import TaxClassificationDisabledError

    raise TaxClassificationDisabledError(
        "Direct tax-lot maturity classification is disabled pending independent "
        "Indian tax/legal approval and exact scheme/plan/lot evidence. No "
        "holding-period, LTCG or STCG classification has been generated."
    )


# Guard both public methods; the legacy holding_months parameter is not accepted
# as a way to substitute a generic statutory holding period.
TaxLot.is_long_term = _tax_lot_maturity_classification_disabled
TaxLot.is_short_term = _tax_lot_maturity_classification_disabled
TaxLot.is_short_term = _tax_lot_maturity_classification_disabled
