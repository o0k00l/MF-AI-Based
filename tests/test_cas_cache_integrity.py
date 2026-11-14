import math
import pytest
from ingestion.cas_parser import (
    to_cache_csv,
    stage_portfolio,
    validate_statement_reconciliation_envelope,
    parse_cache_csv,
    load_cache_csv,
    compute_holdings_canonical_digest,
)




@pytest.fixture(autouse=True)
def configure_external_client_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("MF_CLIENT_DATA_DIR", str(tmp_path))

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
    with pytest.raises(ValueError, match="invested"):
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
    parsed = {
        "holdings": holdings,
        "as_of": "2026-10-15",
        "stated_total": 1200.0,
        "source_digest": "a" * 64,
    }
    envelope = validate_statement_reconciliation_envelope(parsed)
    res = stage_portfolio(parsed, tmp_path, slug="Test_Staged", envelope=envelope)
    cache_path = tmp_path / "Test_Staged" / "data" / "_active_funds_cache.csv"
    assert cache_path.is_file()
    assert "Scheme A" in cache_path.read_text(encoding="utf-8")
    assert res.get("staging_failed") is False
    assert res.get("reconciliation_envelope") is not None

def test_stage_portfolio_cleans_up_on_validation_failure(tmp_path):
    corrupt_holdings = [
        {"scheme": "Scheme Invalid", "current_value": -500.0, "units": 10.0, "invested_value": 1000.0}
    ]
    res = stage_portfolio({"holdings": corrupt_holdings}, tmp_path, slug="Test_Corrupt")
    assert res.get("staging_failed") is True
    cache_path = tmp_path / "Test_Corrupt" / "data" / "_active_funds_cache.csv"
    assert not cache_path.exists()


def test_stage_portfolio_rejects_missing_envelope_by_default(tmp_path):
    holdings = [
        {"scheme": "Scheme A", "current_value": 1200.0, "units": 10.0, "invested_value": 1000.0, "folio": "F1", "isin": "INF1", "nav": 120.0}
    ]
    # Plain dictionary without as_of or stated_total
    res = stage_portfolio({"holdings": holdings}, tmp_path, slug="Test_No_Envelope")
    assert res.get("staging_failed") is True
    assert "explicit verified_reconciled" in res.get("error", "").lower()
    cache_path = tmp_path / "Test_No_Envelope" / "data" / "_active_funds_cache.csv"
    assert not cache_path.exists()


def test_stage_portfolio_rejects_reconciliation_mismatch(tmp_path):
    holdings = [
        {"scheme": "Scheme A", "current_value": 1000.0, "units": 10.0, "invested_value": 900.0, "folio": "F1", "isin": "INF1", "nav": 100.0}
    ]
    parsed = {
        "holdings": holdings,
        "as_of": "2026-10-15",
        "stated_total": 5000.0,
        "source_digest": "b" * 64,
    }
    # A status-only envelope cannot bypass recomputation of reconciliation.
    res = stage_portfolio(parsed, tmp_path, slug="Test_Mismatch", envelope={"status": "VERIFIED_RECONCILED"})
    assert res.get("staging_failed") is True
    assert "reconciliation failed" in res.get("error", "").lower()
    cache_path = tmp_path / "Test_Mismatch" / "data" / "_active_funds_cache.csv"
    assert not cache_path.exists()

def test_stage_portfolio_preserves_existing_cache_on_failed_replacement(tmp_path):
    valid_holdings = [
        {"scheme": "Scheme Good", "current_value": 2500.0, "units": 25.0, "invested_value": 2000.0, "folio": "F1", "isin": "INF1", "nav": 100.0}
    ]
    valid_parsed = {
        "holdings": valid_holdings,
        "as_of": "2026-10-01",
        "stated_total": 2500.0,
        "source_digest": "c" * 64,
    }
    valid_envelope = validate_statement_reconciliation_envelope(valid_parsed)
    res1 = stage_portfolio(valid_parsed, tmp_path, slug="Test_Preserve", envelope=valid_envelope)
    assert res1.get("staging_failed") is False

    cache_path = tmp_path / "Test_Preserve" / "data" / "_active_funds_cache.csv"
    assert cache_path.is_file()
    original_cache_content = cache_path.read_text(encoding="utf-8")
    assert "Scheme Good" in original_cache_content

    corrupt_parsed = {
        "holdings": [
            {"scheme": "Scheme Corrupt", "current_value": -100.0, "units": 10.0, "invested_value": 100.0}
        ],
        "as_of": "2026-10-15",
        "stated_total": 500.0,
        "source_digest": "d" * 64,
    }
    res2 = stage_portfolio(corrupt_parsed, tmp_path, slug="Test_Preserve")
    assert res2.get("staging_failed") is True
    assert res2.get("last_known_good_preserved") is True
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

def test_to_cache_csv_strict_rejects_boolean_values():
    # Boolean True/False must never be coerced into 1.0/0.0
    with pytest.raises(ValueError, match="Boolean value not allowed"):
        to_cache_csv({"holdings": [{"scheme": "Scheme A", "current_value": True, "units": 10.0, "invested_value": 1000.0}]}, enriched=True, strict=True)

    with pytest.raises(ValueError, match="Boolean value not allowed"):
        to_cache_csv({"holdings": [{"scheme": "Scheme A", "current_value": 1000.0, "units": False, "invested_value": 1000.0}]}, enriched=True, strict=True)

    with pytest.raises(ValueError, match="Boolean value not allowed"):
        to_cache_csv({"holdings": [{"scheme": "Scheme A", "current_value": 1000.0, "units": 10.0, "invested_value": 1000.0, "nav": True}]}, enriched=True, strict=True)


def test_to_cache_csv_strict_rejects_empty_string_and_none():
    with pytest.raises(ValueError, match="Missing required field"):
        to_cache_csv({"holdings": [{"scheme": "Scheme A", "current_value": "", "units": 10.0, "invested_value": 1000.0}]}, enriched=True, strict=True)

    with pytest.raises(ValueError, match="Missing required field"):
        to_cache_csv({"holdings": [{"scheme": "Scheme A", "current_value": None, "units": 10.0, "invested_value": 1000.0}]}, enriched=True, strict=True)


def test_parse_cache_csv_preserves_unavailable_as_none():
    csv_text = (
        '"Scheme Name",CurrentValue,Units,Invested,"Folio Number",ISIN,NAV,NAV_Source\n'
        '"Scheme Incomplete",UNAVAILABLE,UNAVAILABLE,1000.00,"F1","INF1",UNAVAILABLE,NONE\n'
        '"Scheme Complete",1500.00,10.000,1000.00,"F2","INF2",150.0000,SOURCE\n'
    )
    rows = parse_cache_csv(csv_text)
    assert len(rows) == 2
    inc = rows[0]
    assert inc["scheme"] == "Scheme Incomplete"
    assert inc["current_value"] is None
    assert inc["units"] is None
    assert inc["invested"] == 1000.00
    assert inc["nav"] is None

    comp = rows[1]
    assert comp["scheme"] == "Scheme Complete"
    assert comp["current_value"] == 1500.00
    assert comp["units"] == 10.000
    assert comp["invested"] == 1000.00
    assert comp["nav"] == 150.0000


def test_load_cache_csv_from_file_preserves_none(tmp_path):
    p = tmp_path / "cache.csv"
    p.write_text(
        '"Scheme Name",CurrentValue,Units,Invested,"Folio Number",ISIN,NAV,NAV_Source\n'
        '"Scheme A",UNAVAILABLE,5.000,500.00,"F1","INF1",UNAVAILABLE,NONE\n',
        encoding="utf-8"
    )
    rows = load_cache_csv(p)
    assert len(rows) == 1
    assert rows[0]["current_value"] is None
    assert rows[0]["units"] == 5.000


def test_stage_portfolio_has_no_validation_or_envelope_opt_out(tmp_path):
    parsed = {"holdings": []}
    with pytest.raises(TypeError):
        stage_portfolio(parsed, tmp_path, require_validation=False)
    with pytest.raises(TypeError):
        stage_portfolio(parsed, tmp_path, require_envelope=False)


@pytest.mark.parametrize("field,value", [
    ("current_value", None),
    ("current_value", ""),
    ("current_value", "not-a-number"),
    ("units", None),
    ("units", ""),
    ("units", "broken"),
    ("invested_value", None),
    ("invested_value", ""),
    ("invested_value", "broken"),
])
def test_holdings_digest_rejects_missing_or_malformed_financial_values(field, value):
    row = {
        "scheme": "Scheme A", "current_value": "1000.00",
        "units": "10.000", "invested_value": "900.00",
    }
    row[field] = value
    with pytest.raises(ValueError):
        compute_holdings_canonical_digest([row])


@pytest.mark.parametrize("field,value", [
    ("current_value", float("nan")),
    ("units", float("inf")),
    ("invested_value", -1),
    ("current_value", True),
])
def test_holdings_digest_rejects_nonfinite_negative_and_boolean_values(field, value):
    row = {
        "scheme": "Scheme A", "current_value": "1000.00",
        "units": "10.000", "invested_value": "900.00",
    }
    row[field] = value
    with pytest.raises(ValueError):
        compute_holdings_canonical_digest([row])


def test_holdings_digest_preserves_exact_decimal_values_without_float_roundtrip():
    base = {
        "scheme": "Scheme A", "current_value": "1000.000000000000000001",
        "units": "10.000000000000000001", "invested_value": "900.000000000000000001",
    }
    changed = {**base, "current_value": "1000.000000000000000002"}
    assert compute_holdings_canonical_digest([base]) != compute_holdings_canonical_digest([changed])
    equivalent = {**base, "current_value": "1000.0000000000000000010"}
    assert compute_holdings_canonical_digest([base]) == compute_holdings_canonical_digest([equivalent])


def test_stage_portfolio_rejects_envelope_with_tampered_stated_total(tmp_path):
    parsed = {
        "holdings": [{
            "scheme": "Scheme A", "current_value": 1000.0,
            "units": 10.0, "invested_value": 900.0,
        }],
        "as_of": "2026-10-15", "stated_total": 1000.0, "source_digest": "e" * 64,
    }
    envelope = validate_statement_reconciliation_envelope(parsed)
    envelope["stated_total"] = 9999.0
    result = stage_portfolio(parsed, tmp_path, envelope=envelope)
    assert result["staging_failed"] is True
    assert "stated_total mismatch" in result["error"]


def test_stage_portfolio_rejects_repository_storage_root(tmp_path, monkeypatch):
    from pathlib import Path

    repository_root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("MF_CLIENT_DATA_DIR", str(repository_root))
    result = stage_portfolio({"holdings": []}, repository_root, slug="Must_Not_Write")
    assert result["staging_failed"] is True
    assert result["root"] is None
    assert not (repository_root / "Must_Not_Write").exists()


def test_stage_portfolio_requires_explicit_external_root(tmp_path, monkeypatch):
    monkeypatch.delenv("MF_CLIENT_DATA_DIR", raising=False)
    result = stage_portfolio({"holdings": []}, tmp_path, slug="No_Storage_Policy")
    assert result["staging_failed"] is True
    assert result["root"] is None
    assert not (tmp_path / "No_Storage_Policy").exists()


def test_stage_portfolio_rejects_path_traversal_storage_key(tmp_path):
    result = stage_portfolio({"holdings": []}, tmp_path, slug="../outside")
    assert result["staging_failed"] is True
    assert not (tmp_path.parent / "outside").exists()
