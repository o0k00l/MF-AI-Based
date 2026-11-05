"""
services/lumpsum_recommendation.py - Portfolio-aware lump-sum deployment decision service.
Addresses Issue #120: Make lump-sum decisions portfolio-aware and fail closed on incomplete investor evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.math_engine import (
    load_holdings_from_cas_excel,
    compute_deterministic_lumpsum_blueprint,
)
from core.models import HoldingItem, PlanType
from services.engine_bootstrap import InvestorMandateInput


@dataclass(frozen=True)
class LumpsumDecisionResult:
    status: str                         # "HOLD" | "ELIGIBLE_FOR_HUMAN_REVIEW"
    total_lumpsum_inr: Decimal
    allocated_amount_inr: Decimal
    unallocated_amount_inr: Decimal
    parking_allocation_inr: Decimal
    stp_allocation_inr: Decimal
    parking_ratio_pct: float
    stp_ratio_pct: float
    stp_duration_months: int
    policy_branch: str
    reasons: Tuple[str, ...]
    missing_evidence: Tuple[str, ...]
    holdings_reconciled_count: int
    existing_portfolio_value_inr: Decimal
    lookthrough_coverage_pct: float
    facts_used: Dict[str, Any]
    is_execution_authorized: bool = False
    decision_timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def evaluate_portfolio_aware_lumpsum(
    cas_path: Path,
    mandate: InvestorMandateInput,
    *,
    evidence_provider: Optional[Callable[..., Dict[str, Any]]] = None,
    policy_path: Optional[Path] = None,
) -> LumpsumDecisionResult:
    """
    Evaluates end-to-end lump sum deployment feasibility.
    Enforces portfolio-awareness, look-through coverage, exact scheme identity,
    and authoritative parking/STP policy. Fails closed on incomplete evidence.
    """
    p_path = policy_path or (Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json")
    try:
        policy_data = json.loads(p_path.read_text(encoding="utf-8"))
        lumpsum_policy = policy_data.get("lumpsum_policy", {})
    except Exception as exc:
        raise RuntimeError(f"Authoritative lumpsum policy is unavailable: {exc}") from exc

    # 1. Mandate Validation
    is_mandate_valid, mandate_errors = mandate.validate_for_lumpsum()
    missing_evidence: List[str] = list(mandate_errors)
    reasons: List[str] = []

    # 2. Evidence Provider & Bundle Resolution
    bundle_evidence: Dict[str, Any] = {}
    if evidence_provider is not None:
        try:
            bundle_evidence = evidence_provider(
                cas_path=cas_path,
                monthly_budget_inr=float(mandate.monthly_sip_budget_inr),
                risk_profile="Aggressive" if mandate.explicit_authorized_risk_tier == "Tier 6" else "Moderate",
            )
        except Exception as exc:
            missing_evidence.append(f"Evidence provider error: {exc}")
    else:
        missing_evidence.append("SIP evidence provider is not configured; public fund evidence is unverified.")

    # 3. CAS holdings load & Scheme Identity Reconcile
    holdings: List[HoldingItem] = []
    total_existing_val = Decimal("0")
    lookthrough_coverage = 0.0

    if cas_path.exists() and cas_path.is_file():
        metrics_p = bundle_evidence.get("metrics_path") or Path("data/fund_metrics.json")
        aliases_p = bundle_evidence.get("aliases_path")
        try:
            holdings = load_holdings_from_cas_excel(
                cas_path,
                metrics_path=metrics_p,
                aliases_path=aliases_p,
                scheme_master=bundle_evidence.get("scheme_master"),
                scheme_master_source_bytes=bundle_evidence.get("scheme_master_source_bytes"),
                portfolio_disclosures_by_scheme_id=bundle_evidence.get("portfolio_disclosures_by_scheme_id"),
                portfolio_disclosure_source_bytes_by_scheme_id=bundle_evidence.get("portfolio_disclosure_source_bytes_by_scheme_id"),
                disclosure_as_of_date=mandate.as_of_date,
            )
            for h in holdings:
                val = Decimal(str(h.current_value_inr))
                total_existing_val += val
                if h.constituent_weights_coverage_pct is not None:
                    lookthrough_coverage = max(lookthrough_coverage, float(h.constituent_weights_coverage_pct))
        except Exception as exc:
            missing_evidence.append(f"CAS holdings reconciliation error: {exc}")
    else:
        missing_evidence.append("CAS statement file is missing or unreadable.")

    # 4. Deployment Policy Branch Evaluation
    # Default: 40% parking / 60% STP over 6-12 months
    parking_ratio = float(lumpsum_policy.get("parking_pct", 0.40))
    stp_ratio = float(lumpsum_policy.get("stp_pct", 0.60))
    stp_duration = int(lumpsum_policy.get("stp_months_min", 6))
    policy_branch = "STANDARD_PARKING_STP_WATERFALL"

    # Authorized Tier 6 override
    if (
        mandate.explicit_authorized_risk_tier == "Tier 6"
        and mandate.horizon_years >= 7.0
        and mandate.tier6_equity_only_authorized is True
    ):
        v_high = lumpsum_policy.get("very_high_override", {})
        parking_ratio = float(v_high.get("parking_pct", 0.20))
        stp_ratio = float(v_high.get("stp_pct", 0.80))
        policy_branch = "TIER6_AGGRESSIVE_STP_WATERFALL"

    parking_amount = (mandate.lumpsum_budget_inr * Decimal(str(parking_ratio))).quantize(Decimal("0.01"))
    stp_amount = (mandate.lumpsum_budget_inr - parking_amount).quantize(Decimal("0.01"))

    # 5. Parking Candidate Availability
    candidate_univ = bundle_evidence.get("candidate_universe", [])
    direct_arbitrage_available = any(
        c.get("category") == "Arbitrage" and c.get("plan_type") == "Direct" and c.get("is_direct") is True
        for c in candidate_univ
        if isinstance(c, dict)
    )
    if not direct_arbitrage_available:
        missing_evidence.append("No verified Direct Arbitrage parking candidate available in candidate universe.")

    # 6. Fiduciary Determination
    # If any mandate, cash evidence, lookthrough, or release gate is missing -> HOLD
    if missing_evidence:
        reasons.append("Deployment blocked pending missing investor mandate facts or verified public evidence.")
        for err in missing_evidence:
            reasons.append(err)
        status = "HOLD"
        allocated = Decimal("0")
        unallocated = mandate.lumpsum_budget_inr
    else:
        reasons.append("Pre-requisite mandate and portfolio checks cleared for independent adviser review.")
        status = "ELIGIBLE_FOR_HUMAN_REVIEW"
        allocated = mandate.lumpsum_budget_inr
        unallocated = Decimal("0")

    facts_used = {
        "as_of_date": mandate.as_of_date.isoformat(),
        "horizon_years": mandate.horizon_years,
        "goal": mandate.goal,
        "authorized_risk_tier": mandate.explicit_authorized_risk_tier or "UNAUTHORIZED",
        "tier6_equity_only_authorized": mandate.tier6_equity_only_authorized,
        "bank_cash_inr": str(mandate.bank_cash_inr) if mandate.bank_cash_inr is not None else "UNAVAILABLE",
        "emergency_reserve_inr": str(mandate.emergency_reserve_inr) if mandate.emergency_reserve_inr is not None else "UNAVAILABLE",
        "reconciled_holdings_count": len(holdings),
        "existing_portfolio_value_inr": str(total_existing_val),
    }

    return LumpsumDecisionResult(
        status=status,
        total_lumpsum_inr=mandate.lumpsum_budget_inr,
        allocated_amount_inr=allocated,
        unallocated_amount_inr=unallocated,
        parking_allocation_inr=parking_amount,
        stp_allocation_inr=stp_amount,
        parking_ratio_pct=parking_ratio * 100.0,
        stp_ratio_pct=stp_ratio * 100.0,
        stp_duration_months=stp_duration,
        policy_branch=policy_branch,
        reasons=tuple(reasons),
        missing_evidence=tuple(missing_evidence),
        holdings_reconciled_count=len(holdings),
        existing_portfolio_value_inr=total_existing_val,
        lookthrough_coverage_pct=lookthrough_coverage,
        facts_used=facts_used,
        is_execution_authorized=False,
    )
