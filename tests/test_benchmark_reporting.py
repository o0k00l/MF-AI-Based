from core.benchmark_reporting import BENCHMARK_BLOCKED, format_performance_metrics


def test_missing_benchmark_and_alpha_remain_explicitly_unavailable():
    result = format_performance_metrics(0.1542, None, None)

    assert result["portfolio_xirr"] == "15.42%"
    assert result["benchmark_xirr"] == BENCHMARK_BLOCKED
    assert result["alpha"] == "UNAVAILABLE"


def test_missing_portfolio_xirr_is_not_rendered_as_zero():
    result = format_performance_metrics(None, None, None)

    assert result["portfolio_xirr"] == "UNAVAILABLE"
    assert result["benchmark_xirr"] == BENCHMARK_BLOCKED
    assert result["alpha"] == "UNAVAILABLE"


def test_non_finite_or_boolean_values_are_rejected_for_display():
    result = format_performance_metrics(float("nan"), float("inf"), True)

    assert result["portfolio_xirr"] == "UNAVAILABLE"
    assert result["benchmark_xirr"] == BENCHMARK_BLOCKED
    assert result["alpha"] == "UNAVAILABLE"


def test_verified_numeric_benchmark_fields_are_formatted():
    result = format_performance_metrics(0.1542, 0.1211, 3.31)

    assert result == {
        "portfolio_xirr": "15.42%",
        "benchmark_xirr": "12.11%",
        "alpha": "+3.31%",
    }
