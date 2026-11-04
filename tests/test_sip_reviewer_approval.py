import base64
from datetime import date, datetime, timedelta, timezone
import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from services.sip_reviewer_approval import (
    ApprovalResult,
    verify_sip_reviewer_approval,
    create_sip_reviewer_approval_envelope,
    create_sip_trust_registry,
    canonical_sha256,
)
from ingestion.portfolio_disclosure import (
    validate_portfolio_disclosure,
    resolve_scheme_identity,
)
from core.eligibility import _reviewed_direct_plan_evidence_status


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _make_key_pair(key_id="key-001", reviewer_id="rev-001", role="independent", revoked=False):
    private_key = Ed25519PrivateKey.generate()
    pub_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    key_dict = {
        "key_id": key_id,
        "reviewer_id": reviewer_id,
        "reviewer_role": role,
        "public_key": _b64(pub_bytes),
        "valid_from": "2025-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "revoked_at": "2026-06-01T00:00:00Z" if revoked else None,
    }
    return private_key, key_dict


def test_valid_detached_ed25519_approval_passes():
    priv, key_entry = _make_key_pair()
    registry = create_sip_trust_registry([key_entry])

    source_bytes = b"factsheet disclosure document pdf bytes"
    structured_records = {
        "constituent_weights": {"RELIANCE": 50.0, "TCS": 50.0},
        "coverage_pct": 100.0,
    }
    now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_PORTFOLIO_DISCLOSURE",
        source_bytes=source_bytes,
        structured_records=structured_records,
        scheme_id="SCHEME-1",
        issued_at=now,
    )

    doc_sha = hashlib.sha256(source_bytes).hexdigest()
    res = verify_sip_reviewer_approval(
        envelope,
        registry,
        expected_scope="SIP_PORTFOLIO_DISCLOSURE",
        expected_source_sha256=doc_sha,
        structured_records=structured_records,
        expected_scheme_id="SCHEME-1",
        now=now,
    )

    assert res.ok
    assert res.approval_id is not None
    assert res.reviewer_id == "rev-001"
    assert res.key_id == "key-001"


def test_tampered_structured_records_with_unchanged_source_bytes_fails():
    priv, key_entry = _make_key_pair()
    registry = create_sip_trust_registry([key_entry])

    source_bytes = b"original source document"
    original_records = {"weights": {"RELIANCE": 10.0, "TCS": 90.0}}
    tampered_records = {"weights": {"RELIANCE": 99.0, "TCS": 1.0}}

    now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_PORTFOLIO_DISCLOSURE",
        source_bytes=source_bytes,
        structured_records=original_records,
        issued_at=now,
    )

    doc_sha = hashlib.sha256(source_bytes).hexdigest()
    res = verify_sip_reviewer_approval(
        envelope,
        registry,
        expected_scope="SIP_PORTFOLIO_DISCLOSURE",
        expected_source_sha256=doc_sha,
        structured_records=tampered_records,
        now=now,
    )

    assert not res.ok
    assert any("Structured records digest mismatch" in err for err in res.errors)


def test_tampered_source_bytes_fails_digest_check():
    priv, key_entry = _make_key_pair()
    registry = create_sip_trust_registry([key_entry])

    source_bytes = b"original factsheet bytes"
    records = {"weights": {"INFY": 100.0}}
    now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)

    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_PORTFOLIO_DISCLOSURE",
        source_bytes=source_bytes,
        structured_records=records,
        issued_at=now,
    )

    tampered_bytes = b"tampered factsheet bytes"
    tampered_sha = hashlib.sha256(tampered_bytes).hexdigest()

    res = verify_sip_reviewer_approval(
        envelope,
        registry,
        expected_scope="SIP_PORTFOLIO_DISCLOSURE",
        expected_source_sha256=tampered_sha,
        structured_records=records,
        now=now,
    )

    assert not res.ok
    assert any("Source document digest mismatch" in err for err in res.errors)


def test_unknown_or_missing_key_id_fails_closed():
    priv, key_entry = _make_key_pair(key_id="key-unknown")
    registry = create_sip_trust_registry([])

    source_bytes = b"doc bytes"
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-unknown",
        reviewer_id="rev-001",
        scope="SIP_SCHEME_MASTER",
        source_bytes=source_bytes,
        structured_records=[],
    )

    res = verify_sip_reviewer_approval(envelope, registry)
    assert not res.ok


def test_non_independent_reviewer_role_fails_closed():
    priv, key_entry = _make_key_pair(role="internal_amc_employee")
    registry = create_sip_trust_registry([key_entry])

    source_bytes = b"doc bytes"
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_SCHEME_MASTER",
        source_bytes=source_bytes,
        structured_records=[],
    )

    res = verify_sip_reviewer_approval(envelope, registry)
    assert not res.ok
    assert any("must be 'independent'" in err for err in res.errors)


def test_revoked_key_fails_closed():
    priv, key_entry = _make_key_pair(revoked=True)
    registry = create_sip_trust_registry([key_entry])

    source_bytes = b"doc bytes"
    now = datetime(2026, 11, 4, tzinfo=timezone.utc)
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_SCHEME_MASTER",
        source_bytes=source_bytes,
        structured_records=[],
        issued_at=now,
    )

    res = verify_sip_reviewer_approval(envelope, registry, now=now)
    assert not res.ok
    assert any("revoked" in err.lower() for err in res.errors)


def test_expired_approval_fails_closed():
    priv, key_entry = _make_key_pair()
    registry = create_sip_trust_registry([key_entry])

    source_bytes = b"doc bytes"
    issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expires = datetime(2026, 2, 1, tzinfo=timezone.utc)
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)

    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_SCHEME_MASTER",
        source_bytes=source_bytes,
        structured_records=[],
        issued_at=issued,
        expires_at=expires,
    )

    res = verify_sip_reviewer_approval(envelope, registry, now=now)
    assert not res.ok
    assert any("expired" in err.lower() for err in res.errors)


def test_wrong_approval_scope_fails_closed():
    priv, key_entry = _make_key_pair()
    registry = create_sip_trust_registry([key_entry])

    source_bytes = b"doc bytes"
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_SCHEME_MASTER",
        source_bytes=source_bytes,
        structured_records=[],
    )

    res = verify_sip_reviewer_approval(
        envelope, registry, expected_scope="SIP_PORTFOLIO_DISCLOSURE"
    )
    assert not res.ok
    assert any("scope mismatch" in err.lower() for err in res.errors)


def test_portfolio_disclosure_requires_signature_when_configured():
    priv, key_entry = _make_key_pair()
    registry = create_sip_trust_registry([key_entry])

    source = b"official monthly portfolio disclosure bytes"
    weights = {"INE000A01001": 60.0, "INE000A01002": 40.0}
    cov = 100.0
    scheme_id = "SCHEME-001"

    # Case 1: Plain boolean alone without envelope when signature is required -> fails
    plain_disclosure = {
        "scheme_id": scheme_id,
        "source_url": "https://amc.example/factsheet.pdf",
        "source_document_sha256": hashlib.sha256(source).hexdigest(),
        "reviewer_attested": True,
        "effective_date": "2026-10-15",
        "constituent_weights": weights,
        "constituent_weights_coverage_pct": cov,
    }
    result_rejected = validate_portfolio_disclosure(
        plain_disclosure,
        source,
        as_of=date(2026, 10, 31),
        max_age_days=45,
        trust_registry=registry,
        require_reviewer_signature=True,
    )
    assert result_rejected["status"] == "MISSING"
    assert "Independent reviewer approval signature is required" in result_rejected["reason"]

    # Case 2: Valid detached signature envelope attached -> VERIFIED
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_PORTFOLIO_DISCLOSURE",
        source_bytes=source,
        structured_records={"constituent_weights": weights, "coverage_pct": cov},
        scheme_id=scheme_id,
        issued_at=now,
    )
    signed_disclosure = dict(plain_disclosure, reviewer_approval_envelope=envelope)

    result_verified = validate_portfolio_disclosure(
        signed_disclosure,
        source,
        as_of=date(2026, 10, 31),
        max_age_days=45,
        trust_registry=registry,
        require_reviewer_signature=True,
    )
    assert result_verified["status"] == "VERIFIED"
    assert result_verified["constituent_weights"]["INE000A01001"] == 60.0

    # Case 3: Tampered weights with valid source document -> fails closed
    tampered_disclosure = dict(
        signed_disclosure,
        constituent_weights={"INE000A01001": 99.0, "INE000A01002": 1.0},
    )
    result_tampered = validate_portfolio_disclosure(
        tampered_disclosure,
        source,
        as_of=date(2026, 10, 31),
        max_age_days=45,
        trust_registry=registry,
        require_reviewer_signature=True,
    )
    assert result_tampered["status"] == "CONFLICTING"
    assert "signature verification failed" in result_tampered["reason"].lower()


def test_scheme_identity_resolution_requires_signature_when_configured():
    priv, key_entry = _make_key_pair()
    registry = create_sip_trust_registry([key_entry])

    source_bytes = b"official scheme master csv bytes"
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    schemes = [{
        "scheme_id": "SCHEME-1",
        "isin": "INF000000001",
        "scheme_name": "Axis Bluechip Fund Direct Growth",
        "amc_name": "Axis Mutual Fund",
        "plan_type": "Direct",
        "option_type": "Growth",
    }]
    cas_holding = {
        "scheme": "Axis Bluechip Fund Direct Growth",
        "amc_name": "Axis Mutual Fund",
    }

    scheme_master = {
        "status": "VERIFIED",
        "reviewer_attested": True,
        "source_url": "https://amfiindia.com/master.csv",
        "source_document_sha256": source_hash,
        "schemes": schemes,
    }

    # Plain boolean rejected when signature required
    rejected = resolve_scheme_identity(
        cas_holding,
        scheme_master,
        source_bytes=source_bytes,
        trust_registry=registry,
        require_reviewer_signature=True,
    )
    assert rejected["status"] == "MISSING"

    # Signed scheme master passes
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_SCHEME_MASTER",
        source_bytes=source_bytes,
        structured_records=schemes,
    )
    signed_master = dict(scheme_master, reviewer_approval_envelope=envelope)

    verified = resolve_scheme_identity(
        cas_holding,
        signed_master,
        source_bytes=source_bytes,
        trust_registry=registry,
        require_reviewer_signature=True,
    )
    assert verified["status"] == "VERIFIED"
    assert verified["scheme_id"] == "SCHEME-1"


def test_direct_plan_evidence_requires_signature_when_configured(tmp_path):
    priv, key_entry = _make_key_pair()
    registry = create_sip_trust_registry([key_entry])

    doc_bytes = b"direct plan factsheet doc"
    doc_file = tmp_path / "plan_source.pdf"
    doc_file.write_bytes(doc_bytes)
    doc_sha = hashlib.sha256(doc_bytes).hexdigest()

    fund_data = {
        "fund_name": "Fund Direct Growth",
        "scheme_id": "SCH-1",
        "isin": "INF000000001",
        "amc_name": "Test AMC",
        "plan": "Direct",
        "as_of_date": date.today(),
        "_evidence_root": str(tmp_path),
        "direct_plan_evidence": {
            "source_file": "plan_source.pdf",
            "source_document_sha256": doc_sha,
            "source_url": "https://amc.example/plan.pdf",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Fund Direct Growth",
            "scheme_id": "SCH-1",
            "isin": "INF000000001",
            "amc_name": "Test AMC",
            "reviewed_at": date.today().isoformat(),
        },
    }

    # Plain evidence missing envelope when signature required
    status_missing = _reviewed_direct_plan_evidence_status(
        fund_data, trust_registry=registry, require_signature=True
    )
    assert status_missing == "SIGNATURE_MISSING"

    # Signed evidence passes
    structured_records = {
        "scheme_id": "SCH-1",
        "isin": "INF000000001",
        "plan": "Direct",
        "amc_name": "Test AMC",
    }
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_DIRECT_PLAN_EVIDENCE",
        source_bytes=doc_bytes,
        structured_records=structured_records,
        scheme_id="SCH-1",
    )
    fund_data["direct_plan_evidence"]["reviewer_approval_envelope"] = envelope

    status_verified = _reviewed_direct_plan_evidence_status(
        fund_data, trust_registry=registry, require_signature=True
    )
    assert status_verified == "REVIEWER_ATTESTED_HASH_MATCH"


def test_runtime_trust_registry_loader_requires_external_configuration(monkeypatch):
    from services.sip_reviewer_approval import (
        ENV_SIP_REGISTRY, load_sip_reviewer_trust_registry,
    )
    monkeypatch.delenv(ENV_SIP_REGISTRY, raising=False)
    with pytest.raises(ValueError, match="is required"):
        load_sip_reviewer_trust_registry()


def test_runtime_trust_registry_loader_parses_independently_configured_registry(monkeypatch):
    import json
    from services.sip_reviewer_approval import (
        ENV_SIP_REGISTRY, load_sip_reviewer_trust_registry,
    )
    _, key_entry = _make_key_pair()
    registry = create_sip_trust_registry([key_entry])
    monkeypatch.setenv(ENV_SIP_REGISTRY, json.dumps(registry))
    assert load_sip_reviewer_trust_registry() == registry
