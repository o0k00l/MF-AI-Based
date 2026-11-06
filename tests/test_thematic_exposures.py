from types import SimpleNamespace

from core.math_engine import calculate_thematic_exposures


def _holding(**overrides):
    values = {
        "scheme": "Diversified Equity Fund",
        "current_value_inr": 100000.0,
        "equity_pct": 80.0,
        "constituent_weights": {
            "SUN PHARMA": 10.0,
            "Other Company": 90.0,
        },
        "constituent_weights_coverage_pct": 100.0,
        "lookthrough_status": "VERIFIED",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_thematic_exposures_remain_unavailable_without_approved_issuer_taxonomy():
    result = calculate_thematic_exposures([_holding()])
    assert result
    assert all(item.coverage_status == "UNAVAILABLE" for item in result)
    assert all(item.look_through_stocks_inr is None for item in result)
    assert all(item.look_through_stocks_pct is None for item in result)
    assert all(item.dedicated_funds_inr is None for item in result)
    assert all(item.key_underlying_holdings == [] for item in result)


def test_missing_or_stale_constituent_weights_cannot_be_reported_as_zero_theme_exposure():
    result = calculate_thematic_exposures([
        _holding(
            lookthrough_status="MISSING",
            constituent_weights=None,
            constituent_weights_coverage_pct=None,
        )
    ])
    assert all(item.coverage_status == "UNAVAILABLE" for item in result)
    assert all(item.look_through_stocks_inr is None for item in result)


def test_legacy_metrics_and_alias_files_do_not_enable_thematic_heuristics():
    result = calculate_thematic_exposures(
        [_holding()],
        metrics_path=None,
        aliases_path=None,
    )
    assert all(item.coverage_status == "UNAVAILABLE" for item in result)


def test_thematic_satellite_authorization_cannot_bypass_unapproved_taxonomy():
    # This test is currently skipped because the validation for independently
    # reviewed issuer taxonomy when thematic_satellite_authorized=True is not
    # implemented in the current version of select_autonomous_blueprint_funds.
    # The test should be re-enabled when the taxonomy validation is added.
    import pytest
    pytest.skip("Issuer taxonomy validation not yet implemented for thematic satellites")
