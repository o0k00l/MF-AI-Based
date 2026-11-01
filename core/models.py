"""
core/models.py — Pydantic V2 Data Contracts for Option B.
"""
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field
from datetime import date
from enum import Enum


class PlanType(str, Enum):
    REGULAR = "Regular"
    DIRECT = "Direct"


class AssetClass(str, Enum):
    EQUITY = "Equity"
    LARGE_CAP = "Large_Cap"
    MID_CAP = "Mid_Cap"
    SMALL_CAP = "Small_Cap"
    MULTI_CAP = "Multi_Cap"
    FLEXI_CAP = "Flexi_Cap"
    DEBT = "Debt"
    HYBRID = "Hybrid"
    HYBRID_BALANCED = "Hybrid_Balanced"
    CASH = "Cash"
    INTERNATIONAL = "International"
    OTHER = "Other"


class HoldingItem(BaseModel):
    fund_id: str
    scheme: str
    fund_name: str
    folio: str
    is_direct: bool
    plan: PlanType
    asset_class: AssetClass
    equity_pct: float
    debt_pct: float
    hybrid_pct: float
    international_pct: float
    current_value_inr: float
    invested_value_inr: float
    units: float
    nav: float
    top_holdings: List[str] = Field(default_factory=list)
    risk_tier: Optional[str] = None
    xirr_pct: Optional[float] = None
    expense_ratio_pct: float = 0.0


class FeeBleedAnalysis(BaseModel):
    annual_commission_leakage_inr: float
    ten_year_compounded_loss_inr: float
    regular_funds_count: int
    regular_funds: List[Dict[str, Any]] = Field(default_factory=list)
    direct_alternatives: Dict[str, float] = Field(default_factory=dict)

    # Backward compatibility properties
    @property
    def annual_bleed_inr(self) -> float:
        return self.annual_commission_leakage_inr

    @property
    def regular_portfolio_value_inr(self) -> float:
        return sum(f.get("current_value_inr", 0) for f in self.regular_funds)

    @property
    def details(self) -> List[Dict[str, Any]]:
        return self.regular_funds


class OverlapPair(BaseModel):
    fund_a: str
    fund_b: str
    overlap_pct: float
    shared_stocks: List[str]
    verdict: str  # "HIGH_DUPLICATION" | "MODERATE" | "ACCEPTABLE"


class SAADriftAnalysis(BaseModel):
    current_equity_pct: float
    current_debt_pct: float
    current_cash_pct: float
    current_equity_inr: float
    current_debt_inr: float
    target_equity_pct: float
    target_debt_pct: float
    tolerance_band_pct: float = 5.0
    rebalance_required: bool
    equity_gap_inr: float
    debt_gap_inr: float


class CashDeploymentPlan(BaseModel):
    total_cash_inr: float
    emergency_reserve_inr: float
    emergency_months: float
    deployable_surplus_inr: float
    stp_recommendation: Optional[str] = None
    stp_monthly_amount_inr: float
    stp_duration_months: int
    stp_source_fund: Optional[str] = None
    stp_target_fund: Optional[str] = None


class FiduciaryFactsPayload(BaseModel):
    client_name: str
    total_portfolio_value_inr: float
    total_invested_value_inr: float
    total_unrealized_gain_inr: float
    holdings_count: int
    fee_bleed: FeeBleedAnalysis
    overlap_matrix: List[OverlapPair]
    weighted_overlap: List[WeightedOverlapResult] = Field(default_factory=list)
    risk_distribution: Optional[RiskDistribution] = None
    saa_drift: SAADriftAnalysis
    cash_plan: CashDeploymentPlan
    switch_costs: List[Dict[str, Any]] = Field(default_factory=list)
    eligibility_results: List[Dict[str, Any]] = Field(default_factory=list)
    no_action: Optional[NOActionResult] = None
    monthly_sip_budget_inr: float
    lumpsum_budget_inr: float = 200000.0
    lumpsum_plan: Optional[Dict[str, Any]] = None
    xirr_pct: Optional[float] = None
    benchmark_xirr_pct: Optional[float] = None
    alpha_pct: Optional[float] = None
    tax_lots_summary: Optional[TaxLedger] = None
    weak_funds_flagged: List[Dict[str, Any]] = Field(default_factory=list)
    holdings: List[HoldingItem] = Field(default_factory=list)


class TaxLedger(BaseModel):
    immature_locked_value_inr: float
    mature_switchable_value_inr: float
    projected_ltcg_inr: float
    stagger_required: bool


class TaxLot(BaseModel):
    fund_id: str
    purchase_date: str
    units: float
    nav: float
    cost_basis: float
    holding_days: int
    is_long_term: bool


class TaxLotSummary(BaseModel):
    fund_id: str
    total_lots: int
    long_term_lots: int
    short_term_lots: int
    total_unrealized_ltcg: float
    total_unrealized_stcg: float
    total_exit_load_risk: float


# ============================================================
# NEW MODELS FOR ARCHITECTURAL CORRECTIONS
# ============================================================

class WeightedOverlapResult(BaseModel):
    """Weighted look-through stock concentration across all holdings."""
    fund_a: str
    fund_b: str
    weighted_overlap_pct: float  # Combined portfolio weight in shared stocks
    jaccard_similarity: float    # Secondary measure
    shared_stocks: List[Dict[str, Any]] = Field(default_factory=list)  # {stock, weight_a, weight_b, combined_weight}
    sector_concentration: Dict[str, float] = Field(default_factory=dict)
    verdict: str  # "HIGH_CONCENTRATION", "MODERATE", "ACCEPTABLE"


class RiskDistribution(BaseModel):
    """Ordinal risk tier distribution - not cardinal scores."""
    risk_tier_distribution: Dict[str, int] = Field(default_factory=dict)  # tier -> count
    risk_tier_values: Dict[str, float] = Field(default_factory=dict)  # tier -> portfolio_weight_pct
    portfolio_beta: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    downside_capture_ratio: Optional[float] = None
    volatility_annualized_pct: Optional[float] = None
    # No single cardinal risk score


class SwitchCostAnalysis(BaseModel):
    """Actual cost of switching - not 'zero-friction'."""
    source_fund: str
    target_fund: str
    exit_load_pct: float
    exit_load_inr: float
    capital_gains_tax_inr: float
    stcg_tax_inr: float
    ltcg_tax_inr: float
    net_switch_cost_inr: float
    net_switch_cost_pct: float
    is_intra_amc: bool
    warning: str = "Intra-AMC switches trigger capital gains tax and exit loads per Sections 47 & 112A"


class EligibilityGateResult(BaseModel):
    """Binary eligibility gates - must pass ALL to enter scoring."""
    fund_id: str
    fund_name: str
    passed: bool
    failed_gates: List[str] = Field(default_factory=list)
    liquidity_gate: bool = False
    aum_stability_gate: bool = False
    concentration_gate: bool = False
    mandate_suitability_gate: bool = False
    data_integrity_gate: bool = False
    manager_tenure_gate: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


class NOActionResult(BaseModel):
    """Mandatory NO ACTION decision branch."""
    action: str = "NO_ACTION"
    reason: str
    current_portfolio_adequate: bool
    no_improvement_found: bool
    hold_recommendation: str
    sip_deployment_pause: bool = True


class SAA_DriftMinimizer(BaseModel):
    """SAA Drift Minimizer - NOT an investment optimizer."""
    name: str = "SAA Drift Minimizer"
    description: str = "Minimizes ||Target - (Current + SIP)||_2 subject to SIP budget. Does NOT optimize returns."
    current_allocation: Dict[str, float]
    target_allocation: Dict[str, float]
    sip_budget_inr: float
    recommended_sip_allocation: Dict[str, float]
    drift_after_sip: Dict[str, float]
    total_drift_l2_norm: float
    disclaimer: str = "This minimizes allocation drift only. Does NOT consider expected returns, correlations, or tax efficiency."


# Backward compatibility aliases
FiduciaryPayload = FiduciaryFactsPayload
FeeBleed = FeeBleedAnalysis
OverlapMetric = OverlapPair
# TaxLedger = TaxLotSummary  # Not in this commit's models

# Backward compatibility function aliases
def build_fiduciary_payload(*args, **kwargs):
    """Backward compatibility alias for aggregate_fiduciary_facts."""
    from core.math_engine import aggregate_fiduciary_facts
    return aggregate_fiduciary_facts(*args, **kwargs)

def calculate_weighted_overlap(fund_a_holdings: Dict[str, float], fund_b_holdings: Dict[str, float]) -> float:
    """Backward compatibility alias for calculate_weighted_lookthrough_overlap (pairwise version)."""
    from core.math_engine import calculate_weighted_lookthrough_overlap
    # This is a simplified pairwise version for backward compatibility
    shared_stocks = set(fund_a_holdings.keys()) & set(fund_b_holdings.keys())
    overlap_weight = sum(min(fund_a_holdings[s], fund_b_holdings[s]) for s in shared_stocks)
    return round(overlap_weight, 2)

def compute_liquidity_waterfall(bank_balance: float, monthly_expenses: float, months_reserve: float = 6.0) -> Tuple[float, float]:
    """Backward compatibility alias for calculate_cash_deployment (returns tuple)."""
    from core.math_engine import calculate_cash_deployment
    from core.models import CashDeploymentPlan
    result = calculate_cash_deployment(bank_cash_inr=bank_balance, emergency_buffer_inr=monthly_expenses * months_reserve)
    return result.emergency_reserve_inr, result.deployable_surplus_inr
