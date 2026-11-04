"""Structural contract for injected SIP evidence providers.

This module validates payload shape only. It does NOT authenticate publishers,
verify source hashes, attest reviewers, establish universe completeness, or
approve a recommendation release. Those checks remain downstream gates.
"""
from __future__ import annotations

from datetime import date
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
})
REQUEST_BOUND_FIELDS = frozenset({"cas_path", "monthly_budget_inr", "risk_profile"})


class EvidenceProviderContractError(ValueError):
    """Raised when a provider response violates the structural contract."""


def validate_evidence_provider_payload(payload: Any) -> dict[str, Any]:
    """Validate required fields and types without upgrading evidence status."""
    if not isinstance(payload, dict):
        raise EvidenceProviderContractError("Provider response must be a mapping.")

    supplied = set(payload)
    missing = REQUIRED_EVIDENCE_FIELDS - supplied
    unexpected = supplied - REQUIRED_EVIDENCE_FIELDS
    if missing:
        raise EvidenceProviderContractError(
            "Provider response is missing required fields: " + ", ".join(sorted(missing))
        )
    if unexpected:
        raise EvidenceProviderContractError(
            "Provider response contains unsupported fields: " + ", ".join(sorted(unexpected))
        )

    master = payload["scheme_master"]
    master_bytes = payload["scheme_master_source_bytes"]
    if not isinstance(master, dict) or not master:
        raise EvidenceProviderContractError("scheme_master must be a non-empty mapping.")
    if not isinstance(master_bytes, bytes) or not master_bytes:
        raise EvidenceProviderContractError("scheme_master_source_bytes must be non-empty bytes.")

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
        if not isinstance(record, dict) or not record:
            raise EvidenceProviderContractError(f"Disclosure for {scheme_id!r} must be a non-empty mapping.")
        raw = disclosure_bytes[scheme_id]
        if not isinstance(raw, bytes) or not raw:
            raise EvidenceProviderContractError(f"Original source bytes for {scheme_id!r} are missing.")

    as_of = payload["disclosure_as_of_date"]
    if not isinstance(as_of, date):
        raise EvidenceProviderContractError("disclosure_as_of_date must be a date, not a string or timestamp.")

    candidates = payload["candidate_universe"]
    if not isinstance(candidates, list) or not candidates:
        raise EvidenceProviderContractError("candidate_universe must be a non-empty list.")
    if any(not isinstance(candidate, dict) or not candidate for candidate in candidates):
        raise EvidenceProviderContractError("Every candidate must be a non-empty mapping.")

    for optional_path in ("metrics_path", "aliases_path"):
        value = payload[optional_path]
        if value is not None and not hasattr(value, "is_file"):
            raise EvidenceProviderContractError(f"{optional_path} must be a Path-like object or None.")

    # Return a shallow copy. Validation deliberately does not mutate or enrich
    # provider evidence and does not assign VERIFIED status to any source.
    return dict(payload)
