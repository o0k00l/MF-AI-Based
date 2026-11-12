"""Detached Ed25519 independent reviewer approval verification for SIP evidence.

Covers scheme-master, candidate-universe, portfolio-disclosure, and Direct-plan evidence.
The reviewer trust registry is supplied by an independently administered trust root.
No key embedded in an evidence payload or caller-asserted boolean flag is trusted.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import rfc8785
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey, Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from cryptography.exceptions import InvalidSignature


ENV_SIP_REGISTRY = "SIP_REVIEWER_TRUST_REGISTRY_JSON"
ENV_SIP_APPROVAL = "SIP_REVIEWER_APPROVAL_JSON"

MAX_APPROVAL_LIFETIME_DAYS = 90
MAX_REGISTRY_BYTES = 256 * 1024
MAX_APPROVAL_BYTES = 1024 * 1024

RFC3339_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

SUPPORTED_APPROVAL_SCOPES: Set[str] = {
    "SIP_EVIDENCE_RELEASE",
    "SIP_SCHEME_MASTER",
    "SIP_PORTFOLIO_DISCLOSURE",
    "SIP_CANDIDATE_UNIVERSE",
    "SIP_DIRECT_PLAN_EVIDENCE",
    "STATEMENT_PUBLISHER_AUTHENTICATION",
}

REQUIRED_PAYLOAD_FIELDS: Set[str] = {
    "schema_version",
    "approval_id",
    "approval_scope",
    "reviewer_id",
    "reviewer_key_id",
    "issued_at",
    "expires_at",
    "repository",
    "source_document_sha256",
    "structured_records_sha256",
    "review_attestation",
}


@dataclass(frozen=True)
class ApprovalResult:
    ok: bool
    errors: tuple[str, ...] = ()
    approval_id: Optional[str] = None
    reviewer_id: Optional[str] = None
    key_id: Optional[str] = None
    scope: Optional[str] = None


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not RFC3339_UTC_RE.fullmatch(value):
        raise ValueError("Timestamp must be canonical UTC RFC 3339 with seconds and ending in Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("Timestamp must be UTC")
    return parsed


def _b64url_decode(value: Any, expected_length: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Value must be unpadded base64url string")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(decoded) != expected_length:
        raise ValueError(f"Decoded cryptographic value length {len(decoded)} != expected {expected_length}")
    if base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise ValueError("Cryptographic value is not canonically base64url-encoded")
    return decoded


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def canonical_jcs(data: Any) -> bytes:
    """Serialize data to deterministic RFC 8785 JSON Canonicalization Scheme bytes."""
    return rfc8785.dumps(data)


def canonical_sha256(data: Any) -> str:
    """Compute SHA-256 of canonical RFC 8785 JCS bytes of structured data."""
    return hashlib.sha256(canonical_jcs(data)).hexdigest().lower()


def _strict_json(raw: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-standard JSON numeric constant is not allowed: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)


def load_sip_reviewer_trust_registry() -> dict[str, Any]:
    """Load the independently administered reviewer trust root from runtime config.

    The trust registry is intentionally not read from the evidence bundle: a
    bundle publisher must not be able to nominate or replace its own reviewers.
    """
    raw = os.getenv(ENV_SIP_REGISTRY)
    if not raw or not raw.strip():
        raise ValueError(f"{ENV_SIP_REGISTRY} is required for production SIP evidence validation")
    if len(raw.encode("utf-8")) > MAX_REGISTRY_BYTES:
        raise ValueError("SIP reviewer trust registry exceeds maximum allowed size")
    registry = _strict_json(raw)
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        raise ValueError("SIP reviewer trust registry has an unsupported schema")
    keys = registry.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("SIP reviewer trust registry must contain active keys")
    return registry


def verify_sip_reviewer_approval(
    envelope: Any,
    trust_registry: Any,
    *,
    expected_scope: Optional[str] = None,
    expected_source_sha256: Optional[str] = None,
    structured_records: Optional[Any] = None,
    expected_scheme_id: Optional[str] = None,
    expected_commit_sha: Optional[str] = None,
    expected_policy_digest: Optional[str] = None,
    expected_artifact_digest: Optional[str] = None,
    require_commit_binding: bool = False,
    require_policy_binding: bool = False,
    require_artifact_binding: bool = False,
    repository: str = "o0k00l/MF-AI-Based",
    now: Optional[datetime] = None,
) -> ApprovalResult:
    """
    Verify an independent reviewer Ed25519 approval envelope against the trust registry.
    Binds both original source bytes and the normalized structured records.
    """
    errors: list[str] = []
    current_time = now or datetime.now(timezone.utc)

    # 1. Parse / validate trust registry
    if isinstance(trust_registry, str):
        if len(trust_registry.encode("utf-8")) > MAX_REGISTRY_BYTES:
            return ApprovalResult(ok=False, errors=("Trust registry exceeds maximum allowed size",))
        try:
            trust_registry = _strict_json(trust_registry)
        except Exception as e:
            return ApprovalResult(ok=False, errors=(f"Failed to parse trust registry JSON: {e}",))

    if not isinstance(trust_registry, dict):
        return ApprovalResult(ok=False, errors=("Trust registry must be a mapping",))
    if trust_registry.get("schema_version") != 1:
        return ApprovalResult(ok=False, errors=("Trust registry schema_version must be 1",))
    keys = trust_registry.get("keys")
    if not isinstance(keys, list) or not keys:
        return ApprovalResult(ok=False, errors=("Trust registry contains no active keys",))

    keys_by_id: dict[str, dict[str, Any]] = {}
    for idx, k in enumerate(keys):
        if not isinstance(k, dict):
            return ApprovalResult(ok=False, errors=(f"Trust registry key entry {idx} is not a mapping",))
        kid = k.get("key_id")
        if not isinstance(kid, str) or not kid.strip():
            return ApprovalResult(ok=False, errors=(f"Trust registry key entry {idx} lacks key_id",))
        if kid in keys_by_id:
            return ApprovalResult(ok=False, errors=(f"Duplicate key_id in trust registry: {kid}",))
        keys_by_id[kid] = k

    # 2. Parse / validate envelope
    if isinstance(envelope, str):
        if len(envelope.encode("utf-8")) > MAX_APPROVAL_BYTES:
            return ApprovalResult(ok=False, errors=("Approval envelope exceeds maximum allowed size",))
        try:
            envelope = _strict_json(envelope)
        except Exception as e:
            return ApprovalResult(ok=False, errors=(f"Failed to parse approval envelope JSON: {e}",))

    if not isinstance(envelope, dict):
        return ApprovalResult(ok=False, errors=("Approval envelope must be a mapping",))
    if set(envelope.keys()) != {"payload", "signature"}:
        return ApprovalResult(ok=False, errors=("Approval envelope must contain exactly 'payload' and 'signature'",))

    payload = envelope.get("payload")
    sig_raw = envelope.get("signature")
    if not isinstance(payload, dict):
        return ApprovalResult(ok=False, errors=("Envelope payload must be a mapping",))

    missing_fields = REQUIRED_PAYLOAD_FIELDS - set(payload.keys())
    if missing_fields:
        return ApprovalResult(ok=False, errors=(f"Approval payload missing required fields: {sorted(missing_fields)}",))

    if payload.get("schema_version") != 1:
        errors.append("Payload schema_version must be 1")

    approval_id = payload.get("approval_id")
    approval_scope = payload.get("approval_scope")
    reviewer_id = payload.get("reviewer_id")
    key_id = payload.get("reviewer_key_id")

    if not isinstance(approval_id, str) or not approval_id.strip():
        errors.append("Invalid or missing approval_id")
    if approval_scope not in SUPPORTED_APPROVAL_SCOPES:
        errors.append(f"Unsupported approval_scope: {approval_scope}")
    if expected_scope and approval_scope != expected_scope:
        errors.append(f"Approval scope mismatch: expected {expected_scope}, got {approval_scope}")

    if not isinstance(reviewer_id, str) or not reviewer_id.strip():
        errors.append("Invalid or missing reviewer_id")
    if not isinstance(key_id, str) or not key_id.strip():
        errors.append("Invalid or missing reviewer_key_id")

    # 3. Check key in trust registry
    key_entry = keys_by_id.get(key_id) if key_id else None
    if not key_entry:
        errors.append(f"Reviewer key_id '{key_id}' is absent from trust registry")
        return ApprovalResult(ok=False, errors=tuple(errors))

    # Reviewer independence check: mandatory
    if key_entry.get("reviewer_role") != "independent":
        errors.append(f"Reviewer role is '{key_entry.get('reviewer_role')}'; must be 'independent'")

    if key_entry.get("reviewer_id") != reviewer_id:
        errors.append("Reviewer identity mismatch between approval payload and trust registry")

    # Check key revocation
    revoked_at_raw = key_entry.get("revoked_at")
    if key_entry.get("revoked") is True or revoked_at_raw is not None:
        if revoked_at_raw is not None:
            try:
                revoked_at = _utc(revoked_at_raw)
                errors.append(f"Reviewer key was revoked at {revoked_at.isoformat()}")
            except ValueError:
                errors.append("Invalid revoked_at timestamp in key entry; key treated as revoked")
        else:
            errors.append("Reviewer key is revoked")

    # Check key validity window
    try:
        key_valid_from = _utc(key_entry.get("valid_from"))
        key_valid_until = _utc(key_entry.get("valid_until"))
    except ValueError as e:
        errors.append(f"Invalid key validity timestamps: {e}")
        key_valid_from = key_valid_until = None

    # Check approval timestamps
    try:
        issued_at = _utc(payload.get("issued_at"))
        expires_at = _utc(payload.get("expires_at"))
    except ValueError as e:
        errors.append(f"Invalid approval timestamps: {e}")
        issued_at = expires_at = None

    if issued_at and expires_at:
        if expires_at <= issued_at:
            errors.append("Approval expires_at must be strictly after issued_at")
        lifetime_days = (expires_at - issued_at).total_seconds() / 86400.0
        if lifetime_days > MAX_APPROVAL_LIFETIME_DAYS:
            errors.append(f"Approval lifetime {lifetime_days:.1f} days exceeds {MAX_APPROVAL_LIFETIME_DAYS} days limit")
        if current_time < issued_at:
            errors.append("Approval was issued in the future")
        if current_time > expires_at:
            errors.append(f"Approval expired at {expires_at.isoformat()}")

        if key_valid_from and key_valid_until:
            if not (key_valid_from <= issued_at <= key_valid_until):
                errors.append("Approval issued_at is outside the authorized key validity period")

    # Check repository match
    if payload.get("repository") != repository:
        errors.append(f"Repository mismatch: expected {repository}, got {payload.get('repository')}")

    # Check review attestation
    if payload.get("review_attestation") is not True:
        errors.append("Explicit review_attestation is required and must be true")

    # 4. Check source document digest binding
    doc_sha = payload.get("source_document_sha256")
    if not isinstance(doc_sha, str) or not SHA256_RE.fullmatch(doc_sha.lower()):
        errors.append("Invalid source_document_sha256 in payload")
    elif expected_source_sha256:
        if doc_sha.lower() != expected_source_sha256.lower():
            errors.append(f"Source document digest mismatch: expected {expected_source_sha256}, got {doc_sha}")

    # 5. Check structured records binding
    records_sha = payload.get("structured_records_sha256")
    if not isinstance(records_sha, str) or not SHA256_RE.fullmatch(records_sha.lower()):
        errors.append("Invalid structured_records_sha256 in payload")
    elif structured_records is not None:
        try:
            actual_records_sha = canonical_sha256(structured_records)
            if records_sha.lower() != actual_records_sha.lower():
                errors.append(
                    f"Structured records digest mismatch: canonical digest {actual_records_sha} != signed {records_sha}"
                )
        except Exception as e:
            errors.append(f"Failed to canonicalize and hash structured records: {e}")

    # 6. Check scheme_id binding if provided
    if expected_scheme_id:
        payload_scheme_id = payload.get("scheme_id")
        if payload_scheme_id != expected_scheme_id:
            errors.append(f"Scheme ID mismatch: expected {expected_scheme_id}, got {payload_scheme_id}")

    # 6b. Check commit_sha binding
    commit_sha = payload.get("commit_sha")
    if commit_sha is not None:
        if not isinstance(commit_sha, str) or not COMMIT_RE.fullmatch(commit_sha.lower()):
            errors.append("Invalid commit_sha in approval payload: must be a 40-character hex string")
        elif expected_commit_sha is not None:
            if commit_sha.lower() != expected_commit_sha.lower():
                errors.append(f"Commit SHA mismatch: expected {expected_commit_sha}, got {commit_sha}")
    elif require_commit_binding:
        errors.append("Approval payload is missing required commit_sha binding")

    # 6c. Check policy_digest binding
    policy_digest = payload.get("policy_digest") or payload.get("policy_sha256")
    if policy_digest is not None:
        if not isinstance(policy_digest, str) or not SHA256_RE.fullmatch(policy_digest.lower()):
            errors.append("Invalid policy_digest in approval payload: must be a 64-character hex SHA-256")
        elif expected_policy_digest is not None:
            if policy_digest.lower() != expected_policy_digest.lower():
                errors.append(f"Policy digest mismatch: expected {expected_policy_digest}, got {policy_digest}")
    elif require_policy_binding:
        errors.append("Approval payload is missing required policy_digest binding")

    # 6d. Check artifact_digest / bundle_sha256 binding
    art_digest = payload.get("artifact_digest") or payload.get("bundle_sha256")
    if art_digest is not None:
        if not isinstance(art_digest, str) or not SHA256_RE.fullmatch(art_digest.lower()):
            errors.append("Invalid artifact_digest in approval payload: must be a 64-character hex SHA-256")
        elif expected_artifact_digest is not None:
            if art_digest.lower() != expected_artifact_digest.lower():
                errors.append(f"Artifact digest mismatch: expected {expected_artifact_digest}, got {art_digest}")
    elif require_artifact_binding or expected_artifact_digest is not None:
        errors.append("Approval payload is missing required artifact_digest binding")

    # 7. Cryptographic Ed25519 signature verification
    try:
        pub_bytes = _b64url_decode(key_entry.get("public_key"), 32)
        sig_bytes = _b64url_decode(sig_raw, 64)
        public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
        canonical_payload_bytes = canonical_jcs(payload)
        public_key.verify(sig_bytes, canonical_payload_bytes)
    except InvalidSignature:
        errors.append("Ed25519 signature verification failed")
    except Exception as e:
        errors.append(f"Cryptographic verification error: {e}")

    if errors:
        return ApprovalResult(
            ok=False,
            errors=tuple(errors),
            approval_id=approval_id,
            reviewer_id=reviewer_id,
            key_id=key_id,
            scope=approval_scope,
        )

    return ApprovalResult(
        ok=True,
        approval_id=approval_id,
        reviewer_id=reviewer_id,
        key_id=key_id,
        scope=approval_scope,
    )


def create_sip_reviewer_approval_envelope(
    private_key: Ed25519PrivateKey,
    *,
    key_id: str,
    reviewer_id: str,
    scope: str,
    source_bytes: bytes,
    structured_records: Any,
    scheme_id: Optional[str] = None,
    source_url: Optional[str] = None,
    commit_sha: Optional[str] = None,
    policy_digest: Optional[str] = None,
    artifact_digest: Optional[str] = None,
    repository: str = "o0k00l/MF-AI-Based",
    issued_at: Optional[datetime] = None,
    expires_at: Optional[datetime] = None,
    approval_id: Optional[str] = None,
    publisher: Optional[str] = None,
    verification_method: Optional[str] = None,
    verified_at: Optional[str] = None,
    evidence_reference: Optional[str] = None,
) -> Dict[str, Any]:
    """Helper to generate a valid detached approval envelope for testing and ceremony use."""
    now = issued_at or datetime.now(timezone.utc)
    exp = expires_at or (now.replace(microsecond=0) + (timezone.utc.utcoffset(now) or timezone.utc.utcoffset(datetime.now(timezone.utc))))
    # Default 30-day expiry
    from datetime import timedelta
    if expires_at is None:
        exp = now + timedelta(days=30)

    source_sha256 = hashlib.sha256(source_bytes).hexdigest().lower()
    records_sha256 = canonical_sha256(structured_records)

    payload: Dict[str, Any] = {
        "schema_version": 1,
        "approval_id": approval_id or f"sip-appr-{hashlib.sha256(source_bytes[:32]).hexdigest()[:12]}",
        "approval_scope": scope,
        "reviewer_id": reviewer_id,
        "reviewer_key_id": key_id,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": exp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": repository,
        "source_document_sha256": source_sha256,
        "structured_records_sha256": records_sha256,
        "review_attestation": True,
    }
    if scope == "STATEMENT_PUBLISHER_AUTHENTICATION":
        payload.update({
            "publisher": publisher,
            "verification_method": verification_method,
            "verified_at": verified_at,
            "evidence_reference": evidence_reference,
            "source_url": source_url,
        })
    if scheme_id is not None:
        payload["scheme_id"] = scheme_id
    if source_url is not None:
        payload["source_url"] = source_url
    if commit_sha is not None:
        if not COMMIT_RE.fullmatch(commit_sha.lower()):
            raise ValueError(f"commit_sha must be a 40-character hex string, got {commit_sha!r}")
        payload["commit_sha"] = commit_sha.lower()
    if policy_digest is not None:
        if not SHA256_RE.fullmatch(policy_digest.lower()):
            raise ValueError(f"policy_digest must be a 64-character hex SHA-256, got {policy_digest!r}")
        payload["policy_digest"] = policy_digest.lower()
    if artifact_digest is not None:
        if not SHA256_RE.fullmatch(artifact_digest.lower()):
            raise ValueError(f"artifact_digest must be a 64-character hex SHA-256, got {artifact_digest!r}")
        payload["artifact_digest"] = artifact_digest.lower()

    canonical_bytes = canonical_jcs(payload)
    signature_bytes = private_key.sign(canonical_bytes)
    return {
        "payload": payload,
        "signature": _b64url_encode(signature_bytes),
    }


def create_sip_trust_registry(keys: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Create a standardized SIP reviewer trust registry structure."""
    return {
        "schema_version": 1,
        "keys": keys,
    }

