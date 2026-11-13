"""Cryptographic authentication for investor SIP mandate schedules.

The trust root is deployment-owned configuration, never supplied by the uploaded
CAS, evidence bundle, or request payload. The signed envelope binds original
source bytes, the complete normalized schedule, and the investor owner reference.
"""
from __future__ import annotations

import base64
import binascii
from datetime import date, datetime, timezone
import hashlib
import json
import os
import re
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


TRUST_REGISTRY_ENV = "SIP_MANDATE_TRUST_REGISTRY_JSON"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RFC3339_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
_AUTH_METHOD_TO_SIGNER_TYPE = {
    "REGISTRAR_SIGNED": "REGISTRAR",
    "AMC_SIGNED": "AMC",
    "BANK_MANDATE_SIGNED": "BANK",
    "INVESTOR_SIGNED_CONFIRMATION": "INVESTOR",
}


class MandateAuthenticationError(ValueError):
    """A mandate schedule failed cryptographic or identity verification."""


def _strict_json(raw: str) -> Any:
    def reject_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=reject_duplicates, parse_constant=lambda v: (_ for _ in ()).throw(ValueError(v)))


def _decode_b64url(value: Any, expected_length: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise MandateAuthenticationError("Cryptographic value must be canonical base64url")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise MandateAuthenticationError("Cryptographic value has invalid encoding") from exc
    if len(decoded) != expected_length or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise MandateAuthenticationError("Cryptographic value has invalid encoding or length")
    return decoded


def _utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not _RFC3339_UTC_RE.fullmatch(value):
        raise MandateAuthenticationError(f"{label} must be canonical UTC RFC3339")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise MandateAuthenticationError(f"{label} is invalid") from exc


def load_mandate_trust_registry() -> dict[str, Any]:
    """Load the separately administered mandate signer trust root."""
    raw = os.getenv(TRUST_REGISTRY_ENV)
    if not raw or not raw.strip():
        raise MandateAuthenticationError(f"{TRUST_REGISTRY_ENV} is required")
    if len(raw.encode("utf-8")) > 256 * 1024:
        raise MandateAuthenticationError("Mandate trust registry exceeds size limit")
    try:
        registry = _strict_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        raise MandateAuthenticationError("Mandate trust registry JSON is invalid") from exc
    if not isinstance(registry, dict) or type(registry.get("schema_version")) is not int or registry.get("schema_version") != 1:
        raise MandateAuthenticationError("Mandate trust registry schema is unsupported")
    keys = registry.get("keys")
    if not isinstance(keys, list) or not keys:
        raise MandateAuthenticationError("Mandate trust registry has no active keys")
    return registry


def verify_mandate_schedule(
    evidence: Any,
    *,
    owner_ref: str,
    as_of: date,
    trust_registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify Ed25519 signer authority and bind schedule + source bytes + owner."""
    if not isinstance(evidence, dict):
        raise MandateAuthenticationError("Mandate evidence must be a mapping")
    if not isinstance(owner_ref, str) or not owner_ref.strip():
        raise MandateAuthenticationError("Investor owner reference is required")
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise MandateAuthenticationError("Decision as-of must be a date")

    source_bytes = evidence.get("source_bytes")
    if not isinstance(source_bytes, bytes) or not source_bytes or len(source_bytes) > 20 * 1024 * 1024:
        raise MandateAuthenticationError("Original mandate source bytes are missing or exceed size limit")
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    if evidence.get("source_ref") != "sha256:" + source_sha:
        raise MandateAuthenticationError("Mandate source reference does not match original source bytes")

    mandates = evidence.get("mandates")
    if not isinstance(mandates, list):
        raise MandateAuthenticationError("Mandate schedule records are malformed")
    try:
        schedule_sha = hashlib.sha256(rfc8785.dumps(mandates)).hexdigest()
    except Exception as exc:
        raise MandateAuthenticationError("Mandate schedule cannot be canonically serialized") from exc

    envelope = evidence.get("signature_envelope")
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise MandateAuthenticationError("A detached mandate signature envelope is required")
    payload = envelope.get("payload")
    required = {
        "schema_version", "signer_id", "signer_key_id", "signer_type",
        "owner_ref", "source_sha256", "schedule_sha256", "coverage_status",
        "issued_at", "expires_at",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != required
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
    ):
        raise MandateAuthenticationError("Mandate signature payload schema is invalid")
    # A signed schedule cannot prove omitted mandates do not exist unless the
    # trusted signer explicitly attests that the source extract is complete.
    if payload.get("coverage_status") != "COMPLETE":
        raise MandateAuthenticationError("Mandate schedule completeness is not signer-attested")
    if evidence.get("coverage_status") != payload["coverage_status"]:
        raise MandateAuthenticationError("Mandate schedule coverage metadata is not signature-bound")
    if payload["owner_ref"] != owner_ref:
        raise MandateAuthenticationError("Signed mandate schedule owner does not match investor")
    if payload["source_sha256"] != source_sha or payload["schedule_sha256"] != schedule_sha:
        raise MandateAuthenticationError("Signed mandate schedule does not bind the exact source and normalized records")

    signer_type = payload.get("signer_type")
    if not isinstance(signer_type, str) or signer_type not in set(_AUTH_METHOD_TO_SIGNER_TYPE.values()):
        raise MandateAuthenticationError("Mandate signer type is not an authorized issuer class")
    methods = set()
    for record in mandates:
        if not isinstance(record, dict):
            raise MandateAuthenticationError("Mandate schedule contains malformed records")
        method = record.get("authentication_method")
        if not isinstance(method, str):
            raise MandateAuthenticationError("Mandate schedule authentication method is malformed")
        methods.add(method)
    if mandates and (
        len(methods) != 1
        or _AUTH_METHOD_TO_SIGNER_TYPE.get(next(iter(methods))) != signer_type
    ):
        raise MandateAuthenticationError("Mandate signer authority does not match schedule authentication method")

    issued_at = _utc(payload["issued_at"], "Mandate signature issued_at")
    expires_at = _utc(payload["expires_at"], "Mandate signature expires_at")
    as_of_end = datetime.combine(as_of, datetime.max.time(), tzinfo=timezone.utc)
    if expires_at <= issued_at or issued_at > as_of_end or expires_at < as_of_end:
        raise MandateAuthenticationError("Mandate signature is not valid for the decision as-of date")

    registry = trust_registry if trust_registry is not None else load_mandate_trust_registry()
    if (
        not isinstance(registry, dict)
        or type(registry.get("schema_version")) is not int
        or registry.get("schema_version") != 1
    ):
        raise MandateAuthenticationError("Mandate trust registry schema is invalid")
    keys = registry.get("keys")
    if not isinstance(keys, list) or not keys:
        raise MandateAuthenticationError("Mandate trust registry contains no signer keys")
    signer_id = payload.get("signer_id")
    key_id = payload.get("signer_key_id")
    matches = [entry for entry in keys if isinstance(entry, dict) and entry.get("key_id") == key_id]
    if len(matches) != 1:
        raise MandateAuthenticationError("Mandate signer key is missing or ambiguous")
    key = matches[0]
    if key.get("signer_id") != signer_id or key.get("signer_type") != signer_type:
        raise MandateAuthenticationError("Mandate signer identity or authority does not match trust registry")
    if key.get("revoked") is not False or key.get("revoked_at") is not None:
        raise MandateAuthenticationError("Mandate signer key is revoked or lacks an explicit active state")
    key_from = _utc(key.get("valid_from"), "Signer key valid_from")
    key_until = _utc(key.get("valid_until"), "Signer key valid_until")
    if not (key_from <= issued_at <= key_until and as_of_end <= key_until):
        raise MandateAuthenticationError("Mandate signer key is not valid for the signed schedule date")
    if signer_type == "INVESTOR" and signer_id != owner_ref:
        raise MandateAuthenticationError("Investor confirmation must be signed by the matching investor identity")

    public_key = _decode_b64url(key.get("public_key"), 32)
    signature = _decode_b64url(envelope.get("signature"), 64)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, rfc8785.dumps(payload))
    except (InvalidSignature, ValueError) as exc:
        raise MandateAuthenticationError("Mandate schedule Ed25519 signature verification failed") from exc

    return {
        "status": "VERIFIED",
        "signer_id": signer_id,
        "signer_type": signer_type,
        "source_ref": "sha256:" + source_sha,
        "schedule_sha256": schedule_sha,
        "owner_ref": owner_ref,
    }
