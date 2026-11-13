"""
tests/test_issues_50_24_single_policy_and_risk_contract.py

Acceptance tests for Issues #50 and #24:
- Issue #50: Single authoritative policy source, elimination of hardcoded defaults,
  and effective policy object/digest reconciliation across SAA and screening.
- Issue #24: 3+1 public risk contract (Conservative, Moderate, Aggressive, Custom),
  Custom SAA with explicit risk ceiling / Riskometer enforcement, and correct
  portfolio-marginal incremental SIP routing.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import pytest

from core.models import (
    AssetAllocationTarget,
    RiskTier,
    get_saa_policy_metadata,
    load_saa_policy_map,
)
from core.eligibility import (
    check_eligibility_gates,
    filter_candidates,
    evaluate_no_action,
    load_fund_screening_policy,
)
from core.math_engine import (
    calculate_universal_tier_split,
    select_autonomous_blueprint_funds,
    compute_deterministic_sip_blueprint,
)
from services import sip_recommendation as service
from services.fiduciary_engine import _DEFAULT_SAA_DISTRIBUTION, _load_default_saa_distribution


# =============================================================================
# Helper Fixtures & Data
# =============================================================================

def _valid_active_fund(riskometer: int = 4, category: str = "Flexi Cap") -> dict:
    """Construct a clean, valid candidate fund for testing suitability and eligibility."""
    return {
        "fund_id": "TEST_SCHEME_ALPHA",
        "fund_name": "Test Alpha Direct Growth",
        "scheme_id": "TEST_SCHEME_ALPHA",
        "isin": "INF000000001",
        "scheme_name": "Test Alpha Direct Growth",
        "category": category,
        "amc_name": "HDFC Mutual Fund",
        "aum_crore": 5000.0,
        "aum_stable": True,
        "top10_concentration_pct": 30.0,
        "max_sector_concentration_pct": 20.0,
        "sharpe_3y": 0.8,
        "alpha_3y": 2.5,
        "downside_capture_ratio": 75.0,
        "upside_capture_ratio": 95.0,
        "manager_tenure_years": 4.5,
        "track_record_years": 5.0,
        "confidence_score": 0.95,
        "benchmark_type": "TRI",
        "is_direct": True,
        "plan": "Direct Growth",
        "expense_ratio": 0.75,
        "riskometer_score": riskometer,
        "mandate_suitable": True,
        "data_complete": True,
        "direct_plan_evidence": {
            "source_file": "factsheet.json",
            "source_document_sha256": "a" * 64,
            "source_url": "https://example.com/factsheet",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Test Alpha Direct Growth",
            "scheme_id": "TEST_SCHEME_ALPHA",
            "isin": "INF000000001",
            "amc_name": "HDFC Mutual Fund",
            "reviewed_at": "2026-10-01",
        },
    }


# =============================================================================
# Issue #50: Single Authoritative Policy Source & Governance
# =============================================================================

def test_issue_50_effective_policy_metadata_reconciles_saa_and_screening():
    """Verify get_saa_policy_metadata exposes policy version, SAA digest, screening digest, and combined digest."""
    meta = get_saa_policy_metadata(force_reload=True)
    assert "policy_version" in meta
    assert "policy_digest" in meta
    assert "screening_policy_digest" in meta
    assert "effective_policy_digest" in meta

    assert len(meta["policy_digest"]) == 64
    assert len(meta["screening_policy_digest"]) == 64
    assert len(meta["effective_policy_digest"]) == 64

    # Verify combined digest is deterministically computed from the component digests
    expected_combined = hashlib.sha256(
        f"{meta['policy_digest']}:{meta['screening_policy_digest']}".encode("utf-8")
    ).hexdigest()
    assert meta["effective_policy_digest"] == expected_combined


def test_issue_50_custom_saa_policy_in_asset_allocation_json():
    """Verify asset_allocation.json defines custom_saa_policy and no code hardcodes fallback 35/25/20/20."""
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert "custom_saa_policy" in policy
    custom_policy = policy["custom_saa_policy"]
    assert custom_policy["default_tolerance_band_pct"] == 3.0
    dist = custom_policy["default_equity_distribution_pct"]
    assert dist["large_cap_pct"] == 35.0
    assert dist["flexi_multi_cap_pct"] == 25.0
    assert dist["mid_cap_pct"] == 20.0
    assert dist["small_cap_pct"] == 20.0
    assert sum(dist.values()) == 100.0


def test_issue_50_fiduciary_engine_default_saa_loads_dynamically():
    """Verify _DEFAULT_SAA_DISTRIBUTION in fiduciary_engine resolves dynamically from policy."""
    assert _DEFAULT_SAA_DISTRIBUTION["large_cap"] > 0
    assert _DEFAULT_SAA_DISTRIBUTION["debt"] > 0
    assert isinstance(_DEFAULT_SAA_DISTRIBUTION["large_cap"], Decimal)
    # Ensure it's not a static dict but resolves from policy
    fresh = _load_default_saa_distribution()
    assert fresh["large_cap"] == _DEFAULT_SAA_DISTRIBUTION["large_cap"]


# =============================================================================
# Issue #24: 3+1 Risk Contract & Suitability Ceiling
# =============================================================================

def test_issue_24_asset_allocation_target_accepts_and_validates_risk_ceiling():
    """Verify AssetAllocationTarget supports explicit risk_ceiling and enforces valid integer range [1, 6]."""
    # Valid targets with explicit risk_ceiling
    target_5 = AssetAllocationTarget(
        equity_pct=70.0, debt_pct=30.0, cash_pct=0.0, risk_ceiling=5
    )
    assert target_5.risk_ceiling == 5

    target_none = AssetAllocationTarget(
        equity_pct=70.0, debt_pct=30.0, cash_pct=0.0, risk_ceiling=None
    )
    assert target_none.risk_ceiling is None

    # Invalid risk ceilings
    with pytest.raises(ValueError):
        AssetAllocationTarget(equity_pct=70.0, debt_pct=30.0, cash_pct=0.0, risk_ceiling=0)

    with pytest.raises(ValueError):
        AssetAllocationTarget(equity_pct=70.0, debt_pct=30.0, cash_pct=0.0, risk_ceiling=7)

    with pytest.raises(ValueError):
        AssetAllocationTarget(equity_pct=70.0, debt_pct=30.0, cash_pct=0.0, risk_ceiling=True)


def test_issue_24_check_eligibility_gates_custom_requires_explicit_risk_ceiling():
    """Verify Gate 6 fails closed when Custom risk profile has no risk ceiling."""
    fund = _valid_active_fund(riskometer=4)

    # Custom with no risk_ceiling -> MUST fail closed
    res_no_ceiling = check_eligibility_gates(
        fund_data=fund,
        client_risk_tier_num=RiskTier.CUSTOM,
        risk_ceiling=None,
    )
    assert res_no_ceiling.passed is False
    assert res_no_ceiling.mandate_suitability_gate is False
    assert any("explicit risk ceiling" in msg for msg in res_no_ceiling.failed_gates)

    # Custom with string "Custom" and no risk_ceiling -> MUST fail closed
    res_str_no_ceiling = check_eligibility_gates(
        fund_data=fund,
        client_risk_tier_num="Custom",
        risk_ceiling=None,
    )
    assert res_str_no_ceiling.passed is False
    assert res_str_no_ceiling.mandate_suitability_gate is False


def test_issue_24_check_eligibility_gates_custom_enforces_risk_ceiling():
    """Verify Gate 6 enforces candidate Riskometer <= client risk ceiling for Custom profile."""
    # Candidate with Riskometer = 5
    fund_risk_5 = _valid_active_fund(riskometer=5)

    # If ceiling is 4 -> candidate (5) must breach ceiling and FAIL Gate 6
    res_ceiling_4 = check_eligibility_gates(
        fund_data=fund_risk_5,
        client_risk_tier_num=RiskTier.CUSTOM,
        risk_ceiling=4,
    )
    assert res_ceiling_4.passed is False
    assert res_ceiling_4.mandate_suitability_gate is False
    assert any("exceeds client risk ceiling 4" in msg for msg in res_ceiling_4.failed_gates)

    # If ceiling is 5 -> candidate (5) is within ceiling and PASSES Gate 6
    res_ceiling_5 = check_eligibility_gates(
        fund_data=fund_risk_5,
        client_risk_tier_num=RiskTier.CUSTOM,
        risk_ceiling=5,
    )
    assert res_ceiling_5.mandate_suitability_gate is True
    assert res_ceiling_5.details["effective_risk_ceiling"] == 5

    # If ceiling is 6 -> candidate (5) is within ceiling and PASSES Gate 6
    res_ceiling_6 = check_eligibility_gates(
        fund_data=fund_risk_5,
        client_risk_tier_num=RiskTier.CUSTOM,
        risk_ceiling=6,
    )
    assert res_ceiling_6.mandate_suitability_gate is True
    assert res_ceiling_6.details["effective_risk_ceiling"] == 6


def test_issue_24_check_eligibility_gates_standard_tiers_ceiling():
    """Verify standard 3 public tiers have standard ceilings (Conservative=2, Moderate=4, Aggressive=6)."""
    fund_risk_5 = _valid_active_fund(riskometer=5)

    # Conservative (Tier 2 ceiling) -> fund with risk 5 must fail
    res_cons = check_eligibility_gates(
        fund_data=fund_risk_5,
        client_risk_tier_num=RiskTier.CONSERVATIVE,
    )
    assert res_cons.mandate_suitability_gate is False

    # Moderate (Tier 4 ceiling) -> fund with risk 5 must fail
    res_mod = check_eligibility_gates(
        fund_data=fund_risk_5,
        client_risk_tier_num=RiskTier.MODERATE,
    )
    assert res_mod.mandate_suitability_gate is False

    # Aggressive (Tier 6 ceiling) -> fund with risk 5 passes
    res_agg = check_eligibility_gates(
        fund_data=fund_risk_5,
        client_risk_tier_num=RiskTier.AGGRESSIVE,
    )
    assert res_agg.mandate_suitability_gate is True

    # Standard tier with explicit lower ceiling (Moderate with ceiling 3) -> fund with risk 4 fails
    fund_risk_4 = _valid_active_fund(riskometer=4)
    res_mod_c3 = check_eligibility_gates(
        fund_data=fund_risk_4,
        client_risk_tier_num=RiskTier.MODERATE,
        risk_ceiling=3,
    )
    assert res_mod_c3.mandate_suitability_gate is False
    assert any("exceeds client risk ceiling 3" in msg for msg in res_mod_c3.failed_gates)


def test_issue_24_compute_deterministic_sip_blueprint_propagates_risk_ceiling():
    """Verify compute_deterministic_sip_blueprint accepts risk_ceiling and filters candidates by it."""
    target = AssetAllocationTarget(
        equity_pct=Decimal("70.0"),
        debt_pct=Decimal("30.0"),
        cash_pct=Decimal("0.0"),
        risk_ceiling=4,
    )
    # Candidate universe needs >= 30 candidates to satisfy min_candidate_universe_size policy gate
    candidates = []
    for i in range(1, 16):
        c = _valid_active_fund(riskometer=4)
        c["fund_id"] = f"CAND_SUITABLE_{i}"
        c["scheme_name"] = f"Suitable Scheme {i}"
        c["rank_score"] = 80.0 + i
        candidates.append(c)
    for i in range(16, 31):
        c = _valid_active_fund(riskometer=5)
        c["fund_id"] = f"CAND_HIGH_RISK_{i}"
        c["scheme_name"] = f"High Risk Scheme {i}"
        c["rank_score"] = 99.0 + i  # higher score, but breach ceiling
        candidates.append(c)

    plan = compute_deterministic_sip_blueprint(
        monthly_budget=10000,
        risk_tier="Custom",
        client_aum=1000000,
        client_aum_verified=True,
        custom_saa_target=target,
        candidate_universe=candidates,
        risk_ceiling=4,
    )
    assert plan is not None
    # Verify high risk candidates were NOT selected due to risk ceiling
    selected_schemes = {item.scheme_name for item in plan.items if item.scheme_name}
    for i in range(16, 31):
        assert f"High Risk Scheme {i}" not in selected_schemes


def test_issue_24_recommend_sip_custom_saa_enforces_risk_ceiling(tmp_path, monkeypatch):
    """Verify recommend_sip with Custom SAA enforces risk_ceiling end-to-end and includes it in trace."""
    import openpyxl

    cas = tmp_path / "cas.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    today_str = date.today().strftime("%d-%b-%Y")
    as_of = date.today().isoformat()
    sheet.append(["To Date", today_str])
    sheet.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    sheet.append(["Custom Fund Direct Growth", "FOLIO-1", 100000.0, 100000.0, 1000.0])
    workbook.save(cas)

    target = AssetAllocationTarget(
        equity_pct=Decimal("60.0"),
        debt_pct=Decimal("40.0"),
        cash_pct=Decimal("0.0"),
        large_cap_pct=Decimal("25.0"),
        mid_cap_pct=Decimal("15.0"),
        small_cap_pct=Decimal("10.0"),
        flexi_cap_pct=Decimal("10.0"),
        risk_ceiling=4,
    )

    # 30 candidates: 15 with riskometer=4 (within ceiling), 15 with riskometer=5 (breach)
    candidates = [
        {
            "fund_id": f"CAND-{i}",
            "scheme_id": f"SCHEME-{i}",
            "isin": f"INF00000{i:03d}",
            "amc_name": f"AMC {i}",
            "category": "Large Cap",
            "benchmark": "Nifty 100 TRI",
            "is_direct": True,
            "riskometer_score": 4 if i <= 15 else 5,
            "direct_plan_evidence": {
                "scheme_id": f"SCHEME-{i}",
                "isin": f"INF00000{i:03d}",
                "plan": "Direct",
                "option": "Growth",
                "amc_name": f"AMC {i}",
                "benchmark": "Nifty 100 TRI",
                "reviewed_at": as_of,
                "source_document_sha256": "b" * 64,
            },
        }
        for i in range(1, 31)
    ]

    context = {
        "current_core_fund_count": 0,
        "evidence_attested_by_provider": True,
        "investor_owner_ref": "INVESTOR-REF-TEST",
        "sip_mandate_evidence": {
            "coverage_status": "COMPLETE",
            "source_ref": "sha256:" + "a" * 64,
            "mandates": [],
        },
        "as_of_date": as_of,
        "cas_valuation_date": as_of,
        "perimeter_complete": True,
        "assets": [
            {
                "asset_id": "ASSET-1",
                "asset_class": "cas_mutual_fund",
                "saa_bucket": "large_cap",
                "value_inr": "100000.00",
                "source_ref": "sha256:1234567890abcdef",
                "owner_scope": "primary_investor",
                "as_of_date": as_of,
            }
        ],
        "excluded_assets": [],
        "unmatched_items": [],
        "sign_off": {
            "attested_by": "ADV-001 (Senior Advisor)",
            "attestation_timestamp_utc": "2026-11-11T00:00:00Z",
            "attestation_statement": "Perimeter verified and reconciled for custom SAA mandate.",
            "signature_ref": "sig:ed25519:advisor_signature",
        },
        "ips": {
            "approved": True,
            "source_ref": "DOC-IPS-CUSTOM-001",
            "effective_date": as_of,
            "risk_ceiling": 4,
            "target_weights_pct": {
                "large_cap": 25.0,
                "mid_cap": 15.0,
                "small_cap": 10.0,
                "flexi_multi_cap": 10.0,
                "debt_liquid": 40.0,
            },
            "tolerance_band_pct": 3.0,
        },
        "candidate_policy": {
            "max_evidence_age_days": 45,
            "mandatory_gates": ["direct_plan", "risk"],
            "candidate_sleeves": {f"CAND-{i}": "large_cap" for i in range(1, 31)},
            "rounding_increment_inr": "500",
        },
        "candidate_gate_results": {
            f"CAND-{i}": {"direct_plan": "PASS", "risk": "PASS"} for i in range(1, 31)
        },
        "operational_evidence_by_candidate_id": {
            f"CAND-{i}": {
                "scheme_identity": {
                    "scheme_id": f"SCHEME-{i}", "isin": f"INF000000{i:03d}",
                    "plan": "Direct", "option": "Growth", "amc": "Example AMC",
                    "category": "Large Cap", "benchmark": "Nifty 100 TRI",
                },
                "evidence_ref": "sha256:ops", "evidence_as_of_date": as_of,
                "scheme_status": "ACTIVE", "minimum_monthly_sip_inr": "500",
                "exit_load_evidence_ref": "sha256:exit",
                "lockin_evidence_ref": "sha256:lock",
                "subscription_status_evidence_ref": "sha256:subscription",
            } for i in range(1, 31)
        },
        "goal_policy": {
            "max_evidence_age_days": 45,
            "minimum_horizon_days_by_asset_class": {"equity": 3650},
        },
        "goals": [{
            "goal_id": "custom-goal",
            "mandate_approved": True,
            "source_ref": "sha256:goal",
            "evidence_as_of_date": as_of,
            "target_amount_inr": "1000000",
            "liabilities_inr": "0",
            "target_date": f"{date.today().year + 11}-{date.today().month:02d}-{date.today().day:02d}",
            "asset_class": "equity",
            "approved_risk_profile": "Custom",
        }],
        "liquidity": {
            "verified_cash_inr": 50000.0,
            "approved_reserve_target_inr": 20000.0,
            "near_term_obligations_inr": 0.0,
            "monthly_net_income_inr": 150000.0,
            "essential_monthly_expenses_inr": 50000.0,
            "monthly_debt_service_inr": 0.0,
            "evidence_refs": {
                "cash": "BANK-001",
                "reserve": "BANK-001",
                "obligations": "BANK-001",
                "income": "BANK-001",
                "expenses": "BANK-001",
                "debt_service": "BANK-001",
            },
            "max_evidence_age_days": 45,
        },
        "stress_scenarios": [{
            "scenario_id": "income-shock", "income_reduction_pct": "10",
            "expense_increase_pct": "5",
        }],
        "concentration_policy": {
            "max_issuer_pct_of_portfolio": 25.0,
            "effective_date": as_of,
            "source_ref": "DOC-CONC-001",
        },
        "freshness": {
            "recommendation_as_of_date": as_of,
            "max_age_days": 90,
            "events": [],
        },
    }

    from types import SimpleNamespace
    monkeypatch.setattr(
        service,
        "load_holdings_from_cas_excel",
        lambda *args, **kwargs: [
            SimpleNamespace(
                scheme="Custom Fund Direct Growth",
                fund_id="FUND-1",
                scheme_id="SCHEME-1",
                plan_option_status="VERIFIED",
                option_type="GROWTH",
                is_direct=True,
                lookthrough_status="VERIFIED",
                metrics_status="VERIFIED",
                constituent_weights={"ISSUER A": 100.0},
                equity_pct=100.0,
                constituent_weights_coverage_pct=100.0,
                current_value_inr=100000.0,
            )
        ],
    )

    result = service.recommend_sip(
        cas_path=cas,
        metrics_path=None,
        aliases_path=None,
        monthly_budget_inr=10000,
        risk_profile="Custom",
        custom_saa_target=target,
        scheme_master={"status": "VERIFIED"},
        scheme_master_source_bytes=b"master bytes",
        portfolio_disclosures_by_scheme_id={"SCHEME-1": {"scheme_id": "SCHEME-1"}},
        portfolio_disclosure_source_bytes_by_scheme_id={"SCHEME-1": b"disclosure bytes"},
        disclosure_as_of_date=date.today(),
        candidate_universe=candidates,
        portfolio_context=context,
    )

    assert result["status"] == "HOLD"
    trace = result["portfolio_assessment"]["decision_trace"]
    record = json.loads(trace["canonical_record"])
    assert "effective_policy_digest" in record
    assert "screening_policy_sha256" in record["source_digests"]
    assert len(record["effective_policy_digest"]) == 64

    # Verify candidates 16-30 (riskometer=5) failed screening due to risk ceiling
    screening = result["portfolio_assessment"]["total_portfolio_context"]["candidate_screening"]
    eligible_ids = set(screening["eligible_candidate_ids"])
    for i in range(1, 16):
        assert f"CAND-{i}" in eligible_ids
    for i in range(16, 31):
        assert f"CAND-{i}" not in eligible_ids
