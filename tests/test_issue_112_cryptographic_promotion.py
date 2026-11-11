"""
tests/test_issue_112_cryptographic_promotion.py - Acceptance tests for Issue #112.
Cryptographic approval enforcement across every promotion path:
- Bind approval to exact artifact digest, scope, policy digest, and commit SHA.
- Reject mismatched commit or policy digests.
- Enforce detached Ed25519 reviewer approval for every promotion path.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from services.sip_reviewer_approval import (
    create_sip_reviewer_approval_envelope,
    create_sip_trust_registry,
    verify_sip_reviewer_approval,
)
from services.engine_bootstrap import EngineBootstrapPipeline
from services.acquisition.bundle_builder import EvidenceBundleBuilder


def _make_key_pair(key_id="key-001", reviewer_id="rev-001"):
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    b64_pub = base64.urlsafe_b64encode(pub_bytes).decode("ascii").rstrip("=")
    key_dict = {
        "key_id": key_id,
        "reviewer_id": reviewer_id,
        "reviewer_role": "independent",
        "public_key": b64_pub,
        "valid_from": "2025-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
    }
    registry = create_sip_trust_registry([key_dict])
    return priv, registry


def test_approval_envelope_binds_commit_sha_and_policy_digest():
    priv, registry = _make_key_pair()
    commit = "07cb506f8c35d4572cf58645e61d36f22302048a"
    policy_hash = hashlib.sha256(b"authoritative_policy_content").hexdigest()
    source_bytes = b"source evidence bytes"
    records = {"verified": True}

    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=source_bytes,
        structured_records=records,
        commit_sha=commit,
        policy_digest=policy_hash,
    )

    res = verify_sip_reviewer_approval(
        envelope,
        registry,
        expected_scope="SIP_EVIDENCE_RELEASE",
        expected_commit_sha=commit,
        expected_policy_digest=policy_hash,
        require_commit_binding=True,
        require_policy_binding=True,
    )
    assert res.ok is True
    assert res.approval_id is not None


def test_approval_envelope_rejects_mismatched_commit_sha():
    priv, registry = _make_key_pair()
    commit_approved = "07cb506f8c35d4572cf58645e61d36f22302048a"
    commit_attempted = "1111111111111111111111111111111111111111"
    policy_hash = hashlib.sha256(b"policy").hexdigest()

    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"source",
        structured_records={"k": "v"},
        commit_sha=commit_approved,
        policy_digest=policy_hash,
    )

    res = verify_sip_reviewer_approval(
        envelope,
        registry,
        expected_commit_sha=commit_attempted,
    )
    assert res.ok is False
    assert any("Commit SHA mismatch" in err for err in res.errors)


def test_approval_envelope_rejects_mismatched_policy_digest():
    priv, registry = _make_key_pair()
    commit = "07cb506f8c35d4572cf58645e61d36f22302048a"
    policy_approved = hashlib.sha256(b"policy_v1").hexdigest()
    policy_attempted = hashlib.sha256(b"policy_v2_tampered").hexdigest()

    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"source",
        structured_records={"k": "v"},
        commit_sha=commit,
        policy_digest=policy_approved,
    )

    res = verify_sip_reviewer_approval(
        envelope,
        registry,
        expected_policy_digest=policy_attempted,
    )
    assert res.ok is False
    assert any("Policy digest mismatch" in err for err in res.errors)


def test_approval_fails_when_mandatory_bindings_are_missing():
    priv, registry = _make_key_pair()
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"source",
        structured_records={"k": "v"},
        # Neither commit_sha nor policy_digest passed
    )

    res = verify_sip_reviewer_approval(
        envelope,
        registry,
        require_commit_binding=True,
        require_policy_binding=True,
    )
    assert res.ok is False
    assert any("missing required commit_sha binding" in err for err in res.errors)
    assert any("missing required policy_digest binding" in err for err in res.errors)


def test_engine_bootstrap_promote_enforces_commit_and_policy_binding(tmp_path):
    pipeline = EngineBootstrapPipeline()
    staging = tmp_path / "staging"
    staging.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "disclosure_as_of_date": "2026-11-05",
        "metrics_file": "metrics.json",
        "scheme_master_file": "scheme_master.json",
    }
    (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (staging / "metrics.json").write_text("{}", encoding="utf-8")
    (staging / "scheme_master.json").write_text("{}", encoding="utf-8")

    target = tmp_path / "target"

    priv, registry = _make_key_pair()
    commit = "07cb506f8c35d4572cf58645e61d36f22302048a"
    policy_hash = hashlib.sha256(b"screening_policy").hexdigest()

    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"source",
        structured_records={"k": "v"},
        commit_sha=commit,
        policy_digest=policy_hash,
    )

    # 1. Promotion with wrong commit SHA fails closed
    with pytest.raises(ValueError, match="Commit SHA mismatch"):
        pipeline.promote(
            staging,
            target,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha="2222222222222222222222222222222222222222",
        )

    # 2. Promotion with matching commit SHA and policy digest succeeds
    promoted = pipeline.promote(
        staging,
        target,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
        expected_commit_sha=commit,
        expected_policy_digest=policy_hash,
        require_commit_binding=True,
        require_policy_binding=True,
    )
    assert promoted["status"] == "PROMOTED"
    assert promoted["approval_id"] is not None
    assert (target / "manifest.json").is_file()

