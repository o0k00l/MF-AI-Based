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


def test_thematic_exposure_uses_actual_verified_constituent_weights():
    result = calculate_thematic_exposures([_holding()])
    pharma = next(item for item in result if item.theme_name == "Pharma & Healthcare")

    assert pharma.look_through_stocks_inr == 8000.0
    assert pharma.look_through_stocks_pct == 8.0
    assert pharma.coverage_status == "FULL"
    assert pharma.key_underlying_holdings == ["sunpharma"]


def test_thematic_exposure_does_not_use_top_ten_or_equal_weight_proxy():
    holding = _holding(
        lookthrough_status="MISSING",
        constituent_weights=None,
        constituent_weights_coverage_pct=None,
    )
    result = calculate_thematic_exposures(
        [holding],
        metrics_path=None,
        aliases_path=None,
    )
    pharma = next(item for item in result if item.theme_name == "Pharma & Healthcare")

    assert pharma.look_through_stocks_inr is None
    assert pharma.look_through_stocks_pct is None
    assert pharma.coverage_status == "UNAVAILABLE"


def test_thematic_exposure_withholds_aggregate_if_any_holding_lacks_coverage():
    result = calculate_thematic_exposures([
        _holding(),
        _holding(
            scheme="Second Equity Fund",
            current_value_inr=50000.0,
            lookthrough_status="STALE",
        ),
    ])
    pharma = next(item for item in result if item.theme_name == "Pharma & Healthcare")

    assert pharma.look_through_stocks_inr is None
    assert pharma.coverage_status == "UNAVAILABLE"


def test_thematic_exposure_matches_exact_normalized_company_name_only():
    result = calculate_thematic_exposures([
        _holding(constituent_weights={
            "SUN PHARMA LTD": 10.0,
            "Other Company": 90.0,
        })
    ])
    pharma = next(item for item in result if item.theme_name == "Pharma & Healthcare")

    assert pharma.look_through_stocks_inr == 0.0
    assert pharma.key_underlying_holdings == []
