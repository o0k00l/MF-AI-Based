"""End-to-end cryptographic mandate evidence tests for issue #106.

All signing keys in this module are ephemeral test keys. Production trust roots
remain deployment-owned and are never committed to the repository.
"""
from __future__ import annotations

import base64
from datetime import date
import hashlib
import json

import rfc8785
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from api.sip import _verify_provider_mandate_schedule
from services import sip_mandate_auth
from services.sip_recommendation import _validate_active_sip_commitments


AS_OF = date(2026, 11, 13)
OWNER = "investor-test-001"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _signed_schedule(*, status: str = "ACTIVE", amount: str = "7500.00",
                     next_debit: str = "2026-11-20", mandates_present: bool = True):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    source_bytes = b"registrar-issued SIP mandate schedule test fixture"
    source_sha = hashlib.sha256(source_bytes).hexdigest()

    mandates = []
    if mandates_present:
        record = {
            "mandate_id": "MANDATE-TEST-001",
            "owner_ref": OWNER,
            "folio_no": "FOLIO-001",
            "scheme_id": "SCHEME-001",
            "authentication_method": "REGISTRAR_SIGNED",
            "status": status,
            "monthly_amount_inr": amount,
            "frequency": "MONTHLY",
            "effective_from": "2026-01-01",
            "effective_to": None,
            "next_debit_date": next_debit,
        }
        record["evidence_ref"] = "sha256:" + hashlib.sha256(
            rfc8785.dumps(record)
        ).hexdigest()
        mandates.append(record)

    schedule_sha = hashlib.sha256(rfc8785.dumps(mandates)).hexdigest()
    payload = {
        "schema_version": 1,
        "signer_id": "registrar-test",
        "signer_key_id": "registrar-key-test-1",
        "signer_type": "REGISTRAR",
        "owner_ref": OWNER,
        "source_sha256": source_sha,
        "schedule_sha256": schedule_sha,
        "issued_at": "2026-11-01T00:00:00Z",
        "expires_at": "2026-12-01T00:00:00Z",
    }
    signature = private_key.sign(rfc8785.dumps(payload))
    evidence = {
        "coverage_status": "COMPLETE",
        "source_bytes": source_bytes,
        "source_ref": "sha256:" + source_sha,
        "mandates": mandates,
        "signature_envelope": {
            "payload": payload,
            "signature": _b64url(signature),
        },
    }
    trust_registry = {
        "schema_version": 1,
        "keys": [{
            "key_id": "registrar-key-test-1",
            "signer_id": "registrar-test",
            "signer_type": "REGISTRAR",
            "public_key": _b64url(public_key),
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
            "revoked": False,
            "revoked_at": None,
        }],
    }
    return evidence, trust_registry


def _context(evidence):
    return {
        "as_of_date": AS_OF.isoformat(),
        "investor_owner_ref": OWNER,
        "sip_mandate_evidence": evidence,
    }


def test_signed_registrar_schedule_flows_into_affordability_commitment(monkeypatch):
    evidence, trust_registry = _signed_schedule()
    monkeypatch.setattr(
        sip_mandate_auth, "load_mandate_trust_registry",
        lambda: trust_registry,
    )

    result = _validate_active_sip_commitments(_context(evidence), AS_OF)

    assert result["status"] == "VERIFIED"
    assert result["active_mandate_count"] == 1
    assert result["inactive_mandate_count"] == 0
    assert result["existing_monthly_sip_commitments_inr"] == "7500.00"
    assert result["commitment_evidence_basis"] == (
        "ED25519_VERIFIED_SOURCE_AND_OWNER_BOUND_MANDATE_SCHEDULE"
    )


def test_signed_empty_schedule_is_verified_zero_but_missing_schedule_is_hold(monkeypatch):
    evidence, trust_registry = _signed_schedule(mandates_present=False)
    monkeypatch.setattr(
        sip_mandate_auth, "load_mandate_trust_registry",
        lambda: trust_registry,
    )

    verified_zero = _validate_active_sip_commitments(_context(evidence), AS_OF)
    missing = _validate_active_sip_commitments({
        "as_of_date": AS_OF.isoformat(),
        "investor_owner_ref": OWNER,
    }, AS_OF)

    assert verified_zero["status"] == "VERIFIED"
    assert verified_zero["active_mandate_count"] == 0
    assert verified_zero["existing_monthly_sip_commitments_inr"] == "0.00"
    assert missing == {
        "status": "HOLD",
        "reason": "ACTIVE_SIP_MANDATE_EVIDENCE_MISSING",
    }


def test_source_schedule_and_owner_tampering_fail_closed(monkeypatch):
    evidence, trust_registry = _signed_schedule()
    monkeypatch.setattr(
        sip_mandate_auth, "load_mandate_trust_registry",
        lambda: trust_registry,
    )

    changed_source = dict(evidence)
    changed_source["source_bytes"] = b"changed registrar source bytes"
    changed_source["source_ref"] = "sha256:" + hashlib.sha256(
        changed_source["source_bytes"]
    ).hexdigest()
    source_result = _validate_active_sip_commitments(_context(changed_source), AS_OF)

    changed_schedule = dict(evidence)
    changed_schedule["mandates"] = [dict(evidence["mandates"][0])]
    changed_schedule["mandates"][0]["monthly_amount_inr"] = "9000.00"
    schedule_result = _validate_active_sip_commitments(_context(changed_schedule), AS_OF)

    wrong_owner = _context(evidence)
    wrong_owner["investor_owner_ref"] = "different-investor"
    owner_result = _validate_active_sip_commitments(wrong_owner, AS_OF)

    assert source_result["status"] == "HOLD"
    assert schedule_result["status"] == "HOLD"
    assert owner_result["status"] == "HOLD"
    assert all(
        result["reason"] == "SIP_MANDATE_SIGNATURE_VERIFICATION_FAILED"
        for result in (source_result, schedule_result, owner_result)
    )


def test_stale_active_mandate_terms_do_not_add_monthly_commitment(monkeypatch):
    evidence, trust_registry = _signed_schedule(next_debit="2026-10-20")
    monkeypatch.setattr(
        sip_mandate_auth, "load_mandate_trust_registry",
        lambda: trust_registry,
    )

    result = _validate_active_sip_commitments(_context(evidence), AS_OF)

    assert result["status"] == "HOLD"
    assert result["reason"] == "SIP_MANDATE_RECORD_1_ACTIVE_TERMS_STALE"


def test_api_boundary_uses_real_schedule_signature_not_caller_boolean(monkeypatch):
    evidence, trust_registry = _signed_schedule()
    monkeypatch.setenv(
        sip_mandate_auth.TRUST_REGISTRY_ENV,
        json.dumps(trust_registry),
    )
    context = _context(evidence)
    context["evidence_attested_by_provider"] = True

    assert _verify_provider_mandate_schedule(context) is True

    tampered = dict(context)
    tampered["sip_mandate_evidence"] = dict(evidence)
    tampered["sip_mandate_evidence"]["source_bytes"] = b"tampered"
    tampered["sip_mandate_evidence"]["source_ref"] = "sha256:" + hashlib.sha256(
        b"tampered"
    ).hexdigest()
    assert _verify_provider_mandate_schedule(tampered) is False
