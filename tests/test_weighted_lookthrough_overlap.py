from types import SimpleNamespace

from core.math_engine import (
    calculate_weighted_lookthrough_overlap,
    weighted_lookthrough_overlap_status,
)


def _holding(fund_id, weights, *, status="VERIFIED", coverage=100.0, top_holdings=None):
    return SimpleNamespace(
        fund_id=fund_id,
        scheme_id=fund_id,
        current_value_inr=100000.0,
        constituent_weights=weights,
        constituent_weights_coverage_pct=coverage,
        lookthrough_status=status,
        top_holdings=top_holdings or [],
    )


def test_weighted_overlap_uses_actual_constituent_weights():
    holdings = [
        _holding("scheme-a", {"RELIANCE INDUSTRIES": 30.0, "OTHER A": 70.0}),
        _holding("scheme-b", {"RELIANCE INDUSTRIES": 20.0, "OTHER B": 80.0}),
    ]

    assert weighted_lookthrough_overlap_status(holdings) == "VERIFIED"
    result = calculate_weighted_lookthrough_overlap(holdings, metrics_path=None)

    assert len(result) == 1
    assert result[0].weighted_overlap_pct == 20.0
    assert result[0].shared_stocks[0]["weight_a_pct"] == 30.0
    assert result[0].shared_stocks[0]["weight_b_pct"] == 20.0
    assert result[0].verdict == "MODERATE"


def test_weighted_overlap_never_infers_equal_weights_from_top_holdings():
    holdings = [
        _holding("scheme-a", None, status="MISSING", coverage=None,
                 top_holdings=["Reliance", "TCS", "Infosys"]),
        _holding("scheme-b", None, status="MISSING", coverage=None,
                 top_holdings=["Reliance", "HDFC Bank", "ICICI Bank"]),
    ]

    assert weighted_lookthrough_overlap_status(holdings) == "UNAVAILABLE"
    assert calculate_weighted_lookthrough_overlap(holdings) == []


def test_weighted_overlap_is_unavailable_when_any_holding_is_unverified():
    holdings = [
        _holding("scheme-a", {"RELIANCE": 100.0}),
        _holding("scheme-b", {"RELIANCE": 100.0}, status="STALE"),
    ]

    assert weighted_lookthrough_overlap_status(holdings) == "UNAVAILABLE"
    assert calculate_weighted_lookthrough_overlap(holdings) == []


def test_weighted_overlap_rejects_incomplete_or_invalid_weights():
    holdings = [
        _holding("scheme-a", {"RELIANCE": 70.0, "OTHER": 30.0}),
        _holding("scheme-b", {"RELIANCE": 70.0, "OTHER": 29.0}),
    ]

    assert weighted_lookthrough_overlap_status(holdings) == "UNAVAILABLE"
    assert calculate_weighted_lookthrough_overlap(holdings) == []


def test_zero_equity_holding_does_not_require_stock_disclosure():
    debt = _holding(
        "scheme-debt",
        None,
        status="MISSING",
        coverage=None,
    )
    debt.equity_pct = 0.0
    equity = _holding("scheme-equity", {"RELIANCE": 100.0})

    assert weighted_lookthrough_overlap_status([debt, equity]) == "VERIFIED"
    assert calculate_weighted_lookthrough_overlap([debt, equity]) == []
