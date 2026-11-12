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


def _make_valid_cas_fund_rows(ws, base_scheme="Generic Fund"):
    """Add 3 fund rows to make a valid CAS Excel with 5+ total rows."""
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append([f"{base_scheme} Direct Growth", "123456", 10000, 12000, 100])
    ws.append([f"{base_scheme} Hybrid Equity", "234567", 15000, 16000, 150])
    ws.append([f"{base_scheme} Debt Fund", "345678", 8000, 8500, 80])
    ws.append([f"{base_scheme} Liquid Fund", "456789", 5000, 5100, 50])


def test_cas_excel_without_registrar_evidence_reports_unknown():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    _make_valid_cas_fund_rows(ws)

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
    _make_valid_cas_fund_rows(ws)

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cas_excel(file_bytes, "cams_cas.xlsx")
    assert res.is_valid is True
    assert res.structural_validity is True
    assert res.rta_source == "Unknown"
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
    assert res.rta_source == "Unknown"
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
    _make_valid_cas_fund_rows(ws, base_scheme="Spoofed Scheme")

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cas_excel(file_bytes, "spoofed_cas.xlsx")
    assert res.is_valid is True
    assert res.structural_validity is True
    # Still unauthenticated despite mentions of multiple RTAs
    assert res.is_publisher_authenticated is False
    assert res.authenticated_publisher is None
    assert res.publisher_authenticity_status == "AMBIGUOUS_DOCUMENT_CONTENT"
    assert res.detected_content_publisher == "Ambiguous"


def test_authentic_statement_provenance_verification():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["CAMS Consolidated Account Statement"])
    _make_valid_cas_fund_rows(ws, base_scheme="Verified Scheme")

    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()

    res = validate_cas_excel(file_bytes, "official_cams.xlsx")
    assert res.is_publisher_authenticated is False

    valid_evidence = {
        "source_digest": res.provenance_digest,
        "publisher": "CAMS",
        "verification_method": "INDEPENDENT_REVIEW",
        "verified_at": "2026-11-05T10:00:00Z",
        "evidence_reference": "review-record:OP-104:2026-11-05",
    }

    authenticated_res = authenticate_statement_provenance(
        res,
        valid_evidence,
        trusted_verifier=lambda digest, publisher, evidence: digest == res.provenance_digest and publisher == "CAMS",
    )
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
    _make_valid_cas_fund_rows(ws, base_scheme="Verified Scheme")

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
        authenticate_statement_provenance(res, tampered_evidence, trusted_verifier=lambda *_: True)
    assert res.is_publisher_authenticated is False
    assert res.publisher_authenticity_status == "AUTHENTICATION_FAILED"

    # 2. Unrecognized publisher
    invalid_publisher_evidence = {
        "source_digest": res.provenance_digest,
        "publisher": "UnknownThirdPartyBroker",
        "reviewer_attestation": "Audited",
    }
    with pytest.raises(ValueError, match="Unrecognized authentic publisher"):
        authenticate_statement_provenance(res, invalid_publisher_evidence, trusted_verifier=lambda *_: True)

    # 3. Missing attestation / signature / download metadata
    no_attestation_evidence = {
        "source_digest": res.provenance_digest,
        "publisher": "CAMS",
        "verification_method": "INDEPENDENT_REVIEW",
        "verified_at": "2026-11-05T10:00:00Z",
    }
    with pytest.raises(ValueError, match="evidence_reference"):
        authenticate_statement_provenance(res, no_attestation_evidence, trusted_verifier=lambda *_: True)


def _make_valid_cgs_with_claims(*claims):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Capital Gains Statement Summary", " ".join(claims)])
    ws.append(["Short Term Capital Gain/Loss", 1000])
    ws.append(["Section 112A Long Term Capital Gain/Loss", 2000])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.parametrize("claims", [
    ("CAMS", "KFintech"),
    ("CAMS", "MFCentral"),
    ("KFintech", "MFCentral"),
    ("CAMS", "KFintech", "MFCentral"),
])
def test_cgs_mixed_or_spoofed_publisher_claims_remain_unknown_and_ambiguous(claims):
    result = validate_cgs_excel(_make_valid_cgs_with_claims(*claims), "spoofed_cgs.xlsx")
    assert result.is_valid is True
    assert result.structural_validity is True
    assert result.rta_source == "Unknown"
    assert result.detected_content_publisher == "Ambiguous"
    assert result.publisher_authenticity_status == "AMBIGUOUS_DOCUMENT_CONTENT"
    assert result.is_publisher_authenticated is False
    with pytest.raises(ValueError, match="unauthenticated"):
        require_authenticated_statement(result)


def test_document_content_claim_never_changes_authenticated_publisher_field():
    result = validate_cgs_excel(
        _make_valid_cgs_with_claims("CAMS Capital Gains Statement"),
        "claimed_cams_cgs.xlsx",
    )
    assert result.is_valid is True  # Structural validity only.
    assert result.rta_source == "Unknown"
    assert result.detected_content_publisher == "CAMS"
    assert result.authenticated_publisher is None
    assert result.is_publisher_authenticated is False


def test_reviewer_string_url_and_timestamp_without_trusted_verifier_cannot_authenticate():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    _make_valid_cas_fund_rows(ws)
    buf = io.BytesIO()
    wb.save(buf)
    result = validate_cas_excel(buf.getvalue(), "generic.xlsx")
    weak_evidence = {
        "source_digest": result.provenance_digest,
        "publisher": "CAMS",
        "reviewer_attestation": "I reviewed this; trust me",
        "source_url": "https://www.camsonline.com/",
        "verified_at": "2026-11-12T10:00:00Z",
        "verification_method": "INDEPENDENT_REVIEW",
        "evidence_reference": "free-text-reference",
    }
    with pytest.raises(ValueError, match="No trusted publisher provenance verifier"):
        authenticate_statement_provenance(result, weak_evidence)
    assert result.rta_source == "Unknown"
    assert result.is_publisher_authenticated is False


def test_trusted_verifier_rejection_does_not_promote_source():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    _make_valid_cas_fund_rows(ws)
    buf = io.BytesIO()
    wb.save(buf)
    result = validate_cas_excel(buf.getvalue(), "generic.xlsx")
    evidence = {
        "source_digest": result.provenance_digest,
        "publisher": "CAMS",
        "verification_method": "TRUSTED_SIGNATURE",
        "verified_at": "2026-11-12T10:00:00Z",
        "evidence_reference": "signature:receipt-123",
    }
    with pytest.raises(ValueError, match="rejected the evidence"):
        authenticate_statement_provenance(result, evidence, trusted_verifier=lambda *_: False)
    assert result.rta_source == "Unknown"
    assert result.authenticated_publisher is None
    assert result.is_publisher_authenticated is False


def test_structural_validity_false_cannot_be_overridden_by_is_valid_flag():
    result = StatementValidationResult(
        is_valid=True,
        document_type="CAS_EXCEL",
        rta_source="Unknown",
        structural_validity=False,
    )
    with pytest.raises(ValueError, match="structurally invalid"):
        require_authenticated_statement(result)
    with pytest.raises(ValueError, match="structurally invalid"):
        authenticate_statement_provenance(result, {}, trusted_verifier=lambda *_: True)
