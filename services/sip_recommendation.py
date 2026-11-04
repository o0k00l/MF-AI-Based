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
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from core.math_engine import (
    compute_deterministic_sip_blueprint,
    load_holdings_from_cas_excel,
)
from core.models import DeterministicSIPPlan, MandateExecutionState
from core.portfolio_sip_controls import (
    PortfolioInputError,
    build_decision_trace,
    calculate_lookthrough_exposure,
    calculate_saa_drift,
    reconcile_total_portfolio,
    route_incremental_sip,
    screen_candidates_before_scoring,
    validate_goal_mandate,
    assess_liquidity_and_sip_surplus,
    stress_test_sip_affordability,
    validate_scheme_operational_feasibility,
    evaluate_recommendation_freshness,
)


_ALLOWED_RISK_PROFILES = {
    "Conservative": "Conservative",
    "Moderate": "Moderate",
    "Aggressive": "Aggressive",
}



_SAA_POLICY_PROFILE_BY_RISK = {
    "Conservative": "low_to_moderate",
    "Moderate": "moderately_high",
    "Aggressive": "very_high",
}
_ASSET_CLASS_TO_SAA_BUCKET = {
    "LARGE_CAP": "large_cap", "MID_CAP": "mid_cap",
    "SMALL_CAP": "small_cap", "FLEXI_CAP": "flexi_multi_cap",
    "MULTI_CAP": "flexi_multi_cap", "DEBT_LIQUID": "debt_liquid",
}


def _build_cas_portfolio_assessment(holdings: list[Any], risk_profile: str) -> dict[str, Any]:
    """Return a CAS-only SAA diagnostic; never imply total-portfolio completeness."""
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        profile_key = _SAA_POLICY_PROFILE_BY_RISK[risk_profile]
        profile = policy["behavioral_risk_profiles"][profile_key]
        raw_targets = profile["saa_targets"]
        tolerance = profile["tolerance_band_pct"]
        policy_bucket_map = {
            "large_cap_pct": "large_cap",
            "mid_cap_pct": "mid_cap",
            "small_cap_pct": "small_cap",
            "flexi_multi_cap_pct": "flexi_multi_cap",
            "debt_liquid_pct": "debt_liquid",
        }
        if set(raw_targets) != set(policy_bucket_map):
            raise ValueError("SAA policy buckets do not match service contract")
        targets = {bucket: raw_targets[source] for source, bucket in policy_bucket_map.items()}
        targets["unclassified"] = 0
        current = {key: 0.0 for key in targets}
        total = 0.0
        for holding in holdings:
            value = float(holding.current_value_inr)
            if not math.isfinite(value) or value <= 0:
                raise ValueError("holding valuation is invalid")
            asset_class = getattr(holding, "asset_class", None)
            asset_class = getattr(asset_class, "value", asset_class)
            normalized_class = str(asset_class).upper().replace("-", "_").replace(" ", "_")
            bucket = _ASSET_CLASS_TO_SAA_BUCKET.get(normalized_class, "unclassified")
            current[bucket] += value
            total += value
        if not math.isfinite(total) or total <= 0:
            raise ValueError("CAS holdings total is invalid")
        drift = calculate_saa_drift(
            current, targets, tolerance_band_pct=tolerance, portfolio_total_inr=total
        )
        equity_rows = []
        for holding in holdings:
            holding_value = float(holding.current_value_inr)
            equity_pct = float(getattr(holding, "equity_pct", 0.0))
            if not math.isfinite(equity_pct) or not 0.0 <= equity_pct <= 100.0:
                raise ValueError("holding equity exposure is invalid")
            equity_value = holding_value * equity_pct / 100.0
            if equity_value <= 0:
                continue
            constituents = getattr(holding, "constituent_weights", None)
            if not isinstance(constituents, dict) or not constituents:
                raise ValueError("verified equity holding has no constituent weights")
            equity_rows.append({
                "holding_value_inr": equity_value,
                "coverage_pct": holding.constituent_weights_coverage_pct,
                "constituents": constituents,
            })
        if equity_rows:
            lookthrough = calculate_lookthrough_exposure(
                equity_rows, required_coverage_pct="99.5"
            )
        else:
            lookthrough = {
                "status": "HOLD",
                "reason": "NO_VERIFIED_EQUITY_EXPOSURE_AVAILABLE",
                "issuer_exposure_inr": None,
            }
        return {
            "status": "DIAGNOSTIC_ONLY",
            "scope": "CAS_MUTUAL_FUND_HOLDINGS_ONLY",
            "portfolio_perimeter_complete": False,
            "valuation_date_verified": False,
            "total_value_inr": round(total, 2),
            "holding_count": len(holdings),
            "current_sleeve_values_inr": {
                key: round(value, 2) for key, value in sorted(current.items())
            },
            "target_sleeve_weights_pct": {
                key: value for key, value in sorted(targets.items())
            },
            "policy_profile": profile_key,
            "policy_as_of": policy.get("as_of"),
            "tolerance_band_pct": tolerance,
            "saa_drift": drift,
            "lookthrough": lookthrough,
            "sip_routing": {
                "status": "HOLD",
                "reason": "TOTAL_PORTFOLIO_PERIMETER_AND_EXTERNAL_ASSETS_NOT_RECONCILED",
                "allocated_budget_inr": 0.0,
                "unallocated_budget_pct": 100.0,
            },
        }
    except (OSError, ValueError, TypeError, KeyError, PortfolioInputError) as exc:
        return {
            "status": "HOLD",
            "scope": "CAS_MUTUAL_FUND_HOLDINGS_ONLY",
            "portfolio_perimeter_complete": False,
            "reason": f"CAS portfolio assessment unavailable ({type(exc).__name__}).",
        }




_TOTAL_PORTFOLIO_SLEEVES = (
    "large_cap", "mid_cap", "small_cap", "flexi_multi_cap", "debt_liquid"
)


def _assess_complete_portfolio_context(
    context: dict[str, Any],
    *,
    candidate_universe: list[dict[str, Any]],
    monthly_budget_inr: float,
    risk_profile: str,
    existing_lookthrough: dict[str, Any],
    cas_holdings_total_inr: float,
) -> dict[str, Any]:
    """Orchestrate portfolio, suitability, affordability and candidate gates.

    This returns diagnostics and a routing simulation only. It never authorizes
    an allocation; the independent research/TRI release gate remains separate.
    """
    try:
        as_of = context["as_of_date"]
        assets = context["assets"]
        if not isinstance(assets, list) or not assets:
            raise PortfolioInputError("complete portfolio asset rows are required")
        for row in assets:
            if not isinstance(row, dict) or row.get("saa_bucket") not in _TOTAL_PORTFOLIO_SLEEVES:
                raise PortfolioInputError("every asset requires an explicit approved SAA sleeve mapping")
        reconciliation = reconcile_total_portfolio(
            assets,
            perimeter_complete=context.get("perimeter_complete") is True,
            as_of_date=as_of,
            excluded_assets=context.get("excluded_assets", []),
        )
        if reconciliation["status"] != "RECONCILED":
            return {"status": "HOLD", "portfolio_reconciliation": reconciliation,
                    "reason": reconciliation.get("reason", "TOTAL_PORTFOLIO_RECONCILIATION_FAILED")}
        total = float(reconciliation["total_value_inr"])
        current = {sleeve: 0.0 for sleeve in _TOTAL_PORTFOLIO_SLEEVES}
        for row in assets:
            current[row["saa_bucket"]] += float(row["value_inr"])
        if abs(sum(current.values()) - total) > 0.01:
            raise PortfolioInputError("SAA sleeve values do not reconcile to total portfolio")
        policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        profile_key = _SAA_POLICY_PROFILE_BY_RISK[risk_profile]
        profile = policy["behavioral_risk_profiles"][profile_key]
        ips = context["ips"]
        ips_date = date.fromisoformat(ips["effective_date"])
        valuation_date = date.fromisoformat(as_of)
        if (
            ips.get("approved") is not True
            or not isinstance(ips.get("source_ref"), str) or not ips["source_ref"].strip()
            or ips_date > valuation_date
        ):
            raise PortfolioInputError("approved, dated client IPS evidence is required")
        if risk_profile == "Aggressive" and profile_key == "very_high" and ips.get("tier6_equity_only_authorized") is not True:
            raise PortfolioInputError("Tier 6 equity-only routing requires explicit IPS authorization")
        targets = ips["target_weights_pct"]
        if not isinstance(targets, dict) or set(targets) != set(_TOTAL_PORTFOLIO_SLEEVES):
            raise PortfolioInputError("client IPS must specify all five SAA sleeves")
        tolerance = ips["tolerance_band_pct"]
        cas_value_in_perimeter = sum(
            float(row["value_inr"]) for row in assets if row.get("asset_class") == "cas_mutual_fund"
        )
        if abs(cas_value_in_perimeter - cas_holdings_total_inr) > 0.01:
            raise PortfolioInputError("CAS holdings do not reconcile to declared CAS asset perimeter")
        drift = calculate_saa_drift(
            current, targets, tolerance_band_pct=tolerance,
            portfolio_total_inr=total,
        )

        goal_policy = context["goal_policy"]
        goals = validate_goal_mandate(
            context.get("goals", []), as_of_date=as_of,
            max_evidence_age_days=int(goal_policy["max_evidence_age_days"]),
            minimum_horizon_days_by_asset_class=goal_policy["minimum_horizon_days_by_asset_class"],
        )
        liquidity_input = context["liquidity"]
        liquidity = assess_liquidity_and_sip_surplus(
            verified_cash_inr=liquidity_input["verified_cash_inr"],
            approved_reserve_target_inr=liquidity_input["approved_reserve_target_inr"],
            near_term_obligations_inr=liquidity_input["near_term_obligations_inr"],
            monthly_net_income_inr=liquidity_input["monthly_net_income_inr"],
            essential_monthly_expenses_inr=liquidity_input["essential_monthly_expenses_inr"],
            monthly_debt_service_inr=liquidity_input["monthly_debt_service_inr"],
            proposed_monthly_sip_inr=monthly_budget_inr,
            evidence_refs=liquidity_input["evidence_refs"],
            as_of_date=as_of,
            max_evidence_age_days=int(liquidity_input["max_evidence_age_days"]),
        )
        stress = stress_test_sip_affordability(
            monthly_net_income_inr=liquidity_input["monthly_net_income_inr"],
            essential_monthly_expenses_inr=liquidity_input["essential_monthly_expenses_inr"],
            monthly_debt_service_inr=liquidity_input["monthly_debt_service_inr"],
            proposed_monthly_sip_inr=monthly_budget_inr,
            scenarios=context.get("stress_scenarios", []),
        )

        candidate_policy = context["candidate_policy"]
        gate_results = context["candidate_gate_results"]
        operational_evidence = context["operational_evidence_by_candidate_id"]
        prepared_candidates = []
        operational_results = {}
        for candidate in candidate_universe:
            candidate_id = str(candidate.get("fund_id") or candidate.get("scheme_id") or "")
            direct = candidate.get("direct_plan_evidence") or {}
            identity = {
                "scheme_id": candidate.get("scheme_id") or direct.get("scheme_id"),
                "isin": candidate.get("isin") or direct.get("isin"),
                "plan": direct.get("plan"),
                "option": direct.get("option"),
                "amc": candidate.get("amc_name") or direct.get("amc_name"),
                "category": candidate.get("category"),
                "benchmark": candidate.get("benchmark") or direct.get("benchmark"),
            }
            prepared_candidates.append({
                "candidate_id": candidate_id,
                "scheme_identity": identity,
                "evidence_as_of_date": direct.get("reviewed_at") or direct.get("effective_date"),
                "evidence_ref": direct.get("source_document_sha256"),
                "gates": gate_results.get(candidate_id, {}),
            })
            operational = operational_evidence.get(candidate_id)
            if isinstance(operational, dict):
                operational_results[candidate_id] = validate_scheme_operational_feasibility(
                    operational, requested_monthly_sip_inr=monthly_budget_inr,
                    as_of_date=as_of,
                    max_evidence_age_days=int(candidate_policy["max_evidence_age_days"]),
                )
            else:
                operational_results[candidate_id] = {
                    "status": "HOLD", "execution_authorized": False,
                    "reasons": ["OPERATIONAL_EVIDENCE_MISSING"],
                }
        screening = screen_candidates_before_scoring(
            prepared_candidates, as_of_date=as_of,
            max_evidence_age_days=int(candidate_policy["max_evidence_age_days"]),
            mandatory_gates=candidate_policy["mandatory_gates"],
        )
        eligible_ids = set(screening["eligible_candidate_ids"])
        eligible_ids = {
            candidate_id for candidate_id in eligible_ids
            if operational_results.get(candidate_id, {}).get("status") == "FEASIBLE_FOR_REVIEW"
        }
        eligible_sleeves = sorted({
            candidate_policy.get("candidate_sleeves", {}).get(candidate_id)
            for candidate_id in eligible_ids
            if candidate_policy.get("candidate_sleeves", {}).get(candidate_id) in _TOTAL_PORTFOLIO_SLEEVES
        })
        routing = route_incremental_sip(
            monthly_budget_inr, current, targets, portfolio_total_inr=total,
            tolerance_band_pct=tolerance,
            eligible_sleeves=eligible_sleeves,
            rounding_increment_inr=candidate_policy.get("rounding_increment_inr", "500"),
        )
        # Candidate incremental exposure is compared with existing CAS look-through.
        # Concentration is measured against the reconciled total portfolio.
        concentration_policy = context.get("concentration_policy", {})
        max_issuer_pct = float(concentration_policy.get("max_issuer_pct_of_portfolio", 0))
        concentration_date = date.fromisoformat(concentration_policy.get("effective_date", ""))
        if (
            not 0 < max_issuer_pct <= 100
            or not isinstance(concentration_policy.get("source_ref"), str)
            or not concentration_policy["source_ref"].strip()
            or concentration_date > valuation_date
        ):
            raise PortfolioInputError("approved, dated issuer concentration policy is required")
        existing_issuer_values = {}
        if existing_lookthrough.get("status") == "CALCULATED":
            existing_issuer_values = {
                key: float(value)
                for key, value in existing_lookthrough.get("issuer_exposure_inr", {}).items()
            }
        elif existing_lookthrough.get("status") != "HOLD":
            raise PortfolioInputError("existing portfolio look-through state is invalid")
        overlap_results = {}
        for candidate in candidate_universe:
            candidate_id = str(candidate.get("fund_id") or candidate.get("scheme_id") or "")
            if candidate_id not in eligible_ids:
                overlap_results[candidate_id] = {"status": "HOLD", "reason": "CANDIDATE_NOT_ELIGIBLE_FOR_REVIEW"}
                continue
            constituents = candidate.get("constituent_weights")
            coverage = candidate.get("constituent_weights_coverage_pct")
            if not isinstance(constituents, dict) or coverage is None:
                overlap_results[candidate_id] = {"status": "HOLD", "reason": "CANDIDATE_LOOKTHROUGH_MISSING"}
                continue
            candidate_exposure = calculate_lookthrough_exposure(
                [{"holding_value_inr": str(monthly_budget_inr),
                  "coverage_pct": coverage, "constituents": constituents}],
                required_coverage_pct="99.5",
            )
            if candidate_exposure.get("status") != "CALCULATED":
                overlap_results[candidate_id] = candidate_exposure
                continue
            issuers = candidate_exposure["issuer_exposure_inr"]
            combined_values = {
                issuer: existing_issuer_values.get(issuer, 0.0) + float(value)
                for issuer, value in issuers.items()
            }
            for issuer, value in existing_issuer_values.items():
                combined_values.setdefault(issuer, value)
            concentrations = {
                issuer: value / total * 100 for issuer, value in combined_values.items()
            }
            breaches = sorted(
                issuer for issuer, pct in concentrations.items()
                if pct > max_issuer_pct
            )
            overlap_results[candidate_id] = {
                "status": "HOLD" if breaches else "ASSESSED",
                "ticket_basis_inr": monthly_budget_inr,
                "shared_issuers": sorted(set(issuers) & set(existing_issuer_values)),
                "candidate_issuer_exposure_inr": issuers,
                "combined_issuer_concentration_pct": concentrations,
                "max_issuer_pct_of_portfolio": max_issuer_pct,
                "breaching_issuers": breaches,
                "reason": "Candidate one-instalment issuer impact against existing holdings.",
            }
        freshness_input = context["freshness"]
        freshness = evaluate_recommendation_freshness(
            recommendation_as_of_date=freshness_input["recommendation_as_of_date"],
            current_as_of_date=as_of,
            max_age_days=int(freshness_input["max_age_days"]),
            event_flags=freshness_input.get("event_flags", {}),
        )
        client_supplied_unverified = context.get("_client_supplied_unverified") is True
        provider_attested = context.get("evidence_attested_by_provider") is True
        all_gates_pass = (
            provider_attested
            and not client_supplied_unverified
            and goals["status"] == "VALIDATED"
            and liquidity["status"] == "AFFORDABLE"
            and stress["all_scenarios_sustainable"]
            and screening["scoring_permitted"]
            and bool(eligible_ids)
            and freshness["status"] == "CURRENT"
            and routing["status"] in {"ROUTED", "HOLD"}
            and all(overlap_results.get(candidate_id, {}).get("status") == "ASSESSED"
                    for candidate_id in eligible_ids)
        )
        return {
            "status": "ASSESSMENT_COMPLETE" if all_gates_pass else "HOLD",
            "scope": "DECLARED_TOTAL_PORTFOLIO",
            "trust_level": "UNVERIFIED_CLIENT_DECLARATIONS" if client_supplied_unverified else ("PROVIDER_ATTESTED" if provider_attested else "UNVERIFIED_CONTEXT"),
            "portfolio_reconciliation": reconciliation,
            "saa": {"current_sleeve_values_inr": current, "target_weights_pct": targets,
                    "drift": drift, "policy_as_of": policy.get("as_of")},
            "goal_suitability": goals,
            "liquidity_and_affordability": liquidity,
            "affordability_stress": stress,
            "candidate_screening": screening,
            "scheme_operational_feasibility": operational_results,
            "candidate_overlap_diagnostics": overlap_results,
            "incremental_sip_routing_simulation": routing,
            "freshness": freshness,
            "all_input_gates_pass": all_gates_pass,
            "recommendation_authorized": False,
            "execution_authorized": False,
            "important_limit": "Only a provider-attested context bundle can pass provenance gating. Research/TRI release, approved client IPS and independent review remain separate release gates.",
        }
    except (KeyError, TypeError, ValueError, OSError) as exc:
        return {
            "status": "HOLD",
            "scope": "DECLARED_TOTAL_PORTFOLIO",
            "reason": f"PORTFOLIO_CONTEXT_INVALID_OR_INCOMPLETE:{type(exc).__name__}",
            "recommendation_authorized": False,
            "execution_authorized": False,
        }


def _build_sip_decision_trace(
    *,
    cas_path: Path,
    scheme_master_source_bytes: bytes,
    portfolio_disclosure_source_bytes_by_scheme_id: dict[str, bytes],
    disclosure_as_of_date: date,
    candidate_universe: list[dict[str, Any]],
    monthly_budget_inr: float,
    portfolio_assessment: dict[str, Any],
    context_assessment: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Hash the source and diagnostic inputs that led to a fail-closed SIP result."""
    candidate_source_hashes = {}
    for candidate in candidate_universe:
        evidence = candidate.get("direct_plan_evidence", {})
        candidate_source_hashes[candidate.get("fund_id", candidate.get("id", "UNKNOWN"))] = (
            evidence.get("source_document_sha256")
            if isinstance(evidence, dict) else None
        )
    record = {
        "schema_version": 1,
        "source_digests": {
            "cas_upload_sha256": hashlib.sha256(cas_path.read_bytes()).hexdigest(),
            "scheme_master_sha256": hashlib.sha256(scheme_master_source_bytes).hexdigest(),
            "portfolio_disclosures_sha256": {
                key: hashlib.sha256(value).hexdigest()
                for key, value in sorted(portfolio_disclosure_source_bytes_by_scheme_id.items())
            },
            "candidate_direct_plan_sources": candidate_source_hashes,
        },
        "as_of_dates": {
            "disclosure_as_of_date": disclosure_as_of_date.isoformat(),
            "policy_as_of_date": portfolio_assessment.get("policy_as_of"),
            "cas_valuation_date": "UNVERIFIED_NOT_EXTRACTED",
        },
        "policy_version": f"asset_allocation.json@{portfolio_assessment.get('policy_as_of')}",
        "engine_version": "core.math_engine.compute_deterministic_sip_blueprint",
        "eligibility": {
            "current_holding_evidence": "PASS",
            "candidate_universe_count": len(candidate_universe),
            "candidate_scoring": "SUPPRESSED_PENDING_RELEASE_APPROVAL",
        },
        "portfolio_effect": {
            "scope": portfolio_assessment.get("scope"),
            "saa_drift": portfolio_assessment.get("saa_drift"),
            "lookthrough": portfolio_assessment.get("lookthrough"),
            "total_portfolio_context": context_assessment,
        },
        "allocation": {
            "requested_budget_inr": monthly_budget_inr,
            "allocated_budget_inr": 0,
            "unallocated_budget_inr": monthly_budget_inr,
        },
        "decision": {
            "status": "HOLD",
            "decision": "NO_ACTION",
            "reason": "RESEARCH_AND_TOTAL_PORTFOLIO_RELEASE_GATES_NOT_APPROVED",
        },
    }
    return build_decision_trace(record)


def _hold_plan(monthly_budget_inr: float, reasons: list[str], portfolio_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
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
    result = {
        "status": "HOLD",
        "decision": "NO_ACTION",
        "reasons": reasons,
        "plan": plan.model_dump(mode="json"),
    }
    if portfolio_assessment is not None:
        result["portfolio_assessment"] = portfolio_assessment
    return result


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
    portfolio_context: dict[str, Any] | None = None,
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
        if getattr(holding, "metrics_status", "MISSING") != "VERIFIED":
            evidence_gaps.append(
                f"{scheme_label}: fund category/risk/exposure metrics are MISSING or unverified."
            )
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

    # This is a CAS-only diagnostic, deliberately not a total-portfolio
    # denominator. External assets, cash, liabilities and valuation date have
    # not been reconciled, so it cannot authorize SIP routing.
    portfolio_assessment = _build_cas_portfolio_assessment(holdings, risk_profile)

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
        return _hold_plan(
            budget,
            [f"SIP engine validation did not pass: {type(exc).__name__}."],
            portfolio_assessment,
        )

    context_assessment = None
    if portfolio_context is not None:
        if not isinstance(portfolio_context, dict):
            context_assessment = {
                "status": "HOLD", "reason": "PORTFOLIO_CONTEXT_MUST_BE_AN_OBJECT",
                "recommendation_authorized": False, "execution_authorized": False,
            }
        else:
            context_assessment = _assess_complete_portfolio_context(
                portfolio_context,
                candidate_universe=candidate_universe,
                monthly_budget_inr=budget,
                risk_profile=risk_profile,
                existing_lookthrough=portfolio_assessment.get("lookthrough", {}),
                cas_holdings_total_inr=sum(float(holding.current_value_inr) for holding in holdings),
            )
        portfolio_assessment["total_portfolio_context"] = context_assessment
    portfolio_assessment["recommendation_lifecycle"] = {
        "state": "DRAFT",
        "state_persisted": False,
        "execution_authorized": False,
        "note": "Lifecycle is returned as a draft snapshot; persistent review history is not yet configured.",
    }
    portfolio_assessment["decision_trace"] = _build_sip_decision_trace(
        cas_path=cas_path,
        scheme_master_source_bytes=scheme_master_source_bytes,
        portfolio_disclosure_source_bytes_by_scheme_id=portfolio_disclosure_source_bytes_by_scheme_id,
        disclosure_as_of_date=disclosure_as_of_date,
        candidate_universe=candidate_universe,
        monthly_budget_inr=budget,
        portfolio_assessment=portfolio_assessment,
        context_assessment=context_assessment,
    )
    return _hold_plan(budget, [
        "Evidence reached the deterministic SIP engine, but the independent benchmark/research release gate is not approved.",
        "Provisional engine allocations are suppressed; the full monthly budget remains unallocated.",
    ], portfolio_assessment)
