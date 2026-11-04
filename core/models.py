"""
core/models.py — Pydantic V2 Data Contracts for Option B.
"""
from __future__ import annotations

from typing import List, Dict, Optional, Any, Tuple
from pydantic import BaseModel, Field, model_validator
from datetime import date
from enum import Enum


class PlanType(str, Enum):
    UNKNOWN = "Unknown"
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
    DEBT_LIQUID = "Debt_Liquid"  # For liquid/debt funds (added to support transition planner)


class MandateExecutionState(str, Enum):
    ADVISORY_PROPOSAL = "ADVISORY_PROPOSAL_PENDING_WRITTEN_CLIENT_AUTHORIZATION"
    CLIENT_APPROVED = "CLIENT_APPROVED_EXECUTION_READY"
    HOLD_PENDING_TRI_VALIDATION = "HOLD_PENDING_TRI_VALIDATION"
    FROZEN_PORTFOLIO_REVIEW = "FROZEN_PORTFOLIO_REVIEW_APRIL_2027" 

def _validate_mandate_flags(state: MandateExecutionState, authorized: bool, actionable: bool = False) -> None:
    state_value = state.value if isinstance(state, MandateExecutionState) else str(state)
    approved_value = MandateExecutionState.CLIENT_APPROVED.value
    if authorized is not True and actionable is True:
        raise ValueError("An actionable order cannot exist without explicit execution authorization")
    if authorized is True and state_value != approved_value:
        raise ValueError("Execution authorization is valid only in CLIENT_APPROVED_EXECUTION_READY state")


# New simplified 3+1 risk tier system
class RiskTier(str, Enum):
    CONSERVATIVE = "Conservative"
    MODERATE = "Moderate"
    AGGRESSIVE = "Aggressive"
    CUSTOM = "Custom"

class AssetAllocationTarget(BaseModel):
    """Validated total-portfolio SAA; all sleeves must reconcile to 100%."""

    equity_pct: float = Field(ge=0.0, le=100.0)
    debt_pct: float = Field(ge=0.0, le=100.0)
    cash_pct: float = Field(ge=0.0, le=100.0)

    @model_validator(mode="after")
    def validate_total_allocation(self) -> "AssetAllocationTarget":
        import math

        values = (self.equity_pct, self.debt_pct, self.cash_pct)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("SAA percentages must be finite numbers")
        if abs(sum(values) - 100.0) > 0.01:
            raise ValueError("Custom SAA equity, debt and cash percentages must sum to 100%")
        return self

# The deterministic 3+1 Policy Map
# Keep the investor-facing 3-tier labels aligned with the authoritative
# behavioural-risk SAA profiles used by the SIP engine:
# Conservative -> SEBI Tier 2 (40/60), Moderate -> Tier 4 (75/25),
# Aggressive -> Tier 6 (95/5). Custom remains explicit and separately approved.
def _load_saa_policy_map() -> Dict[RiskTier, AssetAllocationTarget]:
    """Build the public SAA contract from the single authoritative policy file."""
    import json
    from pathlib import Path

    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        profiles = policy["behavioral_risk_profiles"]
        profile_by_risk = {
            RiskTier.CONSERVATIVE: "low_to_moderate",
            RiskTier.MODERATE: "moderately_high",
            RiskTier.AGGRESSIVE: "very_high",
        }
        result: Dict[RiskTier, AssetAllocationTarget] = {}
        for risk, profile_name in profile_by_risk.items():
            targets = profiles[profile_name]["saa_targets"]
            equity = sum(float(targets[key]) for key in (
                "large_cap_pct", "mid_cap_pct", "small_cap_pct", "flexi_multi_cap_pct"
            ))
            result[risk] = AssetAllocationTarget(
                equity_pct=equity,
                debt_pct=float(targets["debt_liquid_pct"]),
                cash_pct=float(targets.get("cash_pct", 0.0)),
            )
        return result
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise RuntimeError("Authoritative asset-allocation policy is missing or invalid") from exc


SAA_POLICY_MAP = _load_saa_policy_map()


class HoldingItem(BaseModel):
    fund_id: str
    scheme: str
    fund_name: str
    amc_name: Optional[str] = None
    folio: str
    is_direct: Optional[bool] = None
    plan: PlanType = PlanType.UNKNOWN
    plan_option_status: str = "MISSING"
    option_type: Optional[str] = None
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
    # Full, source-verified constituent weights as percentages of the fund equity sleeve.
    # Missing or partial look-through data must not be interpreted as zero overlap.
    constituent_weights: Optional[Dict[str, float]] = None
    constituent_weights_coverage_pct: Optional[float] = None
    # Stable identity and disclosure state are separate from display names.
    scheme_id: Optional[str] = None
    isin: Optional[str] = None
    lookthrough_status: str = "MISSING"
    lookthrough_reason: Optional[str] = "No verified stock-level disclosure attached."
    lookthrough_effective_date: Optional[str] = None
    lookthrough_source_url: Optional[str] = None
    lookthrough_source_document_sha256: Optional[str] = None
    risk_tier: Optional[str] = None
    riskometer_score: Optional[int] = None
    riskometer_as_of_date: Optional[str] = None
    riskometer_source_url: Optional[str] = None
    riskometer_source_document_sha256: Optional[str] = None
    # Metrics are independent of scheme identity. MISSING/INCOMPLETE metrics
    # must never be interpreted as zero exposure or used for SIP scoring.
    metrics_status: str = "MISSING"
    xirr_pct: Optional[float] = None
    expense_ratio_pct: Optional[float] = None


class FeeBleedAnalysis(BaseModel):
    """Verified commission analysis; unavailable is distinct from zero."""
    annual_commission_leakage_inr: Optional[float] = None
    ten_year_compounded_loss_inr: Optional[float] = None
    regular_funds_count: int
    regular_funds: List[Dict[str, Any]] = Field(default_factory=list)
    direct_alternatives: Dict[str, float] = Field(default_factory=dict)
    availability_status: str = "UNAVAILABLE"
    unavailable_reason: Optional[str] = (
        "Scheme-, plan-, distributor- and effective-date-specific commission evidence is not supplied."
    )

    # Backward compatibility properties
    @property
    def annual_bleed_inr(self) -> Optional[float]:
        return self.annual_commission_leakage_inr

    @property
    def regular_portfolio_value_inr(self) -> float:
        if not self.regular_funds or any(f.get("current_value_inr") is None for f in self.regular_funds):
            return None
        return sum(f["current_value_inr"] for f in self.regular_funds)

    @property
    def details(self) -> List[Dict[str, Any]]:
        return self.regular_funds


class OverlapPair(BaseModel):
    fund_a: str
    fund_b: str
    overlap_pct: float
    shared_stocks: List[str]
    verdict: str  # "HIGH_DUPLICATION" | "MODERATE" | "ACCEPTABLE"
    # Legacy top-holdings set overlap is a count proxy, never verified weighted
    # constituent overlap. The evidence basis is explicit in serialized output.
    evidence_basis: str = "TOP_HOLDINGS_COUNT_PROXY"
    verification_status: str = "HEURISTIC"


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
    look_through_debt_inr: Optional[float] = None
    look_through_cash_inr: Optional[float] = None
    look_through_stability_buffer_pct: Optional[float] = None


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

    @property
    def bank_cash_inr(self) -> float:
        return self.total_cash_inr

    @property
    def emergency_buffer_inr(self) -> float:
        return self.emergency_reserve_inr



class ThematicExposureItem(BaseModel):
    theme_name: str
    dedicated_funds_inr: Optional[float] = None
    dedicated_funds_pct: Optional[float] = None
    look_through_stocks_inr: Optional[float] = None
    look_through_stocks_pct: Optional[float] = None
    coverage_status: str = "MISSING"  # unavailable until source coverage is established
    key_underlying_holdings: List[str] = Field(default_factory=list)


class LookThroughStabilityBuffer(BaseModel):
    embedded_debt_inr: Optional[float] = None
    embedded_debt_pct: Optional[float] = None
    embedded_cash_inr: Optional[float] = None
    embedded_cash_pct: Optional[float] = None
    bank_deployable_cash_inr: Optional[float] = None
    emergency_reserve_inr: Optional[float] = None
    total_stability_buffer_inr: Optional[float] = None
    total_stability_buffer_pct: Optional[float] = None
    meets_tier_target: Optional[bool] = None


class DeterministicSIPRecommendation(BaseModel):
    category_role: str        # e.g., 'Core Flexi-Cap', 'Mid-Cap Alpha'
    scheme_name: str          # Must be Direct Plan
    isin: Optional[str] = None
    folio_target: Optional[str] = None
    is_direct: Optional[bool] = None
    monthly_inr: float
    allocation_pct: float
    rational_code: str        # 'CORE_COMPOUNDER', 'ALPHA_ENGINE', 'SATELLITE_THEME'
    fiduciary_rationale: str


class DeterministicSIPPlan(BaseModel):
    @model_validator(mode="after")
    def validate_mandate_authorization(self):
        _validate_mandate_flags(self.mandate_state, self.is_execution_authorized, self.is_actionable_order)
        return self

    @model_validator(mode="after")
    def validate_budget_and_allocation_reconciliation(self):
        import math

        amounts = (
            self.total_monthly_budget_inr,
            self.unallocated_budget_inr,
            self.equity_sip_pct,
            self.debt_sip_pct,
        )
        item_amounts = [item.monthly_inr for item in self.items]
        item_pcts = [item.allocation_pct for item in self.items]
        if any(not math.isfinite(value) for value in (*amounts, *item_amounts, *item_pcts)):
            raise ValueError("SIP plan amounts and percentages must be finite")
        if self.total_monthly_budget_inr < 0 or self.unallocated_budget_inr < 0:
            raise ValueError("SIP budget and unallocated amount cannot be negative")
        if any(value < 0 for value in (*item_amounts, *item_pcts)):
            raise ValueError("SIP item amounts and percentages cannot be negative")
        if any(not 0.0 <= value <= 100.0 for value in (self.equity_sip_pct, self.debt_sip_pct, *item_pcts)):
            raise ValueError("SIP allocation percentages must be between 0 and 100")
        allocated = sum(item_amounts)
        if abs((allocated + self.unallocated_budget_inr) - self.total_monthly_budget_inr) > 0.01:
            raise ValueError("Allocated SIP amounts plus unallocated budget must equal the monthly budget")
        if abs(sum(item_pcts) - (self.equity_sip_pct + self.debt_sip_pct)) > 0.11:
            raise ValueError("SIP item percentages must reconcile to the equity and debt SIP percentages")
        return self

    total_monthly_budget_inr: float
    unallocated_budget_inr: float
    equity_sip_pct: float
    debt_sip_pct: float
    items: List[DeterministicSIPRecommendation] = Field(default_factory=list)
    mandate_state: MandateExecutionState = MandateExecutionState.HOLD_PENDING_TRI_VALIDATION
    is_execution_authorized: bool = False
    is_actionable_order: bool = False
    execution_status: str = "ON_HOLD_PENDING_TRI_VALIDATION"
    enforcement_notice: str = (
        "MANDATE ENFORCEMENT: Live SIP fresh-money deployment is strictly ON HOLD pending "
        "benchmark TRI and constituent look-through validation. Orders are non-actionable conditional scenarios."
    )


class LumpsumTrancheItem(BaseModel):
    role: str
    scheme_name: str
    folio_target: Optional[str] = None
    amount_inr: float
    monthly_inr: Optional[float] = None
    allocation_pct: float
    timing: str
    source_vehicle: str
    fiduciary_rationale: str


class DeterministicLumpsumPlan(BaseModel):
    @model_validator(mode="after")
    def validate_mandate_authorization(self):
        _validate_mandate_flags(self.mandate_state, self.is_execution_authorized, self.is_actionable_order)
        return self

    total_lumpsum_inr: float
    unallocated_amount_inr: float
    is_big_ticket: bool
    stp_duration_months: int
    immediate_amount_inr: float
    stp_total_amount_inr: float
    monthly_stp_total_inr: float
    parking_vehicle: str
    tax_savings_vs_debt_fund_inr: Optional[float] = None
    cash_validation_passed: Optional[bool] = None
    cash_validation_message: str = ""
    tranches: List[LumpsumTrancheItem] = Field(default_factory=list)
    mandate_state: MandateExecutionState = MandateExecutionState.HOLD_PENDING_TRI_VALIDATION
    is_execution_authorized: bool = False
    is_actionable_order: bool = False
    execution_status: str = "ON_HOLD_PENDING_TRI_VALIDATION"
    enforcement_notice: str = (
        "MANDATE ENFORCEMENT: Lumpsum parking deployment is strictly ON HOLD pending "
        "April 2027 review. Orders are non-actionable conditional scenarios."
    )


class FiduciaryFactsPayload(BaseModel):
    @model_validator(mode="after")
    def validate_mandate_authorization(self):
        _validate_mandate_flags(self.mandate_state, self.is_execution_authorized)
        return self

    client_name: str
    client_age: Optional[int] = None
    horizon_years: Optional[int] = None
    risk_tier_name: Optional[str] = None
    total_portfolio_value_inr: float
    total_invested_value_inr: float
    total_unrealized_gain_inr: float
    holdings_count: int
    fee_bleed: FeeBleedAnalysis
    overlap_matrix: List[OverlapPair]
    weighted_overlap: List[WeightedOverlapResult] = Field(default_factory=list)
    weighted_overlap_status: str = "UNAVAILABLE"
    risk_distribution: Optional[RiskDistribution] = None
    saa_drift: SAADriftAnalysis
    cash_plan: CashDeploymentPlan
    switch_costs: List[Dict[str, Any]] = Field(default_factory=list)
    eligibility_results: List[Dict[str, Any]] = Field(default_factory=list)
    no_action: Optional[NOActionResult] = None
    monthly_sip_budget_inr: float
    lumpsum_budget_inr: float = 0.0
    lumpsum_plan: Optional[Dict[str, Any]] = None
    xirr_pct: Optional[float] = None
    benchmark_xirr_pct: Optional[float] = None
    alpha_pct: Optional[float] = None
    tax_lots_summary: Optional[TaxLedger] = None
    weak_funds_flagged: List[Dict[str, Any]] = Field(default_factory=list)
    mandate_state: MandateExecutionState = MandateExecutionState.ADVISORY_PROPOSAL
    is_execution_authorized: bool = False
    authorization_disclaimer: str = (
        "MANDATE NOTICE: This report constitutes a fiduciary wealth advisory proposal. "
        "Autonomous trade execution is strictly disabled. Execution requires formal, "
        "signed written client authorization and explicit mandate consent."
    )
    holdings: List[HoldingItem] = Field(default_factory=list)
    stability_buffer: Optional[LookThroughStabilityBuffer] = None
    thematic_exposures: List[ThematicExposureItem] = Field(default_factory=list)
    deterministic_sip_plan: Optional[DeterministicSIPPlan] = None
    deterministic_lumpsum_plan: Optional[DeterministicLumpsumPlan] = None
    cas_reconciliation: Optional[Dict[str, Any]] = None


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
    folio_name: str = "UNKNOWN"

    def is_long_term_given(self, as_of_date, lt_holding_months: int = 12) -> bool:
        """Disabled legacy tax classification; use only an approved lot-level tax engine."""
        raise RuntimeError(
            "Tax-lot maturity classification is disabled pending independently "
            "approved statutory rules and verified scheme/plan/lot evidence."
        )


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
    weighted_overlap_pct: Optional[float] = None  # Combined portfolio weight in shared stocks
    jaccard_similarity: Optional[float] = None    # Secondary measure
    shared_stocks: List[Dict[str, Any]] = Field(default_factory=list)  # {stock, weight_a, weight_b, combined_weight}
    sector_concentration: Dict[str, float] = Field(default_factory=dict)
    verdict: str  # "HIGH_CONCENTRATION", "MODERATE", "ACCEPTABLE", "UNKNOWN", "UNAVAILABLE"
    status: str = "VERIFIED"  # "VERIFIED", "UNKNOWN", "UNAVAILABLE", "LIMITED_COVERAGE"
    source: Optional[str] = None
    source_refs: List[Dict[str, str]] = Field(default_factory=list)
    effective_date: Optional[str] = None
    coverage_status: Optional[str] = None
    coverage_pct: Optional[float] = None
    reason: Optional[str] = None


class RiskDistribution(BaseModel):
    """Scheme Riskometer distribution; unknown coverage is explicit."""
    risk_tier_distribution: Dict[str, int] = Field(default_factory=dict)
    risk_tier_values: Dict[str, float] = Field(default_factory=dict)
    availability_status: str = "UNAVAILABLE"
    verified_coverage_pct: Optional[float] = None
    unknown_value_inr: Optional[float] = None
    portfolio_beta: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    downside_capture_ratio: Optional[float] = None
    volatility_annualized_pct: Optional[float] = None


class SwitchCostAnalysis(BaseModel):
    """Scheme/lot-level switch cost result; unavailable is distinct from zero cost."""
    source_fund: str
    target_fund: str
    exit_load_pct: Optional[float] = None
    exit_load_inr: Optional[float] = None
    capital_gains_tax_inr: Optional[float] = None
    stcg_tax_inr: Optional[float] = None
    ltcg_tax_inr: Optional[float] = None
    net_switch_cost_inr: Optional[float] = None
    net_switch_cost_pct: Optional[float] = None
    is_intra_amc: bool
    is_available: bool = False
    unavailable_reason: Optional[str] = None
    warning: str = (
        "NO ACTION: scheme/plan/lot-specific exit-load evidence and independently "
        "approved tax rules are required. Unavailable costs are not zero."
    )


class EligibilityGateResult(BaseModel):
    """Tri-state eligibility gates; absence of evidence must never pass."""

    fund_id: str
    fund_name: str
    passed: bool
    failed_gates: List[str] = Field(default_factory=list)
    amc_concentration_gate: Optional[bool] = None
    aum_stability_gate: Optional[bool] = None
    concentration_gate: Optional[bool] = None
    sharpe_alpha_gate: Optional[bool] = None
    liquidity_gate: Optional[bool] = None
    mandate_suitability_gate: Optional[bool] = None
    data_integrity_gate: Optional[bool] = None
    manager_tenure_gate: Optional[bool] = None
    thematic_satellite_gate: Optional[bool] = None
    direct_plan_gate: Optional[bool] = None
    details: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_gate_evidence_matches_verdict(self) -> "EligibilityGateResult":
        gate_names = (
            "amc_concentration_gate",
            "aum_stability_gate",
            "concentration_gate",
            "sharpe_alpha_gate",
            "liquidity_gate",
            "mandate_suitability_gate",
            "data_integrity_gate",
            "manager_tenure_gate",
            "thematic_satellite_gate",
            "direct_plan_gate",
        )
        gate_values = [getattr(self, name) for name in gate_names]
        if self.passed is True:
            if any(value is not True for value in gate_values):
                raise ValueError("Eligibility cannot pass while any gate is false or unevaluated")
            if self.failed_gates:
                raise ValueError("A passing eligibility result cannot contain failed gates")
        elif not self.failed_gates:
            raise ValueError("A failed or unevaluated eligibility result requires explicit failed/unknown reasons")
        return self


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

# Self-contained backward compatibility calculation functions (Zero circular imports)
def calculate_weighted_overlap(fund_a_holdings: Dict[str, float], fund_b_holdings: Dict[str, float]) -> float:
    """Self-contained pairwise weighted overlap calculation."""
    shared_stocks = set(fund_a_holdings.keys()) & set(fund_b_holdings.keys())
    overlap_weight = sum(min(fund_a_holdings[s], fund_b_holdings[s]) for s in shared_stocks)
    return round(overlap_weight, 2)

def compute_liquidity_waterfall(bank_balance: float, monthly_expenses: float, months_reserve: float = 6.0) -> Tuple[float, float]:
    """Self-contained cash deployment liquidity calculation."""
    emergency_reserve = monthly_expenses * months_reserve
    deployable_surplus = max(0.0, bank_balance - emergency_reserve)
    return round(emergency_reserve, 2), round(deployable_surplus, 2)


# ============================================================
# PERSONAL REDEMPTION ENGINE MODELS
# ============================================================

class RedemptionPriorityTier(int, Enum):
    BUBBLE_DERISKING = 1       # Priority 1: Toxic Sector Bubbles & Extreme Concentration
    FEE_BLEED_ELIMINATION = 2  # Priority 2: Regular Plans Commission Bleed
    SAA_REBALANCING = 3        # Priority 3: Duplicate / Overweight Direct Holdings
    CORE_CAPITAL_ANCHOR = 4    # Priority 4: Core Direct Compounding Anchors (Protected)


class RedemptionTrancheItem(BaseModel):
    """Execution line item for personal cash redemption."""
    fund_id: str
    scheme_name: str
    folio: str
    priority_tier: int         # 1, 2, 3, or 4
    priority_label: str        # e.g., 'Priority 1: Toxic Sector Bubble Derisking'
    fiduciary_reason: str
    gross_amount_inr: float
    units_to_redeem: float
    nav: float
    exit_load_inr: Optional[float] = None
    realized_capital_gain_inr: Optional[float] = None
    is_long_term: Optional[bool] = None
    projected_stcg_tax_inr: Optional[float] = None
    projected_ltcg_tax_inr: Optional[float] = None
    tax_sheltered_under_112a_inr: Optional[float] = None
    net_tax_liability_inr: Optional[float] = None
    net_cash_realized_inr: Optional[float] = None
    annual_commission_saved_inr: Optional[float] = None
    is_full_redemption: bool = False
    action_step: str


class PersonalRedemptionPlan(BaseModel):
    """Complete mathematically grounded Personal Cash Redemption Plan."""
    requested_amount_inr: float
    ticket_category: str       # "SMALL_TICKET" (<= 1L) | "MEDIUM_TICKET" (1L-5L) | "LARGE_TICKET" (> 5L)
    ticket_rationale: str
    is_net_cash_target: bool
    total_gross_redeemed_inr: float
    total_exit_load_inr: Optional[float] = None
    total_realized_gain_loss_inr: Optional[float] = None
    total_stcg_tax_inr: Optional[float] = None
    total_ltcg_tax_inr: Optional[float] = None
    total_tax_sheltered_under_112a_inr: Optional[float] = None
    total_net_tax_inr: Optional[float] = None
    total_net_cash_inr: Optional[float] = None
    total_annual_commission_saved_inr: Optional[float] = None
    funds_liquidated_count: int
    full_folio_exits_count: int
    tranches: List[RedemptionTrancheItem] = Field(default_factory=list)
    execution_steps: List[str] = Field(default_factory=list)
    fiduciary_safeguards: List[str] = Field(default_factory=list)


class MandateHoldViolationError(RuntimeError):
    """Raised when an attempt is made to execute transactions or generate actionable orders under an active HOLD mandate."""
    pass


class InsufficientDataError(RuntimeError):
    """Raised when required financial data is missing and the engine must fail safe per Zero Hardcoding & Zero Fabrication Mandate.
    
    In fiduciary financial engineering: Explicit Safe Failure >> Fabricated / Hardcoded Fallbacks
    """
    def __init__(self, message: str, missing_data: str = "", required_source: str = ""):
        self.missing_data = missing_data
        self.required_source = required_source
        super().__init__(message)


class TriProvenanceError(RuntimeError):
    """Raised when benchmark TRI series provenance validation fails (checksum, coverage, missing-date policy)."""
    def __init__(self, message: str, benchmark: str = "", validation_stage: str = ""):
        self.benchmark = benchmark
        self.validation_stage = validation_stage
        super().__init__(message)
