"""Fail-closed portfolio-aware SIP primitives.

These pure functions are deliberately separate from recommendation orchestration.
They do not select funds, invent policy thresholds, or authorize transactions.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_DOWN, ROUND_CEILING
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


SUPPORTED_PORTFOLIO_PERIMETER = frozenset({
    "cas_mutual_fund",
    "bank_cash",
    "deposit",
    "epf_ppf_nps",
    "direct_equity",
    "debt",
    "equity",
    "cash",
    "excluded_asset",
})


def reconcile_total_portfolio(
    assets: Iterable[Mapping[str, Any]],
    *,
    perimeter_complete: bool,
    as_of_date: str,
    excluded_assets: Iterable[Mapping[str, Any]] = (),
    unmatched_items: Iterable[Mapping[str, Any]] = (),
    sign_off: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile a declared asset perimeter; absent assets are never assumed zero.

    Each included row requires asset_id, asset_class, value_inr, source_ref,
    owner_scope and as_of_date. The caller must explicitly attest perimeter
    completeness; this helper cannot establish it from CAS alone.
    """
    valuation_date = _date(as_of_date, "as_of_date")
    rows = list(assets)
    excluded = list(excluded_assets)
    unmatched = list(unmatched_items)

    if perimeter_complete is not True:
        return {
            "status": "HOLD",
            "reason": "PORTFOLIO_PERIMETER_NOT_ATTESTED",
            "total_value_inr": None,
            "included_count": len(rows),
            "excluded_count": len(excluded),
            "unmatched_count": len(unmatched),
            "is_approved_for_sip_routing": False,
        }
    if not rows:
        return {
            "status": "HOLD",
            "reason": "NO_INCLUDED_ASSETS",
            "total_value_inr": None,
            "included_count": 0,
            "excluded_count": len(excluded),
            "unmatched_count": len(unmatched),
            "is_approved_for_sip_routing": False,
        }
    if unmatched:
        return {
            "status": "HOLD",
            "reason": "UNMATCHED_PORTFOLIO_ITEMS_PRESENT",
            "total_value_inr": None,
            "included_count": len(rows),
            "excluded_count": len(excluded),
            "unmatched_count": len(unmatched),
            "unmatched_items": unmatched,
            "is_approved_for_sip_routing": False,
        }
    if sign_off is not None:
        if not isinstance(sign_off, Mapping):
            return {
                "status": "HOLD",
                "reason": "SIGN_OFF_ATTESTATION_INVALID",
                "total_value_inr": None,
                "included_count": len(rows),
                "excluded_count": len(excluded),
                "unmatched_count": len(unmatched),
                "is_approved_for_sip_routing": False,
            }
        attested_by = sign_off.get("attested_by")
        ts = sign_off.get("attestation_timestamp_utc")
        stmt = sign_off.get("attestation_statement")
        if not (isinstance(attested_by, str) and attested_by.strip() and
                isinstance(ts, str) and ts.strip() and
                isinstance(stmt, str) and stmt.strip()):
            return {
                "status": "HOLD",
                "reason": "SIGN_OFF_ATTESTATION_INVALID",
                "total_value_inr": None,
                "included_count": len(rows),
                "excluded_count": len(excluded),
                "unmatched_count": len(unmatched),
                "is_approved_for_sip_routing": False,
            }

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
        norm_class = str(asset_class).strip().lower()
        if norm_class not in SUPPORTED_PORTFOLIO_PERIMETER:
            raise PortfolioInputError(
                f"unsupported asset class '{asset_class}'; must be one of {sorted(SUPPORTED_PORTFOLIO_PERIMETER)}"
            )
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
        by_class[norm_class] = by_class.get(norm_class, Decimal("0")) + value

    result: dict[str, Any] = {
        "status": "RECONCILED",
        "as_of_date": valuation_date.isoformat(),
        "total_value_inr": str(total),
        "included_count": len(rows),
        "excluded_count": len(excluded),
        "unmatched_count": len(unmatched),
        "by_asset_class_inr": {k: str(v) for k, v in sorted(by_class.items())},
        "excluded_assets": excluded,
        "unmatched_items": unmatched,
        "is_approved_for_sip_routing": True,
    }
    if sign_off is not None:
        result["sign_off"] = dict(sign_off)
    return result


def generate_signed_portfolio_reconciliation_report(
    assets: Iterable[Mapping[str, Any]],
    *,
    perimeter_complete: bool,
    as_of_date: str,
    sign_off: Mapping[str, Any],
    excluded_assets: Iterable[Mapping[str, Any]] = (),
    unmatched_items: Iterable[Mapping[str, Any]] = (),
    report_id: str | None = None,
) -> dict[str, Any]:
    """Generate an authoritative, signed-off portfolio reconciliation report artifact.

    Acceptance criteria for Issue #23:
    - Included and excluded assets catalog with verified source and valuation dates.
    - Zero unmatched items required for approval.
    - Denominator arithmetic reconciliation down to exact Decimal string representation.
    - Explicit fiduciary sign-off metadata (attested_by, UTC timestamp, attestation statement).
    - RFC 8785 (JCS) SHA-256 cryptographic report digest.
    """
    valuation_date = _date(as_of_date, "as_of_date")
    if not isinstance(sign_off, Mapping) or not sign_off:
        recon = {
            "status": "HOLD",
            "reason": "SIGN_OFF_ATTESTATION_REQUIRED",
            "is_approved_for_sip_routing": False,
            "total_value_inr": None,
            "included_count": len(list(assets)),
            "excluded_count": len(list(excluded_assets)),
            "unmatched_count": len(list(unmatched_items)),
        }
    else:
        recon = reconcile_total_portfolio(
            assets,
            perimeter_complete=perimeter_complete,
            as_of_date=as_of_date,
            excluded_assets=excluded_assets,
            unmatched_items=unmatched_items,
            sign_off=sign_off,
        )

    included_list = [dict(r) for r in assets]
    excluded_list = [dict(r) for r in excluded_assets]
    unmatched_list = [dict(r) for r in unmatched_items]

    rid = report_id or f"PRR-{hashlib.sha256(valuation_date.isoformat().encode('utf-8')).hexdigest()[:12].upper()}"
    report: dict[str, Any] = {
        "report_id": rid,
        "as_of_date": valuation_date.isoformat(),
        "status": recon["status"],
        "is_approved_for_sip_routing": recon.get("is_approved_for_sip_routing", False),
        "total_value_inr": recon.get("total_value_inr"),
        "included_count": recon.get("included_count", len(included_list)),
        "excluded_count": recon.get("excluded_count", len(excluded_list)),
        "unmatched_count": recon.get("unmatched_count", len(unmatched_list)),
        "by_asset_class_inr": recon.get("by_asset_class_inr", {}),
        "included_assets": included_list,
        "excluded_assets": excluded_list,
        "unmatched_items": unmatched_list,
        "sign_off": dict(sign_off) if isinstance(sign_off, Mapping) else None,
    }
    if recon.get("reason"):
        report["reason"] = recon["reason"]

    def _to_json_compat(v: Any) -> Any:
        if isinstance(v, (int, float, str, bool)) or v is None:
            return v
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, Mapping):
            return {str(k): _to_json_compat(val) for k, val in sorted(v.items())}
        if isinstance(v, (list, tuple, set)):
            return [_to_json_compat(item) for item in v]
        return str(v)

    canonical_obj = _to_json_compat(report)
    try:
        import rfc8785
        encoded = rfc8785.dumps(canonical_obj)
    except Exception:
        encoded = json.dumps(canonical_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    report["report_sha256"] = hashlib.sha256(encoded).hexdigest()
    return report


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
    """Route only each eligible sleeve's pro-rata share of total SAA gaps.

    An ineligible or unfillable underweight sleeve retains its own share of the
    requested contribution as unallocated. Its budget is never redistributed
    to a different sleeve.
    """
    budget = _decimal(monthly_budget_inr, "monthly_budget_inr")
    increment = _decimal(rounding_increment_inr, "rounding_increment_inr")
    if budget <= 0 or increment <= 0:
        raise PortfolioInputError("budget and rounding increment must be positive")
    drift = calculate_saa_drift(
        current_values_inr, target_weights_pct,
        tolerance_band_pct=tolerance_band_pct, portfolio_total_inr=portfolio_total_inr,
    )
    if isinstance(eligible_sleeves, (str, bytes)):
        raise PortfolioInputError("eligible_sleeves must be an iterable of sleeve names, not a string")
    try:
        eligible_items = list(eligible_sleeves)
    except TypeError:
        raise PortfolioInputError("eligible_sleeves must be an iterable of sleeve names") from None
    if any(not isinstance(item, str) or not item.strip() for item in eligible_items):
        raise PortfolioInputError("eligible_sleeves must contain non-empty sleeve names")
    eligible = set(eligible_items)
    unknown_eligible = eligible - set(target_weights_pct)
    if unknown_eligible:
        raise PortfolioInputError(
            "eligible_sleeves contains unknown target sleeves: "
            + ", ".join(sorted(unknown_eligible))
        )
    # Tolerance is a dead-band: a sleeve is not treated as underweight until
    # its shortfall exceeds the approved tolerance. Route only the excess gap.
    # This prevents small measurement/valuation noise from driving SIP flows.
    tolerance = _decimal(tolerance_band_pct, "tolerance_band_pct")
    all_gaps = {
        sleeve: max(
            Decimal("0"),
            -_decimal(drift["drift_pct_points"][sleeve], sleeve) - tolerance,
        )
        for sleeve in target_weights_pct
    }
    all_gaps = {key: value for key, value in all_gaps.items() if value > 0}
    eligible_gaps = {key: value for key, value in all_gaps.items() if key in eligible}
    if not all_gaps or not eligible_gaps:
        return {
            "status": "HOLD",
            "reason": "NO_ELIGIBLE_UNDERWEIGHT_SLEEVE",
            "allocations_inr": {},
            "requested_budget_inr": str(budget),
            "allocated_budget_inr": "0",
            "unallocated_budget_inr": str(budget),
            "unallocated_by_sleeve_inr": {
                key: str(budget * gap / sum(all_gaps.values()))
                for key, gap in all_gaps.items()
            } if all_gaps else {},
            "reconciliation_ok": True,
        }

    gap_total = sum(all_gaps.values(), Decimal("0"))
    allocations: dict[str, Decimal] = {}
    unallocated_by_sleeve: dict[str, Decimal] = {}
    for sleeve, gap in sorted(all_gaps.items()):
        raw = budget * gap / gap_total
        if sleeve not in eligible:
            unallocated_by_sleeve[sleeve] = raw
            continue
        rounded = (raw / increment).quantize(Decimal("1"), rounding=ROUND_DOWN) * increment
        allocations[sleeve] = rounded
        unallocated_by_sleeve[sleeve] = raw - allocations[sleeve]

    # Rounding may create fractional remainder. Never spill it into another
    # sleeve; all values remain reconciled to the original requested budget.
    allocated = sum(allocations.values(), Decimal("0"))
    unallocated = budget - allocated
    detail_total = sum(unallocated_by_sleeve.values(), Decimal("0"))
    if detail_total != unallocated:
        difference = unallocated - detail_total
        if unallocated_by_sleeve:
            final_sleeve = sorted(unallocated_by_sleeve)[-1]
            unallocated_by_sleeve[final_sleeve] += difference
        else:
            unallocated_by_sleeve["rounding_unallocated"] = difference

    # Calculate post-contribution exposure mathematically using invested portfolio denominator.
    # Unallocated contributions remain outside the invested perimeter (in cash / bank).
    port_total_dec = _decimal(portfolio_total_inr, "portfolio_total_inr")
    post_contribution_invested_total = port_total_dec + allocated
    post_contribution_perimeter_total = port_total_dec + budget
    post_contribution_values: dict[str, str] = {}
    post_contribution_weights_pct: dict[str, str] = {}
    post_contribution_drift_pct: dict[str, str] = {}
    for sleeve in target_weights_pct:
        cur_v = Decimal(str(current_values_inr.get(sleeve, "0")))
        alloc_v = allocations.get(sleeve, Decimal("0"))
        post_v = cur_v + alloc_v
        post_contribution_values[sleeve] = str(post_v)
        if post_contribution_invested_total > 0:
            post_w = (post_v / post_contribution_invested_total) * Decimal("100")
            post_contribution_weights_pct[sleeve] = str(post_w.quantize(Decimal("0.01")))
            tgt_w = _decimal(target_weights_pct[sleeve], sleeve)
            post_contribution_drift_pct[sleeve] = str((post_w - tgt_w).quantize(Decimal("0.01")))

    return {
        "status": "ROUTED" if allocated > 0 else "HOLD",
        "allocations_inr": {k: str(v) for k, v in sorted(allocations.items()) if v > 0},
        "requested_budget_inr": str(budget),
        "allocated_budget_inr": str(allocated),
        "unallocated_budget_inr": str(unallocated),
        "unallocated_by_sleeve_inr": {k: str(v) for k, v in sorted(unallocated_by_sleeve.items())},
        "post_contribution_total_inr": str(post_contribution_invested_total),
        "post_contribution_invested_total_inr": str(post_contribution_invested_total),
        "post_contribution_perimeter_total_inr": str(post_contribution_perimeter_total),
        "unallocated_cash_inr": str(unallocated),
        "post_contribution_values_inr": post_contribution_values,
        "post_contribution_weights_pct": post_contribution_weights_pct,
        "post_contribution_drift_pct": post_contribution_drift_pct,
        "reconciliation_ok": (
            allocated + unallocated == budget
            and sum(Decimal(v) for v in post_contribution_values.values()) == post_contribution_invested_total
        ),
        "basis": "PRO_RATA_TO_ALL_APPROVED_SAA_UNDERWEIGHT_GAPS_NO_REDISTRIBUTION",
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
    if (isinstance(max_evidence_age_days, bool)
            or not isinstance(max_evidence_age_days, int)
            or max_evidence_age_days < 0):
        raise PortfolioInputError("max_evidence_age_days must be a non-negative integer")
    if isinstance(mandatory_gates, (str, bytes)):
        raise PortfolioInputError("mandatory_gates must be an iterable of gate names, not a string")
    try:
        gates = tuple(mandatory_gates)
    except TypeError:
        raise PortfolioInputError("mandatory_gates must be an iterable of gate names") from None
    if (not gates or any(not isinstance(gate, str) or not gate.strip() for gate in gates)
            or len(set(gates)) != len(gates)):
        raise PortfolioInputError("mandatory_gates must contain non-empty, unique gate names")
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



def allocate_candidate_sip(
    sleeve_budgets_inr: Mapping[str, Any],
    candidates: Iterable[Mapping[str, Any]],
    *,
    as_of_date: str,
    min_sip_per_fund_inr: Any,
    rounding_increment_inr: Any,
    max_funds: int,
    max_score_age_days: int,
) -> dict[str, Any]:
    """Allocate sleeve budgets using fund-specific minimums and evidenced scores.

    Only candidates with current score provenance and cleared portfolio,
    eligibility and operational evidence can be selected. The effective minimum
    is the greater of policy and scheme minimum, rounded up to the SIP increment.
    Unfillable rupees remain in their original sleeve.
    """
    today = _date(as_of_date, "as_of_date")
    policy_minimum = _decimal(min_sip_per_fund_inr, "min_sip_per_fund_inr")
    increment = _decimal(rounding_increment_inr, "rounding_increment_inr")
    if policy_minimum <= 0 or increment <= 0:
        raise PortfolioInputError("minimum SIP and rounding increment must be positive")
    if isinstance(max_funds, bool) or not isinstance(max_funds, int) or max_funds < 0:
        raise PortfolioInputError("max_funds must be a non-negative integer")
    if isinstance(max_score_age_days, bool) or not isinstance(max_score_age_days, int) or max_score_age_days < 0:
        raise PortfolioInputError("max_score_age_days must be a non-negative integer")

    def rounded_minimum(value: Decimal) -> Decimal:
        return (value / increment).to_integral_value(rounding=ROUND_CEILING) * increment

    policy_ticket_minimum = rounded_minimum(policy_minimum)
    budgets = {str(k): _decimal(v, f"sleeve_budget[{k}]") for k, v in sleeve_budgets_inr.items()}
    if any(value < 0 for value in budgets.values()):
        raise PortfolioInputError("sleeve budgets cannot be negative")

    rows = list(candidates)
    candidate_id_counts: dict[str, int] = {}
    for row in rows:
        if isinstance(row, Mapping):
            value = row.get("candidate_id")
            if isinstance(value, str) and value.strip():
                candidate_id_counts[value] = candidate_id_counts.get(value, 0) + 1
    duplicate_candidate_ids = {
        candidate_id for candidate_id, count in candidate_id_counts.items() if count > 1
    }
    ranked: dict[str, list[tuple[Decimal, str]]] = {key: [] for key in budgets}
    required_ticket: dict[str, Decimal] = {}
    rejected: dict[str, list[str]] = {}
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise PortfolioInputError("candidate allocation rows must be mappings")
        candidate_id = row.get("candidate_id")
        sleeve = row.get("sleeve")
        reasons = []
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            reasons.append("CANDIDATE_ID_MISSING")
        elif candidate_id in duplicate_candidate_ids:
            reasons.append("DUPLICATE_CANDIDATE_ID")
        elif candidate_id in seen:
            reasons.append("DUPLICATE_CANDIDATE_ID")
        else:
            seen.add(candidate_id)
        if sleeve not in budgets:
            reasons.append("SLEEVE_NOT_ROUTED")
        if row.get("eligibility_status") != "ELIGIBLE":
            reasons.append("CANDIDATE_NOT_ELIGIBLE")
        if row.get("overlap_status") != "ASSESSED":
            reasons.append("LOOKTHROUGH_OR_CONCENTRATION_NOT_CLEARED")
        if row.get("operational_status") != "FEASIBLE_FOR_REVIEW":
            reasons.append("OPERATIONAL_FEASIBILITY_NOT_CLEARED")

        try:
            scheme_minimum = _decimal(
                row.get("minimum_monthly_sip_inr", policy_minimum),
                "candidate.minimum_monthly_sip_inr",
            )
            if scheme_minimum <= 0:
                reasons.append("SCHEME_MINIMUM_SIP_NOT_POSITIVE")
            else:
                required = rounded_minimum(max(policy_minimum, scheme_minimum))
                if isinstance(candidate_id, str) and candidate_id.strip():
                    required_ticket[candidate_id] = required
        except PortfolioInputError:
            reasons.append("SCHEME_MINIMUM_SIP_MISSING_OR_INVALID")

        score_ref = row.get("score_evidence_ref")
        if not isinstance(score_ref, str) or not score_ref.strip():
            reasons.append("RANK_SCORE_SOURCE_REFERENCE_MISSING")
        try:
            score_date = _date(row.get("score_as_of_date"), "score_as_of_date")
            if (today - score_date).days < 0 or (today - score_date).days > max_score_age_days:
                reasons.append("RANK_SCORE_STALE_OR_FUTURE")
        except PortfolioInputError:
            reasons.append("RANK_SCORE_DATE_MISSING_OR_INVALID")
        try:
            score = _decimal(row.get("rank_score"), "rank_score")
            if score <= 0:
                reasons.append("RANK_SCORE_NOT_POSITIVE")
        except PortfolioInputError:
            score = Decimal("0")
            reasons.append("RANK_SCORE_MISSING_OR_INVALID")

        if reasons:
            rejected[str(candidate_id or "UNKNOWN")] = reasons
            continue
        if required_ticket[candidate_id] > budgets[sleeve]:
            rejected[candidate_id] = ["ALLOCATED_SLEEVE_BUDGET_BELOW_EFFECTIVE_SCHEME_MINIMUM"]
            continue
        ranked[sleeve].append((score, candidate_id))

    ranked_candidates = []
    for sleeve, values in ranked.items():
        ranked_candidates.extend((sleeve, score, candidate_id) for score, candidate_id in values)
    ranked_candidates.sort(key=lambda item: (-item[1], item[0], item[2]))

    active_sleeves = [
        sleeve for sleeve, values in ranked.items()
        if any(required_ticket[candidate_id] <= budgets[sleeve] for _, candidate_id in values)
    ]
    sleeve_priority = sorted(active_sleeves, key=lambda sleeve: (-budgets[sleeve], sleeve))
    selected: list[tuple[str, Decimal, str]] = []
    selected_ids: set[str] = set()
    selected_minimum_by_sleeve = {sleeve: Decimal("0") for sleeve in budgets}

    # Reserve one viable candidate per routed sleeve first where the remaining
    # global fund cap allows; then fill remaining slots in deterministic score
    # order without exceeding each sleeve's minimum-ticket capacity.
    for sleeve in sleeve_priority:
        if len(selected) >= max_funds:
            break
        viable = sorted(
            (
                (score, candidate_id)
                for score, candidate_id in ranked[sleeve]
                if required_ticket[candidate_id] <= budgets[sleeve]
            ),
            key=lambda item: (-item[0], item[1]),
        )
        if not viable:
            continue
        score, candidate_id = viable[0]
        selected.append((sleeve, score, candidate_id))
        selected_ids.add(candidate_id)
        selected_minimum_by_sleeve[sleeve] += required_ticket[candidate_id]

    for sleeve, score, candidate_id in ranked_candidates:
        if len(selected) >= max_funds:
            break
        if candidate_id in selected_ids:
            continue
        candidate_minimum = required_ticket[candidate_id]
        if selected_minimum_by_sleeve[sleeve] + candidate_minimum > budgets[sleeve]:
            rejected[candidate_id] = ["SLEEVE_BUDGET_CANNOT_SUPPORT_SCHEME_MINIMUM"]
            continue
        selected.append((sleeve, score, candidate_id))
        selected_ids.add(candidate_id)
        selected_minimum_by_sleeve[sleeve] += candidate_minimum

    for sleeve, values in ranked.items():
        for _, candidate_id in values:
            if candidate_id not in selected_ids and candidate_id not in rejected:
                rejected[candidate_id] = ["MAX_CORE_FUND_COUNT_REACHED"]

    allocations = []
    unallocated_by_sleeve = {}
    selected_by_sleeve: dict[str, list[tuple[Decimal, str]]] = {}
    for sleeve, score, candidate_id in selected:
        selected_by_sleeve.setdefault(sleeve, []).append((score, candidate_id))

    for sleeve, budget in budgets.items():
        sleeve_rows = sorted(
            selected_by_sleeve.get(sleeve, []),
            key=lambda item: (-item[0], item[1]),
        )
        if not sleeve_rows:
            unallocated_by_sleeve[sleeve] = str(budget)
            continue
        minimums = [required_ticket[candidate_id] for _, candidate_id in sleeve_rows]
        if sum(minimums, Decimal("0")) > budget:
            unallocated_by_sleeve[sleeve] = str(budget)
            for _, candidate_id in sleeve_rows:
                rejected[candidate_id] = ["SLEEVE_BUDGET_CANNOT_SUPPORT_SCHEME_MINIMUMS"]
            continue

        score_total = sum((score for score, _ in sleeve_rows), Decimal("0"))
        remaining = budget
        sleeve_allocations = []
        for index, (score, candidate_id) in enumerate(sleeve_rows):
            minimum = required_ticket[candidate_id]
            if index == len(sleeve_rows) - 1:
                amount = (remaining / increment).to_integral_value(rounding=ROUND_DOWN) * increment
            else:
                raw = budget * score / score_total
                amount = (raw / increment).to_integral_value(rounding=ROUND_DOWN) * increment
                amount = max(minimum, amount)
                minimum_for_rest = sum(
                    (required_ticket[other_id] for _, other_id in sleeve_rows[index + 1:]),
                    Decimal("0"),
                )
                maximum_now = remaining - minimum_for_rest
                maximum_now = (maximum_now / increment).to_integral_value(rounding=ROUND_DOWN) * increment
                amount = min(amount, maximum_now)
            if amount < minimum:
                sleeve_allocations = []
                break
            sleeve_allocations.append((candidate_id, amount))
            remaining -= amount

        if not sleeve_allocations:
            unallocated_by_sleeve[sleeve] = str(budget)
            for _, candidate_id in sleeve_rows:
                rejected[candidate_id] = ["ROUNDED_ALLOCATION_BELOW_SCHEME_MINIMUM"]
            continue
        for candidate_id, amount in sleeve_allocations:
            allocations.append({
                "candidate_id": candidate_id,
                "sleeve": sleeve,
                "monthly_sip_inr": str(amount),
                "scheme_minimum_monthly_sip_inr": str(required_ticket[candidate_id]),
            })
        unallocated_by_sleeve[sleeve] = str(remaining)

    requested = sum(budgets.values(), Decimal("0"))
    allocated = sum(
        (_decimal(item["monthly_sip_inr"], "allocation") for item in allocations),
        Decimal("0"),
    )
    unallocated = sum(
        (_decimal(value, "unallocated") for value in unallocated_by_sleeve.values()),
        Decimal("0"),
    )
    return {
        "status": "ALLOCATED" if allocated > 0 else "HOLD",
        "allocations": allocations,
        "rejected_candidates": rejected,
        "requested_budget_inr": str(requested),
        "allocated_budget_inr": str(allocated),
        "unallocated_budget_inr": str(unallocated),
        "unallocated_by_sleeve_inr": unallocated_by_sleeve,
        "reconciliation_ok": allocated + unallocated == requested,
        "ranking_basis": "SOURCE_REFERENCED_RANK_SCORE_DESCENDING",
    }


def calculate_lookthrough_exposure(
    holdings: Iterable[Mapping[str, Any]],
    *,
    required_coverage_pct: Any,
    security_master: Optional[Mapping[str, Any]] = None,
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
        disclosed_weight_total = Decimal("0")
        from core.security_master import normalize_security_identifier
        for issuer, weight_raw in constituents.items():
            if not isinstance(issuer, str) or not issuer.strip():
                raise PortfolioInputError("invalid issuer identifier")
            canon_issuer, is_resolved = normalize_security_identifier(issuer, security_master=security_master)
            if security_master is not None and not is_resolved:
                return {
                    "status": "HOLD",
                    "reason": f"LOOKTHROUGH_INCOMPLETE_OR_UNRESOLVED:{issuer}",
                    "unresolved_issuer": issuer,
                    "issuer_exposure_inr": None,
                }
            weight = _decimal(weight_raw, f"constituent[{issuer}]")
            if weight < 0 or weight > 100:
                raise PortfolioInputError("constituent weight must be between 0 and 100")
            disclosed_weight_total += weight
            issuer_exposure[canon_issuer] = issuer_exposure.get(canon_issuer, Decimal("0")) + value * weight / 100
        if coverage >= required and abs(disclosed_weight_total - Decimal("100")) > Decimal("0.5"):
            raise PortfolioInputError("constituent weights do not reconcile to reported coverage")
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



def evaluate_classified_concentration(
    issuer_exposure_inr: Mapping[str, Any],
    classifications: Mapping[str, Any],
    *,
    total_portfolio_inr: Any,
    as_of_date: str,
    classification_as_of_date: str,
    classification_source_ref: str,
    max_evidence_age_days: int,
    max_sector_pct: Any,
    max_market_cap_pct: Any,
    max_theme_pct: Any,
) -> dict[str, Any]:
    """Evaluate sector, market-cap and theme exposure using dated issuer classifications."""
    today = _date(as_of_date, "as_of_date")
    class_date = _date(classification_as_of_date, "classification_as_of_date")
    if class_date > today or (today - class_date).days > max_evidence_age_days:
        return {"status": "HOLD", "reason": "ISSUER_CLASSIFICATION_STALE_OR_FUTURE"}
    if not isinstance(classification_source_ref, str) or not classification_source_ref.strip():
        return {"status": "HOLD", "reason": "ISSUER_CLASSIFICATION_SOURCE_REFERENCE_MISSING"}
    total = _decimal(total_portfolio_inr, "total_portfolio_inr")
    limits = {
        "sector": _decimal(max_sector_pct, "max_sector_pct"),
        "market_cap": _decimal(max_market_cap_pct, "max_market_cap_pct"),
        "theme": _decimal(max_theme_pct, "max_theme_pct"),
    }
    if total <= 0 or any(value <= 0 or value > 100 for value in limits.values()):
        raise PortfolioInputError("portfolio total and concentration limits must be positive and bounded by 100")
    if not isinstance(classifications, Mapping):
        raise PortfolioInputError("issuer classifications must be a mapping")
    aggregates = {
        "sector": {},
        "market_cap": {},
        "theme": {},
    }
    missing = []
    normalized_issuer_values = {}
    for issuer, raw_value in issuer_exposure_inr.items():
        if not isinstance(issuer, str) or not issuer.strip():
            raise PortfolioInputError("issuer exposure keys must be stable identifiers")
        value = _decimal(raw_value, f"issuer_exposure[{issuer}]")
        if value < 0:
            raise PortfolioInputError("issuer exposures cannot be negative")
        normalized_issuer_values[issuer] = value
        facts = classifications.get(issuer)
        if not isinstance(facts, Mapping):
            missing.append(issuer)
            continue
        sector = facts.get("sector")
        market_cap = facts.get("market_cap_bucket")
        themes = facts.get("themes")
        if not isinstance(sector, str) or not sector.strip():
            missing.append(issuer)
            continue
        if not isinstance(market_cap, str) or not market_cap.strip():
            missing.append(issuer)
            continue
        if not isinstance(themes, list) or any(not isinstance(item, str) or not item.strip() for item in themes):
            missing.append(issuer)
            continue
        aggregates["sector"][sector] = aggregates["sector"].get(sector, Decimal("0")) + value
        aggregates["market_cap"][market_cap] = aggregates["market_cap"].get(market_cap, Decimal("0")) + value
        for theme in set(themes):
            aggregates["theme"][theme] = aggregates["theme"].get(theme, Decimal("0")) + value
    if missing:
        return {
            "status": "HOLD",
            "reason": "ISSUER_CLASSIFICATION_MISSING_OR_INVALID",
            "unclassified_issuers": sorted(set(missing)),
            "source_ref": classification_source_ref,
        }
    percentages = {
        dimension: {key: value / total * 100 for key, value in sorted(values.items())}
        for dimension, values in aggregates.items()
    }
    breaches = {
        dimension: {
            key: str(pct)
            for key, pct in values.items()
            if pct > limits[dimension]
        }
        for dimension, values in percentages.items()
    }
    breaches = {key: value for key, value in breaches.items() if value}
    return {
        "status": "HOLD" if breaches else "ASSESSED",
        "as_of_date": class_date.isoformat(),
        "source_ref": classification_source_ref,
        "limits_pct": {key: str(value) for key, value in limits.items()},
        "exposure_pct": {
            dimension: {key: str(pct) for key, pct in values.items()}
            for dimension, values in percentages.items()
        },
        "breaches": breaches,
    }


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


def validate_goal_mandate(
    goals: Iterable[Mapping[str, Any]],
    *,
    as_of_date: str,
    max_evidence_age_days: int,
    minimum_horizon_days_by_asset_class: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate goal evidence, priority, earmarks and compare horizons with caller-approved constraints.

    Issue #30: Enforces versioned goal contract, explicit priority, near-term liquidity needs,
    and prevents double-counting of earmarked assets across multiple goals.
    """
    today = _date(as_of_date, "as_of_date")
    if not minimum_horizon_days_by_asset_class:
        raise PortfolioInputError("approved minimum horizon policy is required")
    minimums = {k: _decimal(v, f"minimum_horizon[{k}]")
                for k, v in minimum_horizon_days_by_asset_class.items()}
    if any(v < 0 for v in minimums.values()):
        raise PortfolioInputError("minimum horizons cannot be negative")
    results = []
    seen_earmarked_assets: dict[str, str] = {}
    double_counted_assets = set()

    for index, goal in enumerate(goals):
        reasons = []
        if not isinstance(goal, Mapping):
            raise PortfolioInputError(f"goal row {index} must be an object")
        goal_id = goal.get("goal_id")
        if not isinstance(goal_id, str) or not goal_id.strip():
            reasons.append("GOAL_ID_MISSING")

        schema_version = goal.get("schema_version")
        if schema_version is not None and schema_version != "goal_mandate.v1":
            reasons.append("GOAL_SCHEMA_VERSION_INVALID")

        if "priority" in goal:
            priority = goal.get("priority")
            if isinstance(priority, bool) or not (isinstance(priority, (int, str)) and str(priority).strip()):
                reasons.append("GOAL_PRIORITY_INVALID")

        if "liquidity_needs_inr" in goal:
            try:
                liq_val = _decimal(goal.get("liquidity_needs_inr"), "goal.liquidity_needs_inr")
                if liq_val < 0:
                    reasons.append("GOAL_LIQUIDITY_NEEDS_NEGATIVE")
            except PortfolioInputError:
                reasons.append("GOAL_LIQUIDITY_NEEDS_INVALID")

        # Multi-goal earmarked asset double counting detection
        earmarked = goal.get("earmarked_assets")
        allow_shared = goal.get("allow_shared_earmark") is True
        if earmarked is not None:
            if not isinstance(earmarked, (list, tuple)) or any(not isinstance(a, str) or not a.strip() for a in earmarked):
                reasons.append("GOAL_EARMARKED_ASSETS_INVALID")
            elif not allow_shared:
                for asset_id in earmarked:
                    aid = str(asset_id).strip()
                    if aid in seen_earmarked_assets and seen_earmarked_assets[aid] != goal_id:
                        double_counted_assets.add(aid)
                        reasons.append(f"EARMARKED_ASSET_DOUBLE_COUNTED:{aid}")
                    else:
                        seen_earmarked_assets[aid] = str(goal_id)

        if goal.get("mandate_approved") is not True:
            reasons.append("GOAL_MANDATE_NOT_APPROVED")
        if not isinstance(goal.get("source_ref"), str) or not goal.get("source_ref", "").strip():
            reasons.append("GOAL_SOURCE_REFERENCE_MISSING")
        try:
            evidence_date = _date(goal.get("evidence_as_of_date"), "goal.evidence_as_of_date")
            age = (today - evidence_date).days
            if age < 0 or age > max_evidence_age_days:
                reasons.append("GOAL_EVIDENCE_STALE_OR_FUTURE")
        except PortfolioInputError:
            reasons.append("GOAL_EVIDENCE_DATE_INVALID")
        try:
            target_value = _decimal(goal.get("target_amount_inr"), "goal.target_amount_inr")
            if target_value <= 0:
                reasons.append("GOAL_TARGET_NOT_POSITIVE")
        except PortfolioInputError:
            reasons.append("GOAL_TARGET_MISSING_OR_INVALID")
        try:
            _decimal(goal.get("liabilities_inr"), "goal.liabilities_inr")
            if _decimal(goal.get("liabilities_inr"), "goal.liabilities_inr") < 0:
                reasons.append("GOAL_LIABILITIES_NEGATIVE")
        except PortfolioInputError:
            reasons.append("GOAL_LIABILITIES_MISSING_OR_INVALID")
        try:
            target_date = _date(goal.get("target_date"), "goal.target_date")
            horizon_days = (target_date - today).days
            if horizon_days < 0:
                reasons.append("GOAL_TARGET_DATE_PASSED")
        except PortfolioInputError:
            horizon_days = None
            reasons.append("GOAL_TARGET_DATE_INVALID")
        asset_class = goal.get("asset_class")
        if asset_class not in minimums:
            reasons.append("NO_APPROVED_HORIZON_POLICY_FOR_ASSET_CLASS")
        elif horizon_days is not None and Decimal(horizon_days) < minimums[asset_class]:
            reasons.append("GOAL_HORIZON_BELOW_APPROVED_MINIMUM")
        if not isinstance(goal.get("approved_risk_profile"), str) or not goal.get("approved_risk_profile", "").strip():
            reasons.append("APPROVED_RISK_PROFILE_MISSING")
        results.append({"goal_id": goal_id, "status": "VALID" if not reasons else "HOLD",
                        "horizon_days": horizon_days, "reasons": reasons})
    if not results:
        return {"status": "HOLD", "reason": "NO_GOALS_SUPPLIED", "goals": []}
    return {
        "status": "VALIDATED" if all(x["status"] == "VALID" for x in results) else "HOLD",
        "goals": results,
        "double_counted_assets": sorted(double_counted_assets),
    }


def assess_liquidity_and_sip_surplus(
    *,
    verified_cash_inr: Any,
    approved_reserve_target_inr: Any,
    near_term_obligations_inr: Any,
    monthly_net_income_inr: Any,
    essential_monthly_expenses_inr: Any,
    monthly_debt_service_inr: Any,
    proposed_monthly_sip_inr: Any,
    evidence_refs: Mapping[str, str],
    as_of_date: str,
    max_evidence_age_days: int,
) -> dict[str, Any]:
    """Calculate investible cash and sustainable monthly surplus from sourced facts."""
    today = _date(as_of_date, "as_of_date")
    required = ("cash", "reserve", "obligations", "income", "expenses", "debt_service")
    if any(not isinstance(evidence_refs.get(k), str) or not evidence_refs[k].strip()
           for k in required):
        return {"status": "HOLD", "reason": "LIQUIDITY_EVIDENCE_REFERENCE_MISSING",
                "deployable_cash_inr": None, "sustainable_monthly_sip_inr": None}
    raw_dates = evidence_refs.get("as_of_dates")
    if not isinstance(raw_dates, Mapping):
        return {"status": "HOLD", "reason": "LIQUIDITY_AS_OF_DATES_MISSING",
                "deployable_cash_inr": None, "sustainable_monthly_sip_inr": None}
    for key in required:
        try:
            evidence_date = _date(raw_dates.get(key), f"as_of_dates.{key}")
        except PortfolioInputError:
            return {"status": "HOLD", "reason": "LIQUIDITY_AS_OF_DATE_INVALID",
                    "deployable_cash_inr": None, "sustainable_monthly_sip_inr": None}
        age = (today - evidence_date).days
        if age < 0 or age > max_evidence_age_days:
            return {"status": "HOLD", "reason": "LIQUIDITY_EVIDENCE_STALE_OR_FUTURE",
                    "deployable_cash_inr": None, "sustainable_monthly_sip_inr": None}
    cash = _decimal(verified_cash_inr, "verified_cash_inr")
    reserve = _decimal(approved_reserve_target_inr, "approved_reserve_target_inr")
    obligations = _decimal(near_term_obligations_inr, "near_term_obligations_inr")
    income = _decimal(monthly_net_income_inr, "monthly_net_income_inr")
    expenses = _decimal(essential_monthly_expenses_inr, "essential_monthly_expenses_inr")
    debt = _decimal(monthly_debt_service_inr, "monthly_debt_service_inr")
    proposed = _decimal(proposed_monthly_sip_inr, "proposed_monthly_sip_inr")
    if any(v < 0 for v in (cash, reserve, obligations, income, expenses, debt, proposed)):
        raise PortfolioInputError("liquidity and affordability amounts cannot be negative")
    deployable = max(Decimal("0"), cash - reserve - obligations)
    monthly_surplus = max(Decimal("0"), income - expenses - debt)
    # Cash reserve adequacy and recurring monthly affordability are distinct:
    # do not cap a monthly SIP by a one-time cash stock.
    if cash < reserve + obligations:
        return {"status": "HOLD", "reason": "VERIFIED_CASH_BELOW_RESERVE_AND_OBLIGATIONS",
                "deployable_cash_inr": str(deployable),
                "monthly_surplus_inr": str(monthly_surplus),
                "sustainable_monthly_sip_inr": "0",
                "proposed_monthly_sip_inr": str(proposed)}
    sustainable = monthly_surplus
    if proposed > sustainable:
        return {"status": "HOLD", "reason": "PROPOSED_SIP_EXCEEDS_VERIFIED_SURPLUS",
                "deployable_cash_inr": str(deployable),
                "monthly_surplus_inr": str(monthly_surplus),
                "sustainable_monthly_sip_inr": str(sustainable),
                "proposed_monthly_sip_inr": str(proposed)}
    return {"status": "AFFORDABLE", "deployable_cash_inr": str(deployable),
            "monthly_surplus_inr": str(monthly_surplus),
            "sustainable_monthly_sip_inr": str(sustainable),
            "proposed_monthly_sip_inr": str(proposed)}


def stress_test_sip_affordability(
    *,
    monthly_net_income_inr: Any,
    essential_monthly_expenses_inr: Any,
    monthly_debt_service_inr: Any,
    proposed_monthly_sip_inr: Any,
    scenarios: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate explicitly supplied income/expense shocks; scenarios are not forecasts."""
    income = _decimal(monthly_net_income_inr, "monthly_net_income_inr")
    expenses = _decimal(essential_monthly_expenses_inr, "essential_monthly_expenses_inr")
    debt = _decimal(monthly_debt_service_inr, "monthly_debt_service_inr")
    sip = _decimal(proposed_monthly_sip_inr, "proposed_monthly_sip_inr")
    if any(v < 0 for v in (income, expenses, debt, sip)):
        raise PortfolioInputError("affordability amounts cannot be negative")
    results = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, Mapping):
            raise PortfolioInputError(f"scenario {index} must be an object")
        income_shock = _decimal(scenario.get("income_reduction_pct"), "income_reduction_pct")
        expense_shock = _decimal(scenario.get("expense_increase_pct"), "expense_increase_pct")
        if not (0 <= income_shock <= 100 and expense_shock >= 0):
            raise PortfolioInputError("invalid affordability stress percentages")
        stressed_income = income * (100 - income_shock) / 100
        stressed_expenses = expenses * (100 + expense_shock) / 100
        surplus = stressed_income - stressed_expenses - debt
        results.append({"scenario_id": scenario.get("scenario_id"),
                        "stressed_monthly_surplus_inr": str(surplus),
                        "status": "SUSTAINABLE" if surplus >= sip else "UNSUSTAINABLE"})
    return {"status": "ASSESSED",
            "all_scenarios_sustainable": bool(results) and all(
                item["status"] == "SUSTAINABLE" for item in results),
            "scenarios": results}


def validate_scheme_operational_feasibility(
    scheme: Mapping[str, Any],
    *,
    requested_monthly_sip_inr: Any,
    as_of_date: str,
    max_evidence_age_days: int,
    check_requested_minimum: bool = True,
) -> dict[str, Any]:
    """Validate dated scheme status and SIP constraints without implying execution."""
    today = _date(as_of_date, "as_of_date")
    reasons = []
    identity = scheme.get("scheme_identity")
    if not isinstance(identity, Mapping) or not all(
        isinstance(identity.get(k), str) and identity.get(k).strip()
        for k in ("scheme_id", "isin", "plan", "option", "amc")
    ):
        reasons.append("EXACT_SCHEME_IDENTITY_INCOMPLETE")
    if not isinstance(scheme.get("evidence_ref"), str) or not scheme.get("evidence_ref", "").strip():
        reasons.append("OPERATIONAL_EVIDENCE_REFERENCE_MISSING")
    try:
        evidence_date = _date(scheme.get("evidence_as_of_date"), "evidence_as_of_date")
        age = (today - evidence_date).days
        if age < 0 or age > max_evidence_age_days:
            reasons.append("OPERATIONAL_EVIDENCE_STALE_OR_FUTURE")
    except PortfolioInputError:
        reasons.append("OPERATIONAL_EVIDENCE_DATE_INVALID")
    if scheme.get("scheme_status") != "ACTIVE":
        reasons.append("SCHEME_NOT_CONFIRMED_ACTIVE")
    requested = _decimal(requested_monthly_sip_inr, "requested_monthly_sip_inr")
    minimum = _decimal(scheme.get("minimum_monthly_sip_inr"), "minimum_monthly_sip_inr")
    if requested <= 0 or minimum <= 0:
        reasons.append("INVALID_SIP_MINIMUM_OR_REQUEST")
    elif check_requested_minimum and requested < minimum:
        reasons.append("REQUEST_BELOW_SCHEME_MINIMUM")
    for key in ("exit_load_evidence_ref", "lockin_evidence_ref", "subscription_status_evidence_ref"):
        if not isinstance(scheme.get(key), str) or not scheme.get(key, "").strip():
            reasons.append(f"MISSING_{key.upper()}")
    return {"status": "FEASIBLE_FOR_REVIEW" if not reasons else "HOLD",
            "reasons": reasons, "minimum_monthly_sip_inr": str(minimum),
            "execution_authorized": False}


def evaluate_recommendation_freshness(
    *,
    recommendation_as_of_date: str,
    current_as_of_date: str,
    max_age_days: int,
    event_flags: Mapping[str, Any],
) -> dict[str, Any]:
    """Flag expired or event-invalidated recommendations; never mutate a SIP."""
    original = _date(recommendation_as_of_date, "recommendation_as_of_date")
    current = _date(current_as_of_date, "current_as_of_date")
    if current < original:
        raise PortfolioInputError("current review date cannot precede recommendation date")
    if isinstance(max_age_days, bool) or max_age_days < 0:
        raise PortfolioInputError("max_age_days must be non-negative")
    age = (current - original).days
    triggered = sorted(str(k) for k, value in event_flags.items() if value is True)
    reasons = []
    if age > max_age_days:
        reasons.append("RECOMMENDATION_EXPIRED")
    if triggered:
        reasons.append("MATERIAL_REVIEW_EVENT:" + ",".join(triggered))
    return {"status": "REVIEW_REQUIRED" if reasons else "CURRENT",
            "age_days": age, "reasons": reasons,
            "execution_authorized": False}


def transition_recommendation_lifecycle(
    *,
    current_state: str,
    requested_state: str,
    decision_trace_sha256: str,
    author_id: str,
    reviewer_id: str | None = None,
) -> dict[str, Any]:
    """Enforce a monotonic review state machine with independent reviewer separation."""
    allowed = {
        "DRAFT": {"REVIEWED", "WITHDRAWN"},
        "REVIEWED": {"SUPERSEDED", "WITHDRAWN"},
        "SUPERSEDED": set(),
        "WITHDRAWN": set(),
    }
    if current_state not in allowed or requested_state not in allowed:
        raise PortfolioInputError("unknown recommendation lifecycle state")
    if requested_state not in allowed[current_state]:
        raise PortfolioInputError("invalid or non-monotonic lifecycle transition")
    if not isinstance(decision_trace_sha256, str) or len(decision_trace_sha256) != 64:
        raise PortfolioInputError("a SHA-256 decision trace is required")
    try:
        int(decision_trace_sha256, 16)
    except ValueError:
        raise PortfolioInputError("decision trace must be hexadecimal SHA-256") from None
    if requested_state == "REVIEWED":
        if not isinstance(author_id, str) or not author_id.strip():
            raise PortfolioInputError("author identity is required")
        if not isinstance(reviewer_id, str) or not reviewer_id.strip() or reviewer_id == author_id:
            raise PortfolioInputError("independent reviewer identity is required")
    return {"previous_state": current_state, "state": requested_state,
            "decision_trace_sha256": decision_trace_sha256,
            "execution_authorized": False}


def _validate_new_fund_limit(
    recommendations: list[dict[str, Any]],
    sip_policy: dict[str, Any],
    portfolio_introduction_history: dict[str, Any] | None = None,
    existing_schemes: list[Any] | None = None,
    is_starter: bool = False,
) -> list[str]:
    """Validate the 12-month new fund limit for proposed SIP allocations.

    Returns a list of violation messages; empty list means compliant.
    Fail-closed: missing history or policy misconfiguration returns violations.

    Issue #4: Enforces max_new_funds_per_12_months policy to prevent
    excessive scheme introduction within a 12-month window.
    """
    from core.math_engine import _sip_operational_constraint_violations

    # Convert recommendations to DeterministicSIPRecommendation objects if needed
    from core.models import DeterministicSIPRecommendation
    items = []
    for rec in recommendations:
        if isinstance(rec, DeterministicSIPRecommendation):
            items.append(rec)
        elif isinstance(rec, dict):
            items.append(DeterministicSIPRecommendation(
                category_role=rec.get("category_role", ""),
                scheme_name=rec.get("scheme_name", ""),
                monthly_inr=float(rec.get("monthly_inr", 0)),
                allocation_pct=float(rec.get("allocation_pct", 0)),
                rational_code=rec.get("rational_code", ""),
                fiduciary_rationale=rec.get("fiduciary_rationale", ""),
            ))

    violations = _sip_operational_constraint_violations(
        items,
        sip_policy,
        portfolio_introduction_history=portfolio_introduction_history,
        existing_schemes=existing_schemes or [],
        is_starter=is_starter,
    )

    # Filter to only return new-fund-related violations
    new_fund_violations = [
        v for v in violations
        if "new fund" in v.lower() or "12-month" in v.lower()
    ]
    return new_fund_violations
