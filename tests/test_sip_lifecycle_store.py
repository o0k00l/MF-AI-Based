import json
from pathlib import Path

import pytest

from services.sip_lifecycle_store import persist_draft_snapshot


def test_lifecycle_store_is_opt_in_and_does_not_require_fake_storage(monkeypatch):
    monkeypatch.delenv("MF_SIP_LIFECYCLE_DIR", raising=False)
    result = persist_draft_snapshot(decision_trace_sha256="a" * 64)
    assert result == {
        "state": "DRAFT",
        "state_persisted": False,
        "persistence_status": "STORE_NOT_CONFIGURED",
    }


def test_lifecycle_store_persists_only_minimal_trace_record_and_is_idempotent(tmp_path):
    digest = "b" * 64
    first = persist_draft_snapshot(decision_trace_sha256=digest, storage_dir=tmp_path)
    second = persist_draft_snapshot(decision_trace_sha256=digest, storage_dir=tmp_path)
    record_path = tmp_path / f"{digest}.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))

    assert first["persistence_status"] == "RECORDED"
    assert second["persistence_status"] == "ALREADY_RECORDED"
    assert first["state_persisted"] is True
    assert record["state"] == "DRAFT"
    assert record["decision_trace_sha256"] == digest
    assert record["execution_authorized"] is False
    assert set(record) == {
        "schema_version", "state", "decision_trace_sha256",
        "created_at", "execution_authorized",
    }


def test_lifecycle_store_rejects_repository_local_path(tmp_path):
    repository_root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="outside the Git checkout"):
        persist_draft_snapshot(
            decision_trace_sha256="c" * 64,
            storage_dir=repository_root / ".unsafe-lifecycle",
        )


def test_lifecycle_store_rejects_conflicting_existing_record(tmp_path):
    digest = "d" * 64
    path = tmp_path / f"{digest}.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "state": "REVIEWED",
        "decision_trace_sha256": digest,
        "execution_authorized": False,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="conflicts"):
        persist_draft_snapshot(decision_trace_sha256=digest, storage_dir=tmp_path)
