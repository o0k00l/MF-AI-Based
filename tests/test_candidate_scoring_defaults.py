"""
Unit tests verifying no default category, no repository-local client data default, and Small Cap scoring support.
Addresses Issue #41 & Issue #42: Remove hardcoded defaults from legacy candidate selector and define approved anchors.
"""
from __future__ import annotations

import pytest
from core.candidate_scoring import (
    CATEGORY_BENCHMARK_ANCHORS,
    FiduciaryFundSelector,
    ScoringWeights,
    calculate_candidate_6_pillar_score,
)


def _weights() -> ScoringWeights:
    return ScoringWeights(
        w_alpha=0.25,
        w_sharpe=0.20,
        w_ter=0.15,
        w_downside_buffer=0.15,
        w_international=0.15,
        w_mpb_overlap=0.10,
    )


def test_fiduciary_fund_selector_rejects_missing_path_without_data_default():
    with pytest.raises(ValueError, match="fund_metrics_path is required"):
        FiduciaryFundSelector(fund_metrics_path=None)


def test_calculate_score_rejects_empty_or_whitespace_category():
    candidate = {
        "alpha_3y": 2.0,
        "return_1y": 15.0,
        "sharpe_3y": 0.9,
        "ter_direct_pct": 0.65,
        "cash_debt_buffer_pct": 5.0,
        "international_equity_pct": 0.0,
    }
    with pytest.raises(ValueError, match="Explicit approved category_key is required"):
        calculate_candidate_6_pillar_score(candidate, category_key="", weights=_weights())


def test_small_cap_category_anchors_are_approved_and_scoreable():
    assert "Small Cap" in CATEGORY_BENCHMARK_ANCHORS
    anchors = CATEGORY_BENCHMARK_ANCHORS["Small Cap"]
    assert "alpha" in anchors
    assert "sharpe" in anchors
    assert "ter" in anchors
    assert "buffer" in anchors
    assert "intl" in anchors
    assert "overlap" in anchors

    candidate = {
        "alpha_3y": 3.0,
        "return_1y": 20.0,
        "sharpe_3y": 0.85,
        "ter_direct_pct": 0.70,
        "cash_debt_buffer_pct": 5.0,
        "international_equity_pct": 0.0,
        "overlap_pct": 5.0,
        "eligibility_status": "PASS",
        "is_eligible": True,
    }
    score, pillars = calculate_candidate_6_pillar_score(
        candidate,
        category_key="Small Cap",
        weights=_weights(),
    )
    assert 0.0 <= score <= 100.0
    assert len(pillars) == 6

