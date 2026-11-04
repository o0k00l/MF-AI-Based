import pytest

from core.math_engine import _find_matching_metric_by_scheme_identity


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
