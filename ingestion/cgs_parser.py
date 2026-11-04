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
    """
    Parses an official Capital Gains Statement (CGS) Excel workbook.
    Returns clean dictionary of realized capital gains, available losses, and tax headroom.
    """
    path = Path(cgs_path)
    if not path.exists():
        raise FileNotFoundError(f"CGS statement not found at: {path}")

    wb = openpyxl.load_workbook(path, data_only=True)
    summary_data = {
        "stcg_inr": 0.0,
        "ltcg_inr": 0.0,
        "total_outflows": 0.0,
        "total_cost": 0.0,
        "exemption_limit": 125000.0,
        "remaining_ltcg_exemption": 125000.0,
    }
    schemes = []
    transactions = []

    # 1. Overall Summary Sheet
    if "Summary" in wb.sheetnames:
        s = wb["Summary"]
        for row in s.iter_rows(values_only=True):
            r = [c for c in row if c is not None and str(c).strip()]
            if len(r) >= 2:
                lbl = str(r[0]).strip().lower()
                val = r[-1]
                if "short term capital gain/loss" in lbl:
                    try:
                        summary_data["stcg_inr"] = float(val)
                    except (ValueError, TypeError):
                        pass
                elif "longtermwithoutindex-capitalgain/loss" in lbl:
                    try:
                        summary_data["ltcg_inr"] = float(val)
                    except (ValueError, TypeError):
                        pass
                elif "full value consideration" in lbl and summary_data["total_outflows"] == 0.0:
                    try:
                        summary_data["total_outflows"] = float(val)
                    except (ValueError, TypeError):
                        pass
                elif "cost of acquisition" in lbl and summary_data["total_cost"] == 0.0:
                    try:
                        summary_data["total_cost"] = float(val)
                    except (ValueError, TypeError):
                        pass

    # 2. Scheme Level Summary
    if "Scheme_Level_Summary" in wb.sheetnames:
        s = wb["Scheme_Level_Summary"]
        for row in s.iter_rows(min_row=5, values_only=True):
            if row[0]:
                scheme_name = str(row[0]).strip()
                if scheme_name.lower() == "total":
                    # Capture exact totals row if present
                    try:
                        if len(row) > 3 and row[2]:
                            summary_data["total_outflows"] = float(row[2])
                        if len(row) > 3 and row[3]:
                            summary_data["total_cost"] = float(row[3])
                        if len(row) > 6 and row[6] is not None:
                            summary_data["stcg_inr"] = float(row[6])
                        if len(row) > 7 and row[7] is not None:
                            summary_data["ltcg_inr"] = float(row[7])
                    except (ValueError, TypeError):
                        pass
                else:
                    try:
                        outflow = float(row[2] or 0.0)
                        cost = float(row[3] or 0.0)
                        stcg = float(row[6] or 0.0)
                        ltcg = float(row[7] or 0.0)
                        net_gain = outflow - cost
                        schemes.append({
                            "scheme": scheme_name,
                            "outflow_inr": outflow,
                            "cost_inr": cost,
                            "net_gain_inr": net_gain,
                            "stcg_inr": stcg,
                            "ltcg_inr": ltcg,
                            "is_loss": net_gain < 0
                        })
                    except (ValueError, TypeError, IndexError):
                        pass

    # 3. Lot-Level Transaction Details
    if "TransactionDetails" in wb.sheetnames:
        s = wb["TransactionDetails"]
        for r in s.iter_rows(min_row=6, values_only=True):
            if len(r) > 16 and r[2] and r[3]:
                try:
                    transactions.append({
                        "folio": str(r[2]).strip(),
                        "scheme": str(r[3]).strip(),
                        "purchase_type": str(r[4] or "").strip(),
                        "purchase_date": str(r[5] or "").strip(),
                        "purchase_units": float(r[6] or 0.0),
                        "redemption_type": str(r[9] or "").strip(),
                        "redemption_date": str(r[10] or "").strip(),
                        "redemption_amount": float(r[12] or 0.0),
                        "stcg_inr": float(r[16] or 0.0),
                        "ltcg_inr": float(r[19] or 0.0)
                    })
                except (ValueError, TypeError, IndexError):
                    pass

    # Calculate remaining LTCG tax-free exemption
    realized_ltcg = summary_data["ltcg_inr"]
    remaining = max(0.0, 125000.0 - max(0.0, realized_ltcg))
    summary_data["remaining_ltcg_exemption"] = remaining

    return {
        "statement_path": str(path),
        "filename": path.name,
        "summary": summary_data,
        "schemes": schemes,
        "transactions": transactions,
        "has_cgs": True,
        "stcg_loss_available": abs(summary_data["stcg_inr"]) if summary_data["stcg_inr"] < 0 else 0.0,
        "headroom_status": f"INR {remaining:,.0f} tax-free LTCG room remaining this FY"
    }

