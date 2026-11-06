import json
import pytest
from datetime import date
from core.eligibility import (
    load_fund_screening_policy,
    check_eligibility_gates,
    filter_candidates,
    CATEGORY_AUM_CAPS,
)
from core.security_master import (
    load_security_master,
    normalize_security_identifier,
    normalize_constituent_weights,
)
from core.math_engine import (
    HoldingItem,
    compute_candidate_portfolio_overlap,
    evaluate_candidate_portfolio_concentration_controls,
)


def test_load_fund_screening_policy_validates_gate_thresholds():
    policy = load_fund_screening_policy()
    assert policy["_schema"] == "fiduciary.screening_criteria.v1"
    assert "_policy_digest" in policy
    assert len(policy["_policy_digest"]) == 64
    gt = policy["gate_thresholds"]
    assert gt["amc_max_limit_pct"] == 30.0
    assert gt["min_aum_crore"] == 1000.0
    assert gt["min_sharpe"] == 0.40
    assert gt["max_top10_concentration_pct"] == 55.0


def test_load_fund_screening_policy_fails_on_missing_threshold(tmp_path):
    policy = load_fund_screening_policy()
    bad_policy = dict(policy)
    bad_gt = dict(policy["gate_thresholds"])
    del bad_gt["min_sharpe"]
    bad_policy["gate_thresholds"] = bad_gt

    p = tmp_path / "bad_screening.json"
    p.write_text(json.dumps(bad_policy), encoding="utf-8")

    with pytest.raises(ValueError, match="missing required keys"):
        load_fund_screening_policy(p)


def test_changing_policy_threshold_changes_effective_gate_behavior():
    policy = load_fund_screening_policy()

    # Fund with Sharpe 0.50 - all required fields to pass all gates except Sharpe
    fund = {
        "fund_id": "F1",
        "fund_name": "Test Alpha Fund",
        "category": "Flexi Cap",
        "amc_name": "Test AMC",
        "scheme_id": "TEST_SCHEME_1",
        "isin": "INF000000001",
        "aum_crore": 5000.0,
        "aum_stable": True,
        "top10_concentration_pct": 20.0,
        "max_sector_concentration_pct": 15.0,
        "sharpe_3y": 0.50,
        "alpha_3y": 2.0,
        "downside_capture_ratio": 80.0,
        "upside_capture_ratio": 100.0,
        "riskometer_score": 5,
        "mandate_suitable": True,
        "data_complete": True,
        "confidence_score": 0.95,
        "track_record_years": 10.0,
        "manager_tenure_years": 4.0,
        "is_direct": True,
        "plan": "Direct Growth",
        "expense_ratio": 0.60,
        "as_of_date": "2026-10-05",
        "_evidence_root": "tests/test_evidence",
        "direct_plan_evidence": {
            "scheme_id": "TEST_SCHEME_1",
            "isin": "INF000000001",
            "amc_name": "Test AMC",
            "scheme_name": "Test Alpha Fund",
            "plan": "Direct",
            "source_url": "https://example.com/factsheet.pdf",
            "source_type": "AMC_FACTSHEET",
            "source_file": "factsheet.txt",
            "source_document_sha256": "5dc1d1dd8d0be46c5d40fb957d61f0a241723aa27cdf73f9512d351a23edba4b",
            "reviewer_attested": True,
            "reviewed_at": "2026-10-01"
        },
    }
    # Diverse portfolio with AMC concentration below 30% threshold
    holdings = [
        {"amc_name": "Test AMC", "current_value_inr": 20000.0, "total_portfolio_inr": 100000.0},
        {"amc_name": "Other AMC 1", "current_value_inr": 40000.0, "total_portfolio_inr": 100000.0},
        {"amc_name": "Other AMC 2", "current_value_inr": 40000.0, "total_portfolio_inr": 100000.0},
    ]

    # Policy A: min_sharpe = 0.40 -> passes
    res_a = check_eligibility_gates(fund, portfolio_holdings=holdings, policy=policy)
    assert res_a.passed is True
    assert res_a.policy_version == policy["version"]
    assert res_a.policy_digest == policy["_policy_digest"]

    # Policy B: min_sharpe modified to 0.70 -> fails Gate 4 (Sharpe below threshold)
    policy_strict = dict(policy)
    policy_strict["gate_thresholds"] = dict(policy["gate_thresholds"], min_sharpe=0.70)
    res_b = check_eligibility_gates(fund, portfolio_holdings=holdings, policy=policy_strict)
    assert res_b.passed is False
    assert any("Sharpe" in g for g in res_b.failed_gates)


def test_eligibility_fails_closed_when_policy_is_corrupt():
    fund = {"fund_id": "F1", "fund_name": "Test Fund"}
    # Pass empty or invalid policy
    res = check_eligibility_gates(fund, policy={"version": "1.0"})
    assert res.passed is False
    assert any("Policy Validation" in g for g in res.failed_gates)


def test_dynamic_category_aum_caps_matches_policy():
    policy = load_fund_screening_policy()
    rules = [r for r in policy["flag_rules"] if r.get("id") == "AUM_OUT_OF_BAND"]
    expected_limits = rules[0]["limits_crore"]
    assert CATEGORY_AUM_CAPS["Small Cap"] == expected_limits["Small Cap"]
    assert CATEGORY_AUM_CAPS["Mid Cap"] == expected_limits["Mid Cap"]
    assert CATEGORY_AUM_CAPS["Large Cap"] == expected_limits["Large Cap"]


def test_security_master_load_and_digest():
    master = load_security_master()
    assert master["_schema"] == "fiduciary.security_master.v1"
    assert "_master_digest" in master
    assert len(master["_master_digest"]) == 64
    assert "RELIANCE" in master["securities"]
    assert "INFY" in master["securities"]


def test_strict_candidate_portfolio_overlap_rejects_unresolved_constituents():
    sec_master = load_security_master()

    holding = HoldingItem(
        fund_id="fund-1",
        scheme="Existing Scheme",
        fund_name="Existing Scheme",
        folio="TEST-FOLIO",
        asset_class="Equity",
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=100000.0,
        invested_value_inr=90000.0,
        units=1000.0,
        nav=100.0,
        constituent_weights={"Reliance": 60.0, "Infosys Limited": 40.0},
        constituent_weights_coverage_pct=100.0,
    )

    # Candidate with unresolvable security identifier
    candidate_unresolved = {
        "fund_id": "cand-unknown",
        "constituent_weights": {"UNKNOWN CORRUPT EQUITY": 50.0, "INFY": 50.0},
        "constituent_weights_coverage_pct": 100.0,
    }

    # Strict look-through resolution fails closed (returns None, not zero or guessed overlap)
    overlap_none = compute_candidate_portfolio_overlap(
        candidate_unresolved, holdings=[holding], security_master=sec_master, strict=True
    )
    assert overlap_none is None

    # Candidate with verified resolved constituents
    candidate_verified = {
        "fund_id": "cand-known",
        "constituent_weights": {"Reliance": 50.0, "TCS": 50.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    overlap_val = compute_candidate_portfolio_overlap(
        candidate_verified, holdings=[holding], security_master=sec_master, strict=True
    )
    assert overlap_val == 50.0


def test_evaluate_candidate_portfolio_concentration_controls():
    sec_master = load_security_master()

    holding = HoldingItem(
        fund_id="fund-1",
        scheme="Existing Scheme",
        fund_name="Existing Scheme",
        folio="TEST-FOLIO",
        asset_class="Equity",
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=100000.0,
        invested_value_inr=90000.0,
        units=1000.0,
        nav=100.0,
        constituent_weights={"Reliance": 50.0, "Infosys Limited": 50.0},
        constituent_weights_coverage_pct=100.0,
    )

    # 1. Candidate with > 40% duplicate overlap
    dup_candidate = {
        "fund_id": "cand-dup",
        "category": "Flexi Cap",
        "constituent_weights": {"Reliance": 45.0, "Infosys Limited": 55.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    res_dup = evaluate_candidate_portfolio_concentration_controls(
        dup_candidate, holdings=[holding], security_master=sec_master, max_overlap_pct=40.0
    )
    assert res_dup["passed"] is False
    assert res_dup["status"] == "REJECT"
    assert "CANDIDATE_OVERLAP_BREACH" in res_dup["reason"]

    # 2. Candidate with missing look-through
    missing_candidate = {
        "fund_id": "cand-missing",
        "category": "Flexi Cap",
        "constituent_weights": None,
        "constituent_weights_coverage_pct": None,
    }
    res_missing = evaluate_candidate_portfolio_concentration_controls(
        missing_candidate, holdings=[holding], security_master=sec_master
    )
    assert res_missing["passed"] is False
    assert res_missing["status"] == "HOLD"
    assert "LOOKTHROUGH_INCOMPLETE" in res_missing["reason"]

    # 3. Thematic candidate in starter portfolio
    thematic_candidate = {
        "fund_id": "cand-thematic",
        "category": "Thematic - Tech",
        "constituent_weights": {"TCS": 100.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    res_starter = evaluate_candidate_portfolio_concentration_controls(
        thematic_candidate, holdings=[holding], security_master=sec_master, is_starter=True
    )
    assert res_starter["passed"] is False
    assert res_starter["status"] == "REJECT"
    assert "STARTER_PORTFOLIO_THEMATIC_PROHIBITED" in res_starter["reason"]

    # 4. Compliant diversified candidate
    good_candidate = {
        "fund_id": "cand-good",
        "category": "Large Cap",
        "constituent_weights": {"TCS": 50.0, "LT": 50.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    res_good = evaluate_candidate_portfolio_concentration_controls(
        good_candidate, holdings=[holding], security_master=sec_master, max_overlap_pct=40.0
    )
    assert res_good["passed"] is True
    assert res_good["status"] == "PASSED"
    assert res_good["overlap_pct"] == 0.0


def test_filter_candidates_rejects_unauthorized_threshold_overrides():
    policy = load_fund_screening_policy()
    with pytest.raises(ValueError, match="Unauthorized per-call threshold override for 'amc_max_limit_pct'"):
        filter_candidates(
            candidate_universe=[],
            current_portfolio=[],
            policy=policy,
            amc_max_limit_pct=25.0,
            allow_threshold_overrides=False,
        )

    with pytest.raises(ValueError, match="Unauthorized per-call threshold override for 'max_overlap_limit_pct'"):
        filter_candidates(
            candidate_universe=[],
            current_portfolio=[],
            policy=policy,
            max_overlap_limit_pct=35.0,
            allow_threshold_overrides=False,
        )


def test_evaluate_candidate_portfolio_concentration_multi_dimensional_breaches():
    sec_master = {
        "_schema": "fiduciary.security_master.v1",
        "securities": {
            "TCS": {"isin": "INE467B01029", "canonical_name": "Tata Consultancy Services Limited"},
            "INFY": {"isin": "INE009A01021", "canonical_name": "Infosys Limited"},
            "HDFCBANK": {"isin": "INE040A01034", "canonical_name": "HDFC Bank Limited"},
        }
    }
    classifications = {
        "TCS": {"sector": "Technology", "market_cap_bucket": "Large Cap", "themes": ["Digital", "Export"]},
        "INFY": {"sector": "Technology", "market_cap_bucket": "Large Cap", "themes": ["Digital", "Export"]},
        "HDFCBANK": {"sector": "Financial Services", "market_cap_bucket": "Large Cap", "themes": ["Financialization"]},
    }

    holding = HoldingItem(
        fund_id="fund-tech",
        scheme="Existing Tech Scheme",
        fund_name="Existing Tech Scheme",
        folio="TECH-FOLIO",
        asset_class="Equity",
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=100000.0,
        invested_value_inr=90000.0,
        units=1000.0,
        nav=100.0,
        constituent_weights={"TCS": 60.0, "INFY": 40.0},
        constituent_weights_coverage_pct=100.0,
    )

    # Candidate adding more Technology / Digital theme exposure, exceeding max_sector_pct of 35%
    tech_heavy_cand = {
        "fund_id": "cand-more-tech",
        "category": "Flexi Cap",
        "constituent_weights": {"TCS": 50.0, "INFY": 50.0},
        "constituent_weights_coverage_pct": 100.0,
        "allocation_inr": 20000.0,
    }

    res_sector = evaluate_candidate_portfolio_concentration_controls(
        tech_heavy_cand,
        holdings=[holding],
        security_master=sec_master,
        classifications=classifications,
        max_overlap_pct=100.0,  # Allow overlap check to pass, test sector breach
        max_sector_pct=35.0,
        max_issuer_pct=100.0,
    )
    assert res_sector["passed"] is False
    assert res_sector["status"] == "REJECT"
    assert "SECTOR_CONCENTRATION_BREACH" in res_sector["reason"]

    # Candidate exceeding theme concentration cap of 15%
    res_theme = evaluate_candidate_portfolio_concentration_controls(
        tech_heavy_cand,
        holdings=[holding],
        security_master=sec_master,
        classifications=classifications,
        max_overlap_pct=100.0,  # Allow overlap/sector checks to pass, test theme breach
        max_sector_pct=100.0,
        max_theme_pct=15.0,
        max_issuer_pct=100.0,
    )
    assert res_theme["passed"] is False
    assert res_theme["status"] == "REJECT"
    assert "THEME_CONCENTRATION_BREACH" in res_theme["reason"]

    # Missing security master when required returns HOLD
    res_no_master = evaluate_candidate_portfolio_concentration_controls(
        tech_heavy_cand,
        holdings=[holding],
        security_master=None,
        require_security_master=True,
    )
    assert res_no_master["passed"] is False
    assert res_no_master["status"] == "HOLD"
    assert res_no_master["reason"] == "SECURITY_MASTER_REQUIRED"
