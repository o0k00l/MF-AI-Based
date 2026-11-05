import math
import pytest
from ingestion.cas_parser import (
    to_cache_csv,
    stage_portfolio,
    validate_statement_reconciliation_envelope,
)


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
    res = stage_portfolio({
        "holdings": holdings,
        "as_of": "2026-10-15",
        "stated_total": 1200.0,
        "source_digest": "a" * 64,
    }, tmp_path, slug="Test_Staged")
    cache_path = tmp_path / "Test_Staged" / "data" / "_active_funds_cache.csv"
    assert cache_path.is_file()
    assert "Scheme A" in cache_path.read_text(encoding="utf-8")
    assert res.get("staging_failed") is False
    assert res.get("reconciliation_envelope") is not None


def test_stage_portfolio_cleans_up_on_validation_failure(tmp_path):
    corrupt_holdings = [
        {"scheme": "Scheme Invalid", "current_value": -500.0, "units": 10.0, "invested_value": 1000.0}
    ]
    res = stage_portfolio({"holdings": corrupt_holdings}, tmp_path, slug="Test_Corrupt", require_validation=True)
    assert res.get("staging_failed") is True
    cache_path = tmp_path / "Test_Corrupt" / "data" / "_active_funds_cache.csv"
    assert not cache_path.exists()


def test_stage_portfolio_rejects_missing_envelope_by_default(tmp_path):
    holdings = [
        {"scheme": "Scheme A", "current_value": 1200.0, "units": 10.0, "invested_value": 1000.0, "folio": "F1", "isin": "INF1", "nav": 120.0}
    ]
    # Plain dictionary without as_of or stated_total
    res = stage_portfolio({"holdings": holdings}, tmp_path, slug="Test_No_Envelope", require_envelope=True)
    assert res.get("staging_failed") is True
    assert "reconciliation envelope" in res.get("error", "").lower()
    cache_path = tmp_path / "Test_No_Envelope" / "data" / "_active_funds_cache.csv"
    assert not cache_path.exists()


def test_stage_portfolio_rejects_reconciliation_mismatch(tmp_path):
    holdings = [
        {"scheme": "Scheme A", "current_value": 1000.0, "units": 10.0, "invested_value": 900.0, "folio": "F1", "isin": "INF1", "nav": 100.0}
    ]
    # stated_total (5000.0) disagrees with holdings sum (1000.0)
    res = stage_portfolio({
        "holdings": holdings,
        "as_of": "2026-10-15",
        "stated_total": 5000.0,
        "source_digest": "b" * 64,
    }, tmp_path, slug="Test_Mismatch", require_envelope=True)
    assert res.get("staging_failed") is True
    assert "reconciliation failed" in res.get("error", "").lower()
    cache_path = tmp_path / "Test_Mismatch" / "data" / "_active_funds_cache.csv"
    assert not cache_path.exists()


def test_stage_portfolio_preserves_existing_cache_on_failed_replacement(tmp_path):
    # Step 1: Stage valid portfolio
    valid_holdings = [
        {"scheme": "Scheme Good", "current_value": 2500.0, "units": 25.0, "invested_value": 2000.0, "folio": "F1", "isin": "INF1", "nav": 100.0}
    ]
    res1 = stage_portfolio({
        "holdings": valid_holdings,
        "as_of": "2026-10-01",
        "stated_total": 2500.0,
        "source_digest": "c" * 64,
    }, tmp_path, slug="Test_Preserve")
    assert res1.get("staging_failed") is False

    cache_path = tmp_path / "Test_Preserve" / "data" / "_active_funds_cache.csv"
    assert cache_path.is_file()
    original_cache_content = cache_path.read_text(encoding="utf-8")
    assert "Scheme Good" in original_cache_content

    # Step 2: Attempt replacement with corrupt/mismatched data
    corrupt_parsed = {
        "holdings": [
            {"scheme": "Scheme Corrupt", "current_value": -100.0, "units": 10.0, "invested_value": 100.0}
        ],
        "as_of": "2026-10-15",
        "stated_total": 500.0,
    }
    res2 = stage_portfolio(corrupt_parsed, tmp_path, slug="Test_Preserve", require_validation=True, require_envelope=True)
    assert res2.get("staging_failed") is True
    assert res2.get("last_known_good_preserved") is True

    # Step 3: Verify existing active cache was NOT deleted and is preserved
    assert cache_path.is_file()
    assert cache_path.read_text(encoding="utf-8") == original_cache_content


def test_validate_reconciliation_envelope_requires_source_digest_by_default():
    holdings = [
        {"scheme": "Scheme A", "current_value": 1000.0, "units": 10.0, "invested_value": 900.0}
    ]
    with pytest.raises(ValueError, match="Valid 64-character SHA-256 source digest is required"):
        validate_statement_reconciliation_envelope({
            "holdings": holdings,
            "as_of": "2026-10-15",
            "stated_total": 1000.0,
            # missing source_digest
        })


def test_stage_portfolio_rejects_unbound_spoofed_envelope(tmp_path):
    holdings = [
        {"scheme": "Scheme Good", "current_value": 2500.0, "units": 25.0, "invested_value": 2000.0, "folio": "F1", "isin": "INF1", "nav": 100.0}
    ]
    parsed = {
        "holdings": holdings,
        "as_of": "2026-10-01",
        "stated_total": 2500.0,
        "source_digest": "c" * 64,
    }
    # Spoofed envelope with mismatched totals / digest
    spoofed_envelope = {
        "status": "VERIFIED_RECONCILED",
        "statement_date": "2026-10-01",
        "source_digest": "d" * 64,  # mismatched digest
        "holdings_count": 1,
        "parsed_total": 2500.0,
        "validation_token": "fake_token",
    }
    res = stage_portfolio(parsed, tmp_path, slug="Test_Spoofed_Env", envelope=spoofed_envelope)
    assert res.get("staging_failed") is True
    assert "reconciliation envelope" in res.get("error", "").lower()
    assert "mismatch" in res.get("error", "").lower()


def test_stage_portfolio_rejects_tampered_holdings_against_envelope(tmp_path):
    holdings = [
        {"scheme": "Scheme Good", "current_value": 2500.0, "units": 25.0, "invested_value": 2000.0, "folio": "F1", "isin": "INF1", "nav": 100.0}
    ]
    parsed = {
        "holdings": holdings,
        "as_of": "2026-10-01",
        "stated_total": 2500.0,
        "source_digest": "c" * 64,
    }
    valid_envelope = validate_statement_reconciliation_envelope(parsed)
    assert valid_envelope["holdings_digest"] is not None

    # Tamper with holdings units/value while preserving count and stated total
    tampered_parsed = {
        "holdings": [
            {"scheme": "Scheme Tampered", "current_value": 2500.0, "units": 25.0, "invested_value": 2000.0, "folio": "F1", "isin": "INF1", "nav": 100.0}
        ],
        "as_of": "2026-10-01",
        "stated_total": 2500.0,
        "source_digest": "c" * 64,
    }
    res = stage_portfolio(tampered_parsed, tmp_path, slug="Test_Tampered", envelope=valid_envelope)
    assert res.get("staging_failed") is True
    assert "mismatch" in res.get("error", "").lower()
