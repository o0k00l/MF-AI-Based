"""
tests/test_operational_feasibility_and_limits.py - Unit tests for SIP operational feasibility and 12-month introduction limit.
Addresses Issue #34: Enforce scheme lifecycle, transaction-cost and operational SIP feasibility checks.
"""
from __future__ import annotations

from decimal import Decimal
import pytest

from core.math_engine import (
    _sip_operational_constraint_violations,
    compute_deterministic_sip_blueprint,
)
from core.models import DeterministicSIPRecommendation


def test_starter_flexi_sleeve_cap_exception():
    sip_policy = {
        "max_fund_allocation_pct": 20,
        "min_sip_per_fund_inr": 1000,
        "sip_increment_inr": 500,
        "max_core_fund_count": 6,
        "starter_flexi_sleeve_cap_exception": {
            "permitted": True,
            "max_sleeve_pct": 60,
        },
    }
    items = [
        DeterministicSIPRecommendation(
            category_role="Core Flexi-Cap Compounder",
            scheme_name="Parag Parikh Flexi Cap Direct",
            monthly_inr=12000.0,
            allocation_pct=60.0,
            rational_code="CORE",
            fiduciary_rationale="Core anchor",
        )
    ]
    # Under starter heuristic, 60% flexi is permitted
    violations_starter = _sip_operational_constraint_violations(
        items, sip_policy, is_starter=True
    )
    assert len(violations_starter) == 0

    # Under non-starter, without established exception, 60% breaches 20% cap
    violations_non_starter = _sip_operational_constraint_violations(
        items, sip_policy, is_starter=False
    )
    assert any("exceeds the 20.00% per-fund cap" in v for v in violations_non_starter)


def test_established_sleeve_cap_exception():
    sip_policy = {
        "max_fund_allocation_pct": 20,
        "min_sip_per_fund_inr": 1000,
        "sip_increment_inr": 500,
        "max_core_fund_count": 6,
        "established_sleeve_cap_exception": {
            "permitted": True,
            "max_sleeve_pct": 35,
        },
    }
    # 25% single sleeve allocation for Tier 6 established portfolio
    items = [
        DeterministicSIPRecommendation(
            category_role="Mid-Cap Alpha Engine",
            scheme_name="Motilal Oswal Midcap Direct",
            monthly_inr=25000.0,
            allocation_pct=25.0,
            rational_code="CORE",
            fiduciary_rationale="Midcap alpha",
        )
    ]
    violations = _sip_operational_constraint_violations(
        items, sip_policy, is_starter=False
    )
    assert len(violations) == 0


def test_12_month_new_funds_limit_exceeded_fails_closed():
    sip_policy = {
        "max_fund_allocation_pct": 30,
        "min_sip_per_fund_inr": 1000,
        "sip_increment_inr": 500,
        "max_core_fund_count": 6,
        "max_new_funds_per_12_months": 2,
    }
    # 2 brand new funds proposed
    items = [
        DeterministicSIPRecommendation(
            category_role="Mid-Cap Alpha Engine",
            scheme_name="New Scheme Alpha Direct",
            monthly_inr=5000.0,
            allocation_pct=25.0,
            rational_code="CORE",
            fiduciary_rationale="Midcap alpha",
        ),
        DeterministicSIPRecommendation(
            category_role="Small-Cap Growth Engine",
            scheme_name="New Scheme Beta Direct",
            monthly_inr=5000.0,
            allocation_pct=25.0,
            rational_code="CORE",
            fiduciary_rationale="Smallcap growth",
        ),
    ]
    # Prior history already has 1 new fund in last 12 months (1 + 2 = 3 > 2)
    history = {"new_funds_last_12_months": 1}
    violations = _sip_operational_constraint_violations(
        items, sip_policy, portfolio_introduction_history=history, existing_schemes=[]
    )
    assert any("exceed the 12-month limit of 2" in v for v in violations)


def test_plan_migration_regular_to_direct_is_not_counted_as_new_fund():
    sip_policy = {
        "max_fund_allocation_pct": 30,
        "min_sip_per_fund_inr": 1000,
        "sip_increment_inr": 500,
        "max_core_fund_count": 6,
        "max_new_funds_per_12_months": 2,
    }
    items = [
        DeterministicSIPRecommendation(
            category_role="Core Flexi-Cap Compounder",
            scheme_name="SBI Bluechip Fund Direct Plan Growth",
            monthly_inr=5000.0,
            allocation_pct=25.0,
            rational_code="CORE",
            fiduciary_rationale="Migrating existing Regular holding to Direct",
        ),
    ]
    existing = [{"scheme_name": "SBI Bluechip Fund Regular Plan Growth"}]
    history = {"new_funds_last_12_months": 1}  # 1 prior + 0 newly introduced = 1 <= 2
    violations = _sip_operational_constraint_violations(
        items, sip_policy, portfolio_introduction_history=history, existing_schemes=existing
    )
    assert len(violations) == 0
