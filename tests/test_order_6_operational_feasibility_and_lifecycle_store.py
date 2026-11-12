"""
tests/test_order_6_operational_feasibility_and_lifecycle_store.py

Authoritative acceptance test suite for Order 6:
- Issue #34: Operational SIP feasibility, minimum tickets, increment constraints,
  active subscription status, and 12-month new scheme introduction limits with migration exemptions.
- Issue #33: Privacy-minimal immutable SIP draft lifecycle store, git checkout isolation,
  idempotent persistence, and tamper/conflict detection.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from core.math_engine import _sip_operational_constraint_violations
from services.sip_lifecycle_store import persist_draft_snapshot


def _sample_sip_item(
    role: str = "Core Flexi-Cap",
    scheme: str = "Sample Direct Growth",
    amount: float = 1000.0,
    pct: float = 20.0,
    status: str = "ACTIVE",
    sub_status: str = "OPEN",
    min_sip: float = 500.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        category_role=role,
        scheme_name=scheme,
        monthly_inr=amount,
        allocation_pct=pct,
        scheme_status=status,
        subscription_status=sub_status,
        scheme_min_sip_inr=min_sip,
    )


def _sample_policy() -> Dict[str, Any]:
    return {
        "max_fund_allocation_pct": 20.0,
        "min_sip_per_fund_inr": 1000.0,
        "sip_increment_inr": 500.0,
        "max_core_fund_count": 6,
        "max_new_funds_per_12_months": 2,
        "starter_flexi_sleeve_cap_exception": {
            "permitted": True,
            "max_sleeve_pct": 60.0,
        },
    }


# =============================================================================
# PART 1: ISSUE #34 — Operational SIP Feasibility & Constraints
# =============================================================================

def test_order_6_per_fund_cap_enforcement_for_established_and_starter():
    """Verify 20% cap for established portfolios and 60% flexi cap exception for starters."""
    policy = _sample_policy()

    # Established portfolio: 25% allocation violates 20% cap
    item_established = _sample_sip_item(amount=2500.0, pct=25.0)
    v_est = _sip_operational_constraint_violations([item_established], policy, is_starter=False)
    assert any("exceeds the 20.00% per-fund cap" in v for v in v_est)

    # Starter portfolio: 45% flexi allocation is permitted under starter exception
    item_starter = _sample_sip_item(role="Core Flexi-Cap", amount=4500.0, pct=45.0)
    v_starter = _sip_operational_constraint_violations([item_starter], policy, is_starter=True)
    assert v_starter == []

    # Starter portfolio: 65% flexi allocation exceeds 60% starter sleeve cap
    item_starter_breach = _sample_sip_item(role="Core Flexi-Cap", amount=6500.0, pct=65.0)
    v_starter_breach = _sip_operational_constraint_violations([item_starter_breach], policy, is_starter=True)
    assert any("exceeds the 60.00% per-fund cap" in v for v in v_starter_breach)


def test_order_6_minimum_ticket_and_increment_rules():
    """Verify scheme minimum ticket and increment constraints fail closed when breached."""
    policy = _sample_policy()

    # Below scheme-specific minimum ticket (e.g. scheme requires INR 2500, allocated 1000)
    item_below_min = _sample_sip_item(amount=1000.0, min_sip=2500.0)
    v_min = _sip_operational_constraint_violations([item_below_min], policy)
    assert any("below scheme-specific minimum ticket" in v for v in v_min)

    # Non-conforming increment: allocated 1250 when increment is 500 (1000 + 500n)
    item_bad_inc = _sample_sip_item(amount=1250.0, min_sip=500.0)
    v_inc = _sip_operational_constraint_violations([item_bad_inc], policy)
    assert any("SIP increment" in v for v in v_inc)


def test_order_6_rejects_inactive_or_subscription_restricted_schemes():
    """Verify merged, suspended, or subscription-restricted funds fail closed."""
    policy = _sample_policy()

    # Inactive / merged scheme
    item_merged = _sample_sip_item(status="MERGED")
    v_merged = _sip_operational_constraint_violations([item_merged], policy)
    assert any("not confirmed active" in v for v in v_merged)

    # Subscription restricted scheme (e.g. Small cap closed for lump-sum or fresh SIP)
    item_restricted = _sample_sip_item(sub_status="CLOSED_FOR_FRESH_SIP")
    v_restricted = _sip_operational_constraint_violations([item_restricted], policy)
    assert any("subscription is restricted or closed" in v for v in v_restricted)


def test_order_6_twelve_month_new_fund_limits_and_migration_exemption():
    """Verify 12-month new scheme limit rejects excess introductions but exempts Regular->Direct migrations."""
    policy = _sample_policy()
    existing = [SimpleNamespace(scheme_name="Existing Bluechip Fund - Regular Plan - Growth")]
    history_at_limit = {"new_funds_last_12_months": 2}

    # Propose brand new fund when already at limit (2 + 1 = 3 > 2) -> REJECTED
    new_fund_item = [
        _sample_sip_item(scheme="Brand New Small Cap Direct Growth", amount=1500.0, pct=15.0)
    ]
    v_limit = _sip_operational_constraint_violations(
        new_fund_item, policy, portfolio_introduction_history=history_at_limit, existing_schemes=existing
    )
    assert any("exceed the 12-month limit of 2" in v for v in v_limit)

    # Propose Direct plan of already existing Regular holding -> EXEMPT from new fund count
    migration_item = [
        _sample_sip_item(scheme="Existing Bluechip Fund - Direct Plan - Growth", amount=2000.0, pct=20.0)
    ]
    v_mig = _sip_operational_constraint_violations(
        migration_item, policy, portfolio_introduction_history=history_at_limit, existing_schemes=existing
    )
    assert v_mig == []


def test_order_6_missing_introduction_history_fails_closed():
    """Verify missing 12-month introduction history fails closed."""
    policy = _sample_policy()
    unverified_history = {"new_funds_last_12_months": None}
    item = [_sample_sip_item()]
    violations = _sip_operational_constraint_violations(
        item, policy, portfolio_introduction_history=unverified_history
    )
    assert any("Missing 12-month scheme introduction history" in v for v in violations)


# =============================================================================
# PART 2: ISSUE #33 — SIP Draft Lifecycle Store
# =============================================================================

def test_order_6_lifecycle_store_is_opt_in_when_not_configured(monkeypatch):
    """Verify lifecycle store safely reports STORE_NOT_CONFIGURED when environment variable is unset."""
    monkeypatch.delenv("MF_SIP_LIFECYCLE_DIR", raising=False)
    res = persist_draft_snapshot(decision_trace_sha256="0" * 64)
    assert res["state"] == "DRAFT"
    assert res["state_persisted"] is False
    assert res["persistence_status"] == "STORE_NOT_CONFIGURED"


def test_order_6_lifecycle_store_rejects_storage_inside_git_checkout(tmp_path):
    """Verify lifecycle store rejects paths within the repository checkout to avoid leaking state."""
    repo_root = Path(__file__).resolve().parents[1]
    inside_repo_dir = repo_root / "temp_unsafe_lifecycle_dir"

    with pytest.raises(ValueError, match="outside the Git checkout"):
        persist_draft_snapshot(
            decision_trace_sha256="1" * 64,
            storage_dir=inside_repo_dir,
        )


def test_order_6_lifecycle_store_persists_minimal_idempotent_record(tmp_path):
    """Verify store writes minimal privacy record, idempotently handles repeats, and validates digest format."""
    digest = "a" * 64

    # First write -> RECORDED
    res1 = persist_draft_snapshot(decision_trace_sha256=digest, storage_dir=tmp_path)
    assert res1["state"] == "DRAFT"
    assert res1["state_persisted"] is True
    assert res1["persistence_status"] == "RECORDED"

    # Second write with same digest -> ALREADY_RECORDED (idempotent)
    res2 = persist_draft_snapshot(decision_trace_sha256=digest, storage_dir=tmp_path)
    assert res2["state"] == "DRAFT"
    assert res2["state_persisted"] is True
    assert res2["persistence_status"] == "ALREADY_RECORDED"

    # Verify disk content is strictly privacy-minimal (no PII, no amounts, no holdings)
    saved_file = tmp_path / f"{digest}.json"
    assert saved_file.is_file()
    record = json.loads(saved_file.read_text(encoding="utf-8"))
    assert set(record.keys()) == {
        "schema_version", "state", "decision_trace_sha256",
        "created_at", "execution_authorized",
    }
    assert record["state"] == "DRAFT"
    assert record["decision_trace_sha256"] == digest
    assert record["execution_authorized"] is False


def test_order_6_lifecycle_store_detects_conflicting_or_tampered_record(tmp_path):
    """Verify store raises ValueError if an existing record has conflicting state or authorization."""
    digest = "f" * 64
    conflict_path = tmp_path / f"{digest}.json"
    # Write a record claiming execution was authorized
    conflict_path.write_text(json.dumps({
        "schema_version": 1,
        "state": "EXECUTED",
        "decision_trace_sha256": digest,
        "execution_authorized": True,
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="conflicts with this decision trace"):
        persist_draft_snapshot(decision_trace_sha256=digest, storage_dir=tmp_path)


def test_order_6_lifecycle_store_rejects_invalid_hex_digest(tmp_path):
    """Verify non-hex or invalid length digests are rejected immediately."""
    with pytest.raises(ValueError, match="64-character SHA-256"):
        persist_draft_snapshot(decision_trace_sha256="short_digest", storage_dir=tmp_path)

    with pytest.raises(ValueError, match="must be hexadecimal"):
        persist_draft_snapshot(decision_trace_sha256="z" * 64, storage_dir=tmp_path)
