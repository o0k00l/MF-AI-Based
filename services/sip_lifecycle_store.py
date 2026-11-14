"""Append-only, privacy-minimal SIP recommendation lifecycle.

Only opaque actor identifiers, reason codes, decision/policy/source digests and
timestamps are persisted. Investor payloads, CAS data, holdings, amounts and
contact details are never accepted by this module. Storage is opt-in and must
be outside the Git checkout.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows compatibility
    fcntl = None

_ENV_NAME = "MF_SIP_LIFECYCLE_DIR"
_STATES = {"DRAFT", "REVIEWED", "SUPERSEDED", "WITHDRAWN"}
_TERMINAL = {"SUPERSEDED", "WITHDRAWN"}
_OPAQUE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


def _digest(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field} must be a 64-character SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _opaque(value: str, field: str) -> str:
    if not isinstance(value, str) or not _OPAQUE_ID.fullmatch(value):
        raise ValueError(f"{field} must be an opaque identifier")
    return value


def _reason(value: str) -> str:
    if not isinstance(value, str) or not _REASON_CODE.fullmatch(value):
        raise ValueError("reason_code must be an uppercase machine-readable code")
    return value


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _storage_root(storage_dir: str | Path | None) -> Path | None:
    configured = storage_dir if storage_dir is not None else os.getenv(_ENV_NAME)
    if configured is None or not str(configured).strip():
        return None
    root = Path(configured).expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[1]
    try:
        root.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise ValueError("SIP lifecycle store must be outside the Git checkout")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    try:
        root.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise ValueError("SIP lifecycle store must resolve outside the Git checkout")
    if not root.is_dir():
        raise ValueError("SIP lifecycle store must be a directory")
    return root


@contextmanager
def _decision_lock(root: Path, digest: str) -> Iterator[None]:
    lock_path = root / f".{digest}.lock"
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _write_exclusive(path: Path, record: Mapping[str, Any]) -> None:
    payload = _canonical(record)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def persist_draft_snapshot(
    *,
    decision_trace_sha256: str,
    storage_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Backward-compatible minimal DRAFT persistence (not reviewable)."""
    digest = _digest(decision_trace_sha256, "decision trace digest")
    root = _storage_root(storage_dir)
    if root is None:
        return {"state": "DRAFT", "state_persisted": False, "persistence_status": "STORE_NOT_CONFIGURED"}
    record = {
        "schema_version": 1,
        "state": "DRAFT",
        "decision_trace_sha256": digest,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "execution_authorized": False,
    }
    path = root / f"{digest}.json"
    try:
        _write_exclusive(path, record)
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("existing lifecycle record is unreadable") from exc
        if not isinstance(existing, dict) or existing.get("schema_version") != 1 or existing.get("state") != "DRAFT" or existing.get("decision_trace_sha256") != digest or existing.get("execution_authorized") is not False:
            raise ValueError("existing lifecycle record conflicts with this decision trace")
        return {"state": "DRAFT", "state_persisted": True, "persistence_status": "ALREADY_RECORDED"}
    return {"state": "DRAFT", "state_persisted": True, "persistence_status": "RECORDED"}


def create_reviewable_draft(
    *,
    decision_trace_sha256: str,
    policy_sha256: str,
    source_evidence_sha256: str,
    author_id: str,
    storage_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Create a v2 DRAFT bound to its creator, effective policy and source snapshot."""
    digest = _digest(decision_trace_sha256, "decision trace digest")
    policy = _digest(policy_sha256, "policy digest")
    source = _digest(source_evidence_sha256, "source evidence digest")
    author = _opaque(author_id, "author_id")
    root = _storage_root(storage_dir)
    if root is None:
        return {"state": "DRAFT", "state_persisted": False, "persistence_status": "STORE_NOT_CONFIGURED"}
    record = {
        "schema_version": 2,
        "state": "DRAFT",
        "decision_trace_sha256": digest,
        "policy_sha256": policy,
        "source_evidence_sha256": source,
        "created_by": author,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "execution_authorized": False,
    }
    path = root / f"{digest}.json"
    with _decision_lock(root, digest):
        try:
            _write_exclusive(path, record)
        except FileExistsError:
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("existing lifecycle record is unreadable") from exc
            if existing != record and not (
                existing.get("schema_version") == 2
                and existing.get("decision_trace_sha256") == digest
                and existing.get("created_by") == author
                and existing.get("policy_sha256") == policy
                and existing.get("source_evidence_sha256") == source
                and existing.get("execution_authorized") is False
            ):
                raise ValueError("existing lifecycle record conflicts with this decision trace")
            return {"state": "DRAFT", "state_persisted": True, "persistence_status": "ALREADY_RECORDED"}
    return {"state": "DRAFT", "state_persisted": True, "persistence_status": "RECORDED"}


def _load_state(root: Path, digest: str) -> tuple[dict[str, Any], str, int]:
    path = root / f"{digest}.json"
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("lifecycle draft is missing or unreadable") from exc
    if not isinstance(draft, dict) or draft.get("schema_version") != 2 or draft.get("decision_trace_sha256") != digest or draft.get("execution_authorized") is not False:
        raise ValueError("lifecycle draft is not a valid reviewable v2 record")
    previous = hashlib.sha256(_canonical(draft)).hexdigest()
    state = "DRAFT"
    sequence = 0
    event_dir = root / "events" / digest
    if event_dir.exists():
        for event_path in sorted(event_dir.glob("*.json")):
            try:
                event = json.loads(event_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError("lifecycle event is unreadable") from exc
            event_hash = event.pop("event_sha256", None)
            if event.get("sequence") != sequence + 1 or event.get("previous_event_sha256") != previous or hashlib.sha256(_canonical(event)).hexdigest() != event_hash:
                raise ValueError("lifecycle event chain is invalid or tampered")
            if event.get("from_state") != state or event.get("state") not in _STATES:
                raise ValueError("lifecycle event contains an invalid state transition")
            state = event["state"]
            sequence += 1
            previous = event_hash
    return draft, previous, sequence


def transition_lifecycle(
    *,
    decision_trace_sha256: str,
    to_state: str,
    actor_id: str,
    reason_code: str,
    policy_sha256: str,
    source_evidence_sha256: str,
    authorized_reviewer_ids: set[str] | frozenset[str] = frozenset(),
    authorized_operator_ids: set[str] | frozenset[str] = frozenset(),
    replacement_decision_trace_sha256: str | None = None,
    storage_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Append one authorized, immutable lifecycle transition.

    REVIEWED requires a trusted reviewer registry input and reviewer/author
    separation. Registry membership must come from deployment-owned trust
    configuration, never an investor request or editable request flag.
    """
    digest = _digest(decision_trace_sha256, "decision trace digest")
    policy = _digest(policy_sha256, "policy digest")
    source = _digest(source_evidence_sha256, "source evidence digest")
    actor = _opaque(actor_id, "actor_id")
    reason = _reason(reason_code)
    if to_state not in {"REVIEWED", "SUPERSEDED", "WITHDRAWN"}:
        raise ValueError("unsupported lifecycle target state")
    root = _storage_root(storage_dir)
    if root is None:
        return {"state": "DRAFT", "state_persisted": False, "persistence_status": "STORE_NOT_CONFIGURED"}
    with _decision_lock(root, digest):
        draft, previous, sequence = _load_state(root, digest)
        current = "DRAFT"
        event_dir = root / "events" / digest
        if sequence:
            latest = sorted(event_dir.glob("*.json"))[-1]
            current = json.loads(latest.read_text(encoding="utf-8"))["state"]
        if current in _TERMINAL:
            raise ValueError("terminal lifecycle state cannot transition")
        if to_state == "REVIEWED":
            if current != "DRAFT":
                raise ValueError("only a DRAFT can be REVIEWED")
            reviewers = {_opaque(item, "authorized reviewer id") for item in authorized_reviewer_ids}
            if actor not in reviewers:
                raise ValueError("reviewer is not in the trusted reviewer registry")
            if actor == draft.get("created_by"):
                raise ValueError("reviewer must be independent from the draft author")
            if policy != draft["policy_sha256"] or source != draft["source_evidence_sha256"]:
                raise ValueError("policy or source evidence changed; a new decision draft is required")
        elif to_state == "SUPERSEDED":
            if current != "REVIEWED":
                raise ValueError("only a REVIEWED recommendation can be SUPERSEDED")
            operators = {_opaque(item, "authorized operator id") for item in authorized_operator_ids}
            if actor not in operators:
                raise ValueError("superseding actor is not in the trusted operator registry")
            replacement = _digest(replacement_decision_trace_sha256 or "", "replacement decision trace digest")
            if replacement == digest:
                raise ValueError("replacement decision trace must differ")
        elif to_state == "WITHDRAWN":
            if current not in {"DRAFT", "REVIEWED"}:
                raise ValueError("only a DRAFT or REVIEWED recommendation can be WITHDRAWN")
            operators = {_opaque(item, "authorized operator id") for item in authorized_operator_ids}
            if actor != draft.get("created_by") and actor not in operators:
                raise ValueError("withdrawal actor is neither the authenticated author nor a trusted operator")
            replacement = None
        event = {
            "schema_version": 1,
            "sequence": sequence + 1,
            "from_state": current,
            "state": to_state,
            "decision_trace_sha256": digest,
            "actor_id": actor,
            "reason_code": reason,
            "policy_sha256": policy,
            "source_evidence_sha256": source,
            "replacement_decision_trace_sha256": replacement if to_state == "SUPERSEDED" else None,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "previous_event_sha256": previous,
            "execution_authorized": False,
        }
        event_hash = hashlib.sha256(_canonical(event)).hexdigest()
        event["event_sha256"] = event_hash
        event_dir.mkdir(parents=True, exist_ok=True)
        _write_exclusive(event_dir / f"{sequence + 1:08d}-{event_hash}.json", event)
    return {"state": to_state, "state_persisted": True, "event_sha256": event_hash, "persistence_status": "RECORDED"}


def get_lifecycle_status(
    *,
    decision_trace_sha256: str,
    storage_dir: str | Path | None = None,
) -> dict[str, Any]:
    digest = _digest(decision_trace_sha256, "decision trace digest")
    root = _storage_root(storage_dir)
    if root is None:
        return {"state": "UNKNOWN", "state_persisted": False, "persistence_status": "STORE_NOT_CONFIGURED"}
    draft, previous, sequence = _load_state(root, digest)
    state = "DRAFT"
    event_dir = root / "events" / digest
    if sequence:
        latest = sorted(event_dir.glob("*.json"))[-1]
        state = json.loads(latest.read_text(encoding="utf-8"))["state"]
    return {"state": state, "state_persisted": True, "event_count": sequence, "last_event_sha256": previous, "execution_authorized": False}


def assess_review_triggers(
    *,
    decision_policy_sha256: str,
    current_policy_sha256: str,
    decision_source_evidence_sha256: str,
    current_source_evidence_sha256: str,
    decision_holdings_sha256: str,
    current_holdings_sha256: str,
    decision_mandate_sha256: str,
    current_mandate_sha256: str,
    decision_scheme_status_sha256: str,
    current_scheme_status_sha256: str,
    evidence_as_of: datetime,
    now: datetime,
    maximum_evidence_age_days: int,
    review_due_at: datetime | None = None,
) -> dict[str, Any]:
    """Compare decision-bound facts with current facts using effective-policy freshness."""
    digests = (
        (decision_policy_sha256, current_policy_sha256, "EFFECTIVE_POLICY_CHANGED"),
        (decision_source_evidence_sha256, current_source_evidence_sha256, "SOURCE_EVIDENCE_CHANGED"),
        (decision_holdings_sha256, current_holdings_sha256, "PORTFOLIO_HOLDINGS_CHANGED"),
        (decision_mandate_sha256, current_mandate_sha256, "INVESTOR_MANDATE_CHANGED"),
        (decision_scheme_status_sha256, current_scheme_status_sha256, "SCHEME_STATUS_CHANGED"),
    )
    triggers = [label for old, new, label in digests if _digest(old, "decision digest") != _digest(new, "current digest")]
    if not isinstance(now, datetime) or not isinstance(evidence_as_of, datetime) or now.tzinfo is None or evidence_as_of.tzinfo is None:
        raise ValueError("review timestamps must be timezone-aware datetimes")
    if isinstance(maximum_evidence_age_days, bool) or not isinstance(maximum_evidence_age_days, int) or maximum_evidence_age_days < 0:
        raise ValueError("maximum_evidence_age_days must come from a non-negative effective policy value")
    if evidence_as_of > now:
        triggers.append("EVIDENCE_TIMESTAMP_IN_FUTURE")
    elif now - evidence_as_of > timedelta(days=maximum_evidence_age_days):
        triggers.append("EVIDENCE_STALE")
    if review_due_at is not None:
        if not isinstance(review_due_at, datetime) or review_due_at.tzinfo is None:
            raise ValueError("review_due_at must be timezone-aware")
        if now >= review_due_at:
            triggers.append("POLICY_REVIEW_DUE")
    return {"review_required": bool(triggers), "status": "REVIEW_REQUIRED" if triggers else "CURRENT", "trigger_codes": sorted(set(triggers)), "execution_authorized": False}
