"""Safe presentation helpers for benchmark-dependent performance claims."""

from __future__ import annotations

import math
from typing import Any


BENCHMARK_UNAVAILABLE = (
    "UNAVAILABLE — approved benchmark mapping or supporting evidence unavailable"
)


def _finite_number(value: Any) -> float | None:
    """Return a finite numeric value, rejecting booleans and invalid inputs."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def format_performance_metrics(
    portfolio_xirr: Any,
    benchmark_xirr: Any,
    alpha_pct: Any,
) -> dict[str, str]:
    """Format performance fields without turning missing evidence into zero."""
    portfolio = _finite_number(portfolio_xirr)
    benchmark = _finite_number(benchmark_xirr)
    alpha = _finite_number(alpha_pct)

    return {
        "portfolio_xirr": f"{portfolio * 100:.2f}%" if portfolio is not None else "UNAVAILABLE",
        "benchmark_xirr": f"{benchmark * 100:.2f}%" if benchmark is not None else BENCHMARK_UNAVAILABLE,
        "alpha": f"{alpha:+.2f}%" if alpha is not None else "UNAVAILABLE",
    }
