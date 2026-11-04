from datetime import date

import openpyxl
import pytest

from core.math_engine import load_holdings_from_cas_excel


def _cas_workbook(path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", "31-Mar-2026"])
    sheet.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    sheet.append(["Synthetic Equity Fund - Direct Growth", "FOLIO-1", 1000, 1100, 10])
    workbook.save(path)
    return path


def test_disclosure_freshness_date_must_match_uploaded_cas_valuation_date(tmp_path):
    cas_path = _cas_workbook(tmp_path / "cas.xlsx")

    with pytest.raises(ValueError, match="does not match the uploaded CAS valuation date"):
        load_holdings_from_cas_excel(
            cas_path,
            None,
            None,
            disclosure_as_of_date=date(2026, 4, 1),
        )


def test_disclosure_freshness_uses_cas_valuation_date_when_caller_omits_date(tmp_path):
    cas_path = _cas_workbook(tmp_path / "cas.xlsx")

    # No disclosure bundle is supplied, so the loader still parses the CAS
    # successfully and anchors the freshness date to the statement itself.
    holdings = load_holdings_from_cas_excel(cas_path, None, None)
    assert len(holdings) == 1
