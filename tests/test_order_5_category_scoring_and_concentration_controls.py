"""
tests/test_order_5_category_scoring_and_concentration_controls.py

Authoritative acceptance test suite for Order 5:
- Issue #41: Category scoring anchors for fund universe, multi-factor institutional
  scoring, approved benchmark methodology, and fail-closed candidate evaluation.
- Issue #26: Strict security-master identity, cross-AMC aliasing, corporate actions,
  portfolio look-through, and marginal post-SIP concentration controls.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from core.candidate_scoring import (
    CATEGORY_BENCHMARK_ANCHORS,
    ScoringWeights,
    calculate_candidate_6_pillar_score,
    calculate_morningstar_price_score,
    compute_marginal_portfolio_benefit,
    load_category_benchmark_anchors,
    normalize_metric,
    _REQUIRED_ANCHOR_KEYS,
)
from core.portfolio_sip_controls import (
    calculate_lookthrough_exposure,
    evaluate_classified_concentration,
)
from core.security_master import (
    canonicalize_security_label,
    load_security_master,
    normalize_constituent_weights,
    normalize_security_identifier,
)


# =============================================================================
# PART 1: ISSUE #41 — Category Scoring Anchors & Multi-Factor Scoring
# =============================================================================

def test_order_5_category_anchors_policy_structure_and_signature():
    """Verify category_benchmark_anchors.json carries approval envelope, version, and citations."""
    anchors = load_category_benchmark_anchors(force_reload=True)
    assert isinstance(anchors, dict)
    assert len(anchors) >= 7

    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "category_benchmark_anchors.json"
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    assert raw.get("schema_version") == "1.0"
    assert raw.get("approval_envelope", {}).get("approval_status") == "INDEPENDENTLY_APPROVED"
    assert "categories" in raw

    for cat_name, cat_data in raw["categories"].items():
        assert "source_citation" in cat_data
        assert "benchmark_identity" in cat_data
        assert "anchor_set" in cat_data
        anchor_set = cat_data["anchor_set"]
        for key in _REQUIRED_ANCHOR_KEYS:
            assert key in anchor_set, f"Category {cat_name} missing anchor key {key}"
            lower, upper = anchor_set[key]
            assert lower < upper, f"Category {cat_name} key {key} bounds invalid: {lower} >= {upper}"


def test_order_5_all_supported_categories_anchors():
    """Verify all 7 supported SEBI categories have complete valid metric anchor bounds."""
    expected_categories = {
        "Healthcare", "Flexi Cap", "Mid Cap", "Large Cap",
        "Small Cap", "Multi Cap", "Large & Mid Cap"
    }
    anchors = load_category_benchmark_anchors()
    assert expected_categories.issubset(set(anchors.keys()))

    for cat in expected_categories:
        bounds = anchors[cat]
        for key in _REQUIRED_ANCHOR_KEYS:
            assert key in bounds


def test_order_5_unsupported_category_fails_closed():
    """Verify candidate evaluation in an unsupported category strictly raises ValueError."""
    weights = ScoringWeights(
        w_alpha=0.25, w_sharpe=0.20, w_ter=0.15,
        w_downside_buffer=0.15, w_international=0.15, w_mpb_overlap=0.10
    )
    candidate = {
        "fund_id": "cand-crypto-01",
        "scheme_id": "scheme-crypto-01",
        "alpha_3y": 2.0,
        "return_1y": 8.0,
        "sharpe_3y": 0.85,
        "ter_direct_pct": 0.70,
        "cash_debt_buffer_pct": 5.0,
        "international_equity_pct": 0.0,
        "overlap_pct": 20.0,
        "eligibility_status": "PASS",
        "is_eligible": True,
    }
    with pytest.raises(ValueError, match="Unsupported scoring category"):
        calculate_candidate_6_pillar_score(
            candidate,
            category_key="Cryptocurrency Fund",
            weights=weights,
        )


def test_order_5_scoring_fails_closed_on_ineligible_candidate():
    """Verify scoring rejects ineligible candidate funds before calculating metrics."""
    weights = ScoringWeights(
        w_alpha=0.25, w_sharpe=0.20, w_ter=0.15,
        w_downside_buffer=0.15, w_international=0.15, w_mpb_overlap=0.10
    )

    # 1. Candidate with eligibility_status == 'FAILED'
    cand_failed = {
        "fund_id": "cand-01",
        "scheme_id": "sch-01",
        "alpha_3y": 3.0,
        "return_1y": 15.0,
        "sharpe_3y": 1.2,
        "ter_direct_pct": 0.65,
        "cash_debt_buffer_pct": 4.0,
        "international_equity_pct": 0.0,
        "overlap_pct": 10.0,
        "eligibility_status": "FAILED",
        "is_eligible": False,
    }
    with pytest.raises(ValueError, match="eligibility"):
        calculate_candidate_6_pillar_score(cand_failed, category_key="Flexi Cap", weights=weights)

    # 2. Candidate with is_eligible == False
    cand_not_eligible = {
        "fund_id": "cand-02",
        "scheme_id": "sch-02",
        "alpha_3y": 3.0,
        "return_1y": 15.0,
        "sharpe_3y": 1.2,
        "ter_direct_pct": 0.65,
        "cash_debt_buffer_pct": 4.0,
        "international_equity_pct": 0.0,
        "overlap_pct": 10.0,
        "eligibility_status": "PASS",
        "is_eligible": False,
    }
    with pytest.raises(ValueError, match="eligibility"):
        calculate_candidate_6_pillar_score(cand_not_eligible, category_key="Flexi Cap", weights=weights)


def test_order_5_scoring_weights_validation():
    """Verify ScoringWeights validates sum=1.0, non-negative, finite numbers, and rejects booleans."""
    valid_weights = ScoringWeights(0.25, 0.20, 0.15, 0.15, 0.15, 0.10)
    assert valid_weights.validate() is True

    # Sum does not equal 1.0
    invalid_sum = ScoringWeights(0.50, 0.20, 0.15, 0.15, 0.15, 0.10)
    assert invalid_sum.validate() is False

    # Negative weight
    negative_weight = ScoringWeights(-0.10, 0.35, 0.25, 0.20, 0.15, 0.15)
    assert negative_weight.validate() is False

    # Boolean input rejected
    bool_weight = ScoringWeights(True, 0.20, 0.15, 0.15, 0.15, 0.10)  # type: ignore
    assert bool_weight.validate() is False


def test_order_5_normalize_metric_bounds_and_inversion():
    """Verify metric normalization clamps bounds and correctly inverts cost/overlap."""
    # Standard metric (higher is better): alpha
    assert normalize_metric(1.0, 0.0, 4.0) == 25.0
    assert normalize_metric(4.0, 0.0, 4.0) == 100.0
    assert normalize_metric(5.0, 0.0, 4.0) == 100.0  # Clamped upper
    assert normalize_metric(-1.0, 0.0, 4.0) == 0.0   # Clamped lower

    # Inverted metric (lower is better): TER or stock overlap
    # 0.5% TER with range [0.4%, 1.2%]
    # (1.2 - 0.5) / (1.2 - 0.4) = 0.7 / 0.8 = 87.5
    assert normalize_metric(0.5, 0.4, 1.2, invert=True) == 87.5
    # 1.2% TER (worst in range) gives 0.0
    assert normalize_metric(1.2, 0.4, 1.2, invert=True) == 0.0

    # Degenerate zero-variance case (min == max) gives neutral 50.0
    assert normalize_metric(2.0, 2.0, 2.0) == 50.0

    # Missing/None returns 0.0
    assert normalize_metric(None, 0.0, 5.0) == 0.0


def test_order_5_portfolio_aware_scoring_evidence_verification():
    """Verify portfolio-aware candidate scoring enforces cryptographic overlap evidence."""
    weights = ScoringWeights(0.25, 0.20, 0.15, 0.15, 0.15, 0.10)
    cand = {
        "fund_id": "CAND-01",
        "scheme_id": "CAND-01",
        "alpha_3y": 2.5,
        "return_1y": 15.0,
        "sharpe_3y": 1.1,
        "ter_direct_pct": 0.55,
        "cash_debt_buffer_pct": 6.0,
        "international_equity_pct": 0.0,
        "is_eligible": True,
        "eligibility_status": "PASS",
    }
    today_str = date.today().isoformat()

    # Missing overlap evidence fails closed
    with pytest.raises(ValueError, match="Verified portfolio overlap evidence is required"):
        calculate_candidate_6_pillar_score(
            cand, "Flexi Cap", weights=weights, portfolio_aware=True,
            as_of_date=today_str,
        )

    # Valid overlap evidence and anchor evidence
    raw_overlap = b'{"overlap_pct": 15.5, "coverage_pct": 99.8}'
    overlap_hash = hashlib.sha256(raw_overlap).hexdigest()
    valid_overlap_evidence = {
        "status": "VERIFIED",
        "reviewer_attested": True,
        "candidate_id": "CAND-01",
        "overlap_pct": 15.5,
        "coverage_pct": 99.8,
        "as_of_date": today_str,
        "source_bytes": raw_overlap,
        "source_document_sha256": overlap_hash,
        "source_ref": f"sha256:{overlap_hash}",
    }

    raw_anchor = b'{"anchor": "Flexi Cap", "alpha_3y": [-2.0, 5.0]}'
    anchor_hash = hashlib.sha256(raw_anchor).hexdigest()
    valid_anchor_evidence = {
        "status": "APPROVED",
        "reviewer_attested": True,
        "reviewer_id": "REV-01",
        "category": "Flexi Cap",
        "benchmark_identity": "Nifty 500 TRI",
        "policy_version": "2026.10",
        "effective_date": today_str,
        "source_bytes": raw_anchor,
        "source_document_sha256": anchor_hash,
        "source_ref": f"sha256:{anchor_hash}",
        "anchor_set": {
            "alpha": [-2.0, 5.0],
            "ret1y": [0.0, 25.0],
            "sharpe": [0.3, 1.5],
            "ter": [0.3, 1.2],
            "buffer": [0.0, 15.0],
            "intl": [0.0, 25.0],
            "overlap": [0.0, 50.0],
        },
    }

    score, breakdown = calculate_candidate_6_pillar_score(
        cand, "Flexi Cap", weights=weights, portfolio_aware=True,
        portfolio_overlap_evidence=valid_overlap_evidence,
        approved_category_anchor_evidence=valid_anchor_evidence,
        as_of_date=today_str,
    )
    assert 0.0 <= score <= 100.0
    assert "alpha_return" in breakdown
    assert "sharpe_efficiency" in breakdown
    assert "cost_efficiency" in breakdown
    assert "downside_buffer" in breakdown


# =============================================================================
# PART 2: ISSUE #26 — Security Master Identity, Aliasing & Look-Through
# =============================================================================

def test_order_5_security_master_canonicalization_and_corporate_actions():
    """Verify security master handles corporate actions and aliases across AMCs."""
    master = load_security_master()

    # Corporate action normalization: merged entity resolves to surviving canonical id
    canon_hdfc, ok_hdfc = normalize_security_identifier("HDFC Limited", master)
    assert canon_hdfc == "HDFCBANK"
    assert ok_hdfc is True

    # Punctuation and suffix stripping
    assert canonicalize_security_label("Reliance Industries Ltd. - PP") == "RELIANCE INDUSTRIES"
    assert canonicalize_security_label("L&T Limited") == "L AND T"
    assert canonicalize_security_label("Tata Motors Limited - DVR") == "TATA MOTORS"

    # Cross-AMC alias resolution
    canon_lt, ok_lt = normalize_security_identifier("L&T Ltd.", master)
    assert canon_lt == "LT"
    assert ok_lt is True

    canon_ril, ok_ril = normalize_security_identifier("RIL", master)
    assert canon_ril == "RELIANCE"
    assert ok_ril is True


def test_order_5_strict_security_resolution_fails_closed():
    """Verify strict security resolution raises ValueError and lookthrough returns HOLD on unresolved."""
    sec_master = {
        "securities": {
            "RELIANCE": {"canonical_id": "RELIANCE", "name": "Reliance Industries Limited"},
        }
    }

    # Strict normalization fails closed
    with pytest.raises(ValueError, match="Unresolved security identifier"):
        normalize_security_identifier("UNKNOWN_SECURITY_XYZ", sec_master, strict=True)

    # Look-through exposure fails closed to HOLD on unresolved constituent
    holdings = [
        {
            "holding_value_inr": "100000.00",
            "coverage_pct": 100.0,
            "constituents": {
                "RELIANCE": 60.0,
                "UNKNOWN_SECURITY_XYZ": 40.0,
            },
        }
    ]
    res = calculate_lookthrough_exposure(holdings, required_coverage_pct="99.5", security_master=sec_master)
    assert res["status"] == "HOLD"
    assert "LOOKTHROUGH_INCOMPLETE_OR_UNRESOLVED" in res["reason"]
    assert res["unresolved_issuer"] == "UNKNOWN_SECURITY_XYZ"


def test_order_5_lookthrough_coverage_gate_fails_closed():
    """Verify look-through calculation fails closed when disclosure coverage is below required policy threshold."""
    holdings = [
        {
            "holding_value_inr": "100000.00",
            "coverage_pct": 95.0,  # Below 99.5% requirement
            "constituents": {"RELIANCE": 50.0, "TCS": 50.0},
        }
    ]
    res = calculate_lookthrough_exposure(holdings, required_coverage_pct="99.5")
    assert res["status"] == "HOLD"
    assert res["reason"] == "LOOKTHROUGH_COVERAGE_BELOW_POLICY"
    assert res["issuer_exposure_inr"] is None


def test_order_5_classified_concentration_evaluates_sector_market_cap_and_theme():
    """Verify evaluate_classified_concentration detects sector, theme, and cap breaches."""
    classifications = {
        "issuer-a": {"sector": "Financials", "market_cap_bucket": "large_cap", "themes": ["banking"]},
        "issuer-b": {"sector": "Financials", "market_cap_bucket": "large_cap", "themes": ["banking"]},
        "issuer-c": {"sector": "Technology", "market_cap_bucket": "mid_cap", "themes": ["cloud"]},
    }
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # Breach case: Financials = 60%, Banking = 60% with 40% sector limit
    breach_result = evaluate_classified_concentration(
        {"issuer-a": "30000.00", "issuer-b": "30000.00", "issuer-c": "40000.00"},
        classifications,
        total_portfolio_inr="100000.00",
        as_of_date=today,
        classification_as_of_date=yesterday,
        classification_source_ref="sha256:valid-source-hash",
        max_evidence_age_days=30,
        max_sector_pct="40",
        max_market_cap_pct="70",
        max_theme_pct="40",
    )
    assert breach_result["status"] == "HOLD"
    assert "Financials" in breach_result["breaches"]["sector"]
    assert "banking" in breach_result["breaches"]["theme"]

    # Passing case: All below limits
    pass_result = evaluate_classified_concentration(
        {"issuer-a": "20000.00", "issuer-b": "10000.00", "issuer-c": "40000.00"},
        classifications,
        total_portfolio_inr="100000.00",
        as_of_date=today,
        classification_as_of_date=yesterday,
        classification_source_ref="sha256:valid-source-hash",
        max_evidence_age_days=30,
        max_sector_pct="45",
        max_market_cap_pct="70",
        max_theme_pct="45",
    )
    assert pass_result["status"] == "ASSESSED"
    assert pass_result["breaches"] == {}


def test_order_5_classified_concentration_fails_closed_on_stale_or_missing_classifications():
    """Verify evaluate_classified_concentration fails closed on stale classifications or unclassified issuers."""
    today = date.today().isoformat()
    stale_date = (date.today() - timedelta(days=60)).isoformat()

    # Stale classification date (> 30 days max age)
    stale_result = evaluate_classified_concentration(
        {"issuer-a": "50000.00"},
        {"issuer-a": {"sector": "Technology", "market_cap_bucket": "large_cap", "themes": []}},
        total_portfolio_inr="100000.00",
        as_of_date=today,
        classification_as_of_date=stale_date,
        classification_source_ref="sha256:stale-source",
        max_evidence_age_days=30,
        max_sector_pct="50",
        max_market_cap_pct="50",
        max_theme_pct="50",
    )
    assert stale_result["status"] == "HOLD"
    assert stale_result["reason"] == "ISSUER_CLASSIFICATION_STALE_OR_FUTURE"

    # Missing issuer in classification dictionary
    missing_result = evaluate_classified_concentration(
        {"issuer-unclassified": "50000.00"},
        {},
        total_portfolio_inr="100000.00",
        as_of_date=today,
        classification_as_of_date=today,
        classification_source_ref="sha256:valid-source",
        max_evidence_age_days=30,
        max_sector_pct="50",
        max_market_cap_pct="50",
        max_theme_pct="50",
    )
    assert missing_result["status"] == "HOLD"
    assert "issuer-unclassified" in missing_result["unclassified_issuers"]


def test_order_5_marginal_post_sip_exposure_and_concentration_reconciliation():
    """Verify before-and-after marginal exposure reconciliation after proposed SIP allocation."""
    master = load_security_master()

    # Current Portfolio: INR 100,000
    # 60,000 in Scheme 1 (100% RELIANCE)
    # 40,000 in Scheme 2 (100% TCS)
    existing_holdings = [
        {
            "holding_value_inr": "60000.00",
            "coverage_pct": "100.0",
            "constituents": {"RELIANCE": 100.0},
        },
        {
            "holding_value_inr": "40000.00",
            "coverage_pct": "100.0",
            "constituents": {"TCS": 100.0},
        },
    ]
    curr_lookthrough = calculate_lookthrough_exposure(
        existing_holdings, required_coverage_pct="99.5", security_master=master
    )
    assert curr_lookthrough["status"] == "CALCULATED"
    assert Decimal(curr_lookthrough["issuer_exposure_inr"]["RELIANCE"]) == Decimal("60000.00")
    assert Decimal(curr_lookthrough["issuer_exposure_inr"]["TCS"]) == Decimal("40000.00")

    # Proposed Monthly SIP allocation: INR 20,000 into Candidate Scheme
    # Candidate Scheme look-through: 50% RELIANCE, 50% INFOSYS
    # Note: INFOSYS canonicalizes to INFY via security master
    proposed_sip_rows = [
        {
            "holding_value_inr": "20000.00",
            "coverage_pct": "100.0",
            "constituents": {"RELIANCE": 50.0, "INFOSYS": 50.0},
        }
    ]
    sip_lookthrough = calculate_lookthrough_exposure(
        proposed_sip_rows, required_coverage_pct="99.5", security_master=master
    )
    assert sip_lookthrough["status"] == "CALCULATED"
    assert Decimal(sip_lookthrough["issuer_exposure_inr"]["RELIANCE"]) == Decimal("10000.00")
    assert Decimal(sip_lookthrough["issuer_exposure_inr"]["INFY"]) == Decimal("10000.00")

    # Marginal Post-SIP Aggregation
    # New Total = INR 120,000
    # RELIANCE = 60,000 + 10,000 = 70,000 (58.33%)
    # TCS = 40,000 + 0 = 40,000 (33.33%)
    # INFY = 0 + 10,000 = 10,000 (8.33%)
    post_sip_exposures = {}
    for k, v in curr_lookthrough["issuer_exposure_inr"].items():
        post_sip_exposures[k] = Decimal(v)
    for k, v in sip_lookthrough["issuer_exposure_inr"].items():
        post_sip_exposures[k] = post_sip_exposures.get(k, Decimal("0")) + Decimal(v)

    total_post_sip = sum(post_sip_exposures.values())
    assert total_post_sip == Decimal("120000.00")
    assert post_sip_exposures["RELIANCE"] == Decimal("70000.00")
    assert post_sip_exposures["TCS"] == Decimal("40000.00")
    assert post_sip_exposures["INFY"] == Decimal("10000.00")

    # Verify concentration evaluation on post-SIP exposures
    today = date.today().isoformat()
    classifications = {
        "RELIANCE": {"sector": "Energy", "market_cap_bucket": "large_cap", "themes": ["oil"]},
        "TCS": {"sector": "Technology", "market_cap_bucket": "large_cap", "themes": ["it"]},
        "INFY": {"sector": "Technology", "market_cap_bucket": "large_cap", "themes": ["it"]},
    }
    eval_res = evaluate_classified_concentration(
        {k: str(v) for k, v in post_sip_exposures.items()},
        classifications,
        total_portfolio_inr=str(total_post_sip),
        as_of_date=today,
        classification_as_of_date=today,
        classification_source_ref="sha256:post-sip-test",
        max_evidence_age_days=30,
        max_sector_pct="65",
        max_market_cap_pct="100",
        max_theme_pct="65",
    )
    assert eval_res["status"] == "ASSESSED"
    assert eval_res["breaches"] == {}
