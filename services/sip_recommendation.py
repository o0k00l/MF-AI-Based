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

from datetime import date, datetime
import hashlib
import json
import math
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any

from core.math_engine import (
    compute_deterministic_sip_blueprint,
    load_holdings_from_cas_excel,
    _parse_cas_valuation_date,
)
from core.models import DeterministicSIPPlan, MandateExecutionState, quantize_inr
from services.sip_lifecycle_store import persist_draft_snapshot

from core.portfolio_sip_controls import (
    PortfolioInputError,
    build_decision_trace,
    calculate_lookthrough_exposure,
    evaluate_classified_concentration,
    calculate_saa_drift,
    reconcile_total_portfolio,
    generate_signed_portfolio_reconciliation_report,
    route_incremental_sip,
    allocate_candidate_sip,
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



_ASSET_CLASS_TO_SAA_BUCKET = {
    "LARGE_CAP": "large_cap", "MID_CAP": "mid_cap",
    "SMALL_CAP": "small_cap", "FLEXI_CAP": "flexi_multi_cap",
    "MULTI_CAP": "flexi_multi_cap", "DEBT_LIQUID": "debt_liquid",
}


def _required_lookthrough_coverage_pct() -> Any:
    """Resolve the look-through coverage requirement from the validated screening policy."""
    from core.eligibility import load_fund_screening_policy

    policy = load_fund_screening_policy()
    return policy["portfolio_lookthrough_policy"]["required_coverage_pct"]


def _build_cas_portfolio_assessment(
    holdings: list[Any], risk_profile: str, custom_saa_target: Any | None = None
) -> dict[str, Any]:
    """Return a CAS-only SAA diagnostic; never imply total-portfolio completeness."""
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        if risk_profile == "Custom" and custom_saa_target is not None:
            profile_key = "custom"
            from core.models import AssetAllocationTarget
            if not isinstance(custom_saa_target, AssetAllocationTarget):
                raise ValueError("custom_saa_target must be an AssetAllocationTarget instance")
            custom_policy = policy["custom_saa_policy"]
            tolerance = custom_policy["default_tolerance_band_pct"]
            if custom_saa_target.risk_ceiling is None:
                raise ValueError("Custom SAA requires an explicit independent risk ceiling")
            if custom_saa_target.large_cap_pct is not None:
                targets = {
                    "large_cap": float(custom_saa_target.large_cap_pct),
                    "mid_cap": float(custom_saa_target.mid_cap_pct),
                    "small_cap": float(custom_saa_target.small_cap_pct),
                    "flexi_multi_cap": float(custom_saa_target.flexi_cap_pct),
                    "debt_liquid": float(custom_saa_target.debt_pct),
                    "unclassified": 0.0,
                }
            elif float(custom_saa_target.equity_pct) > 0:
                distribution = custom_policy["default_equity_distribution_pct"]
                distribution_keys = (
                    "large_cap_pct", "flexi_multi_cap_pct",
                    "mid_cap_pct", "small_cap_pct",
                )
                if (
                    not isinstance(distribution, dict)
                    or set(distribution) != set(distribution_keys)
                    or sum(float(distribution[key]) for key in distribution_keys) != 100.0
                ):
                    raise ValueError("Custom SAA equity distribution policy is missing or invalid")
                scale = float(custom_saa_target.equity_pct) / 100.0
                targets = {
                    "large_cap": round(float(distribution["large_cap_pct"]) * scale, 2),
                    "flexi_multi_cap": round(float(distribution["flexi_multi_cap_pct"]) * scale, 2),
                    "mid_cap": round(float(distribution["mid_cap_pct"]) * scale, 2),
                    "small_cap": round(float(distribution["small_cap_pct"]) * scale, 2),
                    "debt_liquid": float(custom_saa_target.debt_pct),
                    "unclassified": 0.0,
                }
                equity_sum = sum(targets[key] for key in (
                    "large_cap", "flexi_multi_cap", "mid_cap", "small_cap"
                ))
                targets["large_cap"] = round(
                    targets["large_cap"] + float(custom_saa_target.equity_pct) - equity_sum, 2
                )
            else:
                targets = {
                    "large_cap": 0.0, "mid_cap": 0.0, "small_cap": 0.0,
                    "flexi_multi_cap": 0.0,
                    "debt_liquid": float(custom_saa_target.debt_pct),
                    "unclassified": 0.0,
                }
        else:
            public_mapping = policy["public_risk_profile_mapping"][risk_profile]
            profile_key = public_mapping["behavioral_profile"]
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
        current = {key: Decimal("0") for key in targets}
        total = Decimal("0")
        for holding in holdings:
            value = quantize_inr(holding.current_value_inr)
            if not value.is_finite() or value <= 0:
                raise ValueError("holding valuation is invalid")
            asset_class = getattr(holding, "asset_class", None)
            asset_class = getattr(asset_class, "value", asset_class)
            normalized_class = str(asset_class).upper().replace("-", "_").replace(" ", "_")
            bucket = _ASSET_CLASS_TO_SAA_BUCKET.get(normalized_class, "unclassified")
            current[bucket] += value
            total += value
        if not total.is_finite() or total <= 0:
            raise ValueError("CAS holdings total is invalid")
        drift = calculate_saa_drift(
            current, targets, tolerance_band_pct=tolerance, portfolio_total_inr=total
        )
        equity_rows = []
        for holding in holdings:
            holding_value = quantize_inr(holding.current_value_inr)
            equity_pct = Decimal(str(getattr(holding, "equity_pct", 0.0)))
            if not equity_pct.is_finite() or not Decimal("0") <= equity_pct <= Decimal("100"):
                raise ValueError("holding equity exposure is invalid")
            equity_value = holding_value * equity_pct / Decimal("100")
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
                equity_rows, required_coverage_pct=_required_lookthrough_coverage_pct()
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
            "is_total_portfolio_lookthrough": False,
            "portfolio_perimeter_complete": False,
            "valuation_date_verified": False,
            "total_value_inr": str(total),
            "holding_count": len(holdings),
            "holding_plan_option_identity": [
                {
                    "scheme_id": getattr(holding, "scheme_id", None),
                    "isin": getattr(holding, "isin", None),
                    "plan": getattr(getattr(holding, "plan", None), "value", getattr(holding, "plan", None)),
                    "is_direct": getattr(holding, "is_direct", None),
                    "option_type": getattr(holding, "option_type", None),
                    "status": getattr(holding, "plan_option_status", "MISSING"),
                }
                for holding in holdings
            ],
            "current_sleeve_values_inr": {
                key: str(value) for key, value in sorted(current.items())
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
    monthly_budget_inr: Decimal,
    risk_profile: str,
    existing_lookthrough: dict[str, Any],
    cas_holdings_total_inr: float,
    evidence_as_of_date: date,
    custom_saa_target: Any | None = None,
) -> dict[str, Any]:
    """Orchestrate portfolio, suitability, affordability and candidate gates.

    This returns diagnostics and a routing simulation only. It never authorizes
    an allocation; the independent research/TRI release gate remains separate.
    """
    try:
        as_of = context["as_of_date"]
        if date.fromisoformat(as_of) != evidence_as_of_date:
            raise PortfolioInputError("portfolio context and evidence decision dates do not match")
        if context.get("cas_valuation_date") != as_of:
            raise PortfolioInputError("CAS valuation date is not reconciled to the total-portfolio date")
        assets = context["assets"]
        if not isinstance(assets, list) or not assets:
            raise PortfolioInputError("complete portfolio asset rows are required")
        for row in assets:
            if not isinstance(row, dict) or row.get("saa_bucket") not in _TOTAL_PORTFOLIO_SLEEVES:
                raise PortfolioInputError("every asset requires an explicit approved SAA sleeve mapping")
        # Issue #23: When signed report is requested or sign_off is supplied, generate and enforce
        # the authoritative canonical signed reconciliation report with RFC 8785 (JCS) SHA-256 digest.
        sign_off_input = context.get("sign_off")
        liabilities_input = context.get("liabilities", [])
        if isinstance(sign_off_input, dict) or context.get("require_signed_report") is True:
            reconciliation = generate_signed_portfolio_reconciliation_report(
                assets,
                perimeter_complete=context.get("perimeter_complete") is True,
                as_of_date=as_of,
                sign_off=sign_off_input if isinstance(sign_off_input, dict) else {},
                excluded_assets=context.get("excluded_assets", []),
                unmatched_items=context.get("unmatched_items", []),
                liabilities=liabilities_input,
            )
        else:
            reconciliation = reconcile_total_portfolio(
                assets,
                perimeter_complete=context.get("perimeter_complete") is True,
                as_of_date=as_of,
                excluded_assets=context.get("excluded_assets", []),
                unmatched_items=context.get("unmatched_items", []),
                sign_off=context.get("sign_off"),
                liabilities=liabilities_input,
            )
        if reconciliation["status"] != "RECONCILED" or not reconciliation.get("is_approved_for_sip_routing", True):
            return {"status": "HOLD", "portfolio_reconciliation": reconciliation,
                    "reason": reconciliation.get("reason", "TOTAL_PORTFOLIO_RECONCILIATION_FAILED")}
        reconciliation["excluded_assets"] = [
            {
                "asset_class": row.get("asset_class"),
                "reason": row.get("reason"),
            }
            for row in context.get("excluded_assets", [])
            if isinstance(row, dict)
        ]
        total = Decimal(str(reconciliation["total_value_inr"]))
        current = {sleeve: Decimal("0") for sleeve in _TOTAL_PORTFOLIO_SLEEVES}
        for row in assets:
            current[row["saa_bucket"]] += quantize_inr(row["value_inr"])
        if sum(current.values(), Decimal("0")) != total:
            raise PortfolioInputError("SAA sleeve values do not reconcile exactly to total portfolio")
        policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        if risk_profile == "Custom":
            if custom_saa_target is None:
                raise PortfolioInputError("Custom SAA requires an approved custom_saa_target.")
            from core.models import AssetAllocationTarget
            if not isinstance(custom_saa_target, AssetAllocationTarget):
                raise PortfolioInputError("custom_saa_target must be a validated AssetAllocationTarget instance")
        elif risk_profile not in policy["public_risk_profile_mapping"]:
            raise PortfolioInputError(f"Unsupported risk profile '{risk_profile}'; custom SAA requires an approved custom policy contract.")

        ips = context["ips"]
        ips_date = date.fromisoformat(ips["effective_date"])
        valuation_date = date.fromisoformat(as_of)
        max_policy_age = int(context["candidate_policy"]["max_evidence_age_days"])
        if (
            ips.get("approved") is not True
            or not isinstance(ips.get("source_ref"), str) or not ips["source_ref"].strip()
            or ips_date > valuation_date
            or (valuation_date - ips_date).days > max_policy_age
        ):
            raise PortfolioInputError("approved, dated client IPS evidence is required")

        targets = ips["target_weights_pct"]
        if not isinstance(targets, dict) or set(targets) != set(_TOTAL_PORTFOLIO_SLEEVES):
            raise PortfolioInputError("client IPS must specify all five SAA sleeves")
        tolerance = ips["tolerance_band_pct"]
        equity_target = sum(float(targets[key]) for key in (
            "large_cap", "mid_cap", "small_cap", "flexi_multi_cap"
        ))
        mid_small_target = float(targets["mid_cap"]) + float(targets["small_cap"])
        debt_target = float(targets["debt_liquid"])

        if risk_profile == "Custom":
            risk_ceiling_raw = getattr(custom_saa_target, "risk_ceiling", None)
            if risk_ceiling_raw is None and "risk_ceiling" in ips:
                risk_ceiling_raw = ips.get("risk_ceiling")
            if risk_ceiling_raw is None:
                raise PortfolioInputError("Custom SAA requires an explicit independent risk ceiling")
            try:
                c_val = int(risk_ceiling_raw)
                if not 1 <= c_val <= 6 or isinstance(risk_ceiling_raw, bool):
                    raise ValueError()
                effective_risk_ceiling = c_val
            except (ValueError, TypeError):
                raise PortfolioInputError(f"risk_ceiling must be an integer between 1 and 6; got {risk_ceiling_raw!r}")
            if abs(equity_target - float(custom_saa_target.equity_pct)) > 0.01:
                raise PortfolioInputError("client IPS equity target conflicts with approved custom SAA mandate")
            if abs(debt_target - float(custom_saa_target.debt_pct)) > 0.01:
                raise PortfolioInputError("client IPS debt target conflicts with approved custom SAA mandate")
            if custom_saa_target.large_cap_pct is not None:
                if abs(float(targets["large_cap"]) - float(custom_saa_target.large_cap_pct)) > 0.01:
                    raise PortfolioInputError("client IPS large cap target conflicts with custom SAA")
                if abs(float(targets["mid_cap"]) - float(custom_saa_target.mid_cap_pct)) > 0.01:
                    raise PortfolioInputError("client IPS mid cap target conflicts with custom SAA")
                if abs(float(targets["small_cap"]) - float(custom_saa_target.small_cap_pct)) > 0.01:
                    raise PortfolioInputError("client IPS small cap target conflicts with custom SAA")
                if abs(float(targets["flexi_multi_cap"]) - float(custom_saa_target.flexi_cap_pct)) > 0.01:
                    raise PortfolioInputError("client IPS flexi cap target conflicts with custom SAA")
            if equity_target == 100.0 and debt_target == 0.0 and ips.get("tier6_equity_only_authorized") is not True:
                raise PortfolioInputError("Tier 6 equity-only routing requires explicit IPS authorization")
        else:
            public_mapping = policy["public_risk_profile_mapping"][risk_profile]
            profile_key = public_mapping["behavioral_profile"]
            std_ceiling = public_mapping["risk_ceiling"]
            if (
                not isinstance(profile_key, str) or not profile_key
                or isinstance(std_ceiling, bool) or not isinstance(std_ceiling, int)
                or not 1 <= std_ceiling <= 6
            ):
                raise PortfolioInputError("public risk-profile mapping is invalid")
            if "risk_ceiling" in ips:
                try:
                    c_val = int(ips["risk_ceiling"])
                    if not 1 <= c_val <= 6 or isinstance(ips["risk_ceiling"], bool):
                        raise ValueError()
                    effective_risk_ceiling = min(std_ceiling, c_val)
                except (ValueError, TypeError):
                    raise PortfolioInputError(f"risk_ceiling must be an integer between 1 and 6; got {ips['risk_ceiling']!r}")
            else:
                effective_risk_ceiling = std_ceiling
            profile = policy["behavioral_risk_profiles"][profile_key]
            if std_ceiling == 6 and profile_key == "very_high" and ips.get("tier6_equity_only_authorized") is not True:
                raise PortfolioInputError("Tier 6 equity-only routing requires explicit IPS authorization")
            if (
                equity_target > float(profile["max_equity_pct"])
                or mid_small_target > float(profile["max_mid_small_pct"])
                or debt_target < float(profile["min_debt_pct"])
                or debt_target > float(profile["max_debt_pct"])
            ):
                raise PortfolioInputError("client IPS targets conflict with approved risk-profile limits")
        cas_value_in_perimeter = sum(
            (quantize_inr(row["value_inr"]) for row in assets if row.get("asset_class") == "cas_mutual_fund"),
            Decimal("0"),
        )
        if cas_value_in_perimeter != quantize_inr(cas_holdings_total_inr):
            raise PortfolioInputError("CAS holdings do not reconcile exactly to declared CAS asset perimeter")
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
        mismatched_goal_profiles = [
            goal.get("goal_id", "UNKNOWN_GOAL")
            for goal in context.get("goals", [])
            if goal.get("approved_risk_profile") != risk_profile
        ]
        if mismatched_goal_profiles:
            goals = {
                "status": "HOLD",
                "goals": goals.get("goals", []),
                "reason": "GOAL_RISK_PROFILE_CONFLICT",
                "affected_goal_ids": mismatched_goal_profiles,
            }
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
            c_gates = dict(gate_results.get(candidate_id, {}))
            cand_riskometer = candidate.get("riskometer_score")
            if cand_riskometer is not None:
                try:
                    if int(cand_riskometer) > effective_risk_ceiling:
                        c_gates["risk"] = "FAIL"
                except (ValueError, TypeError):
                    c_gates["risk"] = "FAIL"
            prepared_candidates.append({
                "candidate_id": candidate_id,
                "scheme_identity": identity,
                "evidence_as_of_date": direct.get("reviewed_at") or direct.get("effective_date"),
                "evidence_ref": direct.get("source_document_sha256"),
                "gates": c_gates,
            })
            operational = operational_evidence.get(candidate_id)
            if isinstance(operational, dict):
                operational_results[candidate_id] = validate_scheme_operational_feasibility(
                    operational, requested_monthly_sip_inr=monthly_budget_inr,
                    as_of_date=as_of,
                    max_evidence_age_days=int(candidate_policy["max_evidence_age_days"]),
                    check_requested_minimum=False,
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
        minimum_universe_size = int(policy["fund_universe_requirements"]["min_candidate_universe_size"])
        if len(candidate_universe) < minimum_universe_size:
            screening["status"] = "UNIVERSE_INSUFFICIENT"
            screening["scoring_permitted"] = False
            screening["universe_minimum"] = minimum_universe_size
            screening["universe_observed"] = len(candidate_universe)
            screening["universe_reason"] = "COMPLETE_POLICY_MINIMUM_CANDIDATE_UNIVERSE_NOT_MET"
        eligible_ids = set(screening["eligible_candidate_ids"]) if screening["scoring_permitted"] else set()
        eligible_ids = {
            candidate_id for candidate_id in eligible_ids
            if operational_results.get(candidate_id, {}).get("status") == "FEASIBLE_FOR_REVIEW"
        }
        eligible_sleeves = sorted({
            candidate_policy.get("candidate_sleeves", {}).get(candidate_id)
            for candidate_id in eligible_ids
            if candidate_policy.get("candidate_sleeves", {}).get(candidate_id) in _TOTAL_PORTFOLIO_SLEEVES
        })
        # Issue #30, #31, #32, #23: Fail closed before routing if portfolio perimeter,
        # goal suitability, emergency reserve, or affordability stress tests do not pass.
        pre_routing_pass = (
            reconciliation.get("status") == "RECONCILED"
            and goals.get("status") == "VALIDATED"
            and liquidity.get("status") == "AFFORDABLE"
            and stress.get("all_scenarios_sustainable") is True
        )
        if not pre_routing_pass:
            pre_routing_reason = "PRE_ROUTING_CONTROL_GATE_FAILED"
            if reconciliation.get("status") != "RECONCILED":
                pre_routing_reason = f"RECONCILIATION_NOT_CLEARED:{reconciliation.get('reason')}"
            elif goals.get("status") != "VALIDATED":
                pre_routing_reason = f"GOAL_SUITABILITY_NOT_CLEARED:{goals.get('reason', 'GOAL_VALIDATION_FAILED')}"
            elif liquidity.get("status") != "AFFORDABLE":
                pre_routing_reason = f"LIQUIDITY_NOT_AFFORDABLE:{liquidity.get('reason')}"
            elif not stress.get("all_scenarios_sustainable"):
                pre_routing_reason = "AFFORDABILITY_STRESS_TEST_FAILED"

            routing = {
                "status": "HOLD",
                "reason": pre_routing_reason,
                "allocations_inr": {},
                "requested_budget_inr": str(Decimal(str(monthly_budget_inr))),
                "allocated_budget_inr": "0",
                "unallocated_budget_inr": str(Decimal(str(monthly_budget_inr))),
                "unallocated_by_sleeve_inr": {},
                "reconciliation_ok": True,
            }
        else:
            routing = route_incremental_sip(
                monthly_budget_inr, current, targets, portfolio_total_inr=total,
                tolerance_band_pct=tolerance,
                eligible_sleeves=eligible_sleeves,
                rounding_increment_inr=policy["sip_allocation_policy"]["sip_increment_inr"],
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
            or (valuation_date - concentration_date).days > max_policy_age
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
        external_equity_rows = []
        external_equity_missing = []
        for row in assets:
            if row.get("asset_class") not in {"equity", "direct_equity", "external_mutual_fund"}:
                continue
            constituents = row.get("constituent_weights")
            coverage = row.get("constituent_weights_coverage_pct")
            if not isinstance(constituents, dict) or coverage is None:
                external_equity_missing.append(row.get("asset_id", "UNKNOWN_ASSET"))
                continue
            external_equity_rows.append({
                "holding_value_inr": row["value_inr"],
                "coverage_pct": coverage,
                "constituents": constituents,
            })
        if external_equity_missing:
            external_lookthrough = {
                "status": "HOLD", "reason": "EXTERNAL_EQUITY_LOOKTHROUGH_MISSING",
                "unverified_asset_count": len(external_equity_missing),
            }
        elif external_equity_rows:
            external_lookthrough = calculate_lookthrough_exposure(
                external_equity_rows, required_coverage_pct=_required_lookthrough_coverage_pct()
            )
        else:
            external_lookthrough = {
                "status": "CALCULATED", "coverage_pct": "100",
                "issuer_exposure_inr": {}, "scope": "NO_EXTERNAL_EQUITY_ASSETS_DECLARED",
            }
        if external_lookthrough.get("status") == "CALCULATED":
            for issuer, value in external_lookthrough.get("issuer_exposure_inr", {}).items():
                existing_issuer_values[issuer] = existing_issuer_values.get(issuer, 0.0) + float(value)
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
            candidate_sleeve = candidate_policy.get("candidate_sleeves", {}).get(candidate_id)
            routed_sleeve_budget = Decimal(
                str(routing.get("allocations_inr", {}).get(candidate_sleeve, "0"))
            )
            operational_minimum = operational_results.get(candidate_id, {}).get(
                "minimum_monthly_sip_inr"
            )
            try:
                policy_minimum = Decimal(str(policy["sip_allocation_policy"]["min_sip_per_fund_inr"]))
                scheme_minimum = Decimal(str(operational_minimum))
                sip_increment = Decimal(str(policy["sip_allocation_policy"]["sip_increment_inr"]))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                overlap_results[candidate_id] = {
                    "status": "HOLD", "reason": "CANDIDATE_FUND_MINIMUM_OR_INCREMENT_UNAVAILABLE"
                }
                continue
            if sip_increment <= 0 or policy_minimum <= 0 or scheme_minimum <= 0:
                overlap_results[candidate_id] = {
                    "status": "HOLD", "reason": "CANDIDATE_FUND_MINIMUM_OR_INCREMENT_INVALID"
                }
                continue
            minimum_ticket = max(policy_minimum, scheme_minimum)
            ticket_budget = (
                (minimum_ticket / sip_increment).to_integral_value(rounding=ROUND_CEILING)
                * sip_increment
            )
            if routed_sleeve_budget <= 0 or ticket_budget > routed_sleeve_budget:
                overlap_results[candidate_id] = {
                    "status": "HOLD",
                    "reason": "ROUTED_SLEEVE_BUDGET_BELOW_CANDIDATE_MINIMUM_TICKET",
                    "minimum_ticket_inr": str(ticket_budget),
                    "routed_sleeve_budget_inr": str(routed_sleeve_budget),
                }
                continue
            candidate_post_total = Decimal(str(total)) + ticket_budget
            candidate_exposure = calculate_lookthrough_exposure(
                [{"holding_value_inr": str(ticket_budget),
                  "coverage_pct": coverage, "constituents": constituents}],
                required_coverage_pct=_required_lookthrough_coverage_pct(),
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
                issuer: value / float(candidate_post_total) * 100 for issuer, value in combined_values.items()
            }
            breaches = sorted(
                issuer for issuer, pct in concentrations.items()
                if pct > max_issuer_pct
            )
            classified_concentration = evaluate_classified_concentration(
                combined_values,
                concentration_policy.get("issuer_classifications", {}),
                total_portfolio_inr=candidate_post_total,
                as_of_date=as_of,
                classification_as_of_date=concentration_policy.get("classification_as_of_date", ""),
                classification_source_ref=concentration_policy.get("classification_source_ref", ""),
                max_evidence_age_days=max_policy_age,
                max_sector_pct=concentration_policy.get("max_sector_pct_of_portfolio", 0),
                max_market_cap_pct=concentration_policy.get("max_market_cap_pct_of_portfolio", 0),
                max_theme_pct=concentration_policy.get("max_theme_pct_of_portfolio", 0),
            )
            concentration_blocked = bool(breaches) or classified_concentration.get("status") != "ASSESSED"
            overlap_results[candidate_id] = {
                "status": "HOLD" if concentration_blocked else "ASSESSED",
                "ticket_basis_inr": str(ticket_budget),
                "routed_sleeve_budget_inr": str(routed_sleeve_budget),
                "scheme_minimum_monthly_sip_inr": str(scheme_minimum),
                "shared_issuers": sorted(set(issuers) & set(existing_issuer_values)),
                "candidate_issuer_exposure_inr": issuers,
                "combined_issuer_concentration_pct": concentrations,
                "max_issuer_pct_of_portfolio": max_issuer_pct,
                "breaching_issuers": breaches,
                "sector_market_cap_theme": classified_concentration,
                "reason": "Candidate one-instalment issuer, sector, market-cap and theme impact against existing holdings.",
            }
        screening_by_id = {
            row.get("candidate_id"): row
            for row in screening.get("candidate_results", [])
            if isinstance(row, dict) and row.get("candidate_id")
        }
        candidate_allocation_inputs = []
        for candidate in candidate_universe:
            candidate_id = str(candidate.get("fund_id") or candidate.get("scheme_id") or "")
            candidate_allocation_inputs.append({
                "candidate_id": candidate_id,
                "sleeve": candidate_policy.get("candidate_sleeves", {}).get(candidate_id),
                "eligibility_status": screening_by_id.get(candidate_id, {}).get("status"),
                "overlap_status": overlap_results.get(candidate_id, {}).get("status"),
                "operational_status": operational_results.get(candidate_id, {}).get("status"),
                "minimum_monthly_sip_inr": operational_results.get(candidate_id, {}).get("minimum_monthly_sip_inr"),
                "rank_score": candidate.get("rank_score"),
                "score_evidence_ref": candidate.get("rank_score_source_ref"),
                "score_as_of_date": candidate.get("rank_score_as_of_date"),
            })
        allocation_policy = policy["sip_allocation_policy"]
        remaining_fund_slots = int(allocation_policy["max_core_fund_count"]) - int(context["current_core_fund_count"])
        candidate_allocation = allocate_candidate_sip(
            routing.get("allocations_inr", {}),
            candidate_allocation_inputs,
            as_of_date=as_of,
            min_sip_per_fund_inr=allocation_policy["min_sip_per_fund_inr"],
            rounding_increment_inr=allocation_policy["sip_increment_inr"],
            max_funds=max(0, remaining_fund_slots),
            max_score_age_days=int(candidate_policy["max_evidence_age_days"]),
        )

        # Re-check the actual selected set together. Individual candidate
        # checks cannot detect two different sleeves collectively breaching a
        # sector/theme/issuer threshold.
        candidate_by_id = {
            str(row.get("fund_id") or row.get("scheme_id") or ""): row
            for row in candidate_universe
        }
        selected_candidate_rows = []
        selected_total = Decimal("0")
        for selected in candidate_allocation.get("allocations", []):
            selected_candidate = candidate_by_id.get(selected["candidate_id"], {})
            selected_value = Decimal(str(selected["monthly_sip_inr"]))
            selected_total += selected_value
            selected_candidate_rows.append({
                "holding_value_inr": str(selected_value),
                "coverage_pct": selected_candidate.get("constituent_weights_coverage_pct"),
                "constituents": selected_candidate.get("constituent_weights"),
            })
        if candidate_allocation.get("status") == "ALLOCATED" and selected_candidate_rows:
            selected_lookthrough = calculate_lookthrough_exposure(
                selected_candidate_rows, required_coverage_pct=_required_lookthrough_coverage_pct()
            )
            if selected_lookthrough.get("status") == "CALCULATED":
                proposed_issuer_values = dict(existing_issuer_values)
                for issuer, value in selected_lookthrough["issuer_exposure_inr"].items():
                    proposed_issuer_values[issuer] = (
                        proposed_issuer_values.get(issuer, 0.0) + float(value)
                    )
                post_investment_total = Decimal(str(total)) + selected_total
                proposed_issuer_concentration = {
                    issuer: value / float(post_investment_total) * 100
                    for issuer, value in proposed_issuer_values.items()
                }
                proposed_issuer_breaches = {
                    issuer: pct for issuer, pct in proposed_issuer_concentration.items()
                    if pct > max_issuer_pct
                }
                proposed_classified = evaluate_classified_concentration(
                    proposed_issuer_values,
                    concentration_policy.get("issuer_classifications", {}),
                    total_portfolio_inr=post_investment_total,
                    as_of_date=as_of,
                    classification_as_of_date=concentration_policy.get("classification_as_of_date", ""),
                    classification_source_ref=concentration_policy.get("classification_source_ref", ""),
                    max_evidence_age_days=max_policy_age,
                    max_sector_pct=concentration_policy.get("max_sector_pct_of_portfolio", 0),
                    max_market_cap_pct=concentration_policy.get("max_market_cap_pct_of_portfolio", 0),
                    max_theme_pct=concentration_policy.get("max_theme_pct_of_portfolio", 0),
                )
                candidate_set_concentration = {
                    "status": "ASSESSED" if not proposed_issuer_breaches and proposed_classified.get("status") == "ASSESSED" else "HOLD",
                    "post_investment_portfolio_value_inr": str(post_investment_total),
                    "proposed_sip_budget_inr": str(selected_total),
                    "lookthrough": selected_lookthrough,
                    "issuer_concentration_pct": proposed_issuer_concentration,
                    "issuer_breaches": proposed_issuer_breaches,
                    "sector_market_cap_theme": proposed_classified,
                }
            else:
                candidate_set_concentration = {
                    "status": "HOLD",
                    "reason": "SELECTED_CANDIDATE_SET_LOOKTHROUGH_INCOMPLETE",
                    "lookthrough": selected_lookthrough,
                }
        else:
            candidate_set_concentration = {
                "status": "HOLD",
                "reason": "NO_FUND_LEVEL_ALLOCATION_TO_ASSESS",
            }

        routed_budget = Decimal(str(routing.get("allocated_budget_inr", "0")))
        routing_unallocated = Decimal(str(routing.get("unallocated_budget_inr", monthly_budget_inr)))
        fund_unallocated = Decimal(str(candidate_allocation.get("unallocated_budget_inr", "0")))
        fund_allocated = Decimal(str(candidate_allocation.get("allocated_budget_inr", "0")))
        routing_reconciles = bool(routing.get("reconciliation_ok", False))
        fund_requested = Decimal(str(candidate_allocation.get("requested_budget_inr", "0")))
        if candidate_set_concentration.get("status") != "ASSESSED":
            blocked_by_sleeve = {
                key: Decimal(str(value))
                for key, value in routing.get("unallocated_by_sleeve_inr", {}).items()
            }
            for sleeve, value in routing.get("allocations_inr", {}).items():
                blocked_by_sleeve[sleeve] = (
                    blocked_by_sleeve.get(sleeve, Decimal("0"))
                    + Decimal(str(value))
                )
            candidate_allocation = {
                **candidate_allocation,
                "status": "HOLD",
                "pre_concentration_status": candidate_allocation.get("status"),
                "allocations": [],
                "allocated_budget_inr": "0",
                "unallocated_budget_inr": str(Decimal(str(monthly_budget_inr))),
                "unallocated_by_sleeve_inr": {
                    key: str(value) for key, value in sorted(blocked_by_sleeve.items())
                },
                "concentration_blocked": True,
            }
            # Preserve the SAA split: amounts never routed to an eligible sleeve
            # stay in the unrouted bucket; the exact routed sleeve budget is
            # unallocated because the selected set failed concentration.
            fund_allocated = Decimal("0")
            fund_unallocated = routed_budget
        overall_unallocated = routing_unallocated + fund_unallocated
        candidate_allocation.update({
            "requested_budget_inr": str(Decimal(str(monthly_budget_inr))),
            "allocated_budget_inr": str(fund_allocated),
            "unrouted_saa_budget_inr": str(routing_unallocated),
            "routed_but_unallocated_budget_inr": str(fund_unallocated),
            "unallocated_budget_inr": str(overall_unallocated),
            "reconciliation_ok": (
                routing_reconciles
                and fund_requested == routed_budget
                and fund_allocated + fund_unallocated == routed_budget
                and fund_allocated + overall_unallocated == Decimal(str(monthly_budget_inr))
            ),
        })
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
            and candidate_allocation["status"] == "ALLOCATED"
            and candidate_allocation["reconciliation_ok"] is True
            and candidate_set_concentration["status"] == "ASSESSED"
            and external_lookthrough.get("status") == "CALCULATED"
            and all(
                overlap_results.get(item["candidate_id"], {}).get("status") == "ASSESSED"
                for item in candidate_allocation.get("allocations", [])
            )
        )
        return {
            "status": "ASSESSMENT_COMPLETE" if all_gates_pass else "HOLD",
            "scope": "DECLARED_TOTAL_PORTFOLIO",
            "source_bundle_sha256": context.get("_source_bundle_sha256"),
            "trust_level": "UNVERIFIED_CLIENT_DECLARATIONS" if client_supplied_unverified else ("PROVIDER_ATTESTED" if provider_attested else "UNVERIFIED_CONTEXT"),
            "portfolio_reconciliation": reconciliation,
            "signed_portfolio_reconciliation_report": reconciliation if reconciliation.get("report_sha256") else None,
            "signed_reconciliation_report_sha256": reconciliation.get("report_sha256"),
            "cas_valuation_date_verified": True,
            "cas_valuation_date": as_of,
            "saa": {"current_sleeve_values_inr": current, "target_weights_pct": targets,
                    "drift": drift, "policy_as_of": policy.get("as_of")},
            "goal_suitability": goals,
            "liquidity_and_affordability": liquidity,
            "affordability_stress": stress,
            "candidate_screening": screening,
            "scheme_operational_feasibility": operational_results,
            "candidate_overlap_diagnostics": overlap_results,
            "external_asset_lookthrough": external_lookthrough,
            "incremental_sip_routing_simulation": routing,
            "candidate_level_sip_allocation_simulation": candidate_allocation,
            "proposed_candidate_set_concentration": candidate_set_concentration,
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
    monthly_budget_inr: Decimal,
    portfolio_assessment: dict[str, Any],
    context_assessment: dict[str, Any] | None = None,
    metrics_source_bytes: bytes | None = None,
    candidate_universe_source_bytes: bytes | None = None,
    portfolio_context_source_bytes: bytes | None = None,
    candidate_score_source_bytes: bytes | None = None,
    category_anchor_source_bytes: bytes | None = None,
    metrics_normalized_sha256: str | None = None,
    candidate_universe_normalized_sha256: str | None = None,
) -> dict[str, str]:
    """Hash the source and diagnostic inputs that led to a fail-closed SIP result."""
    candidate_source_hashes = {}
    candidate_rank_evidence = {}
    for candidate in candidate_universe:
        evidence = candidate.get("direct_plan_evidence", {})
        candidate_id = candidate.get("fund_id", candidate.get("id", "UNKNOWN"))
        candidate_source_hashes[candidate_id] = (
            evidence.get("source_document_sha256")
            if isinstance(evidence, dict) else None
        )
        candidate_rank_evidence[candidate_id] = {
            "rank_score": candidate.get("rank_score"),
            "rank_score_source_ref": candidate.get("rank_score_source_ref"),
            "rank_score_as_of_date": candidate.get("rank_score_as_of_date"),
            "rank_score_methodology_version": candidate.get("rank_score_methodology_version"),
        }
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    screening_policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "fund_screening.json"
    try:
        policy_source_sha256 = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    except OSError:
        policy_source_sha256 = None
    try:
        screening_source_sha256 = hashlib.sha256(screening_policy_path.read_bytes()).hexdigest()
    except OSError:
        screening_source_sha256 = None
    effective_policy_digest = (
        hashlib.sha256(f"{policy_source_sha256}:{screening_source_sha256}".encode("utf-8")).hexdigest()
        if policy_source_sha256 and screening_source_sha256 else policy_source_sha256
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
            "metrics_source_sha256": hashlib.sha256(metrics_source_bytes).hexdigest() if metrics_source_bytes else None,
            "metrics_normalized_sha256": metrics_normalized_sha256,
            "candidate_universe_source_sha256": hashlib.sha256(candidate_universe_source_bytes).hexdigest() if candidate_universe_source_bytes else None,
            "candidate_universe_normalized_sha256": candidate_universe_normalized_sha256,
            "candidate_score_source_sha256": hashlib.sha256(candidate_score_source_bytes).hexdigest() if candidate_score_source_bytes else None,
            "category_anchor_source_sha256": hashlib.sha256(category_anchor_source_bytes).hexdigest() if category_anchor_source_bytes else None,
            "portfolio_context_source_sha256": hashlib.sha256(portfolio_context_source_bytes).hexdigest() if portfolio_context_source_bytes else None,
            "screening_policy_sha256": screening_source_sha256,
            "effective_policy_digest": effective_policy_digest,
            "portfolio_context_bundle_sha256": (
                context_assessment.get("source_bundle_sha256")
                if isinstance(context_assessment, dict) else None
            ),
        },
        "as_of_dates": {
            "disclosure_as_of_date": disclosure_as_of_date.isoformat(),
            "policy_as_of_date": portfolio_assessment.get("policy_as_of"),
            "cas_valuation_date": (
                context_assessment.get("cas_valuation_date")
                if isinstance(context_assessment, dict) else "UNVERIFIED_NOT_RECONCILED"
            ),
        },
        "policy_version": f"asset_allocation.json@{portfolio_assessment.get('policy_as_of')}",
        "policy_source_sha256": policy_source_sha256,
        "screening_policy_sha256": screening_source_sha256,
        "effective_policy_digest": effective_policy_digest,
        "engine_version": "core.math_engine.compute_deterministic_sip_blueprint",
        "eligibility": {
            "current_holding_evidence": "PASS",
            "candidate_universe_count": len(candidate_universe),
            "candidate_scoring": "SOURCE_RANK_SCORES_CONSUMED_FOR_DIAGNOSTIC_SIMULATION; RELEASE_APPROVAL_PENDING",
            "candidate_rank_evidence": candidate_rank_evidence,
        },
        "portfolio_effect": {
            "scope": portfolio_assessment.get("scope"),
            "saa_drift": portfolio_assessment.get("saa_drift"),
            "lookthrough": portfolio_assessment.get("lookthrough"),
            "total_portfolio_context": context_assessment,
            "candidate_level_allocation_simulation": (
                context_assessment.get("candidate_level_sip_allocation_simulation")
                if isinstance(context_assessment, dict) else None
            ),
        },
        "allocation": {
            "requested_budget_inr": monthly_budget_inr,
            "simulated_allocated_budget_inr": (
                context_assessment.get("candidate_level_sip_allocation_simulation", {}).get("allocated_budget_inr")
                if isinstance(context_assessment, dict) else None
            ),
            "simulated_unallocated_budget_inr": (
                context_assessment.get("candidate_level_sip_allocation_simulation", {}).get("unallocated_budget_inr")
                if isinstance(context_assessment, dict) else None
            ),
            "authorized_allocated_budget_inr": 0,
            "unallocated_budget_inr": monthly_budget_inr,
        },
        "decision": {
            "status": "HOLD",
            "decision": "NO_ACTION",
            "reason": "RESEARCH_AND_TOTAL_PORTFOLIO_RELEASE_GATES_NOT_APPROVED",
        },
    }
    return build_decision_trace(record)


def _hold_plan(monthly_budget_inr: Decimal, reasons: list[str], portfolio_assessment: dict[str, Any] | None = None) -> dict[str, Any]:
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



def _validate_cas_decision_date(cas_path: Path, decision_as_of_date: date) -> date:
    """Bind SIP evidence freshness to the date embedded in the uploaded CAS."""
    if not isinstance(decision_as_of_date, date) or isinstance(decision_as_of_date, datetime):
        raise ValueError("A date-only SIP decision as-of date is required.")
    cas_date = _parse_cas_valuation_date(cas_path)
    if cas_date != decision_as_of_date:
        raise ValueError(
            "SIP decision date does not match the uploaded CAS valuation date."
        )
    return cas_date


def recommend_sip(
    *,
    cas_path: Path,
    metrics_path: Path | None,
    aliases_path: Path | None,
    monthly_budget_inr: Any,
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
    metrics_source_bytes: bytes | None = None,
    candidate_universe_source_bytes: bytes | None = None,
    portfolio_context_source_bytes: bytes | None = None,
    candidate_score_source_bytes: bytes | None = None,
    category_anchor_source_bytes: bytes | None = None,
    metrics_normalized_sha256: str | None = None,
    candidate_universe_normalized_sha256: str | None = None,
    custom_saa_target: Any | None = None,
) -> dict[str, Any]:
    """Build a fail-closed portfolio-aware SIP decision from explicit evidence.

    The caller must supply the original scheme-master and disclosure bytes.
    Custom SAA is supported when accompanied by an approved investor IPS mandate
    contract with validated AssetAllocationTarget sub-sleeve targets.
    """
    try:
        budget = quantize_inr(monthly_budget_inr)
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError("Monthly SIP budget must be a valid INR decimal amount") from exc
    if not budget.is_finite() or budget <= 0:
        raise ValueError("Monthly SIP budget must be finite and greater than zero")

    if risk_profile not in _ALLOWED_RISK_PROFILES and risk_profile != "Custom":
        return _hold_plan(budget, [
            "HOLD_UNRECOGNIZED_RISK_PROFILE: Unrecognized risk profile is not supported by the current SIP policy adapter."
        ])

    if risk_profile == "Custom":
        if custom_saa_target is None:
            return _hold_plan(budget, [
                "HOLD_CUSTOM_SAA_MANDATE_REQUIRED: Custom risk profile requires an explicit, validated "
                "AssetAllocationTarget with equity/debt/cash weights summing to 100% and explicit investor authorization."
            ])
        from core.models import AssetAllocationTarget
        if not isinstance(custom_saa_target, AssetAllocationTarget):
            return _hold_plan(budget, [
                "HOLD_CUSTOM_SAA_INVALID: custom_saa_target must be a validated AssetAllocationTarget instance."
            ])
        if (
            portfolio_context is None
            or not isinstance(portfolio_context, dict)
            or not isinstance(portfolio_context.get("ips"), dict)
            or portfolio_context.get("ips", {}).get("approved") is not True
        ):
            return _hold_plan(budget, [
                "HOLD_CUSTOM_SAA_BLUEPRINT_PENDING: Custom SAA fund selection blueprint requires an independently "
                "approved client IPS mandate contract; autonomous execution is disabled."
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
    try:
        _validate_cas_decision_date(cas_path, disclosure_as_of_date)
    except (OSError, ValueError, TypeError) as exc:
        return _hold_plan(
            budget,
            [f"CAS valuation-date validation failed closed ({type(exc).__name__})."],
        )
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
            require_exact_metric_identity=True,
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
        if getattr(holding, "plan_option_status", "MISSING") != "VERIFIED":
            evidence_gaps.append(
                f"{scheme_label}: Direct/Regular plan and Growth/IDCW option identity is missing or conflicting."
            )
        if getattr(holding, "metrics_status", "MISSING") != "VERIFIED":
            evidence_gaps.append(
                f"{scheme_label}: fund category/risk/exposure metrics are MISSING or unverified."
            )
        if holding.lookthrough_status != "VERIFIED":
            evidence_gaps.append(
                f"{scheme_label}: constituent disclosure is {holding.lookthrough_status}."
            )
        try:
            coverage = Decimal(str(holding.constituent_weights_coverage_pct))
            current_value = quantize_inr(holding.current_value_inr)
            required_coverage = Decimal(str(_required_lookthrough_coverage_pct()))
        except (TypeError, ValueError, AttributeError, ArithmeticError):
            evidence_gaps.append(f"{scheme_label}: coverage or current valuation is missing or malformed.")
            continue
        if not coverage.is_finite() or not required_coverage <= coverage <= Decimal("100"):
            evidence_gaps.append(f"{scheme_label}: constituent-weight coverage is incomplete or invalid.")
        if not current_value.is_finite() or current_value <= 0:
            evidence_gaps.append(f"{scheme_label}: current holding valuation is missing or invalid.")
    if evidence_gaps:
        return _hold_plan(budget, evidence_gaps)

    # This is a CAS-only diagnostic, deliberately not a total-portfolio
    # denominator. External assets, cash, liabilities and valuation date have
    # not been reconciled, so it cannot authorize SIP routing.
    portfolio_assessment = _build_cas_portfolio_assessment(
        holdings, risk_profile, custom_saa_target=custom_saa_target
    )

    # Run the deterministic engine with the exact evidence bundle. Its output is
    # retained only as an internal diagnostic until independent TRI/research
    # release gates are approved; provisional positive allocations are never
    # exposed by this service boundary.
    try:
        compute_deterministic_sip_blueprint(
            monthly_budget=budget,
            risk_tier=_ALLOWED_RISK_PROFILES.get(risk_profile, "Custom"),
            holdings=holdings,
            client_aum=sum(
                (quantize_inr(h.current_value_inr) for h in holdings),
                Decimal("0"),
            ),
            candidate_universe=candidate_universe,
            thematic_satellite_authorized=thematic_satellite_authorized,
            thematic_satellite_pct_of_equity=thematic_satellite_pct_of_equity,
            portfolio_disclosures_by_scheme_id=portfolio_disclosures_by_scheme_id,
            portfolio_disclosure_source_bytes_by_scheme_id=portfolio_disclosure_source_bytes_by_scheme_id,
            disclosure_as_of_date=disclosure_as_of_date,
            disclosure_max_age_days=disclosure_max_age_days,
            custom_saa_target=custom_saa_target,
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
                cas_holdings_total_inr=sum(
                    (quantize_inr(holding.current_value_inr) for holding in holdings),
                    Decimal("0"),
                ),
                evidence_as_of_date=disclosure_as_of_date,
                custom_saa_target=custom_saa_target,
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
        metrics_source_bytes=metrics_source_bytes,
        candidate_universe_source_bytes=candidate_universe_source_bytes,
        portfolio_context_source_bytes=portfolio_context_source_bytes,
        candidate_score_source_bytes=candidate_score_source_bytes,
        category_anchor_source_bytes=category_anchor_source_bytes,
        metrics_normalized_sha256=metrics_normalized_sha256,
        candidate_universe_normalized_sha256=candidate_universe_normalized_sha256,
    )
    portfolio_assessment["recommendation_lifecycle"]["decision_trace_sha256"] = (
        portfolio_assessment["decision_trace"]["sha256"]
    )
    try:
        lifecycle_persistence = persist_draft_snapshot(
            decision_trace_sha256=portfolio_assessment["decision_trace"]["sha256"]
        )
    except (OSError, ValueError):
        lifecycle_persistence = {
            "state": "DRAFT",
            "state_persisted": False,
            "persistence_status": "STORE_ERROR",
        }
    portfolio_assessment["recommendation_lifecycle"].update(lifecycle_persistence)
    return _hold_plan(budget, [
        "Evidence reached the deterministic SIP engine, but the independent benchmark/research release gate is not approved.",
        "Provisional engine allocations are suppressed; the full monthly budget remains unallocated.",
    ], portfolio_assessment)
