"""
tests/test_category_scoring_anchors.py - Unit tests for approved category-specific benchmark scoring anchors.
Addresses Issue #41: Define approved category-specific scoring anchors for the supported fund universe.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from core.candidate_scoring import (
    CATEGORY_BENCHMARK_ANCHORS,
    _REQUIRED_ANCHOR_KEYS,
    load_category_benchmark_anchors,
    calculate_candidate_6_pillar_score,
)


def test_all_supported_categories_have_complete_anchor_sets():
    anchors = load_category_benchmark_anchors()
    expected_categories = {
        "Healthcare", "Flexi Cap", "Mid Cap", "Large Cap",
        "Small Cap", "Multi Cap", "Large & Mid Cap"
    }
    assert expected_categories.issubset(set(anchors.keys()))

    for category, bounds in anchors.items():
        assert set(bounds.keys()) == _REQUIRED_ANCHOR_KEYS
        for metric, (lower, upper) in bounds.items():
            assert isinstance(lower, (int, float))
            assert isinstance(upper, (int, float))
            assert lower <= upper


def test_dynamic_proxy_resolves_all_categories():
    assert "Flexi Cap" in CATEGORY_BENCHMARK_ANCHORS
    assert "Small Cap" in CATEGORY_BENCHMARK_ANCHORS
    assert "Multi Cap" in CATEGORY_BENCHMARK_ANCHORS
    assert "Healthcare" in CATEGORY_BENCHMARK_ANCHORS

    # Unsupported category raises KeyError
    with pytest.raises(KeyError):
        _ = CATEGORY_BENCHMARK_ANCHORS["Commodities"]


def test_scoring_fails_closed_on_unsupported_category():
    candidate = {
        "fund_id": "cand-1",
        "category": "Unsupported Category",
        "ter": 0.85,
        "cash_buffer_pct": 5.0,
        "international_equity_pct": 0.0,
    }
    with pytest.raises(ValueError, match="category"):
        calculate_candidate_6_pillar_score(
            candidate,
            category_key="Unsupported Category",
        )
