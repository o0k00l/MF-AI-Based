import pytest

from core.math_engine import (
    _find_matching_metric_by_scheme_identity,
    _validate_sip_metrics_exposures,
)


def test_sip_metrics_require_exact_scheme_id_and_isin():
    metrics = {
        "legacy-name": {
            "id": "legacy-name",
            "scheme": "Example Direct Growth",
            "isin": "INF000000001",
            "eq": 95,
        },
        "scheme-1": {
            "id": "scheme-1",
            "scheme_id": "scheme-1",
            "isin": "INF000000001",
            "eq": 95,
        },
    }

    assert _find_matching_metric_by_scheme_identity(
        "scheme-1", "INF000000001", metrics
    ) is metrics["scheme-1"]


def test_sip_metrics_do_not_fall_back_to_name_or_alias():
    metrics = {
        "legacy-name": {
            "id": "legacy-name",
            "scheme": "Example Direct Growth",
            "isin": "INF000000001",
            "eq": 95,
        }
    }

    assert _find_matching_metric_by_scheme_identity(
        "scheme-1", "INF000000001", metrics
    ) is None


def test_sip_metrics_reject_scheme_id_with_conflicting_isin():
    metrics = {
        "scheme-1": {
            "scheme_id": "scheme-1",
            "isin": "INF999999999",
        }
    }

    with pytest.raises(ValueError, match="ISIN conflicts"):
        _find_matching_metric_by_scheme_identity(
            "scheme-1", "INF000000001", metrics
        )


def test_sip_metrics_reject_duplicate_exact_scheme_records():
    metrics = {
        "first": {"scheme_id": "scheme-1", "isin": "INF000000001"},
        "second": {"scheme_id": "scheme-1", "isin": "INF000000001"},
    }

    with pytest.raises(ValueError, match="Duplicate fund metrics"):
        _find_matching_metric_by_scheme_identity(
            "scheme-1", "INF000000001", metrics
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("eq", -0.1),
        ("debt", 100.1),
        ("lc", float("nan")),
        ("mc", float("inf")),
        ("sc", True),
    ],
)
def test_sip_metrics_reject_out_of_domain_exposures(field, value):
    metric = {"eq": 90, "debt": 10, "lc": 50, "mc": 30, "sc": 10, "market_cap_basis": "TOTAL_PORTFOLIO_PCT"}
    metric[field] = value

    with pytest.raises(ValueError, match="exposure"):
        _validate_sip_metrics_exposures(metric, scheme_id="scheme-1")


def test_sip_metrics_reject_equity_and_debt_total_over_100_percent():
    metric = {"eq": 95.1, "debt": 5.0, "lc": 50, "mc": 30, "sc": 10, "market_cap_basis": "TOTAL_PORTFOLIO_PCT"}

    with pytest.raises(ValueError, match="exceeds 100%"):
        _validate_sip_metrics_exposures(metric, scheme_id="scheme-1")


def test_sip_metrics_accept_finite_bounded_exposures():
    metric = {"eq": 90, "debt": 10, "lc": 50, "mc": 30, "sc": 10}

    _validate_sip_metrics_exposures(metric, scheme_id="scheme-1")
