"""
Unit tests for scheme lifecycle, operational constraints, and 12-month new fund limits.
Addresses Issue #34: Enforce scheme lifecycle, transaction-cost and operational SIP feasibility checks.
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace

from core.math_engine import _sip_operational_constraint_violations


def _sip_item(role="Core Flexi-Cap", scheme="Fund A Direct", amount=1000.0, pct=10.0):
    return SimpleNamespace(
        category_role=role,
        scheme_name=scheme,
        monthly_inr=amount,
        allocation_pct=pct
    )


def _sip_policy():
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


def test_starter_flexi_sleeve_cap_exception_permits_starter_heuristic():
    policy = _sip_policy()
    # 45% Flexi allocation in starter mode (< INR 5L AUM) is permitted under starter exception
    item = _sip_item(role="Core Flexi-Cap", scheme="Flexi Direct", amount=4500.0, pct=45.0)
    violations = _sip_operational_constraint_violations(
        [item], policy, is_starter=True
    )
    assert violations == []


def test_starter_flexi_exceeding_sleeve_cap_is_rejected():
    policy = _sip_policy()
    item = _sip_item(role="Core Flexi-Cap", scheme="Flexi Direct", amount=6500.0, pct=65.0)
    violations = _sip_operational_constraint_violations(
        [item], policy, is_starter=True
    )
    assert any("exceeds the 60.00% per-fund cap" in v for v in violations)


def test_established_portfolio_strictly_enforces_20_percent_cap():
    policy = _sip_policy()
    # In established mode (is_starter=False), 25% allocation breaches the 20% cap
    item = _sip_item(role="Core Flexi-Cap", scheme="Flexi Direct", amount=2500.0, pct=25.0)
    violations = _sip_operational_constraint_violations(
        [item], policy, is_starter=False
    )
    assert any("exceeds the 20.00% per-fund cap" in v for v in violations)


def test_12_month_new_fund_limit_enforced_with_history():
    policy = _sip_policy()
    existing = [SimpleNamespace(scheme_name="Existing Scheme 1 Direct")]

    # Client has had 1 new fund in the last 12 months
    history = {"new_funds_last_12_months": 1}

    # Propose 1 new fund (total = 1 + 1 = 2 <= 2) -> Allowed
    items_valid = [
        _sip_item(role="Core Flexi", scheme="New Scheme A Direct", amount=1500.0, pct=15.0)
    ]
    violations_valid = _sip_operational_constraint_violations(
        items_valid, policy, portfolio_introduction_history=history, existing_schemes=existing
    )
    assert violations_valid == []

    # Propose 2 new funds (total = 1 + 2 = 3 > 2) -> Rejected
    items_invalid = [
        _sip_item(role="Core Flexi", scheme="New Scheme A Direct", amount=1500.0, pct=15.0),
        _sip_item(role="Mid Alpha", scheme="New Scheme B Direct", amount=1500.0, pct=15.0),
    ]
    violations_invalid = _sip_operational_constraint_violations(
        items_invalid, policy, portfolio_introduction_history=history, existing_schemes=existing
    )
    assert any("exceed the 12-month limit of 2" in v for v in violations_invalid)


def test_regular_to_direct_plan_migration_is_exempt_from_new_fund_count():
    policy = _sip_policy()
    # Existing holding is Regular Plan of "Bluechip Growth"
    existing = [SimpleNamespace(scheme_name="HDFC Bluechip Fund - Regular Plan - Growth")]

    # Prior introductions in last 12 months = 2 (limit reached)
    history = {"new_funds_last_12_months": 2}

    # Proposed SIP item is Direct Plan of the SAME scheme (migration)
    items = [
        _sip_item(role="Large Cap", scheme="HDFC Bluechip Fund - Direct Plan - Growth", amount=2000.0, pct=20.0)
    ]
    violations = _sip_operational_constraint_violations(
        items, policy, portfolio_introduction_history=history, existing_schemes=existing
    )
    # Does NOT trigger new fund violation because it is a plan migration
    assert violations == []


def test_missing_introduction_history_fails_closed():
    policy = _sip_policy()
    history = {"new_funds_last_12_months": None}
    item = _sip_item()
    violations = _sip_operational_constraint_violations(
        [item], policy, portfolio_introduction_history=history
    )
    assert any("Missing 12-month scheme introduction history" in v for v in violations)

def test_operational_feasibility_rejects_inactive_or_merged_scheme():
    policy = _sip_policy()
    item = _sip_item()
    item.scheme_status = "MERGED"
    violations = _sip_operational_constraint_violations([item], policy)
    assert any("not confirmed active" in v for v in violations)


def test_operational_feasibility_rejects_restricted_subscription():
    policy = _sip_policy()
    item = _sip_item()
    item.subscription_status = "CLOSED_FOR_FRESH_SIP"
    violations = _sip_operational_constraint_violations([item], policy)
    assert any("subscription is restricted or closed" in v for v in violations)


def test_operational_feasibility_enforces_scheme_minimum_ticket():
    policy = _sip_policy()
    item = _sip_item(amount=1000.0)
    item.scheme_min_sip_inr = 2500.0  # Scheme requires min 2500
    violations = _sip_operational_constraint_violations([item], policy)
    assert any("below scheme-specific minimum ticket" in v for v in violations)
