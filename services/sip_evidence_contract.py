"""Structural and provenance contract for injected SIP evidence providers.

Validation here is a gate, not an investment recommendation. Local hashes and
reviewer attestations do not independently authenticate a publisher.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any


REQUIRED_EVIDENCE_FIELDS = frozenset({
    "metrics_path",
    "aliases_path",
    "scheme_master",
    "scheme_master_source_bytes",
    "portfolio_disclosures_by_scheme_id",
    "portfolio_disclosure_source_bytes_by_scheme_id",
    "disclosure_as_of_date",
    "candidate_universe",
    "candidate_universe_source",
    "candidate_universe_source_bytes",
})
REQUEST_BOUND_FIELDS = frozenset({"cas_path", "monthly_budget_inr", "risk_profile"})
OPTIONAL_EVIDENCE_FIELDS = frozenset({"metrics_source_metadata", "metrics_source_bytes", "portfolio_context", "portfolio_context_source_metadata", "portfolio_context_source_bytes"})


class EvidenceProviderContractError(ValueError):
    """Raised when a provider response violates the structural contract."""


def _validate_source_document(metadata: Any, source_bytes: Any, *, label: str, as_of: date) -> None:
    if not isinstance(metadata, dict):
        raise EvidenceProviderContractError(f"{label} source metadata must be a mapping.")
    if not isinstance(source_bytes, bytes) or not source_bytes:
        raise EvidenceProviderContractError(f"{label} original source bytes must be non-empty bytes.")

    source_url = metadata.get("source_url")
    declared_hash = metadata.get("source_document_sha256")
    if not isinstance(source_url, str) or not re.fullmatch(r"https://\S+", source_url):
        raise EvidenceProviderContractError(f"{label} source URL must be HTTPS.")
    if not isinstance(declared_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", declared_hash):
        raise EvidenceProviderContractError(f"{label} source SHA-256 must be 64 hexadecimal characters.")
    actual_hash = hashlib.sha256(source_bytes).hexdigest()
    if actual_hash != declared_hash.lower():
        raise EvidenceProviderContractError(f"{label} source SHA-256 does not match original bytes.")
    if metadata.get("reviewer_attested") is not True:
        raise EvidenceProviderContractError(f"{label} requires explicit reviewer attestation.")

    effective_raw = metadata.get("effective_date")
    try:
        effective = date.fromisoformat(effective_raw) if isinstance(effective_raw, str) else None
    except ValueError:
        effective = None
    if effective is None:
        raise EvidenceProviderContractError(f"{label} effective_date must be an ISO date.")
    if effective > as_of:
        raise EvidenceProviderContractError(f"{label} effective_date is after the decision as-of date.")
    age_days = (as_of - effective).days
    if age_days > 45:
        raise EvidenceProviderContractError(f"{label} source is stale ({age_days} days; maximum 45).")

    source_type = metadata.get("source_type")
    if not isinstance(source_type, str) or not source_type.strip():
        raise EvidenceProviderContractError(f"{label} source_type is required.")


def _validate_scheme_master(master: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(master, dict) or master.get("status") != "VERIFIED":
        raise EvidenceProviderContractError("Scheme master must explicitly carry VERIFIED status.")
    schemes = master.get("schemes")
    if not isinstance(schemes, list) or not schemes:
        raise EvidenceProviderContractError("Verified scheme master must contain a non-empty schemes list.")

    by_scheme_id: dict[str, dict[str, Any]] = {}
    by_isin: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(schemes):
        if not isinstance(record, dict):
            raise EvidenceProviderContractError(f"Scheme master row {index} must be a mapping.")
        scheme_id, isin = record.get("scheme_id"), record.get("isin")
        if not isinstance(scheme_id, str) or not scheme_id.strip():
            raise EvidenceProviderContractError(f"Scheme master row {index} has no stable scheme_id.")
        if not isinstance(isin, str) or not isin.strip():
            raise EvidenceProviderContractError(f"Scheme master row {index} has no ISIN.")
        if scheme_id in by_scheme_id or isin in by_isin:
            raise EvidenceProviderContractError("Scheme master contains duplicate scheme_id or ISIN records.")
        if not all(isinstance(record.get(key), str) and record[key].strip()
                   for key in ("scheme_name", "amc_name")):
            raise EvidenceProviderContractError(f"Scheme master row {index} lacks exact scheme_name or amc_name.")
        by_scheme_id[scheme_id] = record
        by_isin[isin] = record
    return by_scheme_id


def validate_evidence_provider_payload(payload: Any) -> dict[str, Any]:
    """Validate provider shape and critical source provenance before engine use."""
    if not isinstance(payload, dict):
        raise EvidenceProviderContractError("Provider response must be a mapping.")

    supplied = set(payload)
    missing = REQUIRED_EVIDENCE_FIELDS - supplied
    unexpected = supplied - REQUIRED_EVIDENCE_FIELDS - OPTIONAL_EVIDENCE_FIELDS
    optional_present = supplied & OPTIONAL_EVIDENCE_FIELDS
    portfolio_context_fields = {
        "portfolio_context", "portfolio_context_source_metadata",
        "portfolio_context_source_bytes",
    }
    portfolio_context_present = supplied & portfolio_context_fields
    if portfolio_context_present and portfolio_context_present != portfolio_context_fields:
        raise EvidenceProviderContractError(
            "Portfolio context, source metadata and original source bytes must be supplied together."
        )
    if missing:
        raise EvidenceProviderContractError(
            "Provider response is missing required fields: " + ", ".join(sorted(missing))
        )
    if unexpected:
        raise EvidenceProviderContractError(
            "Provider response contains unsupported fields: " + ", ".join(sorted(unexpected))
        )
    if optional_present and optional_present != OPTIONAL_EVIDENCE_FIELDS:
        raise EvidenceProviderContractError(
            "Metrics source metadata and original source bytes must be supplied together."
        )

    as_of = payload["disclosure_as_of_date"]
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise EvidenceProviderContractError("disclosure_as_of_date must be a date, not a timestamp or string.")

    _validate_source_document(
        payload["scheme_master"], payload["scheme_master_source_bytes"],
        label="Scheme master", as_of=as_of,
    )
    if {"metrics_source_metadata", "metrics_source_bytes"} <= optional_present:
        _validate_source_document(
            payload["metrics_source_metadata"], payload["metrics_source_bytes"],
            label="Fund metrics", as_of=as_of,
        )
    if portfolio_context_present:
        if not isinstance(payload["portfolio_context"], dict):
            raise EvidenceProviderContractError("portfolio_context must be a mapping.")
        _validate_source_document(
            payload["portfolio_context_source_metadata"],
            payload["portfolio_context_source_bytes"],
            label="Total portfolio context", as_of=as_of,
        )
    scheme_index = _validate_scheme_master(payload["scheme_master"])

    disclosures = payload["portfolio_disclosures_by_scheme_id"]
    disclosure_bytes = payload["portfolio_disclosure_source_bytes_by_scheme_id"]
    if not isinstance(disclosures, dict) or not isinstance(disclosure_bytes, dict):
        raise EvidenceProviderContractError("Disclosure records and source bytes must be mappings.")
    if set(disclosures) != set(disclosure_bytes):
        raise EvidenceProviderContractError(
            "Disclosure records and source bytes must have identical scheme-ID keys."
        )
    for scheme_id, record in disclosures.items():
        if not isinstance(scheme_id, str) or not scheme_id.strip():
            raise EvidenceProviderContractError("Disclosure keys must be non-empty stable scheme IDs.")
        if scheme_id not in scheme_index:
            raise EvidenceProviderContractError(f"Disclosure scheme ID {scheme_id!r} is absent from verified scheme master.")
        if not isinstance(record, dict) or record.get("scheme_id") != scheme_id:
            raise EvidenceProviderContractError(f"Disclosure record for {scheme_id!r} has conflicting scheme identity.")
        raw = disclosure_bytes[scheme_id]
        if not isinstance(raw, bytes) or not raw:
            raise EvidenceProviderContractError(f"Original source bytes for {scheme_id!r} are missing.")

    candidates = payload["candidate_universe"]
    if not isinstance(candidates, list) or not candidates:
        raise EvidenceProviderContractError("candidate_universe must be a non-empty list.")
    candidate_source = payload["candidate_universe_source"]
    _validate_source_document(
        candidate_source, payload["candidate_universe_source_bytes"],
        label="Candidate universe", as_of=as_of,
    )
    if candidate_source.get("universe_complete") is not True:
        raise EvidenceProviderContractError("Candidate universe must be explicitly reviewer-attested as complete.")
    if not isinstance(candidate_source.get("coverage_scope"), str) or not candidate_source["coverage_scope"].strip():
        raise EvidenceProviderContractError("Candidate universe coverage_scope must identify the covered market/universe.")
    seen_fund_ids: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict) or not candidate:
            raise EvidenceProviderContractError(f"Candidate row {index} must be a non-empty mapping.")
        fund_id = candidate.get("fund_id") or candidate.get("id")
        if not isinstance(fund_id, str) or not fund_id.strip():
            raise EvidenceProviderContractError(f"Candidate row {index} requires a stable fund_id.")
        if fund_id in seen_fund_ids:
            raise EvidenceProviderContractError(f"Duplicate candidate fund_id: {fund_id!r}.")
        seen_fund_ids.add(fund_id)

        required_text = ("fund_name", "scheme_id", "isin", "amc_name", "category")
        for field in required_text:
            if not isinstance(candidate.get(field), str) or not candidate[field].strip():
                raise EvidenceProviderContractError(f"Candidate {fund_id!r} requires {field}.")
        master_record = scheme_index.get(candidate["scheme_id"])
        if master_record is None:
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} scheme_id is absent from verified scheme master.")
        if (candidate["isin"] != master_record["isin"]
                or candidate["fund_name"].strip().casefold() != master_record["scheme_name"].strip().casefold()
                or candidate["amc_name"].strip().casefold() != master_record["amc_name"].strip().casefold()):
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} identity conflicts with verified scheme master.")
        if candidate.get("is_direct") is not True:
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} is not explicitly classified as Direct.")
        if not isinstance(candidate.get("direct_plan_evidence"), dict):
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} is missing Direct-plan source evidence.")
        if not isinstance(candidate.get("_evidence_root"), (str, __import__("pathlib").Path)):
            raise EvidenceProviderContractError(f"Candidate {fund_id!r} is missing its evidence root.")
        from core.eligibility import _reviewed_direct_plan_evidence_status
        if _reviewed_direct_plan_evidence_status(candidate) != "REVIEWER_ATTESTED_HASH_MATCH":
            raise EvidenceProviderContractError(
                f"Candidate {fund_id!r} Direct-plan source evidence is invalid, stale, or identity-conflicting."
            )

    for optional_path in ("metrics_path", "aliases_path"):
        value = payload[optional_path]
        if optional_path == "metrics_path" and (value is None or not hasattr(value, "is_file")):
            raise EvidenceProviderContractError("metrics_path must be a Path-like source for candidate evidence files.")
        if value is not None and not hasattr(value, "is_file"):
            raise EvidenceProviderContractError(f"{optional_path} must be a Path-like object or None.")

    # The completeness flag is an attestation, not an independent proof that
    # every eligible scheme in the stated market scope has been enumerated.
    # Publisher authenticity and reviewer identity also remain external checks.
    return dict(payload)
