"""
ingestion/statement_validator.py — Institutional Statement Pre-Flight Validation Gate.
Performs structural document checks and records untrusted publisher claims.
Structural validity does not establish publisher identity or document authenticity.
"""
from __future__ import annotations

import hashlib
import io
import re
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Callable

import openpyxl

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

# Canonical RTA & CAS signatures
_CAS_KEYWORDS = {
    "consolidated account statement", "portfolio details", "scheme name",
    "folio no", "cams", "kfintech", "karvy", "mfcentral", "current value",
    "closing unit balance", "amfi", "computer age management services"
}

_CGS_KEYWORDS = {
    "capital gain", "short term capital gain", "long term capital gain",
    "section 112a", "cost of acquisition", "scheme_level_summary",
    "fair market value", "stcg", "ltcg"
}


@dataclass
class StatementValidationResult:
    is_valid: bool
    document_type: str                  # "CAS_EXCEL" | "CAS_PDF" | "CGS_EXCEL" | "INVALID"
    rta_source: str                     # Authenticated publisher only; "Unknown" until independent verification.
    structural_validity: bool = False
    detected_content_publisher: str = "Unknown"
    publisher_authenticity_status: str = "UNVERIFIED"
    is_publisher_authenticated: bool = False
    authenticated_publisher: Optional[str] = None
    provenance_digest: Optional[str] = None
    provenance_source: Dict[str, Any] = field(default_factory=dict)
    file_name: str = ""
    file_size_bytes: int = 0
    client_name: Optional[str] = None
    masked_pan: Optional[str] = None
    statement_period: Optional[str] = None
    as_of_date: Optional[str] = None
    holdings_count: int = 0
    total_portfolio_value_inr: float = 0.0
    is_password_protected: bool = False
    password_verified: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


def mask_pan(pan: Optional[str]) -> Optional[str]:
    """Masks PAN for privacy: 'ABCDE1234F' -> 'ABCDE****F'."""
    if not pan:
        return None
    p = str(pan).strip().upper()
    if len(p) == 10 and re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", p):
        return f"{p[:5]}****{p[-1]}"
    return p[:2] + "****" + p[-2:] if len(p) >= 4 else "****"


def validate_file_header(file_bytes: bytes, file_name: str) -> Tuple[bool, str, str]:
    """Validates raw magic bytes and basic file integrity."""
    size = len(file_bytes)
    if size < 100:
        return False, "INVALID", "File is empty or too small (< 100 bytes)."
    if size > 50 * 1024 * 1024:
        return False, "INVALID", "File exceeds maximum permitted size of 50 MB."

    ext = Path(file_name).suffix.lower()

    # PDF Magic Bytes: %PDF-
    if ext == ".pdf":
        if not file_bytes.startswith(b"%PDF-"):
            return False, "INVALID", "Corrupt file: File extension is .pdf but content does not match PDF format."
        return True, "PDF", ""

    # XLSX Magic Bytes: PK\x03\x04 (ZIP container)
    if ext in (".xlsx", ".xlsm"):
        if not file_bytes.startswith(b"PK\x03\x04"):
            return False, "INVALID", "Corrupt file: File extension is .xlsx but content is not a valid Excel package."
        return True, "XLSX", ""

    return False, "INVALID", f"Unsupported file extension '{ext}'. Only official .xlsx and .pdf statements are permitted."


def validate_cas_excel(file_bytes: bytes, file_name: str) -> StatementValidationResult:
    """Deep structural validation for CAMS/KFintech/MFCentral CAS Excel workbooks."""
    digest = hashlib.sha256(file_bytes).hexdigest()
    res = StatementValidationResult(
        is_valid=False,
        document_type="CAS_EXCEL",
        rta_source="Unknown",
        file_name=file_name,
        file_size_bytes=len(file_bytes),
        provenance_digest=digest,
        structural_validity=False,
        detected_content_publisher="Unknown",
        publisher_authenticity_status="UNVERIFIED",
    )

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as exc:
        res.errors.append(f"Unable to read Excel workbook: {exc}")
        return res

    sheet_names = [s.strip() for s in wb.sheetnames]
    portfolio_sheet = None
    _SHEET_KEYWORDS = ("portfolio", "details", "holding", "holdings", "consolidated", "scheme")
    for name in sheet_names:
        if any(k in name.lower() for k in _SHEET_KEYWORDS):
            portfolio_sheet = wb[name]
            break

    if portfolio_sheet is None:
        res.errors.append(
            f"Invalid Statement: Missing required portfolio/holdings sheet. Found sheets: {', '.join(sheet_names[:5])}. "
            "Please ensure you uploaded an official Consolidated Account Statement (CAS)."
        )
        return res

    # Check for header row and column signatures
    rows = list(portfolio_sheet.iter_rows(values_only=True))
    if len(rows) < 5:
        res.errors.append("Invalid Statement: Portfolio sheet contains insufficient data rows.")
        return res

    header_idx = None
    scheme_col = None
    curr_val_col = None
    folio_col = None

    for i, r in enumerate(rows[:30]):
        row_str = [str(c).strip().lower() for c in r if c is not None]
        if any("scheme" in c for c in row_str) and any("current value" in c or "value" in c for c in row_str):
            header_idx = i
            for col_idx, cell in enumerate(r):
                if cell is None:
                    continue
                c_str = str(cell).strip().lower()
                if "scheme" in c_str and scheme_col is None:
                    scheme_col = col_idx
                if ("current value" in c_str or c_str == "value") and curr_val_col is None:
                    curr_val_col = col_idx
                if "folio" in c_str and folio_col is None:
                    folio_col = col_idx
            break

    if header_idx is None or scheme_col is None or curr_val_col is None:
        res.errors.append(
            "Invalid CAS Structure: Could not locate standard holdings table with 'Scheme Name' and 'Current Value' columns."
        )
        return res

    # Extract metadata from header block
    for r in rows[:header_idx]:
        for idx_c, cell in enumerate(r):
            if cell is None:
                continue
            c_low = str(cell).strip().lower()
            if c_low == "name" and idx_c + 1 < len(r) and r[idx_c + 1]:
                res.client_name = str(r[idx_c + 1]).strip()
            elif c_low == "pan" and idx_c + 1 < len(r) and r[idx_c + 1]:
                res.masked_pan = mask_pan(str(r[idx_c + 1]))
            elif c_low == "to date" and idx_c + 1 < len(r) and r[idx_c + 1]:
                res.as_of_date = str(r[idx_c + 1]).strip()
            elif c_low == "current portfolio value":
                # Look below for stated total
                for nxt_r in rows[rows.index(r) + 1: header_idx]:
                    if idx_c < len(nxt_r) and isinstance(nxt_r[idx_c], (int, float)):
                        res.total_portfolio_value_inr = float(nxt_r[idx_c])
                        break

    # Count valid holdings
    valid_holdings = 0
    calculated_total = 0.0
    for r in rows[header_idx + 1:]:
        if scheme_col < len(r) and r[scheme_col] and str(r[scheme_col]).strip():
            val = None
            if curr_val_col < len(r) and r[curr_val_col] is not None:
                try:
                    val = float(str(r[curr_val_col]).replace(",", "").strip())
                except (ValueError, TypeError):
                    val = None
            if val is not None and val > 0:
                valid_holdings += 1
                calculated_total += val

    if valid_holdings == 0:
        res.errors.append("Empty Portfolio: No active mutual fund holdings with positive current value were detected.")
        return res

    res.holdings_count = valid_holdings
    if res.total_portfolio_value_inr == 0.0:
        res.total_portfolio_value_inr = calculated_total

    # Embedded labels are claims only; they never populate authenticated rta_source.
    full_text = " ".join([str(c) for r in rows[:15] for c in r if c is not None]).lower()
    _set_document_claimed_publisher(res, full_text)

    res.is_valid = True
    res.structural_validity = True
    return res


def validate_cgs_excel(file_bytes: bytes, file_name: str) -> StatementValidationResult:
    """Deep structural validation for Capital Gains Statement (CGS) workbooks."""
    digest = hashlib.sha256(file_bytes).hexdigest()
    res = StatementValidationResult(
        is_valid=False,
        document_type="CGS_EXCEL",
        rta_source="Unknown",
        file_name=file_name,
        file_size_bytes=len(file_bytes),
        provenance_digest=digest,
        structural_validity=False,
        detected_content_publisher="Unknown",
        publisher_authenticity_status="UNVERIFIED",
    )

    try:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    except Exception as exc:
        res.errors.append(f"Unable to read Excel workbook: {exc}")
        return res

    sheet_names = [s.strip().lower() for s in wb.sheetnames]
    has_summary = any("summary" in s for s in sheet_names)
    has_scheme_level = any("scheme" in s for s in sheet_names)
    has_txns = any("transaction" in s for s in sheet_names)

    if not (has_summary or has_scheme_level or has_txns):
        res.errors.append(
            f"Invalid CGS Statement: Missing standard capital gains sheets. Found: {', '.join(wb.sheetnames)}. "
            "Expected 'Summary' or 'Scheme_Level_Summary'."
        )
        return res

    # Inspect Summary Sheet
    found_tax_signatures = False
    for sheet_name in wb.sheetnames:
        s = wb[sheet_name]
        for r in s.iter_rows(values_only=True, max_row=25):
            line_str = " ".join([str(c).lower() for c in r if c is not None])
            if any(k in line_str for k in ("capital gain", "short term", "long term", "section 112a", "acquisition cost")):
                found_tax_signatures = True
                break
        if found_tax_signatures:
            break

    if not found_tax_signatures:
        res.errors.append(
            "Invalid CGS Content: No Capital Gains tax sections (STCG / LTCG / Section 112A) detected in workbook."
        )
        return res

    res.is_valid = True
    res.structural_validity = True
    cgs_text = " ".join([
        " ".join([str(c).lower() for c in r if c is not None])
        for sheet_name in wb.sheetnames
        for r in wb[sheet_name].iter_rows(values_only=True, max_row=15)
    ])
    _set_document_claimed_publisher(res, cgs_text)
    return res


def validate_cas_pdf(file_bytes: bytes, file_name: str, password: Optional[str] = None) -> StatementValidationResult:
    """Validates mutual fund CAS PDF files, testing decryption and RTA keyword presence."""
    import pypdf

    digest = hashlib.sha256(file_bytes).hexdigest()
    res = StatementValidationResult(
        is_valid=False,
        document_type="CAS_PDF",
        rta_source="Unknown",
        file_name=file_name,
        file_size_bytes=len(file_bytes),
        provenance_digest=digest,
        structural_validity=False,
        detected_content_publisher="Unknown",
        publisher_authenticity_status="UNVERIFIED",
    )

    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
    except Exception as exc:
        res.errors.append(f"Corrupt or malformed PDF file: {exc}")
        return res

    # 1. Encryption check
    if reader.is_encrypted:
        res.is_password_protected = True
        if not password:
            res.errors.append("🔒 Password Required: This CAS PDF is encrypted. Please enter your PAN in UPPERCASE or password.")
            return res
        try:
            status = reader.decrypt(password)
            if status == 0:
                res.errors.append("❌ Incorrect Password: Decryption failed. CAS PDFs are typically protected with your PAN in UPPERCASE.")
                return res
            res.password_verified = True
        except Exception as exc:
            res.errors.append(f"Decryption error: {exc}")
            return res

    # 2. Extract text and verify mutual fund RTA signatures
    num_pages = len(reader.pages)
    if num_pages == 0:
        res.errors.append("Empty PDF: The uploaded document has 0 pages.")
        return res

    extracted_text = ""
    for p_idx in range(min(5, num_pages)):
        try:
            page_text = reader.pages[p_idx].extract_text() or ""
            extracted_text += " " + page_text.lower()
        except Exception:
            continue

    if not extracted_text.strip():
        res.errors.append("Unreadable PDF: Could not extract text. The document may be a scanned image rather than a digital CAS.")
        return res

    # Check for mutual fund keywords
    matched_keywords = [kw for kw in _CAS_KEYWORDS if kw in extracted_text]
    if len(matched_keywords) < 2:
        res.errors.append(
            "❌ Unrecognized PDF Document: The uploaded file does not contain recognized CAMS, KFintech, or MFCentral Consolidated Account Statement (CAS) records. "
            "Please ensure you did not upload an unrelated document (e.g. utility bill, invoice, or bank statement)."
        )
        return res

    # PDF text is equally untrusted as workbook text.
    _set_document_claimed_publisher(res, extracted_text)

    # Search for PAN pattern
    pan_match = re.search(r"\b([A-Z]{5}[0-9]{4}[A-Z])\b", extracted_text.upper())
    if pan_match:
        res.masked_pan = mask_pan(pan_match.group(1))

    res.is_valid = True
    res.structural_validity = True
    return res


def inspect_and_validate_statement(
    file_bytes: bytes,
    file_name: str,
    password: Optional[str] = None,
    expected_type: Optional[str] = None
) -> StatementValidationResult:
    """
    Unified entry point for validating any uploaded mutual fund statement.
    Rejects random files, non-statements, and corrupt uploads before ingestion.
    """
    digest = hashlib.sha256(file_bytes).hexdigest()
    ok, basic_type, err = validate_file_header(file_bytes, file_name)
    if not ok:
        res = StatementValidationResult(
            is_valid=False,
            document_type="INVALID",
            rta_source="Unknown",
            file_name=file_name,
            file_size_bytes=len(file_bytes),
            provenance_digest=digest,
            structural_validity=False,
            detected_content_publisher="Unknown",
            publisher_authenticity_status="UNVERIFIED",
        )
        res.errors.append(err)
        return res

    if basic_type == "PDF":
        return validate_cas_pdf(file_bytes, file_name, password=password)

    # For Excel, test both CAS and CGS signatures
    cgs_check = validate_cgs_excel(file_bytes, file_name)
    if cgs_check.is_valid:
        return cgs_check

    cas_check = validate_cas_excel(file_bytes, file_name)
    if cas_check.is_valid:
        return cas_check

    # If neither passed, combine relevant error feedback
    combined_res = StatementValidationResult(
        is_valid=False,
        document_type="INVALID",
        rta_source="Unknown",
        file_name=file_name,
        file_size_bytes=len(file_bytes),
        provenance_digest=digest,
        structural_validity=False,
        detected_content_publisher="Unknown",
        publisher_authenticity_status="UNVERIFIED",
    )
    combined_res.errors.append(
        "❌ Unrecognized Spreadsheet: The uploaded file is not an official CAMS / KFintech / MFCentral CAS or CGS statement. "
        "It lacks the required mutual fund portfolio tables and capital gains tax structures."
    )
    return combined_res


def _set_document_claimed_publisher(result: StatementValidationResult, text: str) -> None:
    """Record a publisher claim from document text without authenticating it."""
    normalized = text.lower()
    claims = set()
    if "cams" in normalized or "computer age management services" in normalized:
        claims.add("CAMS")
    if "kfintech" in normalized or "karvy" in normalized:
        claims.add("KFintech")
    if "mfcentral" in normalized:
        claims.add("MFCentral")
    result.rta_source = "Unknown"
    result.is_publisher_authenticated = False
    result.authenticated_publisher = None
    if len(claims) == 1:
        result.detected_content_publisher = next(iter(claims))
        result.publisher_authenticity_status = "UNAUTHENTICATED_DOCUMENT_CONTENT"
    elif len(claims) > 1:
        result.detected_content_publisher = "Ambiguous"
        result.publisher_authenticity_status = "AMBIGUOUS_DOCUMENT_CONTENT"
    else:
        result.detected_content_publisher = "Unknown"
        result.publisher_authenticity_status = "UNVERIFIED"


def authenticate_statement_provenance(
    result: StatementValidationResult,
    evidence: Dict[str, Any],
    *,
    trusted_verifier: Optional[Callable[[str, str, Dict[str, Any]], bool]] = None,
) -> StatementValidationResult:
    """Authenticate only when a configured trusted integration verifies independent evidence.

    A digest, URL, timestamp or free-text reviewer assertion alone is not authentication.
    """
    if not result.is_valid or not result.structural_validity:
        raise ValueError("Cannot authenticate publisher on a structurally invalid statement.")
    if not isinstance(evidence, dict):
        raise TypeError("Provenance evidence must be a dictionary.")
    if trusted_verifier is None or not callable(trusted_verifier):
        raise ValueError("No trusted publisher provenance verifier is configured.")

    expected_digest = evidence.get("source_digest")
    if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest) or expected_digest != result.provenance_digest:
        result.publisher_authenticity_status = "AUTHENTICATION_FAILED"
        result.is_publisher_authenticated = False
        result.authenticated_publisher = None
        result.rta_source = "Unknown"
        raise ValueError("Provenance digest mismatch or malformed source_digest.")

    publisher = evidence.get("publisher")
    if publisher not in ("CAMS", "KFintech", "MFCentral"):
        result.publisher_authenticity_status = "AUTHENTICATION_FAILED"
        result.is_publisher_authenticated = False
        result.authenticated_publisher = None
        result.rta_source = "Unknown"
        raise ValueError("Unrecognized authentic publisher; expected CAMS, KFintech, or MFCentral.")

    method = evidence.get("verification_method")
    if method not in ("TRUSTED_SIGNATURE", "AUTHENTICATED_DOWNLOAD", "INDEPENDENT_REVIEW"):
        raise ValueError("Unsupported or missing independent verification_method.")
    if not isinstance(evidence.get("verified_at"), str) or not evidence["verified_at"].strip():
        raise ValueError("Independent provenance evidence requires verified_at.")
    if not isinstance(evidence.get("evidence_reference"), str) or not evidence["evidence_reference"].strip():
        raise ValueError("Independent provenance evidence requires evidence_reference.")

    try:
        verified = trusted_verifier(result.provenance_digest, publisher, evidence) is True
    except Exception as exc:
        result.publisher_authenticity_status = "AUTHENTICATION_FAILED"
        result.is_publisher_authenticated = False
        result.authenticated_publisher = None
        result.rta_source = "Unknown"
        raise ValueError(f"Trusted publisher provenance verification failed: {exc}") from exc
    if not verified:
        result.publisher_authenticity_status = "AUTHENTICATION_FAILED"
        result.is_publisher_authenticated = False
        result.authenticated_publisher = None
        result.rta_source = "Unknown"
        raise ValueError("Trusted publisher provenance verifier rejected the evidence.")

    result.is_publisher_authenticated = True
    result.publisher_authenticity_status = "AUTHENTICATED_SOURCE"
    result.authenticated_publisher = publisher
    result.rta_source = publisher
    result.provenance_source = dict(evidence)
    return result


def require_authenticated_statement(result: StatementValidationResult) -> None:
    """
    Enforces that downstream workflows requiring authenticated source evidence
    cannot proceed on structural validity or embedded document text markers alone.
    """
    if not result.is_valid or not result.structural_validity:
        raise ValueError("Statement is structurally invalid.")
    if not result.is_publisher_authenticated or result.authenticated_publisher is None:
        raise ValueError(
            f"Statement publisher is unauthenticated (status: {result.publisher_authenticity_status}, "
            f"detected content: {result.detected_content_publisher}). "
            "Structural validity or embedded text markers cannot be promoted to authenticated provenance."
        )
