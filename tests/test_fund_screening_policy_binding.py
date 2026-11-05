import json
from pathlib import Path
import pytest
from core.eligibility import (
    load_fund_screening_policy,
    _load_category_aum_caps,
    check_eligibility_gates,
)


def test_load_fund_screening_policy_loads_valid_versioned_policy():
    policy = load_fund_screening_policy()
    assert isinstance(policy, dict)
    assert policy.get("_schema") == "fiduciary.screening_criteria.v1"
    assert policy.get("version") == "2026.10"
    assert policy.get("status") == "reviewed"
    assert "_policy_digest" in policy
    assert len(policy["_policy_digest"]) == 64


def test_fund_screening_policy_has_no_duplicate_rule_ids():
    policy = load_fund_screening_policy()
    rule_ids = []
    for key in ("quarantine_rules", "reject_rules", "flag_rules", "consolidate_candidate_rules", "discount_track_record_rules"):
        for rule in policy.get(key, []):
            if isinstance(rule, dict) and "id" in rule:
                rule_ids.append(rule["id"])
    
    assert len(rule_ids) == len(set(rule_ids)), f"Duplicate rule IDs detected: {[x for x in rule_ids if rule_ids.count(x) > 1]}"


def test_fund_screening_policy_thematic_action_is_review_required():
    policy = load_fund_screening_policy()
    thematic_rule = policy["category_rules"]["thematic_sectoral_liquidation"]
    assert thematic_rule["action"] == "REVIEW_REQUIRED"


def test_load_category_aum_caps_extracts_all_required_categories():
    caps = _load_category_aum_caps()
    required = {"Small Cap", "Mid Cap", "Flexi Cap", "Large Cap", "Multi Cap"}
    assert set(caps.keys()) == required
    assert all(val > 0 and isinstance(val, (int, float)) for val in caps.values())


def test_check_eligibility_gates_binds_policy_version_and_digest():
    fund_data = {
        "fund_id": "fund-1",
        "fund_name": "Example Direct Growth",
        "category": "Large Cap",
        "amc_name": "Example AMC",
        "aum_crore": 5000.0,
        "aum_stable": True,
        "top10_concentration_pct": 35.0,
        "sector_concentration_pct": 20.0,
        "sharpe": 0.8,
        "alpha": 2.5,
        "downside_capture_ratio": 80.0,
        "upside_capture_ratio": 95.0,
        "riskometer_score": 4,
        "confidence_score": 0.95,
        "benchmark_identity": "NIFTY 50 TRI",
        "manager_tenure_years": 4.0,
        "is_thematic": False,
        "is_direct": True,
        "plan": "Direct",
    }
    holdings = [
        {"amc_name": "Other AMC", "current_value_inr": 100000.0, "asset_class": "EQUITY"}
    ]
    res = check_eligibility_gates(fund_data, portfolio_holdings=holdings, client_risk_tier_num=5)
    assert res.policy_version == "2026.10"
    assert res.policy_digest is not None
    assert len(res.policy_digest) == 64
    assert res.details.get("policy_version") == "2026.10"


def test_check_eligibility_gates_custom_policy_changes_behavior():
    fund_data = {
        "fund_id": "fund-1",
        "fund_name": "Example Direct Growth",
        "category": "Small Cap",
        "amc_name": "Example AMC",
        "aum_crore": 12000.0,  # 12,000 Cr AUM
        "aum_stable": True,
        "top10_concentration_pct": 35.0,
        "sector_concentration_pct": 20.0,
        "sharpe": 0.8,
        "alpha": 2.5,
        "downside_capture_ratio": 80.0,
        "upside_capture_ratio": 95.0,
        "riskometer_score": 4,
        "confidence_score": 0.95,
        "benchmark_identity": "NIFTY SMALLCAP 250 TRI",
        "manager_tenure_years": 4.0,
        "is_thematic": False,
        "is_direct": True,
        "plan": "Direct",
    }
    holdings = [
        {"amc_name": "Other AMC", "current_value_inr": 100000.0, "asset_class": "EQUITY"}
    ]
    
    # 1. Standard policy has Small Cap limit of 15,000 Cr -> Passes AUM drag
    std_policy = load_fund_screening_policy()
    res1 = check_eligibility_gates(fund_data, portfolio_holdings=holdings, client_risk_tier_num=5, policy=std_policy)
    assert not any("AUM Size Drag" in f for f in res1.failed_gates)

    # 2. Modified policy with strict Small Cap limit of 10,000 Cr -> Fails AUM drag
    import copy
    strict_policy = copy.deepcopy(std_policy)
    for r in strict_policy["flag_rules"]:
        if r.get("id") == "AUM_OUT_OF_BAND":
            r["limits_crore"]["Small Cap"] = 10000.0
            break
    
    res2 = check_eligibility_gates(fund_data, portfolio_holdings=holdings, client_risk_tier_num=5, policy=strict_policy)
    assert any("AUM Size Drag" in f for f in res2.failed_gates)
