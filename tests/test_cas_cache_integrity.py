import math
import pytest
from ingestion.cas_parser import to_cache_csv, stage_portfolio


def test_to_cache_csv_strict_rejects_missing_current_value():
    holdings = [
        {"scheme": "Scheme A", "units": 10.0, "invested_value": 1000.0}
    ]
    with pytest.raises(ValueError, match="current_value"):
        to_cache_csv({"holdings": holdings}, enriched=True, strict=True)


def test_to_cache_csv_strict_rejects_missing_units():
    holdings = [
        {"scheme": "Scheme A", "current_value": 1200.0, "invested_value": 1000.0}
    ]
    with pytest.raises(ValueError, match="units"):
        to_cache_csv({"holdings": holdings}, enriched=True, strict=True)


def test_to_cache_csv_strict_rejects_missing_invested_value():
    holdings = [
        {"scheme": "Scheme A", "current_value": 1200.0, "units": 10.0}
    ]
    with pytest.raises(ValueError, match="invested_value"):
        to_cache_csv({"holdings": holdings}, enriched=True, strict=True)


def test_to_cache_csv_strict_rejects_non_finite_values():
    holdings = [
        {"scheme": "Scheme A", "current_value": float("nan"), "units": 10.0, "invested_value": 1000.0}
    ]
    with pytest.raises(ValueError, match="non-finite"):
        to_cache_csv({"holdings": holdings}, enriched=True, strict=True)


def test_to_cache_csv_strict_rejects_negative_values():
    holdings = [
        {"scheme": "Scheme A", "current_value": -500.0, "units": 10.0, "invested_value": 1000.0}
    ]
    with pytest.raises(ValueError, match="Negative"):
        to_cache_csv({"holdings": holdings}, enriched=True, strict=True)


def test_to_cache_csv_derives_nav_when_unreported():
    holdings = [
        {"scheme": "Scheme A", "current_value": 1200.0, "units": 10.0, "invested_value": 1000.0, "folio": "F1", "isin": "INF1"}
    ]
    csv_str = to_cache_csv({"holdings": holdings}, enriched=True, strict=True)
    assert "120.0000" in csv_str
    assert "DERIVED" in csv_str


def test_to_cache_csv_non_strict_skips_invalid_rows():
    holdings = [
        {"scheme": "Scheme Valid", "current_value": 1200.0, "units": 10.0, "invested_value": 1000.0, "folio": "F1", "isin": "INF1", "nav": 120.0},
        {"scheme": "Scheme Corrupt", "current_value": -500.0, "units": 10.0, "invested_value": 1000.0},  # Negative
    ]
    csv_str = to_cache_csv({"holdings": holdings}, enriched=True, strict=False)
    assert "Scheme Valid" in csv_str
    assert "Scheme Corrupt" not in csv_str
    assert "UNAVAILABLE" not in csv_str


def test_stage_portfolio_writes_valid_cache_atomically(tmp_path):
    holdings = [
        {"scheme": "Scheme A", "current_value": 1200.0, "units": 10.0, "invested_value": 1000.0, "folio": "F1", "isin": "INF1", "nav": 120.0}
    ]
    res = stage_portfolio({"holdings": holdings}, tmp_path, slug="Test_Staged")
    cache_path = tmp_path / "Test_Staged" / "data" / "_active_funds_cache.csv"
    assert cache_path.is_file()
    assert "Scheme A" in cache_path.read_text(encoding="utf-8")


def test_stage_portfolio_cleans_up_on_validation_failure(tmp_path):
    corrupt_holdings = [
        {"scheme": "Scheme Invalid", "current_value": -500.0, "units": 10.0, "invested_value": 1000.0}
    ]
    res = stage_portfolio({"holdings": corrupt_holdings}, tmp_path, slug="Test_Corrupt", require_validation=True)
    assert res.get("staging_failed") is True
    cache_path = tmp_path / "Test_Corrupt" / "data" / "_active_funds_cache.csv"
    assert not cache_path.exists()
