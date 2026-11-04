from __future__ import annotations

import json
from pathlib import Path
import pytest

from core.models import HoldingItem, AssetClass, PlanType
from core.math_engine import calculate_weighted_lookthrough_overlap


def _make_holding(
    fund_id: str,
    fund_name: str,
    *,
    constituent_weights: dict[str, float] | None = None,
    constituent_weights_coverage_pct: float | None = None,
    top_holdings: list[str] | None = None,
    current_value_inr: float = 100000.0,
    lookthrough_status: str = "VERIFIED",
    source_url: str | None = "https://example.com/factsheet.pdf",
    effective_date: str | None = "2026-03-31",
) -> HoldingItem:
    return HoldingItem(
        folio_number="12345/67",
        fund_id=fund_id,
        scheme_id=fund_id,
        fund_name=fund_name,
        plan=PlanType.DIRECT,
        asset_class=AssetClass.LARGE_CAP,
        equity_pct=100.0,
        debt_pct=0.0,
        hybrid_pct=0.0,
        international_pct=0.0,
        current_value_inr=current_value_inr,
        invested_value_inr=80000.0,
        units=1000.0,
        nav=100.0,
        top_holdings=top_holdings or [],
        constituent_weights=constituent_weights,
        constituent_weights_coverage_pct=constituent_weights_coverage_pct,
        lookthrough_status=lookthrough_status,
        lookthrough_source_url=source_url,
        lookthrough_effective_date=effective_date,
    )


def test_weighted_overlap_computes_exact_weight_from_verified_individual_constituents():
    h1 = _make_holding(
        "fund-a",
        "Fund A Direct Growth",
        constituent_weights={"RELIANCE": 10.0, "TCS": 8.0, "INFY": 6.0, "HDFCBANK": 76.0},
        constituent_weights_coverage_pct=100.0,
    )
    h2 = _make_holding(
        "fund-b",
        "Fund B Direct Growth",
        constituent_weights={"RELIANCE": 6.0, "TCS": 12.0, "ICICIBANK": 5.0, "LT": 77.0},
        constituent_weights_coverage_pct=100.0,
    )

    results = calculate_weighted_lookthrough_overlap([h1, h2], threshold_pct=5.0)

    assert len(results) == 1
    res = results[0]
    assert res.fund_a == "fund-a"
    assert res.fund_b == "fund-b"
    assert res.status == "VERIFIED"
    assert res.coverage_status == "VERIFIED"
    assert res.coverage_pct == 100.0
    # Overlap = min(10.0, 6.0) + min(8.0, 12.0) = 6.0 + 8.0 = 14.0%
    assert res.weighted_overlap_pct == 14.0
    assert res.verdict == "MODERATE"
    assert len(res.shared_stocks) == 2
    # TCS combined weight = 20.0, Reliance combined weight = 16.0
    assert res.shared_stocks[0]["stock"] == "TCS"
    assert res.shared_stocks[0]["weight_a_pct"] == 8.0
    assert res.shared_stocks[0]["weight_b_pct"] == 12.0
    assert res.shared_stocks[0]["combined_weight_pct"] == 20.0
    assert res.shared_stocks[1]["stock"] == "RELIANCE"
    assert res.shared_stocks[1]["weight_a_pct"] == 10.0
    assert res.shared_stocks[1]["weight_b_pct"] == 6.0
    assert res.shared_stocks[1]["combined_weight_pct"] == 16.0


def test_weighted_overlap_rejects_equal_weight_proxy_and_returns_unknown_limited_coverage(tmp_path):
    # Only aggregate top10 scalar and stock names provided
    metrics_file = tmp_path / "fund_metrics.json"
    metrics_file.write_text(json.dumps({
        "funds": [
            {"id": "fund-a", "top10": 45.0, "h": ["RELIANCE", "TCS", "INFY"]},
            {"id": "fund-b", "top10": 55.0, "h": ["RELIANCE", "TCS", "HDFCBANK"]},
        ]
    }), encoding="utf-8")

    h1 = _make_holding("fund-a", "Fund A Direct", top_holdings=["RELIANCE", "TCS", "INFY"])
    h2 = _make_holding("fund-b", "Fund B Direct", top_holdings=["RELIANCE", "TCS", "HDFCBANK"])

    results = calculate_weighted_lookthrough_overlap([h1, h2], metrics_path=metrics_file)

    assert len(results) == 1
    res = results[0]
    # Critical invariant: must NOT divide top10 / 10.0 to report a numeric overlap or "ACCEPTABLE" verdict
    assert res.weighted_overlap_pct is None
    assert res.verdict == "UNKNOWN"
    assert res.status == "LIMITED_COVERAGE"
    assert res.coverage_status == "INCOMPLETE"
    assert "equal-weight proxies are withheld" in res.reason
    assert len(res.shared_stocks) == 2
    assert {s["stock"] for s in res.shared_stocks} == {"RELIANCE", "TCS"}
    assert all(s["weight_a_pct"] is None for s in res.shared_stocks)
    assert all(s["weight_b_pct"] is None for s in res.shared_stocks)


def test_weighted_overlap_missing_disclosure_returns_unavailable():
    h1 = _make_holding("fund-a", "Fund A Direct", top_holdings=[])
    h2 = _make_holding("fund-b", "Fund B Direct", top_holdings=[])

    results = calculate_weighted_lookthrough_overlap([h1, h2])

    assert len(results) == 1
    res = results[0]
    assert res.weighted_overlap_pct is None
    assert res.verdict == "UNAVAILABLE"
    assert res.status == "UNAVAILABLE"
    assert res.coverage_status == "UNAVAILABLE"
    assert res.shared_stocks == []
    assert "missing" in res.reason


def test_weighted_overlap_disjoint_holdings_produces_zero_acceptable():
    h1 = _make_holding(
        "fund-a",
        "Fund A Direct Growth",
        constituent_weights={"RELIANCE": 50.0, "TCS": 50.0},
        constituent_weights_coverage_pct=100.0,
    )
    h2 = _make_holding(
        "fund-b",
        "Fund B Direct Growth",
        constituent_weights={"INFY": 50.0, "HDFCBANK": 50.0},
        constituent_weights_coverage_pct=100.0,
    )

    results = calculate_weighted_lookthrough_overlap([h1, h2], threshold_pct=0.0)

    assert len(results) == 1
    res = results[0]
    assert res.status == "VERIFIED"
    assert res.weighted_overlap_pct == 0.0
    assert res.verdict == "ACCEPTABLE"
    assert res.shared_stocks == []


def test_weighted_overlap_high_concentration_classification():
    h1 = _make_holding(
        "fund-a",
        "Fund A Direct Growth",
        constituent_weights={"RELIANCE": 25.0, "TCS": 25.0, "CASH": 50.0},
        constituent_weights_coverage_pct=100.0,
    )
    h2 = _make_holding(
        "fund-b",
        "Fund B Direct Growth",
        constituent_weights={"RELIANCE": 20.0, "TCS": 20.0, "DEBT": 60.0},
        constituent_weights_coverage_pct=100.0,
    )

    results = calculate_weighted_lookthrough_overlap([h1, h2])

    assert len(results) == 1
    res = results[0]
    # min(25, 20) + min(25, 20) = 40.0% -> >= 20.0% is HIGH_CONCENTRATION
    assert res.weighted_overlap_pct == 40.0
    assert res.verdict == "HIGH_CONCENTRATION"
    assert res.status == "VERIFIED"


def test_weighted_overlap_single_or_empty_holdings_returns_empty():
    assert calculate_weighted_lookthrough_overlap([]) == []
    h1 = _make_holding("fund-a", "Fund A Direct")
    assert calculate_weighted_lookthrough_overlap([h1]) == []
