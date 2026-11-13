"""Reusable ephemeral signing fixtures for SIP mandate acceptance tests.

These keys are generated per test and are never production credentials.
"""
from __future__ import annotations

import base64
from datetime import date, timedelta
import hashlib

import rfc8785
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services import sip_mandate_auth


def make_signed_mandate_schedule(as_of: str, owner_ref: str, coverage_status: str = "COMPLETE"):
    decision_date = date.fromisoformat(as_of)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    source_bytes = (
        "ephemeral-test-registrar-schedule|"
        + owner_ref
        + "|"
        + decision_date.isoformat()
    ).encode("utf-8")
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    mandates = []
    schedule_sha = hashlib.sha256(rfc8785.dumps(mandates)).hexdigest()
    issued_at = (decision_date - timedelta(days=2)).isoformat() + "T00:00:00Z"
    expires_at = (decision_date + timedelta(days=30)).isoformat() + "T00:00:00Z"
    payload = {
        "schema_version": 2,
        "signer_id": "ephemeral-registrar",
        "signer_key_id": "ephemeral-registrar-key",
        "signer_type": "REGISTRAR",
        "owner_ref": owner_ref,
        "source_sha256": source_sha,
        "schedule_sha256": schedule_sha,
        "coverage_status": coverage_status,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    signature = private_key.sign(rfc8785.dumps(payload))

    def b64url(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    evidence = {
        "coverage_status": coverage_status,
        "source_bytes": source_bytes,
        "source_ref": "sha256:" + source_sha,
        "mandates": mandates,
        "signature_envelope": {
            "payload": payload,
            "signature": b64url(signature),
        },
    }
    trust_registry = {
        "schema_version": 1,
        "keys": [{
            "key_id": "ephemeral-registrar-key",
            "signer_id": "ephemeral-registrar",
            "signer_type": "REGISTRAR",
            "public_key": b64url(public_key),
            "valid_from": (decision_date - timedelta(days=365)).isoformat() + "T00:00:00Z",
            "valid_until": (decision_date + timedelta(days=365)).isoformat() + "T00:00:00Z",
            "revoked": False,
            "revoked_at": None,
        }],
    }
    return evidence, trust_registry


def install_mandate_trust_registry(monkeypatch, trust_registry):
    monkeypatch.setattr(
        sip_mandate_auth,
        "load_mandate_trust_registry",
        lambda: trust_registry,
    )
