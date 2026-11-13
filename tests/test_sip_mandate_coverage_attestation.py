from __future__ import annotations

import hashlib
from datetime import date

import pytest

from services.sip_mandate_auth import MandateAuthenticationError, verify_mandate_schedule


def _evidence(payload: dict, coverage_status: str = "COMPLETE") -> dict:
    source_bytes = b"authoritative mandate extract"
    return {
        "source_bytes": source_bytes,
        "source_ref": "sha256:" + hashlib.sha256(source_bytes).hexdigest(),
        "mandates": [],
        "coverage_status": coverage_status,
        "signature_envelope": {"payload": payload, "signature": "AA"},
    }


def _payload() -> dict:
    return {
        "schema_version": 2,
        "signer_id": "registrar-1",
        "signer_key_id": "key-1",
        "signer_type": "REGISTRAR",
        "owner_ref": "investor-1",
        "source_sha256": hashlib.sha256(b"authoritative mandate extract").hexdigest(),
        "schedule_sha256": hashlib.sha256(b"[]").hexdigest(),
        "issued_at": "2026-11-13T00:00:00Z",
        "expires_at": "2026-11-14T00:00:00Z",
    }


def test_mandate_schedule_rejects_unsigned_completeness_claim() -> None:
    # A caller-controlled COMPLETE flag cannot establish that no mandates were omitted.
    with pytest.raises(MandateAuthenticationError, match="signature payload schema"):
        verify_mandate_schedule(
            _evidence(_payload()), owner_ref="investor-1", as_of=date(2026, 11, 13)
        )


def test_mandate_schedule_rejects_signer_attested_partial_coverage() -> None:
    payload = _payload()
    payload["coverage_status"] = "PARTIAL"
    with pytest.raises(MandateAuthenticationError, match="completeness is not signer-attested"):
        verify_mandate_schedule(
            _evidence(payload, coverage_status="PARTIAL"),
            owner_ref="investor-1",
            as_of=date(2026, 11, 13),
        )


def test_mandate_schedule_rejects_coverage_metadata_not_bound_to_signature() -> None:
    payload = _payload()
    payload["coverage_status"] = "COMPLETE"
    with pytest.raises(MandateAuthenticationError, match="coverage metadata is not signature-bound"):
        verify_mandate_schedule(
            _evidence(payload, coverage_status="PARTIAL"),
            owner_ref="investor-1",
            as_of=date(2026, 11, 13),
        )
