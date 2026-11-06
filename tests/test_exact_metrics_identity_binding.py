"""
Unit tests for exact scheme identity tuple binding on fund metrics.
Addresses Issue #84: Require provenance and exact scheme binding for current-holdings metrics and aliases.
"""
from __future__ import annotations

import pytest
from core.math_engine import _find_matching_metric_by_scheme_identity


def _sample_metric():
    return {
        "scheme_id": "SCH-100",
        "isin": "INF123456789",
        "amc_name": "HDFC Mutual Fund",
        "category": "Flexi Cap",
        "plan_type": "DIRECT",
        "option_type": "GROWTH",
        "eq": 98.0,
        "debt": 2.0,
        "lc": 70.0,
        "mc": 20.0,
        "sc": 8.0,
    }


def test_find_matching_metric_accepts_exact_identity_tuple():
    metrics = {"SCH-100": _sample_metric()}
    identity = {
        "scheme_id": "SCH-100",
        "isin": "INF123456789",
        "amc_name": "HDFC Mutual Fund",
        "category": "Flexi Cap",
        "plan_type": "DIRECT",
        "option_type": "GROWTH",
    }
    match = _find_matching_metric_by_scheme_identity("SCH-100", "INF123456789", metrics, identity=identity)
    assert match is not None
    assert match["scheme_id"] == "SCH-100"


def test_find_matching_metric_rejects_conflicting_amc():
    metrics = {"SCH-100": _sample_metric()}
    identity = {
        "scheme_id": "SCH-100",
        "isin": "INF123456789",
        "amc_name": "Conflicting ICICI AMC",
        "category": "Flexi Cap",
        "plan_type": "DIRECT",
        "option_type": "GROWTH",
    }
    with pytest.raises(ValueError, match="conflicts with verified scheme AMC"):
        _find_matching_metric_by_scheme_identity("SCH-100", "INF123456789", metrics, identity=identity)


def test_find_matching_metric_rejects_conflicting_category():
    metrics = {"SCH-100": _sample_metric()}
    identity = {
        "scheme_id": "SCH-100",
        "isin": "INF123456789",
        "amc_name": "HDFC Mutual Fund",
        "category": "Large Cap",
        "plan_type": "DIRECT",
        "option_type": "GROWTH",
    }
    with pytest.raises(ValueError, match="conflicts with verified scheme.*Category"):
        _find_matching_metric_by_scheme_identity("SCH-100", "INF123456789", metrics, identity=identity)


def test_find_matching_metric_rejects_conflicting_plan():
    metrics = {"SCH-100": _sample_metric()}
    identity = {
        "scheme_id": "SCH-100",
        "isin": "INF123456789",
        "amc_name": "HDFC Mutual Fund",
        "category": "Flexi Cap",
        "plan_type": "REGULAR",
        "option_type": "GROWTH",
    }
    with pytest.raises(ValueError, match="conflicts with verified scheme.*Plan"):
        _find_matching_metric_by_scheme_identity("SCH-100", "INF123456789", metrics, identity=identity)
