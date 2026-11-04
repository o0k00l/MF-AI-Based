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
    import pytest
    from core.math_engine import compute_deterministic_sip_blueprint

    with pytest.raises(ValueError, match="independently reviewed issuer taxonomy"):
        compute_deterministic_sip_blueprint(
            monthly_budget=25000.0,
            risk_tier="Tier 6 (Very High)",
            stability_buffer_pct=0.0,
            client_aum=5000000.0,
            thematic_satellite_pct_of_equity=5.0,
            thematic_satellite_authorized=True,
        )
