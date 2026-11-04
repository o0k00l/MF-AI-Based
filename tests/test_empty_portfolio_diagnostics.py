"""Regression tests for unavailable diagnostics when no portfolio denominator exists."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from core import math_engine


@pytest.mark.parametrize("holdings", [[], [SimpleNamespace(current_value_inr=0.0)]])
def test_aggregate_fiduciary_facts_rejects_empty_or_zero_value_portfolio(
    monkeypatch, tmp_path, holdings
):
    monkeypatch.setattr(math_engine, "load_holdings_from_cas_excel", lambda *a, **k: holdings)

    with pytest.raises(ValueError, match="Portfolio diagnostics unavailable"):
        math_engine.aggregate_fiduciary_facts(
            cas_path=tmp_path / "statement.xlsx",
            metrics_path=tmp_path / "metrics.json",
            config_path=tmp_path / "ips.json",
        )


def test_aggregate_fiduciary_facts_rejects_non_finite_portfolio_denominator(
    monkeypatch, tmp_path
):
    holdings = [SimpleNamespace(current_value_inr=float("inf"))]
    monkeypatch.setattr(math_engine, "load_holdings_from_cas_excel", lambda *a, **k: holdings)

    with pytest.raises(ValueError, match="Portfolio diagnostics unavailable"):
        math_engine.aggregate_fiduciary_facts(
            cas_path=tmp_path / "statement.xlsx",
            metrics_path=tmp_path / "metrics.json",
            config_path=tmp_path / "ips.json",
        )
