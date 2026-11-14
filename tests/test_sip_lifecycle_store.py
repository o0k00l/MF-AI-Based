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


from datetime import datetime, timedelta, timezone

from services.sip_lifecycle_store import (
    assess_review_triggers,
    create_reviewable_draft,
    get_lifecycle_status,
    transition_lifecycle,
)


def _reviewable_draft(tmp_path, digest="e" * 64, author="author-01"):
    return create_reviewable_draft(
        decision_trace_sha256=digest,
        policy_sha256="1" * 64,
        source_evidence_sha256="2" * 64,
        author_id=author,
        storage_dir=tmp_path,
    )


def test_review_lifecycle_requires_independent_trusted_reviewer_and_is_append_only(tmp_path):
    digest = "e" * 64
    _reviewable_draft(tmp_path, digest=digest)

    with pytest.raises(ValueError, match="trusted reviewer registry"):
        transition_lifecycle(
            decision_trace_sha256=digest, to_state="REVIEWED", actor_id="reviewer-01",
            reason_code="APPROVED", policy_sha256="1" * 64, source_evidence_sha256="2" * 64,
            authorized_reviewer_ids=set(), storage_dir=tmp_path,
        )
    with pytest.raises(ValueError, match="independent"):
        transition_lifecycle(
            decision_trace_sha256=digest, to_state="REVIEWED", actor_id="author-01",
            reason_code="APPROVED", policy_sha256="1" * 64, source_evidence_sha256="2" * 64,
            authorized_reviewer_ids={"author-01"}, storage_dir=tmp_path,
        )

    reviewed = transition_lifecycle(
        decision_trace_sha256=digest, to_state="REVIEWED", actor_id="reviewer-01",
        reason_code="APPROVED", policy_sha256="1" * 64, source_evidence_sha256="2" * 64,
        authorized_reviewer_ids={"reviewer-01"}, storage_dir=tmp_path,
    )
    assert reviewed["state"] == "REVIEWED"
    assert get_lifecycle_status(decision_trace_sha256=digest, storage_dir=tmp_path)["state"] == "REVIEWED"

    superseded = transition_lifecycle(
        decision_trace_sha256=digest, to_state="SUPERSEDED", actor_id="operator-01",
        reason_code="NEW_DECISION", policy_sha256="1" * 64, source_evidence_sha256="2" * 64,
        replacement_decision_trace_sha256="f" * 64, authorized_operator_ids={"operator-01"}, storage_dir=tmp_path,
    )
    assert superseded["state"] == "SUPERSEDED"
    with pytest.raises(ValueError, match="terminal"):
        transition_lifecycle(
            decision_trace_sha256=digest, to_state="WITHDRAWN", actor_id="operator-01",
            reason_code="WITHDRAWAL", policy_sha256="1" * 64, source_evidence_sha256="2" * 64,
            storage_dir=tmp_path,
        )
    event_files = list((tmp_path / "events" / digest).glob("*.json"))
    assert len(event_files) == 2
    assert all("investor" not in p.read_text(encoding="utf-8").lower() for p in event_files)


def test_review_lifecycle_rejects_changed_policy_or_source_snapshot(tmp_path):
    digest = "a" * 64
    _reviewable_draft(tmp_path, digest=digest)
    with pytest.raises(ValueError, match="new decision draft"):
        transition_lifecycle(
            decision_trace_sha256=digest, to_state="REVIEWED", actor_id="reviewer-01",
            reason_code="APPROVED", policy_sha256="3" * 64, source_evidence_sha256="2" * 64,
            authorized_reviewer_ids={"reviewer-01"}, storage_dir=tmp_path,
        )


def test_review_lifecycle_detects_event_tampering(tmp_path):
    digest = "b" * 64
    _reviewable_draft(tmp_path, digest=digest)
    transition_lifecycle(
        decision_trace_sha256=digest, to_state="WITHDRAWN", actor_id="author-01",
        reason_code="CLIENT_WITHDRAWAL", policy_sha256="1" * 64, source_evidence_sha256="2" * 64,
        storage_dir=tmp_path,
    )
    event_path = next((tmp_path / "events" / digest).glob("*.json"))
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event["reason_code"] = "ALTERED"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    with pytest.raises(ValueError, match="tampered"):
        get_lifecycle_status(decision_trace_sha256=digest, storage_dir=tmp_path)


def test_review_triggers_cover_policy_source_holdings_mandate_scheme_and_freshness():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    same = "a" * 64
    changed = "b" * 64
    result = assess_review_triggers(
        decision_policy_sha256=same, current_policy_sha256=changed,
        decision_source_evidence_sha256=same, current_source_evidence_sha256=changed,
        decision_holdings_sha256=same, current_holdings_sha256=changed,
        decision_mandate_sha256=same, current_mandate_sha256=changed,
        decision_scheme_status_sha256=same, current_scheme_status_sha256=changed,
        evidence_as_of=now - timedelta(days=10), now=now,
        maximum_evidence_age_days=5, review_due_at=now,
    )
    assert result["review_required"] is True
    assert result["status"] == "REVIEW_REQUIRED"
    assert set(result["trigger_codes"]) == {
        "EFFECTIVE_POLICY_CHANGED", "SOURCE_EVIDENCE_CHANGED",
        "PORTFOLIO_HOLDINGS_CHANGED", "INVESTOR_MANDATE_CHANGED",
        "SCHEME_STATUS_CHANGED", "EVIDENCE_STALE", "POLICY_REVIEW_DUE",
    }
    assert result["execution_authorized"] is False


def test_review_triggers_reject_naive_timestamps_and_invalid_policy_freshness():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    digest = "c" * 64
    kwargs = dict(
        decision_policy_sha256=digest, current_policy_sha256=digest,
        decision_source_evidence_sha256=digest, current_source_evidence_sha256=digest,
        decision_holdings_sha256=digest, current_holdings_sha256=digest,
        decision_mandate_sha256=digest, current_mandate_sha256=digest,
        decision_scheme_status_sha256=digest, current_scheme_status_sha256=digest,
        evidence_as_of=now, now=now, maximum_evidence_age_days=1,
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        assess_review_triggers(**{**kwargs, "now": datetime(2026, 11, 14)})
    with pytest.raises(ValueError, match="effective policy"):
        assess_review_triggers(**{**kwargs, "maximum_evidence_age_days": -1})
