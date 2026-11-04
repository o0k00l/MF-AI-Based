"""
Unit tests for central fund-screening policy binding and integrity.
Addresses Issue #50: Bind runtime eligibility to one validated screening policy and eliminate conflicting rules.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.eligibility import (
    CATEGORY_AUM_CAPS,
    load_fund_screening_policy,
    _load_category_aum_caps,
)


def test_fund_screening_policy_loads_and_has_unique_rule_ids():
    policy = load_fund_screening_policy()
    assert isinstance(policy, dict)
    assert policy.get("_schema") == "fiduciary.screening_criteria.v1"

    # Verify rule ID uniqueness across all rule lists
    rule_ids = []
    for section in ("quarantine_rules", "reject_rules", "flag_rules"):
        for rule in policy.get(section, []):
            if isinstance(rule, dict) and "id" in rule:
                rule_ids.append(rule["id"])

    assert len(rule_ids) == len(set(rule_ids)), f"Duplicate rule IDs detected: {[r for r in rule_ids if rule_ids.count(r) > 1]}"


def test_thematic_action_is_review_required_not_immediate_exit():
    policy = load_fund_screening_policy()
    cat_rules = policy.get("category_rules", {})
    thematic = cat_rules.get("thematic_sectoral_liquidation", {})
    assert thematic.get("action") == "REVIEW_REQUIRED"
    assert thematic.get("action") != "IMMEDIATE_EXIT"


def test_category_aum_caps_matches_policy_limits():
    policy = load_fund_screening_policy()
    caps = _load_category_aum_caps(policy)
    assert caps["Small Cap"] == 20000.0
    assert caps["Mid Cap"] == 40000.0
    assert caps["Flexi Cap"] == 90000.0
    assert caps["Large Cap"] == 250000.0
    assert caps["Multi Cap"] == 40000.0
    assert CATEGORY_AUM_CAPS["Small Cap"] == 20000.0


def test_policy_loader_rejects_duplicate_rule_ids(tmp_path):
    bad_policy = {
        "_schema": "fiduciary.screening_criteria.v1",
        "flag_rules": [
            {"id": "DUP_RULE", "test": "x > 1"},
            {"id": "DUP_RULE", "test": "x > 2"},
        ],
        "category_rules": {
            "thematic_sectoral_liquidation": {"action": "REVIEW_REQUIRED"}
        },
    }
    path = tmp_path / "bad_policy.json"
    path.write_text(json.dumps(bad_policy), encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate screening rule ID"):
        load_fund_screening_policy(path)


def test_policy_loader_rejects_contradictory_thematic_action(tmp_path):
    bad_policy = {
        "_schema": "fiduciary.screening_criteria.v1",
        "flag_rules": [],
        "category_rules": {
            "thematic_sectoral_liquidation": {"action": "IMMEDIATE_EXIT"}
        },
    }
    path = tmp_path / "bad_policy.json"
    path.write_text(json.dumps(bad_policy), encoding="utf-8")

    with pytest.raises(ValueError, match="Contradictory action 'IMMEDIATE_EXIT'"):
        load_fund_screening_policy(path)

