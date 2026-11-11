"""End-to-end smoke test for services/cas_parser.py with a synthetic CAS file."""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openpyxl import Workbook

from services.cas_parser import parse_cas_file


def _make_cas_bytes(sheet_name: str, rows: list[list]) -> io.BytesIO:
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_parse_valid_cas():
    """Parse a synthetic CAS with a 'Portfolio Details' sheet."""
    buf = _make_cas_bytes("Portfolio Details", [
        ["Scheme Name", "Units", "NAV", "Current Value"],
        ["HDFC Flexi Cap Fund Direct Growth", 150.5, 1200.0, 180600.0],
        ["Axis Mid Cap Fund Direct Growth", 200.0, 85.0, 17000.0],
        ["SBI Small Cap Fund Direct Growth", 100.0, 120.0, 12000.0],
        ["ICICI Pru Balanced Advantage Fund Direct Growth", 500.0, 35.0, 17500.0],
        ["HDFC Liquid Fund Direct Growth", 1000.0, 4500.0, 45000.0],
    ])
    funds = parse_cas_file(buf)
    assert len(funds) == 5, f"Expected 5 funds, got {len(funds)}"

    # Verify classification
    by_scheme = {f["scheme"]: f for f in funds}

    flexi = by_scheme["HDFC Flexi Cap Fund Direct Growth"]
    assert flexi["asset_class"] == "Equity"
    assert flexi["category"] == "Flexi Cap"
    # Verified factsheet look-through exposure from scheme master
    assert flexi["eq"] == 94.89
    assert flexi["debt"] == 0.45
    assert flexi["heuristic_display_allocations"] is None
    assert flexi["current_value"] == 180600.0
    assert flexi["plan_type"] == "Direct"
    assert flexi["option_type"] == "Growth"

    ba = by_scheme["ICICI Pru Balanced Advantage Fund Direct Growth"]
    assert ba["category"] == "Hybrid"
    assert ba["heuristic_display_allocations"] is None

    liquid = by_scheme["HDFC Liquid Fund Direct Growth"]
    assert liquid["category"] == "Debt"
    assert liquid["eq"] == 0.0
    assert liquid["debt"] == 100.0
    assert liquid["heuristic_display_allocations"] is None

    print(f"PASS: Parsed {len(funds)} funds correctly.")


def test_parse_multiple_folios_aggregate():
    """Verify that multiple folios for the same scheme are properly aggregated."""
    buf = _make_cas_bytes("Portfolio Details", [
        ["Folio", "Scheme Name", "Units", "NAV", "Invested Value", "Current Value"],
        ["101/A", "HDFC Flexi Cap Fund Direct Growth", 100.0, 1000.0, 80000.0, 100000.0],
        ["101/B", "HDFC Flexi Cap Fund Direct Growth", 50.0, 1000.0, 40000.0, 50000.0],
    ])
    funds = parse_cas_file(buf)
    assert len(funds) == 1
    flexi = funds[0]
    assert flexi["current_value"] == 150000.0
    assert flexi["units"] == 150.0
    assert flexi["invested_value"] == 120000.0
    assert flexi["unrealized_gain"] == 30000.0
    assert flexi["gain_pct"] == 25.0
    assert "101/A" in flexi["folio_no"] and "101/B" in flexi["folio_no"]


def test_parse_skips_zero_balance_closed_folios():
    """Zero-balance redeemed folios are excluded from active holdings."""
    buf = _make_cas_bytes("Portfolio Details", [
        ["Scheme Name", "Units", "NAV", "Current Value"],
        ["Active Fund Direct Growth", 10.0, 100.0, 1000.0],
        ["Redeemed Fund Direct Growth", 0.0, 100.0, 0.0],
    ])
    funds = parse_cas_file(buf)
    assert len(funds) == 1
    assert funds[0]["scheme"] == "Active Fund Direct Growth"


def test_parse_holdings_sheet_kfintech_style():
    """Verify that sheets named 'Holdings' or 'Consolidated' parse properly."""
    buf = _make_cas_bytes("Holdings", [
        ["Folio No.", "Scheme Name", "Balance Units", "NAV", "Cost Value", "Market Value"],
        ["987654", "Parag Parikh Flexi Cap Fund Direct Growth", 250.0, 75.0, 15000.0, 18750.0],
        ["123456", "Mirae Asset Large Cap Fund Direct Growth", 100.0, 110.0, 10000.0, 11000.0],
    ])
    funds = parse_cas_file(buf)
    assert len(funds) == 2, f"Expected 2 funds, got {len(funds)}"
    assert funds[0]["scheme"] == "Parag Parikh Flexi Cap Fund Direct Growth"
    assert funds[0]["current_value"] == 18750.0
    assert funds[0]["invested_value"] == 15000.0


def test_parse_no_matching_sheet():
    """Sheet without 'portfolio' or 'details' in name returns empty."""
    buf = _make_cas_bytes("Summary", [
        ["Scheme", "Value"],
        ["Test Fund", 100],
    ])
    funds = parse_cas_file(buf)
    assert funds == [], f"Expected empty list, got {len(funds)} funds"
    print("PASS: No matching sheet -> 0 funds.")


def test_parse_empty_file():
    """Empty workbook returns empty list."""
    buf = _make_cas_bytes("Portfolio", [])
    funds = parse_cas_file(buf)
    assert funds == []
    print("PASS: Empty portfolio sheet -> 0 funds.")


def test_unverified_scheme_preserves_unmeasured_allocations():
    """Unverified / unindexed funds in CAS must preserve eq/debt as None, never manufactured."""
    buf = _make_cas_bytes("Portfolio Details", [
        ["Scheme Name", "Units", "NAV", "Current Value"],
        ["Completely Nonexistent Obscure Scheme Direct Growth", 100.0, 50.0, 5000.0],
    ])
    funds = parse_cas_file(buf)
    assert len(funds) == 1
    f = funds[0]
    assert f["portfolio_exposure_verified"] is False
    assert f["eq"] is None, "Unverified fund eq must remain None"
    assert f["debt"] is None, "Unverified fund debt must remain None"
    assert f["heuristic_display_allocations"] is None


if __name__ == "__main__":
    test_parse_valid_cas()
    test_parse_multiple_folios_aggregate()
    test_parse_skips_zero_balance_closed_folios()
    test_parse_no_matching_sheet()
    test_parse_empty_file()
    test_unverified_scheme_preserves_unmeasured_allocations()
    print("\n=== ALL SMOKE TESTS PASSED ===")
