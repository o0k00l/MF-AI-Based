"""Fail-closed portfolio-aware SIP primitives.

These pure functions are deliberately separate from recommendation orchestration.
They do not select funds, invent policy thresholds, or authorize transactions.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping


class PortfolioInputError(ValueError):
    """Raised when portfolio inputs are incomplete, inconsistent or unsafe."""


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool) or value is None or (isinstance(value, str) and not value.strip()):
        raise PortfolioInputError(f"{field} is missing")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PortfolioInputError(f"{field} is not a decimal") from None
    if not result.is_finite():
        raise PortfolioInputError(f"{field} must be finite")
    return result


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str):
        raise PortfolioInputError(f"{field} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise PortfolioInputError(f"{field} must be an ISO date") from None
    if parsed.isoformat() != value:
        raise PortfolioInputError(f"{field} must use YYYY-MM-DD")
    return parsed


def reconcile_total_portfolio(
    assets: Iterable[Mapping[str, Any]],
    *,
    perimeter_complete: bool,
    as_of_date: str,
    excluded_assets: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Reconcile a declared asset perimeter; absent assets are never assumed zero.

    Each included row requires asset_id, asset_class, value_inr, source_ref,
    owner_scope and as_of_date. The caller must explicitly attest perimeter
    completeness; this helper cannot establish it from CAS alone.
    """
    valuation_date = _date(as_of_date, "as_of_date")
    rows = list(assets)
    excluded = list(excluded_assets)
    if perimeter_complete is not True:
        return {"status": "HOLD", "reason": "PORTFOLIO_PERIMETER_NOT_ATTESTED",
                "total_value_inr": None, "included_count": len(rows),
                "excluded_count": len(excluded)}
    if not rows:
        return {"status": "HOLD", "reason": "NO_INCLUDED_ASSETS",
                "total_value_inr": None, "included_count": 0,
                "excluded_count": len(excluded)}
    seen: set[str] = set()
    total = Decimal("0")
    by_class: dict[str, Decimal] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise PortfolioInputError(f"asset row {index} must be an object")
        asset_id = row.get("asset_id")
        asset_class = row.get("asset_class")
        source_ref = row.get("source_ref")
        owner_scope = row.get("owner_scope")
        if not all(isinstance(v, str) and v.strip() for v in
                   (asset_id, asset_class, source_ref, owner_scope)):
            raise PortfolioInputError(f"asset row {index} lacks identity/provenance")
        if asset_id in seen:
            raise PortfolioInputError("duplicate asset_id")
        seen.add(asset_id)
        row_date = _date(row.get("as_of_date"), f"assets[{index}].as_of_date")
        if row_date != valuation_date:
            raise PortfolioInputError("asset valuation dates do not match portfolio as_of_date")
        value = _decimal(row.get("value_inr"), f"assets[{index}].value_inr")
        if value < 0:
            raise PortfolioInputError("asset value cannot be negative")
        total += value
        by_class[asset_class] = by_class.get(asset_class, Decimal("0")) + value
    return {
        "status": "RECONCILED",
        "as_of_date": valuation_date.isoformat(),
        "total_value_inr": str(total),
        "included_count": len(rows),
        "excluded_count": len(excluded),
        "by_asset_class_inr": {k: str(v) for k, v in sorted(by_class.items())},
        "excluded_assets": excluded,
    }


def calculate_saa_drift(
    current_values_inr: Mapping[str, Any],
    target_weights_pct: Mapping[str, Any],
    *,
    tolerance_band_pct: Any,
    portfolio_total_inr: Any,
) -> dict[str, Any]:
    """Compare verified total-portfolio exposure with approved target weights."""
    total = _decimal(portfolio_total_inr, "portfolio_total_inr")
    tolerance = _decimal(tolerance_band_pct, "tolerance_band_pct")
    if total <= 0 or tolerance < 0:
        raise PortfolioInputError("portfolio total must be positive and tolerance non-negative")
    if set(current_values_inr) != set(target_weights_pct) or not current_values_inr:
        raise PortfolioInputError("current and target sleeves must match exactly")
    targets = {k: _decimal(v, f"target[{k}]") for k, v in target_weights_pct.items()}
    values = {k: _decimal(v, f"current[{k}]") for k, v in current_values_inr.items()}
    if any(v < 0 for v in values.values()) or any(v < 0 or v > 100 for v in targets.values()):
        raise PortfolioInputError("negative values or invalid target weights")
    if sum(targets.values()) != Decimal("100"):
        raise PortfolioInputError("approved SAA target weights must sum to 100")
    if sum(values.values()) > total:
        raise PortfolioInputError("classified sleeve values exceed reconciled portfolio total")
    current_pct = {k: values[k] / total * 100 for k in values}
    drift = {k: current_pct[k] - targets[k] for k in targets}
    return {
        "status": "CALCULATED",
        "current_weights_pct": {k: str(v) for k, v in sorted(current_pct.items())},
        "target_weights_pct": {k: str(v) for k, v in sorted(targets.items())},
        "drift_pct_points": {k: str(v) for k, v in sorted(drift.items())},
        "underweight_sleeves": sorted(k for k, v in drift.items() if v < -tolerance),
        "overweight_sleeves": sorted(k for k, v in drift.items() if v > tolerance),
        "within_tolerance_sleeves": sorted(k for k, v in drift.items() if abs(v) <= tolerance),
    }


def route_incremental_sip(
    monthly_budget_inr: Any,
    current_values_inr: Mapping[str, Any],
    target_weights_pct: Mapping[str, Any],
    *,
    portfolio_total_inr: Any,
    tolerance_band_pct: Any,
    eligible_sleeves: Iterable[str],
    rounding_increment_inr: Any = "1",
) -> dict[str, Any]:
    """Route only to eligible underweight sleeves; preserve every unfillable rupee."""
    budget = _decimal(monthly_budget_inr, "monthly_budget_inr")
    increment = _decimal(rounding_increment_inr, "rounding_increment_inr")
    if budget <= 0 or increment <= 0:
        raise PortfolioInputError("budget and rounding increment must be positive")
    drift = calculate_saa_drift(
        current_values_inr, target_weights_pct,
        tolerance_band_pct=tolerance_band_pct, portfolio_total_inr=portfolio_total_inr,
    )
    eligible = set(eligible_sleeves)
    gaps = {
        sleeve: max(Decimal("0"), -_decimal(drift["drift_pct_points"][sleeve], sleeve))
        for sleeve in target_weights_pct
    }
    gaps = {k: v for k, v in gaps.items() if v > 0 and k in eligible}
    if not gaps:
        return {"status": "HOLD", "reason": "NO_ELIGIBLE_UNDERWEIGHT_SLEEVE",
                "allocations_inr": {}, "unallocated_budget_inr": str(budget),
                "requested_budget_inr": str(budget)}
    gap_total = sum(gaps.values())
    allocations: dict[str, Decimal] = {}
    for sleeve, gap in gaps.items():
        raw = budget * gap / gap_total
        rounded = (raw / increment).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * increment
        allocations[sleeve] = min(rounded, budget)
    # Deterministic correction: rounding remainder remains unallocated, never spills
    # into a sleeve that has no verified eligibility.
    allocated = sum(allocations.values())
    if allocated > budget:
        overflow = allocated - budget
        for sleeve in sorted(allocations, reverse=True):
            reduction = min(allocations[sleeve], overflow)
            allocations[sleeve] -= reduction
            overflow -= reduction
            if overflow == 0:
                break
        allocated = sum(allocations.values())
    unallocated = budget - allocated
    return {
        "status": "ROUTED" if allocated > 0 else "HOLD",
        "allocations_inr": {k: str(v) for k, v in sorted(allocations.items()) if v > 0},
        "requested_budget_inr": str(budget),
        "allocated_budget_inr": str(allocated),
        "unallocated_budget_inr": str(unallocated),
        "reconciliation_ok": allocated + unallocated == budget,
        "basis": "PRO_RATA_TO_APPROVED_SAA_UNDERWEIGHT_GAPS",
    }


def screen_candidates_before_scoring(
    candidates: Iterable[Mapping[str, Any]],
    *,
    as_of_date: str,
    max_evidence_age_days: int,
    mandatory_gates: Iterable[str],
) -> dict[str, Any]:
    """Only fully evidenced candidates enter ranking; no score is synthesized."""
    today = _date(as_of_date, "as_of_date")
    if isinstance(max_evidence_age_days, bool) or max_evidence_age_days < 0:
        raise PortfolioInputError("max_evidence_age_days must be non-negative")
    gates = tuple(mandatory_gates)
    if not gates or len(set(gates)) != len(gates):
        raise PortfolioInputError("mandatory_gates must be non-empty and unique")
    results = []
    eligible = []
    for row in candidates:
        candidate_id = row.get("candidate_id") if isinstance(row, Mapping) else None
        reasons = []
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            candidate_id = None
            reasons.append("MISSING_CANDIDATE_ID")
        identity = row.get("scheme_identity") if isinstance(row, Mapping) else None
        if not isinstance(identity, Mapping) or not all(
            isinstance(identity.get(k), str) and identity.get(k).strip()
            for k in ("scheme_id", "isin", "plan", "option", "amc", "category", "benchmark")
        ):
            reasons.append("INCOMPLETE_EXACT_SCHEME_IDENTITY")
        evidence_date_raw = row.get("evidence_as_of_date") if isinstance(row, Mapping) else None
        try:
            evidence_date = _date(evidence_date_raw, "evidence_as_of_date")
            age = (today - evidence_date).days
            if age < 0 or age > max_evidence_age_days:
                reasons.append("EVIDENCE_STALE_OR_FUTURE")
        except PortfolioInputError:
            reasons.append("EVIDENCE_DATE_MISSING_OR_INVALID")
        evidence_ref = row.get("evidence_ref") if isinstance(row, Mapping) else None
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            reasons.append("EVIDENCE_REFERENCE_MISSING")
        gate_results = row.get("gates") if isinstance(row, Mapping) else None
        if not isinstance(gate_results, Mapping):
            reasons.append("GATE_RESULTS_MISSING")
        else:
            for gate in gates:
                if gate_results.get(gate) != "PASS":
                    reasons.append(f"GATE_NOT_PASSED:{gate}")
        status = "ELIGIBLE" if not reasons else "EVIDENCE_INSUFFICIENT_OR_INELIGIBLE"
        item = {"candidate_id": candidate_id, "status": status, "reasons": reasons}
        results.append(item)
        if status == "ELIGIBLE":
            eligible.append(candidate_id)
    return {"status": "SCREENED", "candidate_results": results,
            "eligible_candidate_ids": eligible,
            "scoring_permitted": bool(eligible)}


def calculate_lookthrough_exposure(
    holdings: Iterable[Mapping[str, Any]],
    *,
    required_coverage_pct: Any,
) -> dict[str, Any]:
    """Aggregate constituent exposure from portfolio-weighted scheme look-through."""
    required = _decimal(required_coverage_pct, "required_coverage_pct")
    if required <= 0 or required > 100:
        raise PortfolioInputError("required coverage must be in (0, 100]")
    rows = list(holdings)
    if not rows:
        return {"status": "HOLD", "reason": "NO_HOLDINGS"}
    total_value = Decimal("0")
    covered_value = Decimal("0")
    issuer_exposure: dict[str, Decimal] = {}
    for index, row in enumerate(rows):
        value = _decimal(row.get("holding_value_inr"), f"holding[{index}].value")
        if value < 0:
            raise PortfolioInputError("holding value cannot be negative")
        total_value += value
        coverage = _decimal(row.get("coverage_pct"), f"holding[{index}].coverage_pct")
        if coverage < 0 or coverage > 100:
            raise PortfolioInputError("coverage must be between 0 and 100")
        covered_value += value * coverage / 100
        constituents = row.get("constituents")
        if not isinstance(constituents, Mapping):
            raise PortfolioInputError("constituent weights missing")
        if coverage < 100 and not constituents:
            continue
        for issuer, weight_raw in constituents.items():
            if not isinstance(issuer, str) or not issuer.strip():
                raise PortfolioInputError("invalid issuer identifier")
            weight = _decimal(weight_raw, f"constituent[{issuer}]")
            if weight < 0 or weight > 100:
                raise PortfolioInputError("constituent weight must be between 0 and 100")
            issuer_exposure[issuer] = issuer_exposure.get(issuer, Decimal("0")) + value * weight / 100
    if total_value <= 0:
        raise PortfolioInputError("total holdings value must be positive")
    coverage_pct = covered_value / total_value * 100
    if coverage_pct < required:
        return {"status": "HOLD", "reason": "LOOKTHROUGH_COVERAGE_BELOW_POLICY",
                "coverage_pct": str(coverage_pct), "required_coverage_pct": str(required),
                "issuer_exposure_inr": None}
    return {"status": "CALCULATED", "coverage_pct": str(coverage_pct),
            "required_coverage_pct": str(required),
            "issuer_exposure_inr": {k: str(v) for k, v in sorted(issuer_exposure.items())}}


def build_decision_trace(record: Mapping[str, Any]) -> dict[str, str]:
    """Create deterministic content hash over an explicitly versioned decision record."""
    required = ("schema_version", "source_digests", "as_of_dates", "policy_version",
                "engine_version", "eligibility", "portfolio_effect", "allocation", "decision")
    missing = [key for key in required if key not in record]
    if missing:
        raise PortfolioInputError("decision trace missing: " + ", ".join(missing))
    def normalize(value: Any) -> Any:
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise PortfolioInputError("non-finite Decimal in trace")
            return str(value)
        if isinstance(value, Mapping):
            return {str(k): normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise PortfolioInputError("non-finite float in trace")
            return value
        raise PortfolioInputError(f"unsupported trace value: {type(value).__name__}")
    payload = json.dumps(normalize(record), sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {"algorithm": "SHA-256-CANONICAL-JSON-v1",
            "sha256": hashlib.sha256(payload).hexdigest(),
            "canonical_record": payload.decode("utf-8")}
