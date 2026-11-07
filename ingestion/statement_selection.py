"""Fail-closed CAS/CGS statement discovery using embedded dates and source digests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from pathlib import Path
import re
from typing import Iterable

import openpyxl


_DATE_LABELS = {
    "as on date", "to date", "statement date", "report date",
    "period end date", "statement period end", "generated on",
}
_DATE_FORMATS = (
    "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%d/%m/%Y",
    "%Y-%m-%d", "%d.%m.%Y", "%m/%d/%Y",
)


@dataclass(frozen=True)
class StatementEvidence:
    path: Path
    document_type: str
    embedded_date: date
    sha256: str
    rationale: str


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    match = re.search(r"(?<!\\d)(\\d{1,2}[-/ ][A-Za-z]{3,9}[-/ ]\\d{4}|\\d{4}-\\d{2}-\\d{2})(?!\\d)", text)
    if match:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(match.group(1), fmt).date()
            except ValueError:
                continue
    return None


def _embedded_statement_date(workbook) -> date | None:
    found: set[date] = set()
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows(values_only=True):
            for index, value in enumerate(row):
                label = " ".join(str(value or "").casefold().replace("_", " ").split()).rstrip(":")
                if label in _DATE_LABELS and index + 1 < len(row):
                    parsed = _parse_date(row[index + 1])
                    if parsed:
                        found.add(parsed)
                if isinstance(value, str):
                    parsed_label = re.match(
                        r"\\s*(?:as on date|to date|statement date|report date|period end date|generated on)\\s*[:\\-]\\s*(.+?)\\s*$",
                        value,
                        re.IGNORECASE,
                    )
                    if parsed_label:
                        parsed = _parse_date(parsed_label.group(1))
                        if parsed:
                            found.add(parsed)
    if len(found) != 1:
        return None
    return next(iter(found))


def _validate_document(path: Path, document_type: str) -> tuple[date, str]:
    try:
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError(f"Unreadable {document_type} workbook: {path.name}") from exc
    try:
        names = set(workbook.sheetnames)
        if document_type == "CAS":
            # Flexible sheet detection: CAMS, KFinTech, MFCentral variants
            _SHEET_KEYWORDS = ("portfolio", "holdings", "scheme details", "consolidated")
            sheet_name = None
            for name in names:
                if any(kw in name.lower() for kw in _SHEET_KEYWORDS):
                    sheet_name = name
                    break
            if sheet_name is None:
                raise ValueError(f"Not a supported CAS workbook: {path.name}")
            sheet = workbook[sheet_name]
            headers = {
                str(cell.value).strip().lower()
                for row in sheet.iter_rows(values_only=False)
                for cell in row
                if cell.value is not None
            }
            # Flexible header matching with aliases
            _HEADER_ALIASES = {
                "scheme name", "scheme", "fund name",
                "current value", "current", "market value", "closing value",
                "invested value", "invested", "cost value", "invested amount",
                "units", "unit", "closing units", "balance units",
                "folio no.", "folio no", "folio", "folio number",
            }
            # Check that at least the core concepts are present
            has_scheme = any(h in ("scheme name", "scheme", "fund name") for h in headers)
            has_value = any(h in ("current value", "current", "market value", "closing value") for h in headers)
            has_invested = any(h in ("invested value", "invested", "cost value", "invested amount") for h in headers)
            has_units = any(h in ("units", "unit", "closing units", "balance units") for h in headers)
            has_folio = any(h in ("folio no.", "folio no", "folio", "folio number") for h in headers)
            if not (has_scheme and has_value and has_invested and has_units and has_folio):
                raise ValueError(f"CAS workbook lacks required identity/holding headers: {path.name}")
        elif document_type == "CGS":
            if not ({"Summary", "Scheme_Level_Summary", "TransactionDetails"} & names):
                raise ValueError(f"Not a supported CGS workbook: {path.name}")
        else:
            raise ValueError("document_type must be CAS or CGS")
        embedded = _embedded_statement_date(workbook)
    finally:
        workbook.close()
    if embedded is None:
        raise ValueError(f"{document_type} statement has missing or conflicting embedded dates: {path.name}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return embedded, digest


def select_latest_statement(
    candidates: Iterable[Path],
    *,
    document_type: str,
    as_of: date,
    max_age_days: int,
) -> StatementEvidence:
    """Select a uniquely newest, fresh statement; ambiguity is a hard error."""
    if not isinstance(as_of, date) or isinstance(as_of, datetime):
        raise ValueError("An explicit decision as_of date is required")
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days < 0:
        raise ValueError("max_age_days must be a non-negative policy integer")

    unique_paths = sorted({Path(path).resolve() for path in candidates if Path(path).is_file()})
    if not unique_paths:
        raise FileNotFoundError(f"No {document_type} statement candidates found")

    verified: list[StatementEvidence] = []
    rejected: list[str] = []
    for path in unique_paths:
        try:
            embedded, digest = _validate_document(path, document_type)
            verified.append(StatementEvidence(
                path=path,
                document_type=document_type,
                embedded_date=embedded,
                sha256=digest,
                rationale="Selected by uniquely newest validated embedded statement date.",
            ))
        except (OSError, ValueError) as exc:
            rejected.append(str(exc))

    if not verified:
        raise ValueError(
            f"No verifiable {document_type} statement candidate; HOLD. "
            + "; ".join(rejected)
        )
    latest_date = max(item.embedded_date for item in verified)
    latest = [item for item in verified if item.embedded_date == latest_date]
    distinct_digests = {item.sha256 for item in latest}
    if len(distinct_digests) > 1:
        raise ValueError(
            f"Conflicting {document_type} statements share embedded date {latest_date}; HOLD."
        )
    if latest_date > as_of:
        raise ValueError(f"{document_type} statement date is in the future; HOLD.")
    age_days = (as_of - latest_date).days
    if age_days > max_age_days:
        raise ValueError(
            f"{document_type} statement is stale ({age_days} days; policy maximum {max_age_days}); HOLD."
        )
    chosen = latest[0]
    return StatementEvidence(
        path=chosen.path,
        document_type=chosen.document_type,
        embedded_date=chosen.embedded_date,
        sha256=chosen.sha256,
        rationale=(
            f"Uniquely newest validated embedded date {chosen.embedded_date}; "
            f"SHA-256 {chosen.sha256}; age {age_days} days within {max_age_days}-day policy."
        ),
    )
