from datetime import datetime, timezone
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from ingestion.statement_publisher_review import (
    APPROVAL_SCOPE, authenticate_statement_with_reviewer_approval,
)
from ingestion.statement_validator import StatementValidationResult
from services.sip_reviewer_approval import _b64url_encode, create_sip_reviewer_approval_envelope


def _trust():
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    registry = {"schema_version": 1, "keys": [{
        "key_id": "review-key", "reviewer_id": "reviewer-1", "reviewer_role": "independent",
        "public_key": _b64url_encode(public), "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-12-31T23:59:59Z", "revoked": False,
    }]}
    return key, registry


def _result(raw):
    return StatementValidationResult(
        is_valid=True, document_type="CAS_EXCEL", rta_source="Unknown",
        file_name="cas.xlsx", file_size_bytes=len(raw),
        provenance_digest=hashlib.sha256(raw).hexdigest(), structural_validity=True,
        detected_content_publisher="CAMS",
        publisher_authenticity_status="UNAUTHENTICATED_DOCUMENT_CONTENT",
    )


def _envelope(key, raw):
    verified_at = "2026-11-13T00:00:00Z"
    records = {
        "document_type": "CAS_EXCEL", "publisher": "CAMS",
        "verification_method": "INDEPENDENT_REVIEW", "verified_at": verified_at,
        "evidence_reference": "review-ticket:CAS-001", "source_url": "https://www.camsonline.com/",
    }
    return create_sip_reviewer_approval_envelope(
        key, key_id="review-key", reviewer_id="reviewer-1", scope=APPROVAL_SCOPE,
        source_bytes=raw, structured_records=records,
        issued_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        expires_at=datetime(2026, 12, 13, tzinfo=timezone.utc),
        publisher="CAMS", verification_method="INDEPENDENT_REVIEW",
        verified_at=verified_at, evidence_reference="review-ticket:CAS-001",
        source_url="https://www.camsonline.com/",
    )


def test_signed_independent_review_authenticates_exact_upload_and_publisher():
    raw = b"exact uploaded CAS bytes"
    key, registry = _trust()
    result = authenticate_statement_with_reviewer_approval(_result(raw), _envelope(key, raw), registry)
    assert result.is_publisher_authenticated is True
    assert result.authenticated_publisher == "CAMS"
    assert result.rta_source == "CAMS"
    assert result.publisher_authenticity_status == "AUTHENTICATED_SOURCE"
    assert result.provenance_source["reviewer_id"] == "reviewer-1"


def test_signed_review_cannot_be_replayed_for_another_upload():
    key, registry = _trust()
    envelope = _envelope(key, b"reviewed bytes")
    result = _result(b"different bytes")
    with pytest.raises(ValueError, match="rejected"):
        authenticate_statement_with_reviewer_approval(result, envelope, registry)
    assert result.is_publisher_authenticated is False
    assert result.rta_source == "Unknown"
