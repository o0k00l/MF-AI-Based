from datetime import date
from io import BytesIO

import openpyxl
import pytest

from services.sip_recommendation import _validate_cas_decision_date


def _cas_workbook(path, include_date=True):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    if include_date:
        sheet.append(["To Date", "31-Mar-2026"])
    else:
        sheet.append(["CAS Statement"])
    sheet.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    sheet.append(["Synthetic Equity Fund - Direct Growth", "FOLIO-1", 1000, 1100, 10])
    workbook.save(path)
    return path


def test_sip_decision_date_must_match_uploaded_cas_valuation_date(tmp_path):
    cas_path = _cas_workbook(tmp_path / "cas.xlsx")

    with pytest.raises(ValueError, match="does not match the uploaded CAS valuation date"):
        _validate_cas_decision_date(cas_path, date(2026, 4, 1))


def test_sip_decision_date_is_accepted_when_bound_to_cas_valuation_date(tmp_path):
    cas_path = _cas_workbook(tmp_path / "cas.xlsx")
    assert _validate_cas_decision_date(cas_path, date(2026, 3, 31)) == date(2026, 3, 31)


def test_missing_embedded_cas_date_cannot_be_replaced_by_caller_date(tmp_path):
    cas_path = _cas_workbook(tmp_path / "cas.xlsx", include_date=False)
    with pytest.raises(ValueError, match="does not contain a valuation date"):
        _validate_cas_decision_date(cas_path, date(2026, 3, 31))
