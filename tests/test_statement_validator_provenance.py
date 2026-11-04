"""
Unit tests for fail-closed statement validator registrar attribution.
Addresses Issue #52: Stop attributing CAS/CGS registrar identity without source evidence.
"""
from __future__ import annotations

import io
import openpyxl
import pytest

from ingestion.statement_validator import validate_cas_excel, validate_cgs_excel


def test_cas_excel_without_registrar_evidence_reports_unknown():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Generic Fund Direct Growth", "123456", 10000, 12000, 100])

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cas_excel(file_bytes, "generic_cas.xlsx")
    assert res.is_valid is True
    assert res.rta_source == "Unknown"
    assert res.rta_source != "CAMS / AMFI Certified"


def test_cas_excel_with_cams_evidence_reports_cams():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["CAMS Consolidated Account Statement"])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Generic Fund Direct Growth", "123456", 10000, 12000, 100])

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cas_excel(file_bytes, "cams_cas.xlsx")
    assert res.is_valid is True
    assert res.rta_source == "CAMS"


def test_cgs_excel_without_registrar_evidence_reports_unknown():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Capital Gains Statement Summary"])
    ws.append(["Short Term Capital Gain/Loss", 1000])
    ws.append(["Section 112A Long Term Capital Gain/Loss", 2000])

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cgs_excel(file_bytes, "generic_cgs.xlsx")
    assert res.is_valid is True
    assert res.rta_source == "Unknown"
    assert res.rta_source != "CAMS / KFintech Tax Statement"


def test_cgs_excel_with_kfintech_evidence_reports_kfintech():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["KFintech Capital Gains Statement"])
    ws.append(["Short Term Capital Gain/Loss", 1000])
    ws.append(["Section 112A Long Term Capital Gain/Loss", 2000])

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cgs_excel(file_bytes, "kfintech_cgs.xlsx")
    assert res.is_valid is True
    assert res.rta_source == "KFintech"
