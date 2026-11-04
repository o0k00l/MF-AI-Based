"""Detached Ed25519 reviewer approval verification for TRI evidence.

The public-key registry is supplied by a separately administered environment
variable. No key embedded in a fixture or approval envelope is trusted.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ENV_REGISTRY = "TRI_REVIEWER_TRUST_REGISTRY_JSON"
ENV_APPROVAL = "TRI_REVIEWER_APPROVAL_JSON"
MAX_APPROVAL_LIFETIME_DAYS = 90
REQUIRED_BENCHMARKS = {
    "NIFTY 500 TRI", "NIFTY 500 MULTICAP 50:25:25 TRI", "NIFTY MIDCAP 150 TRI"
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_PAYLOAD_FIELDS = {
    "schema_version", "approval_id", "approval_scope", "reviewer_id",
    "reviewer_key_id", "issued_at", "expires_at", "repository",
    "commit_sha", "tri_fixture_sha256", "tri_source_documents",
    "calendar_source_sha256", "calendar_sessions_sha256", "review_attestation",
}


@dataclass(frozen=True)
class ApprovalResult:
    ok: bool
    errors: tuple[str, ...] = ()
    approval_id: str | None = None
    reviewer_id: str | None = None
    key_id: str | None = None


def _utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("timestamp must be UTC RFC3339 ending in Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return parsed


def _strict_json(raw: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def _b64url(value: Any, expected_length: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("signature/public key must be unpadded base64url")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(decoded) != expected_length:
        raise ValueError("decoded cryptographic value has incorrect length")
    return decoded


def verify_approval(
    envelope: Any,
    registry: Any,
    *,
    repository: str,
    expected_commit: str,
    fixture_path: Path,
    root: Path,
    now: datetime | None = None,
) -> ApprovalResult:
    errors: list[str] = []
    try:
        if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
            raise ValueError("approval envelope must contain exactly payload and signature")
        payload = envelope["payload"]
        if not isinstance(payload, dict) or set(payload) != REQUIRED_PAYLOAD_FIELDS:
            raise ValueError("approval payload fields do not match the supported schema")
        if payload["schema_version"] != 1 or payload["approval_scope"] != "TRI_EVIDENCE_RELEASE":
            raise ValueError("unsupported schema version or approval scope")
        if payload["repository"] != repository:
            raise ValueError("approval repository does not match")
        if not isinstance(expected_commit, str) or not COMMIT_RE.fullmatch(expected_commit):
            raise ValueError("expected commit SHA is missing or invalid")
        if payload["commit_sha"] != expected_commit or not COMMIT_RE.fullmatch(str(payload["commit_sha"])):
            raise ValueError("approval is not bound to the exact release commit")
        if not isinstance(payload["approval_id"], str) or not payload["approval_id"].strip():
            raise ValueError("approval_id is missing")
        if payload["review_attestation"] is not True:
            raise ValueError("review_attestation must be explicitly true")
        issued, expires = _utc(payload["issued_at"]), _utc(payload["expires_at"])
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None:
            raise ValueError("verification clock must be timezone-aware")
        if issued > clock:
            raise ValueError("approval issue time is in the future")
        if expires <= clock or expires <= issued:
            raise ValueError("approval is expired or has an invalid expiry")
        if (expires - issued).total_seconds() > MAX_APPROVAL_LIFETIME_DAYS * 86400:
            raise ValueError("approval lifetime exceeds the 90-day maximum")

        if not isinstance(registry, dict) or registry.get("schema_version") != 1:
            raise ValueError("trust registry is missing or has unsupported schema")
        keys = registry.get("keys")
        if not isinstance(keys, list):
            raise ValueError("trust registry keys must be a list")
        key_id = payload["reviewer_key_id"]
        matches = [entry for entry in keys if isinstance(entry, dict) and entry.get("key_id") == key_id]
        if len(matches) != 1:
            raise ValueError("reviewer key is unknown or duplicated in trust registry")
        entry = matches[0]
        if entry.get("reviewer_id") != payload["reviewer_id"]:
            raise ValueError("reviewer identity does not match trusted key registry")
        key_from, key_until = _utc(entry.get("valid_from")), _utc(entry.get("valid_until"))
        if issued < key_from or issued >= key_until or clock < key_from or clock >= key_until:
            raise ValueError("reviewer key is not valid at approval issuance and verification time")
        revoked_at = entry.get("revoked_at")
        if revoked_at is not None and clock >= _utc(revoked_at):
            raise ValueError("reviewer key is revoked; all outstanding approvals are invalid")
        public_key = Ed25519PublicKey.from_public_bytes(_b64url(entry.get("public_key"), 32))
        signature = _b64url(envelope["signature"], 64)
        public_key.verify(signature, rfc8785.dumps(payload))

        if not SHA256_RE.fullmatch(str(payload["tri_fixture_sha256"])):
            raise ValueError("fixture SHA-256 is malformed")
        actual_fixture = __import__("hashlib").sha256(fixture_path.read_bytes()).hexdigest()
        if actual_fixture != payload["tri_fixture_sha256"]:
            raise ValueError("signed TRI fixture digest does not match")
        if not SHA256_RE.fullmatch(str(payload["calendar_source_sha256"])) or not SHA256_RE.fullmatch(str(payload["calendar_sessions_sha256"])):
            raise ValueError("calendar digests are malformed")
        if not isinstance(payload["tri_source_documents"], list) or not payload["tri_source_documents"]:
            raise ValueError("signed TRI source document manifest is empty")
        paths: set[str] = set()
        covered_benchmarks: set[str] = set()
        for item in payload["tri_source_documents"]:
            if not isinstance(item, dict) or set(item) != {"benchmark", "path", "sha256"}:
                raise ValueError("each TRI source document requires benchmark, path and sha256")
            benchmark_name = item["benchmark"]
            if benchmark_name not in REQUIRED_BENCHMARKS or benchmark_name in covered_benchmarks:
                raise ValueError("source manifest benchmark names must be required, unique and exact")
            covered_benchmarks.add(benchmark_name)
            rel = item["path"]
            if not isinstance(rel, str) or not rel or rel in paths:
                raise ValueError("source document paths must be non-empty and unique")
            paths.add(rel)
            candidate = Path(rel)
            if candidate.is_absolute():
                raise ValueError("source document path must be repository-relative")
            resolved = (root / candidate).resolve()
            resolved.relative_to(root.resolve())
            if not resolved.is_file():
                raise ValueError(f"signed source document is missing: {rel}")
            if not SHA256_RE.fullmatch(str(item["sha256"])):
                raise ValueError(f"source document digest is malformed: {rel}")
            actual = __import__("hashlib").sha256(resolved.read_bytes()).hexdigest()
            if actual != item["sha256"]:
                raise ValueError(f"signed source document digest mismatch: {rel}")
        if covered_benchmarks != REQUIRED_BENCHMARKS:
            raise ValueError("signed source manifest must contain one source document for every required benchmark")
        cal = root / "data/policy/nse_trading_calendar.json"
        if not cal.is_file() or __import__("hashlib").sha256(cal.read_bytes()).hexdigest() != payload["calendar_source_sha256"]:
            raise ValueError("signed NSE calendar source digest is missing or mismatched")
        calendar = _strict_json(cal.read_text(encoding="utf-8"))
        sessions = calendar.get("sessions") if isinstance(calendar, dict) else None
        if not isinstance(sessions, list) or not sessions or sessions != sorted(set(sessions)):
            raise ValueError("calendar sessions are malformed, unsorted or duplicated")
        from datetime import date
        for day in sessions:
            parsed = date.fromisoformat(day)
            if parsed.isoformat() != day or parsed.weekday() >= 5:
                raise ValueError(f"calendar contains a non-session date or weekend: {day}")
        normalized = rfc8785.dumps(sessions)
        if __import__("hashlib").sha256(normalized).hexdigest() != payload["calendar_sessions_sha256"]:
            raise ValueError("signed normalized calendar sessions digest mismatch")
        return ApprovalResult(True, (), payload["approval_id"], payload["reviewer_id"], key_id)
    except (ValueError, TypeError, KeyError, OSError, InvalidSignature, binascii.Error, OverflowError) as exc:
        errors.append(f"signed TRI reviewer approval invalid: {exc}")
    except Exception as exc:
        # Cryptographic/parser errors must fail closed; do not expose stack traces in reports.
        errors.append(f"signed TRI reviewer approval verification failed: {type(exc).__name__}")
    return ApprovalResult(False, tuple(errors))


def verify_approval_from_environment(
    *, repository: str, expected_commit: str | None, fixture_path: Path, root: Path
) -> ApprovalResult:
    raw_registry = os.environ.get(ENV_REGISTRY)
    if not raw_registry:
        return ApprovalResult(False, (f"{ENV_REGISTRY} is not configured; release remains blocked",))
    if not expected_commit:
        return ApprovalResult(False, ("expected release commit SHA was not supplied; release remains blocked",))
    raw_approval = os.environ.get(ENV_APPROVAL)
    if not raw_approval:
        return ApprovalResult(False, (f"{ENV_APPROVAL} is not configured; release remains blocked",))
    try:
        registry = _strict_json(raw_registry)
        envelope = _strict_json(raw_approval)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return ApprovalResult(False, (f"signed TRI approval/trust registry cannot be loaded: {exc}",))
    return verify_approval(
        envelope, registry, repository=repository, expected_commit=expected_commit,
        fixture_path=fixture_path, root=root,
    )
