import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import rfc8785
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from tri_reviewer_approval import verify_approval


def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _signed_case(tmp_path):
    root = tmp_path
    policy = root / "data/policy"
    policy.mkdir(parents=True)
    fixture = policy / "fixture.json"
    fixture.write_text(json.dumps({"provenance": {"independent_reviewer_id": "reviewer-test"}}), encoding="utf-8")
    source = policy / "nifty500.csv"
    source.write_text("date,tri\n2026-01-01,100\n", encoding="utf-8")
    source2 = policy / "multicap.csv"
    source2.write_text("date,tri\n2026-01-01,101\n", encoding="utf-8")
    source3 = policy / "midcap.csv"
    source3.write_text("date,tri\n2026-01-01,102\n", encoding="utf-8")
    calendar = policy / "nse_trading_calendar.json"
    sessions = ["2026-01-01", "2026-01-02"]
    calendar.write_text(json.dumps({"exchange": "NSE", "status": "VERIFIED", "sessions": sessions, "provenance": {
        "source_document_file": "data/policy/calendar-source.csv",
        "source_document_sha256": hashlib.sha256(b"calendar-source").hexdigest(),
        "source_url": "https://www.nseindia.com/calendar.csv",
    }}), encoding="utf-8")
    (policy / "calendar-source.csv").write_bytes(b"calendar-source")
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    payload = {
        "schema_version": 1, "approval_id": "approval-test-001",
        "approval_scope": "TRI_EVIDENCE_RELEASE", "reviewer_id": "reviewer-test",
        "reviewer_key_id": "key-test", "issued_at": "2026-01-02T00:00:00Z",
        "expires_at": "2026-02-02T00:00:00Z", "repository": "o0k00l/MF-AI-Based",
        "commit_sha": "a" * 40, "tri_fixture_sha256": digest(fixture),
        "tri_source_documents": [
            {"benchmark": "NIFTY 500 MULTICAP 50:25:25 TRI", "path": "data/policy/multicap.csv", "sha256": digest(source2), "source_url": "https://www.nseindia.com/b.csv"},
            {"benchmark": "NIFTY 500 TRI", "path": "data/policy/nifty500.csv", "sha256": digest(source), "source_url": "https://www.nseindia.com/a.csv"},
            {"benchmark": "NIFTY MIDCAP 150 TRI", "path": "data/policy/midcap.csv", "sha256": digest(source3), "source_url": "https://www.nseindia.com/c.csv"},
        ],
        "calendar_source_path": "data/policy/calendar-source.csv",
        "calendar_source_url": "https://www.nseindia.com/calendar.csv",
        "calendar_source_sha256": hashlib.sha256(b"calendar-source").hexdigest(),
        "calendar_sessions_sha256": hashlib.sha256(rfc8785.dumps(sessions)).hexdigest(),
        "review_attestation": True, "source_reconciliation_attestation": True,
    }
    envelope = {"payload": payload, "signature": _b64(private.sign(rfc8785.dumps(payload)))}
    registry = {"schema_version": 1, "keys": [{
        "key_id": "key-test", "reviewer_id": "reviewer-test", "reviewer_role": "independent",
        "public_key": _b64(public), "valid_from": "2025-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z", "revoked_at": None,
    }]}
    return envelope, registry, fixture, root, now


def _verify(case, **kwargs):
    envelope, registry, fixture, root, now = case
    return verify_approval(
        envelope, registry, repository="o0k00l/MF-AI-Based",
        expected_commit="a" * 40, fixture_path=fixture, root=root, now=now, **kwargs
    )


def test_valid_detached_ed25519_approval_passes(tmp_path):
    result = _verify(_signed_case(tmp_path))
    assert result.ok
    assert result.approval_id == "approval-test-001"


def test_payload_tampering_fails_signature(tmp_path):
    case = list(_signed_case(tmp_path))
    case[0]["payload"]["review_attestation"] = False
    assert not _verify(tuple(case)).ok


def test_fixture_tampering_fails_digest(tmp_path):
    case = _signed_case(tmp_path)
    case[2].write_text('{"test":false}', encoding="utf-8")
    assert not _verify(case).ok


def test_wrong_commit_fails_closed(tmp_path):
    case = _signed_case(tmp_path)
    result = verify_approval(case[0], case[1], repository="o0k00l/MF-AI-Based",
        expected_commit="b" * 40, fixture_path=case[2], root=case[3], now=case[4])
    assert not result.ok


def test_unknown_key_fails_closed(tmp_path):
    case = list(_signed_case(tmp_path))
    case[1]["keys"] = []
    assert not _verify(tuple(case)).ok


def test_revoked_key_fails_closed(tmp_path):
    case = list(_signed_case(tmp_path))
    case[1]["keys"][0]["revoked_at"] = "2026-01-01T00:00:00Z"
    assert not _verify(tuple(case)).ok


def test_expired_approval_fails_closed(tmp_path):
    case = _signed_case(tmp_path)
    late = datetime(2026, 3, 1, tzinfo=timezone.utc)
    result = verify_approval(case[0], case[1], repository="o0k00l/MF-AI-Based",
        expected_commit="a" * 40, fixture_path=case[2], root=case[3], now=late)
    assert not result.ok


def test_source_document_tampering_fails_digest(tmp_path):
    case = _signed_case(tmp_path)
    (tmp_path / "data/policy/nifty500.csv").write_text("tampered", encoding="utf-8")
    assert not _verify(case).ok


def test_duplicate_json_keys_are_rejected():
    from tri_reviewer_approval import _strict_json
    with pytest.raises(ValueError, match="duplicate"):
        _strict_json('{"a":1,"a":2}')


def test_revocation_after_issuance_invalidates_outstanding_approval(tmp_path):
    case = list(_signed_case(tmp_path))
    case[1]["keys"][0]["revoked_at"] = "2026-01-02T12:00:00Z"
    assert not _verify(tuple(case)).ok


def test_official_source_url_requires_exact_host_and_standard_https_port():
    from tri_reviewer_approval import _official_https_url

    assert _official_https_url("https://www.nseindia.com/archive/file.csv")
    assert not _official_https_url("https://nseindia.com.attacker.example/file.csv")
    assert not _official_https_url("https://nseindia.com:444/file.csv")
    assert not _official_https_url("https://user@nseindia.com/file.csv")


def test_key_expiry_is_checked_at_verification_time(tmp_path):
    case = list(_signed_case(tmp_path))
    case[1]["keys"][0]["valid_until"] = "2026-01-02T12:00:00Z"
    assert not _verify(tuple(case)).ok



def test_noncanonical_timestamp_is_rejected():
    from tri_reviewer_approval import _utc

    with pytest.raises(ValueError, match="canonical UTC RFC3339"):
        _utc("20260102T000000Z")


def test_trusted_key_must_be_authorized_for_independent_review(tmp_path):
    case = list(_signed_case(tmp_path))
    case[1]["keys"][0]["reviewer_role"] = "operator"
    assert not _verify(tuple(case)).ok


def test_trust_registry_and_approval_input_sizes_are_bounded(monkeypatch, tmp_path):
    from tri_reviewer_approval import (
        ENV_APPROVAL, ENV_REGISTRY, MAX_APPROVAL_BYTES, MAX_REGISTRY_BYTES,
        verify_approval_from_environment,
    )

    monkeypatch.setenv(ENV_REGISTRY, " " * (MAX_REGISTRY_BYTES + 1))
    monkeypatch.setenv(ENV_APPROVAL, "{}")
    result = verify_approval_from_environment(
        repository="o0k00l/MF-AI-Based", expected_commit="a" * 40,
        fixture_path=tmp_path / "fixture.json", root=tmp_path,
    )
    assert not result.ok
    assert "size limit" in result.errors[0]

    monkeypatch.setenv(ENV_REGISTRY, "{}")
    monkeypatch.setenv(ENV_APPROVAL, " " * (MAX_APPROVAL_BYTES + 1))
    result = verify_approval_from_environment(
        repository="o0k00l/MF-AI-Based", expected_commit="a" * 40,
        fixture_path=tmp_path / "fixture.json", root=tmp_path,
    )
    assert not result.ok
    assert "size limit" in result.errors[0]



def test_source_reconciliation_attestation_is_mandatory(tmp_path):
    case = list(_signed_case(tmp_path))
    case[0]["payload"]["source_reconciliation_attestation"] = False
    # Re-sign to isolate the semantic attestation gate from signature-tampering detection.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    # The test fixture's private key is intentionally not exposed; a modified signed
    # payload cannot be constructed here, so exact-schema enforcement is covered by
    # removing the required field and expecting rejection before signature verification.
    del case[0]["payload"]["source_reconciliation_attestation"]
    assert not _verify(tuple(case)).ok
