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
    assert caps["Mid Cap"] == 120000.0
    assert caps["Flexi Cap"] == 180000.0
    assert caps["Large Cap"] == 250000.0
    assert caps["Multi Cap"] == 40000.0
    assert CATEGORY_AUM_CAPS["Small Cap"] == 20000.0


def test_policy_loader_rejects_duplicate_rule_ids(tmp_path):
    bad_policy = {
        "_schema": "fiduciary.screening_criteria.v1",
        "version": "1.0.0",
        "gate_thresholds": {
            "amc_max_limit_pct": 25, "min_aum_crore": 5, "max_top10_concentration_pct": 30,
            "max_sector_concentration_pct": 25, "min_sharpe": 0.5, "min_manager_tenure_years": 5,
            "min_confidence_score": 0.8, "max_overlap_candidate_pct": 30,
        },
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
        "version": "1.0.0",
        "gate_thresholds": {
            "amc_max_limit_pct": 25, "min_aum_crore": 5, "max_top10_concentration_pct": 30,
            "max_sector_concentration_pct": 25, "min_sharpe": 0.5, "min_manager_tenure_years": 5,
            "min_confidence_score": 0.8, "max_overlap_candidate_pct": 30,
        },
        "flag_rules": [],
        "category_rules": {
            "thematic_sectoral_liquidation": {"action": "IMMEDIATE_EXIT"}
        },
    }
    path = tmp_path / "bad_policy.json"
    path.write_text(json.dumps(bad_policy), encoding="utf-8")

    with pytest.raises(ValueError, match="Contradictory action 'IMMEDIATE_EXIT'"):
        load_fund_screening_policy(path)



@pytest.mark.parametrize(
    "bad_policy",
    [
        {"flag_rules": []},
        {"flag_rules": [{"id": "AUM_OUT_OF_BAND", "limits_crore": {"Small Cap": 20000}}]},
        {"flag_rules": [
            {"id": "AUM_OUT_OF_BAND", "limits_crore": {
                "Small Cap": 20000, "Mid Cap": 40000, "Flexi Cap": 90000,
                "Large Cap": 250000, "Multi Cap": 40000,
            }},
            {"id": "AUM_OUT_OF_BAND", "limits_crore": {
                "Small Cap": 20000, "Mid Cap": 40000, "Flexi Cap": 90000,
                "Large Cap": 250000, "Multi Cap": 40000,
            }},
        ]},
    ],
)
def test_category_aum_caps_fail_closed_for_missing_incomplete_or_duplicate_policy(bad_policy):
    with pytest.raises(ValueError, match="AUM_OUT_OF_BAND"):
        _load_category_aum_caps(bad_policy)


@pytest.mark.parametrize("bad_limit", [None, True, 0, -1, "not-a-number", float("nan"), float("inf")])
def test_category_aum_caps_reject_invalid_policy_values(bad_limit):
    policy = load_fund_screening_policy()
    policy["flag_rules"] = [
        dict(rule, limits_crore=dict(rule.get("limits_crore", {})))
        if isinstance(rule, dict) and rule.get("id") == "AUM_OUT_OF_BAND" else rule
        for rule in policy["flag_rules"]
    ]
    rule = next(rule for rule in policy["flag_rules"] if rule.get("id") == "AUM_OUT_OF_BAND")
    rule["limits_crore"]["Small Cap"] = bad_limit
    with pytest.raises(ValueError, match="AUM limit for Small Cap"):
        _load_category_aum_caps(policy)


def test_screening_policy_rejects_unknown_schema_version(tmp_path):
    path = tmp_path / "unsupported-screening-policy.json"
    path.write_text(json.dumps({
        "_schema": "fiduciary.screening_criteria.v999",
        "version": "999.000",
        "gate_thresholds": {
            "amc_max_limit_pct": 25, "min_aum_crore": 5, "max_top10_concentration_pct": 30,
            "max_sector_concentration_pct": 25, "min_sharpe": 0.5, "min_manager_tenure_years": 5,
            "min_confidence_score": 0.8, "max_overlap_candidate_pct": 30,
        },
        "flag_rules": [],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="schema must be fiduciary.screening_criteria.v1"):
        load_fund_screening_policy(path)
