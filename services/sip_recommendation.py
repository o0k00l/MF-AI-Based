"""Portfolio-aware SIP service boundary.

This adapter is deliberately stricter than the legacy aggregator:
- exact scheme identity and complete, fresh disclosure evidence are required
  for every current holding;
- candidate data and source evidence are passed explicitly to the engine;
- the public service returns HOLD with the entire budget unallocated until the
  separate research/benchmark release gate is approved.

It does not download, infer, or manufacture source evidence.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from core.math_engine import (
    compute_deterministic_sip_blueprint,
    load_holdings_from_cas_excel,
)
from core.models import DeterministicSIPPlan, MandateExecutionState


_ALLOWED_RISK_PROFILES = {
    "Conservative": "Conservative",
    "Moderate": "Moderate",
    "Aggressive": "Aggressive",
}


def _hold_plan(monthly_budget_inr: float, reasons: list[str]) -> dict[str, Any]:
    """Create a valid, zero-allocation response; never leak a provisional split."""
    plan = DeterministicSIPPlan(
        total_monthly_budget_inr=monthly_budget_inr,
        unallocated_budget_inr=monthly_budget_inr,
        equity_sip_pct=0.0,
        debt_sip_pct=0.0,
        items=[],
        mandate_state=MandateExecutionState.HOLD_PENDING_TRI_VALIDATION,
        is_execution_authorized=False,
        is_actionable_order=False,
        execution_status="HOLD_NO_ACTION",
        enforcement_notice="NO ACTION: evidence and release gates must pass before any allocation is shown.",
    )
    return {
        "status": "HOLD",
        "decision": "NO_ACTION",
        "reasons": reasons,
        "plan": plan.model_dump(mode="json"),
    }


def recommend_sip(
    *,
    cas_path: Path,
    metrics_path: Path | None,
    aliases_path: Path | None,
    monthly_budget_inr: float,
    risk_profile: str,
    scheme_master: dict[str, Any] | None,
    scheme_master_source_bytes: bytes | None,
    portfolio_disclosures_by_scheme_id: dict[str, dict[str, Any]] | None,
    portfolio_disclosure_source_bytes_by_scheme_id: dict[str, bytes] | None,
    disclosure_as_of_date: date | None,
    candidate_universe: list[dict[str, Any]] | None,
    disclosure_max_age_days: int = 45,
    thematic_satellite_authorized: bool = False,
    thematic_satellite_pct_of_equity: float = 0.0,
) -> dict[str, Any]:
    """Build a fail-closed portfolio-aware SIP decision from explicit evidence.

    The caller must supply the original scheme-master and disclosure bytes.
    Custom SAA is intentionally rejected until its IPS contract is implemented.
    """
    import math

    try:
        budget = float(monthly_budget_inr)
    except (TypeError, ValueError) as exc:
        raise ValueError("Monthly SIP budget must be numeric") from exc
    if not math.isfinite(budget) or budget <= 0:
        raise ValueError("Monthly SIP budget must be finite and greater than zero")

    if risk_profile not in _ALLOWED_RISK_PROFILES:
        return _hold_plan(budget, [
            "Custom or unrecognized risk profile is not supported by the current SIP policy adapter."
        ])

    if not isinstance(cas_path, Path) or not cas_path.is_file():
        return _hold_plan(budget, ["A readable CAS workbook is required."])
    if not isinstance(scheme_master, dict) or not isinstance(scheme_master_source_bytes, bytes):
        return _hold_plan(budget, ["Verified scheme master and its original source bytes are required."])
    if not isinstance(portfolio_disclosures_by_scheme_id, dict) or not isinstance(
        portfolio_disclosure_source_bytes_by_scheme_id, dict
    ):
        return _hold_plan(budget, ["Exact-ID portfolio disclosures and original source bytes are required."])
    if disclosure_as_of_date is None:
        return _hold_plan(budget, ["A decision as-of date is required for disclosure freshness validation."])
    if not isinstance(candidate_universe, list) or not candidate_universe:
        return _hold_plan(budget, ["A source-verified candidate universe is required."])
    if isinstance(disclosure_max_age_days, bool) or not isinstance(disclosure_max_age_days, int) or disclosure_max_age_days < 0:
        raise ValueError("disclosure_max_age_days must be a non-negative integer")

    try:
        holdings = load_holdings_from_cas_excel(
            cas_path,
            metrics_path,
            aliases_path,
            scheme_master=scheme_master,
            scheme_master_source_bytes=scheme_master_source_bytes,
            portfolio_disclosures_by_scheme_id=portfolio_disclosures_by_scheme_id,
            portfolio_disclosure_source_bytes_by_scheme_id=portfolio_disclosure_source_bytes_by_scheme_id,
            disclosure_as_of_date=disclosure_as_of_date,
            disclosure_max_age_days=disclosure_max_age_days,
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return _hold_plan(budget, [
            f"CAS or evidence validation failed closed ({type(exc).__name__})."
        ])
    if not holdings:
        return _hold_plan(budget, ["CAS produced no active holdings; portfolio reconciliation cannot proceed."])

    evidence_gaps = []
    for holding in holdings:
        scheme_label = holding.scheme or holding.fund_id
        if not holding.scheme_id:
            evidence_gaps.append(f"{scheme_label}: exact scheme identity is missing.")
        if holding.lookthrough_status != "VERIFIED":
            evidence_gaps.append(
                f"{scheme_label}: constituent disclosure is {holding.lookthrough_status}."
            )
        try:
            coverage = float(holding.constituent_weights_coverage_pct)
            current_value = float(holding.current_value_inr)
        except (TypeError, ValueError, AttributeError):
            evidence_gaps.append(f"{scheme_label}: coverage or current valuation is missing or malformed.")
            continue
        if not math.isfinite(coverage) or not 99.5 <= coverage <= 100.0:
            evidence_gaps.append(f"{scheme_label}: constituent-weight coverage is incomplete or invalid.")
        if not math.isfinite(current_value) or current_value <= 0:
            evidence_gaps.append(f"{scheme_label}: current holding valuation is missing or invalid.")
    if evidence_gaps:
        return _hold_plan(budget, evidence_gaps)

    # Run the deterministic engine with the exact evidence bundle. Its output is
    # retained only as an internal diagnostic until independent TRI/research
    # release gates are approved; provisional positive allocations are never
    # exposed by this service boundary.
    try:
        compute_deterministic_sip_blueprint(
            monthly_budget=budget,
            risk_tier=_ALLOWED_RISK_PROFILES[risk_profile],
            holdings=holdings,
            client_aum=sum(float(h.current_value_inr) for h in holdings),
            candidate_universe=candidate_universe,
            thematic_satellite_authorized=thematic_satellite_authorized,
            thematic_satellite_pct_of_equity=thematic_satellite_pct_of_equity,
            portfolio_disclosures_by_scheme_id=portfolio_disclosures_by_scheme_id,
            portfolio_disclosure_source_bytes_by_scheme_id=portfolio_disclosure_source_bytes_by_scheme_id,
            disclosure_as_of_date=disclosure_as_of_date,
            disclosure_max_age_days=disclosure_max_age_days,
        )
    except (ValueError, TypeError, KeyError) as exc:
        return _hold_plan(budget, [f"SIP engine validation did not pass: {type(exc).__name__}."])

    return _hold_plan(budget, [
        "Evidence reached the deterministic SIP engine, but the independent benchmark/research release gate is not approved.",
        "Provisional engine allocations are suppressed; the full monthly budget remains unallocated.",
    ])
