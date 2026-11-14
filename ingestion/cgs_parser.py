"""
core/cgs_parser.py -- Official Capital Gains Statement (CGS) Ingestion and Tax Auditor.

Parses CAMS, KFintech, and MFCentral CGS Excel reports ('cgs_detailed_report_*.xlsx'):
1. Summary Sheet: Realized STCG, LTCG under Section 112A, Outflow and Acquisition Cost.
2. Scheme_Level_Summary: Fund-by-fund realized gain/loss breakdown.
3. TransactionDetails: Lot-level subscription and redemption audit.
"""
from __future__ import annotations
import io
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


def parse_cgs_excel(
    cgs_path: str | Path | bytes | bytearray | memoryview,
    *,
    publisher_approval: dict[str, Any] | str | None = None,
    publisher_trust_registry: dict[str, Any] | None = None,
    require_authenticated_publisher: bool = False,
) -> Dict[str, Any]:
    """Extract CGS figures while preserving structural and publisher-authenticity states."""
    if isinstance(cgs_path, (bytes, bytearray, memoryview)):
        # Uploaded statements stay in memory; never stage investor data on disk.
        path = None
        source_bytes = bytes(cgs_path)
        source_name = "uploaded-cgs.xlsx"
    else:
        path = Path(cgs_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"CGS statement not found at: {path}")
        source_bytes = path.read_bytes()
        source_name = path.name
    if not isinstance(require_authenticated_publisher, bool):
        raise TypeError("require_authenticated_publisher must be boolean")
    from ingestion.statement_validator import validate_cgs_excel, require_authenticated_statement
    from ingestion.statement_publisher_review import (
        authenticate_statement_with_reviewer_approval, public_statement_provenance,
    )
    statement_validation = validate_cgs_excel(source_bytes, source_name)
    if not statement_validation.is_valid or not statement_validation.structural_validity:
        raise ValueError("CGS structural validation failed: " + "; ".join(statement_validation.errors))
    if publisher_approval is not None:
        if publisher_trust_registry is None:
            raise ValueError("A separately configured statement publisher trust registry is required")
        authenticate_statement_with_reviewer_approval(
            statement_validation, publisher_approval, publisher_trust_registry
        )
    if require_authenticated_publisher:
        require_authenticated_statement(statement_validation)
    statement_provenance = public_statement_provenance(statement_validation)

    from ingestion.statement_selection import _embedded_statement_date
    try:
        date_workbook = openpyxl.load_workbook(
            io.BytesIO(source_bytes), read_only=True, data_only=True
        )
        try:
            supported_sheets = {"Summary", "Scheme_Level_Summary", "TransactionDetails"}
            if not (supported_sheets & set(date_workbook.sheetnames)):
                raise ValueError("Not a supported CGS workbook")
            statement_as_of_date = _embedded_statement_date(date_workbook)
        finally:
            date_workbook.close()
        if statement_as_of_date is None:
            raise ValueError("CGS statement has missing or conflicting embedded dates")
        validated_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        statement_selection_error = None
    except (OSError, ValueError, TypeError) as exc:
        statement_as_of_date = None
        statement_selection_error = str(exc)

    wb = openpyxl.load_workbook(io.BytesIO(source_bytes), data_only=True)
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

    # 1. Overall summary: locate any sheet matching 'summary' (and not scheme/transaction)
    summary_sheet_name = None
    for s_name in wb.sheetnames:
        s_low = s_name.strip().casefold()
        if "summary" in s_low and not any(k in s_low for k in ("scheme", "transaction", "trxn", "detail")):
            summary_sheet_name = s_name
            break
    if not summary_sheet_name and "Summary" in wb.sheetnames:
        summary_sheet_name = "Summary"

    if summary_sheet_name:
        sheet = wb[summary_sheet_name]
        stcg_val = None
        ltcg_without_idx_val = None
        ltcg_with_idx_val = None
        ltcg_gen_val = None
        outflow_sum = 0.0
        cost_sum = 0.0
        has_outflow = False
        has_cost = False

        for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            values = [cell for cell in row if cell is not None and str(cell).strip()]
            if len(values) < 2:
                continue
            label = str(values[0]).strip().casefold()
            clean_label = label.replace(" ", "").replace("-", "").replace("_", "")
            source_value = values[-1]

            try:
                if "shorttermcapitalgain" in clean_label or "shortterm" in clean_label:
                    stcg_val = number(source_value, "stcg_inr")
                elif "longtermwithoutindex" in clean_label or "withoutindex" in clean_label:
                    ltcg_without_idx_val = number(source_value, "ltcg_without_index_inr")
                elif "longtermwithindex" in clean_label or "withindex" in clean_label:
                    ltcg_with_idx_val = number(source_value, "ltcg_with_index_inr")
                elif "longtermcapitalgain" in clean_label or "longterm" in clean_label:
                    ltcg_gen_val = number(source_value, "ltcg_inr")
                elif "fullvalueconsideration" in clean_label or "outflow" in clean_label:
                    outflow_sum += number(source_value, "total_outflows")
                    has_outflow = True
                elif "costofacquisition" in clean_label:
                    cost_sum += number(source_value, "total_cost")
                    has_cost = True
            except (TypeError, ValueError, OverflowError) as exc:
                parse_errors.append(f"Summary row {row_number}: {exc}")

        if stcg_val is not None:
            summary_data["stcg_inr"] = stcg_val
        if ltcg_without_idx_val is not None or ltcg_with_idx_val is not None:
            summary_data["ltcg_inr"] = (ltcg_without_idx_val or 0.0) + (ltcg_with_idx_val or 0.0)
        elif ltcg_gen_val is not None:
            summary_data["ltcg_inr"] = ltcg_gen_val
        if has_outflow:
            summary_data["total_outflows"] = outflow_sum
        if has_cost:
            summary_data["total_cost"] = cost_sum

    # 2. Scheme summary sheets: find all sheets matching scheme, equity, debt, tradable, etc.
    scheme_sheet_names = []
    for s_name in wb.sheetnames:
        s_low = s_name.strip().casefold()
        if any(k in s_low for k in ("scheme", "equity", "debt", "tradable", "category", "schemewise")) and not any(k in s_low for k in ("transaction", "trxn", "txndetail")):
            scheme_sheet_names.append(s_name)
    if not scheme_sheet_names and "Scheme_Level_Summary" in wb.sheetnames:
        scheme_sheet_names.append("Scheme_Level_Summary")

    total_scheme_outflows = 0.0
    total_scheme_cost = 0.0
    total_scheme_stcg = 0.0
    total_scheme_ltcg = 0.0
    has_scheme_totals = False

    for s_name in scheme_sheet_names:
        sheet = wb[s_name]
        # Detect header row: must have at least 3 non-empty cells
        header_row_idx = None
        cols: dict[str, int] = {}
        for r_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            if not row:
                continue
            r_non_empty = [str(c or "").strip().lower() for c in row if c is not None and str(c).strip()]
            if len(r_non_empty) >= 3 and any("scheme" in c for c in r_non_empty) and any(
                k in c for c in r_non_empty for k in ("outflow", "cost", "gain", "short", "long", "stcg", "ltcg", "net value")
            ):
                header_row_idx = r_idx
                for col_idx, cell in enumerate(row):
                    if cell is None:
                        continue
                    c_str = str(cell).strip().lower()
                    if "scheme" in c_str or "fund name" in c_str or c_str == "fund":
                        cols.setdefault("scheme", col_idx)
                    elif any(k in c_str for k in ("outflow", "redemption amount", "full value")):
                        cols.setdefault("outflow", col_idx)
                    elif any(k in c_str for k in ("net value", "cost", "acquisition")):
                        cols.setdefault("cost", col_idx)
                    elif any(k in c_str for k in ("short", "stcg")):
                        cols.setdefault("stcg", col_idx)
                    elif ("long" in c_str or "ltcg" in c_str) and ("without index" in c_str or "withoutindex" in c_str):
                        cols.setdefault("ltcg_no_idx", col_idx)
                    elif ("long" in c_str or "ltcg" in c_str) and ("with index" in c_str or "withindex" in c_str):
                        cols.setdefault("ltcg_idx", col_idx)
                    elif any(k in c_str for k in ("long", "ltcg")):
                        cols.setdefault("ltcg_gen", col_idx)
                break

        # Fallback column positions if header not detected
        if header_row_idx is None:
            header_row_idx = 4
            cols = {"scheme": 0, "outflow": 2, "cost": 3, "stcg": 6, "ltcg_idx": 7, "ltcg_no_idx": 8, "ltcg_gen": 7}

        for row_number, row in enumerate(sheet.iter_rows(min_row=header_row_idx + 1, values_only=True), start=header_row_idx + 1):
            if not row or len(row) <= cols.get("scheme", 0) or not row[cols.get("scheme", 0)]:
                continue
            scheme_name = str(row[cols.get("scheme", 0)]).strip()
            if not scheme_name:
                continue
            try:
                # Calculate LTCG for this row
                ltcg_val = None
                if "ltcg_no_idx" in cols or "ltcg_idx" in cols:
                    no_idx = number(row[cols["ltcg_no_idx"]], "ltcg_without_index") if "ltcg_no_idx" in cols and len(row) > cols["ltcg_no_idx"] and row[cols["ltcg_no_idx"]] is not None else 0.0
                    with_idx = number(row[cols["ltcg_idx"]], "ltcg_with_index") if "ltcg_idx" in cols and len(row) > cols["ltcg_idx"] and row[cols["ltcg_idx"]] is not None else 0.0
                    ltcg_val = no_idx + with_idx
                elif "ltcg_gen" in cols and len(row) > cols["ltcg_gen"] and row[cols["ltcg_gen"]] is not None:
                    ltcg_val = number(row[cols["ltcg_gen"]], "LTCG")
                elif len(row) > 7 and row[7] is not None:
                    ltcg_val = number(row[7], "LTCG")

                if scheme_name.casefold() in ("total", "subtotal", "grand total"):
                    if "outflow" in cols and len(row) > cols["outflow"] and row[cols["outflow"]] is not None:
                        total_scheme_outflows += number(row[cols["outflow"]], "total_outflows")
                    if "cost" in cols and len(row) > cols["cost"] and row[cols["cost"]] is not None:
                        total_scheme_cost += number(row[cols["cost"]], "total_cost")
                    if "stcg" in cols and len(row) > cols["stcg"] and row[cols["stcg"]] is not None:
                        total_scheme_stcg += number(row[cols["stcg"]], "stcg_inr")
                    if ltcg_val is not None:
                        total_scheme_ltcg += ltcg_val
                    has_scheme_totals = True
                    continue

                outflow_idx = cols.get("outflow", 2)
                cost_idx = cols.get("cost", 3)
                stcg_idx = cols.get("stcg", 6)

                if len(row) <= max(outflow_idx, cost_idx):
                    raise ValueError("scheme summary row is missing required columns")

                outflow = number(row[outflow_idx], "outflow")
                cost = number(row[cost_idx], "cost")
                stcg = number(row[stcg_idx], "STCG") if len(row) > stcg_idx and row[stcg_idx] is not None else 0.0
                ltcg = ltcg_val if ltcg_val is not None else 0.0

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
                parse_errors.append(f"Scheme summary ({s_name}) row {row_number}: {exc}")

    if has_scheme_totals:
        summary_data["total_outflows"] = total_scheme_outflows
        summary_data["total_cost"] = total_scheme_cost
        summary_data["stcg_inr"] = total_scheme_stcg
        summary_data["ltcg_inr"] = total_scheme_ltcg
    elif schemes:
        if summary_data["total_outflows"] is None:
            summary_data["total_outflows"] = sum(s["outflow_inr"] for s in schemes)
        if summary_data["total_cost"] is None:
            summary_data["total_cost"] = sum(s["cost_inr"] for s in schemes)
        if summary_data["stcg_inr"] is None:
            summary_data["stcg_inr"] = sum(s["stcg_inr"] for s in schemes)
        if summary_data["ltcg_inr"] is None:
            summary_data["ltcg_inr"] = sum(s["ltcg_inr"] for s in schemes)

    # 3. Transaction details: find any sheet matching transaction, trxn, details
    tx_sheet_name = None
    for s_name in wb.sheetnames:
        s_low = s_name.strip().casefold()
        if any(k in s_low for k in ("transactiondetails", "transaction_details", "transaction details", "transactions", "txndetails")):
            tx_sheet_name = s_name
            break
    if not tx_sheet_name and "TransactionDetails" in wb.sheetnames:
        tx_sheet_name = "TransactionDetails"

    if tx_sheet_name:
        sheet = wb[tx_sheet_name]
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
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    required_summary = {"stcg_inr", "ltcg_inr", "total_outflows", "total_cost"}
    missing_summary = sorted(field for field in required_summary if summary_data[field] is None)
    if missing_summary:
        parse_errors.append("Missing source-reported summary fields: " + ", ".join(missing_summary))
    parse_status = "COMPLETE" if not parse_errors else "INCOMPLETE"

    return {
        "statement_path": str(path) if path is not None else None,
        "filename": path.name if path is not None else source_name,
        "source_sha256": source_sha256,
        "statement_provenance": statement_provenance,
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
