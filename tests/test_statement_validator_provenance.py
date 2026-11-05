"""
Unit tests for fail-closed statement validator registrar attribution and provenance.
Addresses Issue #52: Stop attributing CAS/CGS registrar identity without source evidence.
"""
from __future__ import annotations

import io
import openpyxl
import pytest

from ingestion.statement_validator import (
    StatementValidationResult,
    authenticate_statement_provenance,
    require_authenticated_statement,
    validate_cas_excel,
    validate_cgs_excel,
)


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
    assert res.structural_validity is True
    assert res.rta_source == "Unknown"
    assert res.rta_source != "CAMS / AMFI Certified"
    assert res.detected_content_publisher == "Unknown"
    assert res.publisher_authenticity_status == "UNVERIFIED"
    assert res.is_publisher_authenticated is False
    assert res.authenticated_publisher is None
    assert res.provenance_digest is not None

    with pytest.raises(ValueError, match="Statement publisher is unauthenticated"):
        require_authenticated_statement(res)


def test_cas_excel_with_cams_text_marker_is_unauthenticated_content():
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
    assert res.structural_validity is True
    assert res.rta_source == "CAMS"
    assert res.detected_content_publisher == "CAMS"
    assert res.publisher_authenticity_status == "UNAUTHENTICATED_DOCUMENT_CONTENT"
    assert res.is_publisher_authenticated is False
    assert res.authenticated_publisher is None

    # Prove that is_valid=True and text marker CANNOT be promoted to authenticated provenance
    with pytest.raises(ValueError, match="cannot be promoted to authenticated provenance"):
        require_authenticated_statement(res)


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
    assert res.structural_validity is True
    assert res.rta_source == "Unknown"
    assert res.rta_source != "CAMS / KFintech Tax Statement"
    assert res.detected_content_publisher == "Unknown"
    assert res.publisher_authenticity_status == "UNVERIFIED"
    assert res.is_publisher_authenticated is False
    assert res.authenticated_publisher is None

    with pytest.raises(ValueError, match="Statement publisher is unauthenticated"):
        require_authenticated_statement(res)


def test_cgs_excel_with_kfintech_text_marker_is_unauthenticated_content():
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
    assert res.structural_validity is True
    assert res.rta_source == "KFintech"
    assert res.detected_content_publisher == "KFintech"
    assert res.publisher_authenticity_status == "UNAUTHENTICATED_DOCUMENT_CONTENT"
    assert res.is_publisher_authenticated is False
    assert res.authenticated_publisher is None

    with pytest.raises(ValueError, match="cannot be promoted to authenticated provenance"):
        require_authenticated_statement(res)


def test_adversarial_spoofed_text_and_mixed_registrar_labels():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Conflicting CAMS and KFintech and MFCentral headers"])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Spoofed Scheme", "999999", 5000, 6000, 50])

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cas_excel(file_bytes, "spoofed_cas.xlsx")
    assert res.is_valid is True
    assert res.structural_validity is True
    # Still unauthenticated despite mentions of multiple RTAs
    assert res.is_publisher_authenticated is False
    assert res.authenticated_publisher is None
    assert res.publisher_authenticity_status == "UNAUTHENTICATED_DOCUMENT_CONTENT"


def test_authentic_statement_provenance_verification():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["CAMS Consolidated Account Statement"])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Verified Scheme Direct", "111222", 10000, 15000, 100])

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cas_excel(file_bytes, "official_cams.xlsx")
    assert res.is_publisher_authenticated is False

    valid_evidence = {
        "source_digest": res.provenance_digest,
        "publisher": "CAMS",
        "reviewer_attestation": "Audited by Operations Lead OP-104",
        "source_url": "https://www.camsonline.com/InvestorServices/COL_ISAccountStatementCAS.aspx",
        "verified_at": "2026-11-05T10:00:00Z",
    }

    authenticated_res = authenticate_statement_provenance(res, valid_evidence)
    assert authenticated_res.is_publisher_authenticated is True
    assert authenticated_res.authenticated_publisher == "CAMS"
    assert authenticated_res.publisher_authenticity_status == "AUTHENTICATED_SOURCE"
    assert authenticated_res.provenance_source == valid_evidence

    # Guard passes for authenticated statement
    require_authenticated_statement(authenticated_res)


def test_tampered_or_invalid_evidence_fails_closed():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["CAMS Consolidated Account Statement"])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Verified Scheme Direct", "111222", 10000, 15000, 100])

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cas_excel(file_bytes, "official_cams.xlsx")

    # 1. Digest mismatch
    tampered_evidence = {
        "source_digest": "0" * 64,
        "publisher": "CAMS",
        "reviewer_attestation": "Audited by Ops",
    }
    with pytest.raises(ValueError, match="Provenance digest mismatch"):
        authenticate_statement_provenance(res, tampered_evidence)
    assert res.is_publisher_authenticated is False
    assert res.publisher_authenticity_status == "AUTHENTICATION_FAILED"

    # 2. Unrecognized publisher
    invalid_publisher_evidence = {
        "source_digest": res.provenance_digest,
        "publisher": "UnknownThirdPartyBroker",
        "reviewer_attestation": "Audited",
    }
    with pytest.raises(ValueError, match="Unrecognized authentic publisher"):
        authenticate_statement_provenance(res, invalid_publisher_evidence)

    # 3. Missing attestation / signature / download metadata
    no_attestation_evidence = {
        "source_digest": res.provenance_digest,
        "publisher": "CAMS",
    }
    with pytest.raises(ValueError, match="missing reviewer attestation"):
        authenticate_statement_provenance(res, no_attestation_evidence)
