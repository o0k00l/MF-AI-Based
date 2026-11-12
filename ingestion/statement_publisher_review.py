"""Independent Ed25519 reviewer verification for uploaded CAS publisher provenance."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from ingestion.statement_validator import StatementValidationResult, authenticate_statement_provenance

TRUST_REGISTRY_ENV = "STATEMENT_PUBLISHER_TRUST_REGISTRY_JSON"
MAX_REGISTRY_BYTES = 256 * 1024
MAX_APPROVAL_BYTES = 1024 * 1024
APPROVAL_SCOPE = "STATEMENT_PUBLISHER_AUTHENTICATION"


def load_statement_publisher_trust_registry() -> dict[str, Any]:
    raw = os.getenv(TRUST_REGISTRY_ENV)
    if not raw or not raw.strip():
        raise ValueError(f"{TRUST_REGISTRY_ENV} is required")
    if len(raw.encode("utf-8")) > MAX_REGISTRY_BYTES:
        raise ValueError("Statement publisher trust registry exceeds maximum size")
    from services.sip_reviewer_approval import _strict_json
    registry = _strict_json(raw)
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        raise ValueError("Statement publisher trust registry has an unsupported schema")
    if not isinstance(registry.get("keys"), list) or not registry["keys"]:
        raise ValueError("Statement publisher trust registry must contain independent reviewer keys")
    return registry


def authenticate_statement_with_reviewer_approval(
    result: StatementValidationResult,
    approval_envelope: dict[str, Any] | str,
    trust_registry: dict[str, Any],
) -> StatementValidationResult:
    """Promote provenance only after a trusted independent reviewer signs exact bytes and claims."""
    from services.sip_reviewer_approval import verify_sip_reviewer_approval

    if isinstance(approval_envelope, str):
        if len(approval_envelope.encode("utf-8")) > MAX_APPROVAL_BYTES:
            raise ValueError("Statement publisher approval exceeds maximum size")
        approval_envelope = json.loads(approval_envelope)
    if not isinstance(approval_envelope, dict) or set(approval_envelope) != {"payload", "signature"}:
        raise ValueError("Statement publisher approval must be a detached signed envelope")
    payload = approval_envelope.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("Statement publisher approval payload must be an object")
    publisher = payload.get("publisher")
    method = payload.get("verification_method")
    verified_at = payload.get("verified_at")
    evidence_reference = payload.get("evidence_reference")
    source_url = payload.get("source_url")
    if publisher not in {"CAMS", "KFintech", "MFCentral"}:
        raise ValueError("Signed review must identify CAMS, KFintech or MFCentral")
    if method != "INDEPENDENT_REVIEW":
        raise ValueError("Publisher authentication requires an independent reviewer attestation")
    if not isinstance(verified_at, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", verified_at):
        raise ValueError("Signed review requires canonical UTC RFC3339 verified_at")
    parsed_verified_at = datetime.fromisoformat(verified_at[:-1] + "+00:00")
    if parsed_verified_at.tzinfo is None or parsed_verified_at.utcoffset() != timezone.utc.utcoffset(parsed_verified_at):
        raise ValueError("Signed review verified_at must be UTC")
    if not isinstance(evidence_reference, str) or not evidence_reference.strip():
        raise ValueError("Signed review requires a durable evidence_reference")
    if source_url is not None and (not isinstance(source_url, str) or not source_url.startswith("https://")):
        raise ValueError("source_url, when supplied, must use HTTPS")

    records = {
        "document_type": result.document_type,
        "publisher": publisher,
        "verification_method": method,
        "verified_at": verified_at,
        "evidence_reference": evidence_reference,
        "source_url": source_url,
    }
    approval = verify_sip_reviewer_approval(
        approval_envelope,
        trust_registry,
        expected_scope=APPROVAL_SCOPE,
        expected_source_sha256=result.provenance_digest,
        structured_records=records,
    )
    if not approval.ok:
        raise ValueError("Independent statement publisher review rejected: " + "; ".join(approval.errors))

    evidence = {
        "source_digest": result.provenance_digest,
        "publisher": publisher,
        "verification_method": method,
        "verified_at": verified_at,
        "evidence_reference": evidence_reference,
        "source_url": source_url,
        "reviewer_approval_id": approval.approval_id,
        "reviewer_id": approval.reviewer_id,
        "reviewer_key_id": approval.key_id,
        "review_scope": approval.scope,
    }
    return authenticate_statement_provenance(
        result,
        evidence,
        trusted_verifier=lambda digest, signed_publisher, signed_evidence: (
            approval.ok and digest == result.provenance_digest
            and signed_publisher == publisher and signed_evidence == evidence
        ),
    )


def public_statement_provenance(result: StatementValidationResult) -> dict[str, Any]:
    """Safe user-facing and decision-trace representation; never infer identity."""
    authenticated = result.is_publisher_authenticated is True
    return {
        "document_type": result.document_type,
        "structural_validity": bool(result.structural_validity and result.is_valid),
        "source_sha256": result.provenance_digest,
        "publisher_claimed_by_document": result.detected_content_publisher,
        "publisher_authenticity_status": result.publisher_authenticity_status,
        "is_publisher_authenticated": authenticated,
        "authenticated_publisher": result.authenticated_publisher if authenticated else None,
        "rta_source": result.rta_source if authenticated else "Unknown",
        "review_evidence": ({
            key: result.provenance_source.get(key)
            for key in ("verification_method", "verified_at", "evidence_reference",
                        "reviewer_approval_id", "reviewer_id", "reviewer_key_id")
        } if authenticated else None),
    }
