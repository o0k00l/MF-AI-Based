"""Fail-closed validation and attachment of fund portfolio disclosures.

This module does not download or invent AMC data. Callers must supply the
original source bytes, parsed constituent weights, stable scheme identifiers,
and reviewer attestation. Scheme-name matching is deliberately unsupported.
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional


def validate_portfolio_disclosure(
    disclosure: Dict[str, Any],
    source_bytes: bytes,
    *,
    as_of: date,
    max_age_days: int,
    trust_registry: Optional[Dict[str, Any]] = None,
    require_reviewer_signature: bool = False,
) -> Dict[str, Any]:
    """Return VERIFIED only when provenance, freshness and weight coverage pass."""
    def missing(reason: str) -> Dict[str, Any]:
        return {"status": "MISSING", "reason": reason, "constituent_weights": None,
                "constituent_weights_coverage_pct": None}

    if not isinstance(disclosure, dict) or not isinstance(source_bytes, bytes) or not source_bytes:
        return missing("Disclosure metadata or original source bytes are missing.")
    scheme_id = disclosure.get("scheme_id")
    source_url = disclosure.get("source_url")
    source_hash = disclosure.get("source_document_sha256")
    effective_raw = disclosure.get("effective_date")
    reviewer_attested = disclosure.get("reviewer_attested")
    if not isinstance(scheme_id, str) or not scheme_id.strip():
        return missing("A stable scheme identifier is required; scheme-name matching is not accepted.")
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        return missing("An HTTPS source URL is required.")
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
        return missing("A valid SHA-256 source-document hash is required.")
    actual_hash = hashlib.sha256(source_bytes).hexdigest()
    if actual_hash.lower() != source_hash.lower():
        return {"status": "CONFLICTING", "reason": "Source document SHA-256 does not match supplied bytes.",
                "constituent_weights": None, "constituent_weights_coverage_pct": None}
    if reviewer_attested is not True:
        return missing("Reviewer attestation is required before disclosure data can be used.")
    try:
        effective_date = date.fromisoformat(str(effective_raw))
    except (TypeError, ValueError):
        return missing("A valid ISO effective date is required.")
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days < 0:
        raise ValueError("max_age_days must be a non-negative integer")
    age = (as_of - effective_date).days
    if age < 0:
        return {"status": "CONFLICTING", "reason": "Disclosure effective date is after the requested as-of date.",
                "constituent_weights": None, "constituent_weights_coverage_pct": None}
    if age > max_age_days:
        return {"status": "STALE", "reason": f"Disclosure is {age} days old; configured maximum is {max_age_days} days.",
                "constituent_weights": None, "constituent_weights_coverage_pct": None}

    raw_weights = disclosure.get("constituent_weights")
    coverage_raw = disclosure.get("constituent_weights_coverage_pct")
    if not isinstance(raw_weights, dict) or not raw_weights:
        return missing("Constituent weights are absent.")
    if isinstance(coverage_raw, bool):
        return missing("Constituent coverage is absent or invalid.")
    if (
        isinstance(coverage_raw, bool)
        or not isinstance(coverage_raw, (int, float))
        or any(
            not isinstance(key, str) or not key.strip()
            or isinstance(value, bool) or not isinstance(value, (int, float))
            for key, value in raw_weights.items()
        )
    ):
        return missing("Constituent identifiers, weights or coverage are malformed.")

    normalized_keys = [key.strip().upper() for key in raw_weights]
    if len(normalized_keys) != len(set(normalized_keys)):
        return missing("Constituent identifiers are duplicated after normalization.")
    coverage = float(coverage_raw)
    weights = {
        key.strip().upper(): float(value)
        for key, value in raw_weights.items()
    }
    if (not math.isfinite(coverage) or not 99.5 <= coverage <= 100.0
            or any(not key or not math.isfinite(value) or value < 0 or value > 100
                   for key, value in weights.items())
            or not 99.5 <= sum(weights.values()) <= 100.5):
        return missing("Constituent weights must reconcile to 99.5–100.5% with at least 99.5% coverage.")

    envelope = disclosure.get("reviewer_approval_envelope")
    if require_reviewer_signature or envelope is not None or trust_registry is not None:
        if envelope is None:
            return missing("Independent reviewer approval signature is required; plain reviewer_attested boolean is withheld.")
        if trust_registry is None:
            return missing("Trust registry is required to verify independent reviewer signature.")
        from services.sip_reviewer_approval import verify_sip_reviewer_approval
        from datetime import datetime, timezone
        as_of_dt = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc)
        appr_res = verify_sip_reviewer_approval(
            envelope,
            trust_registry,
            expected_scope="SIP_PORTFOLIO_DISCLOSURE",
            expected_source_sha256=actual_hash,
            structured_records={"constituent_weights": weights, "coverage_pct": coverage},
            expected_scheme_id=scheme_id.strip(),
            now=as_of_dt,
        )
        if not appr_res.ok:
            return {
                "status": "CONFLICTING",
                "reason": f"Reviewer signature verification failed: {'; '.join(appr_res.errors)}",
                "constituent_weights": None,
                "constituent_weights_coverage_pct": None,
            }

    return {"status": "VERIFIED", "reason": "Hash, reviewer, date and constituent coverage checks passed.",
            "scheme_id": scheme_id.strip(), "effective_date": effective_date.isoformat(),
            "source_url": source_url, "source_document_sha256": actual_hash,
            "constituent_weights": weights, "constituent_weights_coverage_pct": coverage}


def attach_verified_disclosures(
    holdings: Iterable[Dict[str, Any]],
    disclosures_by_scheme_id: Dict[str, Dict[str, Any]],
    *,
    source_bytes_by_scheme_id: Dict[str, bytes],
    as_of: date,
    max_age_days: int,
) -> List[Dict[str, Any]]:
    """Attach disclosure only on exact stable scheme_id; never fuzzy-match names."""
    enriched: List[Dict[str, Any]] = []
    for original in holdings:
        holding = dict(original)
        scheme_id = holding.get("scheme_id")
        disclosure = disclosures_by_scheme_id.get(scheme_id) if isinstance(scheme_id, str) else None
        source_bytes = source_bytes_by_scheme_id.get(scheme_id) if isinstance(scheme_id, str) else None
        if disclosure is None or source_bytes is None:
            result = {"status": "MISSING", "reason": "No disclosure matched by stable scheme identifier.",
                      "constituent_weights": None, "constituent_weights_coverage_pct": None}
        else:
            result = validate_portfolio_disclosure(
                disclosure, source_bytes, as_of=as_of, max_age_days=max_age_days
            )
            if result.get("scheme_id") != scheme_id:
                result = {"status": "CONFLICTING", "reason": "Disclosure scheme identifier does not match holding.",
                          "constituent_weights": None, "constituent_weights_coverage_pct": None}
        holding.update({
            "constituent_weights": result.get("constituent_weights"),
            "constituent_weights_coverage_pct": result.get("constituent_weights_coverage_pct"),
            "lookthrough_status": result["status"],
            "lookthrough_reason": result["reason"],
            "lookthrough_effective_date": result.get("effective_date"),
            "lookthrough_source_url": result.get("source_url"),
            "lookthrough_source_document_sha256": result.get("source_document_sha256"),
        })
        enriched.append(holding)
    return enriched


def resolve_scheme_identity(
    cas_holding: Dict[str, Any],
    scheme_master: Dict[str, Any],
    *,
    source_bytes: bytes,
    trust_registry: Optional[Dict[str, Any]] = None,
    require_reviewer_signature: bool = False,
) -> Dict[str, Any]:
    """Resolve CAS identity only against a separately verified scheme master.

    Matching is exact on normalized full scheme name and AMC. No substring,
    fuzzy, category-only or display-name-only fallback is permitted.
    """
    def unresolved(reason: str) -> Dict[str, Any]:
        return {"status": "MISSING", "scheme_id": None, "isin": None, "reason": reason}

    if not isinstance(scheme_master, dict) or not isinstance(source_bytes, bytes) or not source_bytes:
        return unresolved("Verified scheme master or original source bytes are missing.")
    expected_hash = scheme_master.get("source_document_sha256")
    source_url = scheme_master.get("source_url")
    if (scheme_master.get("status") != "VERIFIED"
            or scheme_master.get("reviewer_attested") is not True
            or not isinstance(expected_hash, str)
            or hashlib.sha256(source_bytes).hexdigest().lower() != expected_hash.lower()
            or not isinstance(source_url, str) or not source_url.startswith("https://")):
        return unresolved("Scheme master provenance, hash or reviewer attestation is not verified.")
    scheme = " ".join(str(cas_holding.get("scheme") or "").casefold().split())
    amc = " ".join(str(cas_holding.get("amc_name") or "").casefold().split())
    if not scheme or not amc:
        return unresolved("CAS scheme name and AMC are both required for exact identity matching.")
    records = scheme_master.get("schemes")
    if not isinstance(records, list):
        return unresolved("Verified scheme master has no schemes list.")

    envelope = scheme_master.get("reviewer_approval_envelope")
    if require_reviewer_signature or envelope is not None or trust_registry is not None:
        if envelope is None:
            return unresolved("Independent reviewer approval signature is required; plain reviewer_attested boolean is withheld.")
        if trust_registry is None:
            return unresolved("Trust registry is required to verify independent reviewer signature.")
        from services.sip_reviewer_approval import verify_sip_reviewer_approval
        appr_res = verify_sip_reviewer_approval(
            envelope,
            trust_registry,
            expected_scope="SIP_SCHEME_MASTER",
            expected_source_sha256=expected_hash,
            structured_records=records,
        )
        if not appr_res.ok:
            return unresolved(f"Reviewer signature verification failed: {'; '.join(appr_res.errors)}")
    matches = []
    for record in records:
        if not isinstance(record, dict):
            continue
        record_scheme = " ".join(str(record.get("scheme_name") or "").casefold().split())
        record_amc = " ".join(str(record.get("amc_name") or "").casefold().split())
        if record_scheme == scheme and record_amc == amc:
            matches.append(record)
    if len(matches) != 1:
        return unresolved("Exact scheme name + AMC match is absent or ambiguous.")
    record = matches[0]
    scheme_id = record.get("scheme_id") or record.get("isin")
    isin = record.get("isin")
    if not isinstance(scheme_id, str) or not scheme_id.strip():
        return unresolved("Matched master record has no stable scheme identifier.")
    if not isinstance(isin, str) or not isin.strip():
        return unresolved("Matched master record has no ISIN; identity is not accepted.")
    raw_plan = record.get("plan_type")
    raw_option = record.get("option_type")
    raw_riskometer = record.get("riskometer_score")
    if (isinstance(raw_riskometer, bool) or not isinstance(raw_riskometer, int)
            or not 1 <= raw_riskometer <= 6):
        return unresolved("Matched scheme master record has no valid verified SEBI Riskometer score.")
    plan_map = {"direct": "DIRECT", "regular": "REGULAR"}
    option_map = {"growth": "GROWTH", "idcw": "IDCW"}
    plan_type = plan_map.get(str(raw_plan or "").strip().casefold())
    option_type = option_map.get(str(raw_option or "").strip().casefold())
    if plan_type and option_type:
        plan_option_status = "VERIFIED"
    elif raw_plan is not None or raw_option is not None:
        plan_option_status = "CONFLICTING"
    else:
        plan_option_status = "MISSING"
    return {
        "status": "VERIFIED",
        "scheme_id": scheme_id.strip(),
        "isin": isin.strip(),
        "plan_type": plan_type,
        "option_type": option_type,
        "plan_option_status": plan_option_status,
        "riskometer_score": raw_riskometer,
        "riskometer_as_of_date": scheme_master.get("effective_date"),
        "riskometer_source_url": source_url,
        "riskometer_source_document_sha256": expected_hash.lower(),
        "reason": "Exact scheme name + AMC match in verified master; plan/option and scheme Riskometer are source-bound.",
    }
