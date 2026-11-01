"""
core/models.py - Strict Pydantic V2 data contracts for Option B.
"""

from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field


class PlanType(str, Enum):
    DIRECT = "Direct"
    REGULAR = "Regular"
    UNKNOWN = "Unknown"


class AssetClass(str, Enum):
    LARGE_CAP = "Large-Cap"
    MID_CAP = "Mid-Cap"
    SMALL_CAP = "Small-Cap"
    HYBRID_BALANCED = "Hybrid/Balanced"
    DEBT_LIQUID = "Debt/Liquid"
    OTHER = "Other"


class HoldingItem(BaseModel):
    fund_id: str
    fund_name: str
    folio_no: str = ""
    plan: PlanType = PlanType.UNKNOWN
    invested_value_inr: float = 0.0
    current_value_inr: float = 0.0
    expense_ratio_pct: float = 0.0
    category: str = "Unknown"
    asset_class: AssetClass = AssetClass.OTHER
    equity_pct: float = 100.0
    debt_pct: float = 0.0
    large_cap_pct: float = 0.0
    mid_cap_pct: float = 0.0
    small_cap_pct: float = 0.0
    sharpe_ratio: Optional[float] = None
    top_holdings: List[str] = Field(default_factory=list)


class FeeBleedAnalysis(BaseModel):
    annual_bleed_inr: float
    ten_year_compounded_loss_inr: float
    regular_funds_count: int
    regular_portfolio_value_inr: float
    details: List[Dict[str, Any]] = Field(default_factory=list)


class OverlapPair(BaseModel):
    fund_a: str
    fund_b: str
    overlap_pct: float
    shared_stocks: List[str] = Field(default_factory=list)
    verdict: str  # "HIGH_DUPLICATION", "MODERATE", "ACCEPTABLE"


class SAADriftAnalysis(BaseModel):
    current_equity_pct: float
    current_debt_pct: float
    current_cash_pct: float
    current_equity_inr: float
    current_debt_inr: float
    target_equity_pct: float
    target_debt_pct: float
    tolerance_band_pct: float = 5.0
    rebalance_required: bool = False
    equity_gap_inr: float = 0.0
    debt_gap_inr: float = 0.0

    @property
    def equity_drift_pct(self) -> float:
        return round(self.current_equity_pct - self.target_equity_pct, 2)

    @property
    def debt_drift_pct(self) -> float:
        return round(self.current_debt_pct - self.target_debt_pct, 2)


class CashDeploymentPlan(BaseModel):
    total_bank_cash_inr: float
    emergency_buffer_inr: float
    deployable_surplus_inr: float
    immediate_lump_sum_inr: float = 0.0
    stp_monthly_amount_inr: float = 0.0
    stp_duration_months: int = 6


class FiduciaryFactsPayload(BaseModel):
    client_name: str
    total_portfolio_value_inr: float
    total_invested_value_inr: float
    total_unrealized_gain_inr: float
    holdings_count: int
    fee_bleed: FeeBleedAnalysis
    overlap_matrix: List[OverlapPair]
    saa_drift: SAADriftAnalysis
    cash_plan: CashDeploymentPlan
    monthly_sip_budget_inr: float
    lumpsum_budget_inr: float = 200000.0
    lumpsum_plan: Optional[Dict[str, Any]] = None
    xirr_pct: Optional[float] = None
    benchmark_xirr_pct: Optional[float] = None
    alpha_pct: Optional[float] = None
    tax_lots_summary: Optional[Dict[str, Any]] = None
    weak_funds_flagged: List[Dict[str, Any]] = Field(default_factory=list)
    holdings: List[HoldingItem] = Field(default_factory=list)
