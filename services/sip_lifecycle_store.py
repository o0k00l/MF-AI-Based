"""Privacy-minimal immutable SIP draft lifecycle persistence.

Only a decision-trace digest and workflow state are stored. No CAS bytes,
portfolio rows, names, folios, balances or investor identifiers are persisted.
The store is opt-in and must live outside the Git checkout.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ENV_NAME = "MF_SIP_LIFECYCLE_DIR"


def persist_draft_snapshot(
    *,
    decision_trace_sha256: str,
    storage_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Persist one immutable DRAFT event, idempotent by decision trace digest."""
    if not isinstance(decision_trace_sha256, str) or len(decision_trace_sha256) != 64:
        raise ValueError("decision trace digest must be a 64-character SHA-256 hex string")
    try:
        int(decision_trace_sha256, 16)
    except ValueError as exc:
        raise ValueError("decision trace digest must be hexadecimal") from exc

    configured = storage_dir if storage_dir is not None else os.getenv(_ENV_NAME)
    if configured is None or not str(configured).strip():
        return {
            "state": "DRAFT",
            "state_persisted": False,
            "persistence_status": "STORE_NOT_CONFIGURED",
        }

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

    record = {
        "schema_version": 1,
        "state": "DRAFT",
        "decision_trace_sha256": decision_trace_sha256,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "execution_authorized": False,
    }
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    path = root / f"{decision_trace_sha256}.json"
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("existing lifecycle record is unreadable") from exc
        if (
            not isinstance(existing, dict)
            or existing.get("schema_version") != 1
            or existing.get("state") != "DRAFT"
            or existing.get("decision_trace_sha256") != decision_trace_sha256
            or existing.get("execution_authorized") is not False
        ):
            raise ValueError("existing lifecycle record conflicts with this decision trace")
        return {
            "state": "DRAFT",
            "state_persisted": True,
            "persistence_status": "ALREADY_RECORDED",
        }

    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    return {
        "state": "DRAFT",
        "state_persisted": True,
        "persistence_status": "RECORDED",
    }
