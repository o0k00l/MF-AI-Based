import copy
import hashlib
import json
from pathlib import Path
import pytest
from core.eligibility import (
    load_fund_screening_policy,
    _load_category_aum_caps,
    check_eligibility_gates,
    validate_fund_screening_policy,
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
    # A derived policy is a distinct policy snapshot: detach the base-file
    # binding and bind its digest to the exact modified content.
    strict_policy.pop("_policy_path", None)
    strict_policy.pop("_policy_digest", None)
    strict_policy["_policy_digest"] = hashlib.sha256(
        json.dumps(strict_policy, sort_keys=True).encode("utf-8")
    ).hexdigest()

    res2 = check_eligibility_gates(fund_data, portfolio_holdings=holdings, client_risk_tier_num=5, policy=strict_policy)
    assert any("AUM Size Drag" in f for f in res2.failed_gates)


def test_policy_digest_is_rechecked_against_authoritative_file_after_in_memory_mutation():
    policy = load_fund_screening_policy()
    original_digest = policy["_policy_digest"]
    mutated = copy.deepcopy(policy)
    mutated["gate_thresholds"]["min_aum_crore"] += 1

    # Retaining the original, valid digest must not bless changed policy data.
    assert mutated["_policy_digest"] == original_digest
    with pytest.raises(ValueError, match="does not match its authoritative source file"):
        validate_fund_screening_policy(mutated)


def test_policy_digest_claim_without_source_path_is_recomputed_and_verified():
    policy = load_fund_screening_policy()
    policy.pop("_policy_path")
    policy["_policy_digest"] = "0" * 64

    with pytest.raises(ValueError, match="digest does not match"):
        validate_fund_screening_policy(policy)


def test_loaded_policy_can_be_revalidated_without_losing_source_digest():
    policy = load_fund_screening_policy()
    digest = policy["_policy_digest"]

    validated = validate_fund_screening_policy(copy.deepcopy(policy))

    assert validated["_policy_digest"] == digest


@pytest.mark.parametrize("bad_status", ["draft", "unreviewed", "", None])
def test_screening_policy_requires_reviewed_or_approved_status(bad_status):
    policy = load_fund_screening_policy()
    policy.pop("_policy_path", None)
    policy.pop("_policy_digest", None)
    policy["status"] = bad_status
    with pytest.raises(ValueError, match="status must be reviewed or approved"):
        validate_fund_screening_policy(policy)


@pytest.mark.parametrize("bad_as_of", ["not-a-date", "2026-13-40", "", None])
def test_screening_policy_requires_valid_effective_date(bad_as_of):
    policy = load_fund_screening_policy()
    policy.pop("_policy_path", None)
    policy.pop("_policy_digest", None)
    policy["as_of"] = bad_as_of
    with pytest.raises(ValueError, match="as_of"):
        validate_fund_screening_policy(policy)


def test_screening_policy_rejects_future_effective_date():
    from datetime import date, timedelta
    policy = load_fund_screening_policy()
    policy.pop("_policy_path", None)
    policy.pop("_policy_digest", None)
    policy["as_of"] = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="cannot be in the future"):
        validate_fund_screening_policy(policy)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("amc_max_limit_pct", 100.1, "between 0 and 100"),
        ("max_top10_concentration_pct", 101, "between 0 and 100"),
        ("max_sector_concentration_pct", 101, "between 0 and 100"),
        ("max_overlap_candidate_pct", 101, "between 0 and 100"),
        ("min_aum_crore", 0, "greater than zero"),
        ("min_confidence_score", 1.1, "between 0 and 1"),
    ],
)
def test_screening_policy_rejects_out_of_range_threshold_units(field, value, match):
    policy = load_fund_screening_policy()
    policy.pop("_policy_path", None)
    policy.pop("_policy_digest", None)
    policy["gate_thresholds"][field] = value
    with pytest.raises(ValueError, match=match):
        validate_fund_screening_policy(policy)
