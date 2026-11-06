"""
Integration and cross-consumer tests for single authoritative SAA policy binding.
Addresses Issue #80: Remove duplicated hardcoded SAA targets from core models and use the central allocation policy.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import pytest

from core.models import (
    AssetAllocationTarget,
    AssetClass,
    HoldingItem,
    PlanType,
    RiskTier,
    SAA_POLICY_MAP,
    get_saa_policy_metadata,
    load_saa_policy_map,
)
from core.math_engine import (
    calculate_saa_drift_minimizer,
    compute_deterministic_sip_blueprint,
    get_target_allocation,
)


def _load_base_policy() -> dict:
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    return json.loads(policy_path.read_text(encoding="utf-8"))


def test_default_authoritative_policy_binding():
    meta = get_saa_policy_metadata()
    assert meta["policy_version"] == "2026-10-30"
    assert len(meta["policy_digest"]) == 64

    # Verify every public target carries the authoritative version and digest
    for tier in (RiskTier.CONSERVATIVE, RiskTier.MODERATE, RiskTier.AGGRESSIVE):
        target = get_target_allocation(tier)
        assert target.policy_version == meta["policy_version"]
        assert target.policy_digest == meta["policy_digest"]
        assert SAA_POLICY_MAP[tier].equity_pct == target.equity_pct
        assert SAA_POLICY_MAP[tier].debt_pct == target.debt_pct
        assert SAA_POLICY_MAP[tier].policy_version == meta["policy_version"]
        assert SAA_POLICY_MAP[tier].policy_digest == meta["policy_digest"]


def test_dynamic_policy_reload_and_changed_targets(tmp_path):
    base_policy = _load_base_policy()
    mod_policy = copy.deepcopy(base_policy)
    mod_policy["as_of"] = "2027-01-15"
    # Change Conservative SAA target from 40/60 to 50/50
    mod_policy["behavioral_risk_profiles"]["low_to_moderate"]["saa_targets"]["large_cap_pct"] = 35
    mod_policy["behavioral_risk_profiles"]["low_to_moderate"]["saa_targets"]["debt_liquid_pct"] = 50

    custom_policy_file = tmp_path / "custom_asset_allocation.json"
    policy_bytes = json.dumps(mod_policy).encode("utf-8")
    custom_policy_file.write_bytes(policy_bytes)
    expected_digest = hashlib.sha256(policy_bytes).hexdigest()

    custom_target = get_target_allocation(RiskTier.CONSERVATIVE, policy_path=custom_policy_file)
    assert custom_target.equity_pct == 50.0
    assert custom_target.debt_pct == 50.0
    assert custom_target.policy_version == "2027-01-15"
    assert custom_target.policy_digest == expected_digest


def test_cross_consumer_consistency_sip_calculation(tmp_path):
    base_policy = _load_base_policy()
    mod_policy = copy.deepcopy(base_policy)
    mod_policy["as_of"] = "2027-06-30"

    custom_policy_file = tmp_path / "sip_test_policy.json"
    policy_bytes = json.dumps(mod_policy).encode("utf-8")
    custom_policy_file.write_bytes(policy_bytes)
    expected_digest = hashlib.sha256(policy_bytes).hexdigest()

    candidates = [
        {
            "fund_id": "test-flexi-direct",
            "fund_name": "Test Flexi Direct",
            "scheme_name": "Test Flexi Direct",
            "category": "Flexi Cap",
            "is_direct": True,
            "ter": 0.65,
            "equity_holding": 98.0,
            "debt_holding": 2.0,
        },
        {
            "fund_id": "test-mid-direct",
            "fund_name": "Test Mid Direct",
            "scheme_name": "Test Mid Direct",
            "category": "Mid Cap",
            "is_direct": True,
            "ter": 0.70,
            "equity_holding": 97.0,
            "debt_holding": 3.0,
        },
        {
            "fund_id": "test-small-direct",
            "fund_name": "Test Small Direct",
            "scheme_name": "Test Small Direct",
            "category": "Small Cap",
            "is_direct": True,
            "ter": 0.75,
            "equity_holding": 95.0,
            "debt_holding": 5.0,
        },
        {
            "fund_id": "test-large-direct",
            "fund_name": "Test Large Direct",
            "scheme_name": "Test Large Direct",
            "category": "Large Cap",
            "is_direct": True,
            "ter": 0.50,
            "equity_holding": 99.0,
            "debt_holding": 1.0,
        },
    ]

    plan = compute_deterministic_sip_blueprint(
        monthly_budget=20000,
        risk_tier="Aggressive",
        client_aum=1000000.0,
        client_aum_verified=True,
        candidate_universe=candidates,
        policy_path=custom_policy_file,
    )

    assert plan.policy_version == "2027-06-30"
    assert plan.policy_digest == expected_digest


def test_cross_consumer_consistency_saa_drift_diagnostics(tmp_path):
    base_policy = _load_base_policy()
    mod_policy = copy.deepcopy(base_policy)
    mod_policy["as_of"] = "2027-03-01"

    custom_policy_file = tmp_path / "drift_test_policy.json"
    policy_bytes = json.dumps(mod_policy).encode("utf-8")
    custom_policy_file.write_bytes(policy_bytes)
    expected_digest = hashlib.sha256(policy_bytes).hexdigest()

    holding = HoldingItem(
        fund_id="fund-1",
        scheme="Equity Scheme Direct",
        fund_name="Equity Scheme Direct",
        folio="12345",
        is_direct=True,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.EQUITY,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=100000.0,
        invested_value_inr=90000.0,
        units=100.0,
        nav=1000.0,
    )

    target_map = {"equity_pct": 75.0, "debt_pct": 25.0, "cash_pct": 0.0}
    drift = calculate_saa_drift_minimizer(
        holdings=[holding],
        target_allocation=target_map,
        sip_budget_inr=10000.0,
        policy_path=custom_policy_file,
    )

    assert drift.policy_version == "2027-03-01"
    assert drift.policy_digest == expected_digest


def test_missing_and_corrupt_policy_fails_closed(tmp_path):
    missing_file = tmp_path / "non_existent_policy.json"
    with pytest.raises(RuntimeError, match="Authoritative asset-allocation policy is missing"):
        load_saa_policy_map(policy_path=missing_file, force_reload=True)

    with pytest.raises(RuntimeError, match="Authoritative asset-allocation policy is missing"):
        get_target_allocation(RiskTier.CONSERVATIVE, policy_path=missing_file)

    corrupt_file = tmp_path / "corrupt_policy.json"
    corrupt_file.write_text("NOT A VALID JSON", encoding="utf-8")
    with pytest.raises(RuntimeError, match="invalid"):
        load_saa_policy_map(policy_path=corrupt_file, force_reload=True)

    incomplete_file = tmp_path / "incomplete_policy.json"
    incomplete_file.write_text(json.dumps({"as_of": "2026-11-01", "behavioral_risk_profiles": {}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Missing risk profile"):
        load_saa_policy_map(policy_path=incomplete_file, force_reload=True)


def test_custom_tier_requires_explicit_target():
    with pytest.raises(ValueError, match="Custom Tier selected but no custom target provided"):
        get_target_allocation(RiskTier.CUSTOM, custom_target=None)

    explicit_target = AssetAllocationTarget(
        equity_pct=55.0,
        debt_pct=40.0,
        cash_pct=5.0,
    )
    result = get_target_allocation(RiskTier.CUSTOM, custom_target=explicit_target)
    assert result == explicit_target
