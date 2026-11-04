"""
core/cgs_parser.py — Official Capital Gains Statement (CGS) Ingestion & Tax Auditor.

Parses CAMS, KFintech, and MFCentral CGS Excel reports ('cgs_detailed_report_*.xlsx'):
1. Summary Sheet: Realized STCG, LTCG under Section 112A, Outflow & Acquisition Cost.
2. Scheme_Level_Summary: Fund-by-fund realized gain/loss breakdown.
3. TransactionDetails: Lot-level subscription and redemption audit.
"""
from __future__ import annotations
import openpyxl
from pathlib import Path
import hashlib
from typing import Dict, List, Any, Optional
import warnings

# Suppress openpyxl styling warnings on non-standard CGS exports
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")


def discover_cgs_report_evidence(
    client_dir: Path,
    *,
    as_of=None,
    max_statement_age_days=None,
):
    """Return validated CGS selection evidence; missing policy is a hard HOLD."""
    from datetime import date
    from ingestion.statement_selection import select_latest_statement

    if not isinstance(as_of, date):
        raise ValueError("An explicit decision as_of date is required for CGS statement selection")
    if max_statement_age_days is None:
        raise ValueError("An approved maximum CGS statement age policy is required")
    candidates = list((client_dir / "statements").glob("*cgs*.xlsx"))
    candidates.extend(client_dir.glob("*cgs*.xlsx"))
    return select_latest_statement(
        candidates,
        document_type="CGS",
        as_of=as_of,
        max_age_days=max_statement_age_days,
    )


def discover_cgs_report(
    client_dir: Path,
    *,
    as_of=None,
    max_statement_age_days=None,
) -> Optional[Path]:
    """Return the uniquely newest fresh CGS statement by embedded date."""
    return discover_cgs_report_evidence(
        client_dir,
        as_of=as_of,
        max_statement_age_days=max_statement_age_days,
    )


def parse_cgs_excel(cgs_path: str | Path) -> Dict[str, Any]:
    """Extract CGS source-reported figures only; never calculate tax or headroom."""
    path = Path(cgs_path)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"CGS statement not found at: {path}")

    from ingestion.statement_selection import _validate_document
    try:
        statement_as_of_date, validated_source_sha256 = _validate_document(path, "CGS")
        if validated_source_sha256 != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError("CGS source digest changed during validation")
        statement_selection_error = None
    except (OSError, ValueError, TypeError) as exc:
        statement_as_of_date = None
        statement_selection_error = str(exc)

    wb = openpyxl.load_workbook(path, data_only=True)
    summary_data = {
        "stcg_inr": None,
        "ltcg_inr": None,
        "total_outflows": None,
        "total_cost": None,
    }
    parse_errors: list[str] = []
    if statement_selection_error:
        parse_errors.append(f"Statement identity/date validation: {statement_selection_error}")
    schemes: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []

    def number(value: Any, label: str) -> float:
        if isinstance(value, bool) or value is None:
            raise ValueError(f"{label} is missing or not numeric")
        parsed = float(value)
        import math
        if not math.isfinite(parsed):
            raise ValueError(f"{label} is non-finite")
        return parsed

    # 1. Overall summary: preserve missing fields as None, not fabricated zero.
    if "Summary" in wb.sheetnames:
        sheet = wb["Summary"]
        for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            values = [cell for cell in row if cell is not None and str(cell).strip()]
            if len(values) < 2:
                continue
            label = str(values[0]).strip().casefold()
            source_value = values[-1]
            field = None
            if "short term capital gain/loss" in label:
                field = "stcg_inr"
            elif "longtermwithoutindex-capitalgain/loss" in label:
                field = "ltcg_inr"
            elif "full value consideration" in label:
                field = "total_outflows"
            elif "cost of acquisition" in label:
                field = "total_cost"
            if field:
                try:
                    summary_data[field] = number(source_value, field)
                except (TypeError, ValueError, OverflowError) as exc:
                    parse_errors.append(f"Summary row {row_number}: {exc}")

    # 2. Scheme summary: exact totals may fill missing overall summary values.
    if "Scheme_Level_Summary" in wb.sheetnames:
        sheet = wb["Scheme_Level_Summary"]
        for row_number, row in enumerate(sheet.iter_rows(min_row=5, values_only=True), start=5):
            if not row or not row[0]:
                continue
            scheme_name = str(row[0]).strip()
            try:
                if scheme_name.casefold() == "total":
                    for index, field in ((2, "total_outflows"), (3, "total_cost"),
                                         (6, "stcg_inr"), (7, "ltcg_inr")):
                        if len(row) > index and row[index] is not None:
                            summary_data[field] = number(row[index], field)
                    continue
                if len(row) <= 7:
                    raise ValueError("scheme summary row is missing required columns")
                outflow = number(row[2], "outflow")
                cost = number(row[3], "cost")
                stcg = number(row[6], "STCG")
                ltcg = number(row[7], "LTCG")
                schemes.append({
                    "scheme": scheme_name,
                    "outflow_inr": outflow,
                    "cost_inr": cost,
                    "net_gain_inr": outflow - cost,
                    "stcg_inr": stcg,
                    "ltcg_inr": ltcg,
                    "is_loss": outflow - cost < 0,
                })
            except (TypeError, ValueError, OverflowError, IndexError) as exc:
                parse_errors.append(f"Scheme summary row {row_number}: {exc}")

    # 3. Transaction details: rows are either fully parsed or explicitly flagged.
    if "TransactionDetails" in wb.sheetnames:
        sheet = wb["TransactionDetails"]
        for row_number, row in enumerate(sheet.iter_rows(min_row=6, values_only=True), start=6):
            if not row or len(row) <= 3 or not (row[2] or row[3]):
                continue
            try:
                if len(row) <= 19:
                    raise ValueError("transaction row is missing required columns through LTCG")
                transactions.append({
                    "folio": str(row[2]).strip(),
                    "scheme": str(row[3]).strip(),
                    "purchase_type": str(row[4] or "").strip(),
                    "purchase_date": str(row[5] or "").strip(),
                    "purchase_units": number(row[6], "purchase units"),
                    "redemption_type": str(row[9] or "").strip(),
                    "redemption_date": str(row[10] or "").strip(),
                    "redemption_amount": number(row[12], "redemption amount"),
                    "stcg_inr": number(row[16], "transaction STCG"),
                    "ltcg_inr": number(row[19], "transaction LTCG"),
                })
            except (TypeError, ValueError, OverflowError, IndexError) as exc:
                parse_errors.append(f"Transaction row {row_number}: {exc}")

    wb.close()
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    required_summary = {"stcg_inr", "ltcg_inr", "total_outflows", "total_cost"}
    missing_summary = sorted(field for field in required_summary if summary_data[field] is None)
    if missing_summary:
        parse_errors.append("Missing source-reported summary fields: " + ", ".join(missing_summary))
    parse_status = "COMPLETE" if not parse_errors else "INCOMPLETE"

    return {
        "statement_path": str(path),
        "filename": path.name,
        "source_sha256": source_sha256,
        "statement_as_of_date": (
            statement_as_of_date.isoformat() if statement_as_of_date is not None else None
        ),
        "summary": summary_data,
        "schemes": schemes,
        "transactions": transactions,
        "parse_status": parse_status,
        "parse_errors": parse_errors,
        "has_cgs": True,
        "stcg_loss_available": (
            abs(summary_data["stcg_inr"])
            if summary_data["stcg_inr"] is not None and summary_data["stcg_inr"] < 0
            else (0.0 if summary_data["stcg_inr"] is not None else None)
        ),
        "tax_advice_enabled": False,
        "headroom_status": "Tax headroom and statutory exemption calculation is disabled pending independent tax review.",
    }
