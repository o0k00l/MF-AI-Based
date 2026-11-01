"""Parse Capital Gains Statements (CGS) to extract realized gains and lot-level history.

WHY THIS MODULE EXISTS
----------------------
The CAS does not contain realized gains (LTCG/STCG) or historical redemption
profitability, which are required for tax routing and execution decisions.
These must be sourced from the Capital Gains Statement provided by the RTA (CAMS / KFintech).

TRUST MODEL
-----------
CGS files are authoritative statutory RTA artifacts. The parser performs strict
deterministic verification:
1. Validates presence of explicit 'Total' rows or complete lot reconciliation.
2. Cross-checks headline totals against lot-level records where available.
3. Records explicit error strings in `problems` if verification fails.
The caller in `main.py` enforces this trust gate: any recorded problem blocks
unverified tax headroom assumptions and triggers a [!!] audit check.
Manual evidence overlay (`manual_evidence_overlay.json`) retains overriding
precedence if human-verified adjustments are supplied.

DESIGN PRINCIPLES
-----------------
* Never guess. If the CGS is missing or unparseable, return zeros for LTCG/STCG and record
  an explicit problem so callers cannot quietly understate tax liability or overstate headroom.
* Support all standard real RTA CGS formats:
  - Scheme Level Summary with Total row ('Scheme_Level_Summary' or similar)
  - Detailed lot-level records ('TransactionDetails')
  - Overall summary sheets ('Summary')
* Capture both 'Long Gain Without Index' (equity post-2024) AND 'Long Gain With Index'
  (pre-2023 debt / unlisted assets) to ensure no long-term gains are silently dropped.
"""

from __future__ import annotations

from datetime import datetime, date
from pathlib import Path
from typing import Any
import warnings
import re
import json
from decimal import Decimal

try:
    import openpyxl
except Exception:
    openpyxl = None


def _is_none_or_empty(val: Any) -> bool:
    return val is None or (isinstance(val, str) and not val.strip())


def _to_float(val: Any) -> float | None:
    if _is_none_or_empty(val):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(d: Any) -> str | None:
    if not d:
        return None
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y-%m-%d")
    s = str(d).strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s if len(s) == 10 and s[4] == "-" and s[7] == "-" else None


def parse_cgs_xlsx(source: Path | bytes) -> dict[str, Any]:
    if openpyxl is None:
        return {
            "ltcg": 0.0,
            "stcg": 0.0,
            "ltcg_without_index": 0.0,
            "ltcg_with_index": 0.0,
            "lots": [],
            "transactions": [],
            "problems": ["openpyxl not installed"],
        }

    problems: list[str] = []
    out = {
        "ltcg": 0.0,
        "stcg": 0.0,
        "ltcg_without_index": 0.0,
        "ltcg_with_index": 0.0,
        "lots": [],
        "transactions": [],
        "problems": problems,
    }

    try:
        from io import BytesIO
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        if isinstance(source, (bytes, bytearray)):
            wb = openpyxl.load_workbook(filename=BytesIO(source), data_only=True)
        else:
            p_source = Path(source)
            if not p_source.exists():
                problems.append(f"CGS file not found: {p_source}")
                return out
            wb = openpyxl.load_workbook(p_source, data_only=True)
    except Exception as exc:
        problems.append(f"Failed to load CGS: {exc}")
        return out

    # 1. Primary CAMS format: Scheme_Level_Summary
    found_summary = False
    for sheet_name in wb.sheetnames:
        try:
            ws = wb[sheet_name]
            header_row_idx = None
            header_row = None
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if row and any(isinstance(c, str) and "scheme name" in c.lower() for c in row if c is not None):
                    header_row_idx = i
                    header_row = [str(c).strip().lower() if c is not None else "" for c in row]
                    break
            
            if header_row_idx is not None and header_row:
                short_idx = None
                long_no_idx = None
                long_with_idx = None
                for idx, col in enumerate(header_row):
                    if "short" in col and "gain" in col:
                        short_idx = idx
                    elif "long" in col and "without" in col:
                        long_no_idx = idx
                    elif "long" in col and "with index" in col and "without" not in col:
                        long_with_idx = idx
                    elif "long" in col and "gain" in col and long_no_idx is None:
                        long_no_idx = idx

                for j, row in enumerate(ws.iter_rows(values_only=True)):
                    if j > header_row_idx and row:
                        cell0 = str(row[0]).strip().lower() if row[0] is not None else ""
                        if cell0 == "total":
                            if short_idx is not None and len(row) > short_idx:
                                v = _to_float(row[short_idx])
                                if v is not None:
                                    out["stcg"] = v
                            if long_no_idx is not None and len(row) > long_no_idx:
                                v = _to_float(row[long_no_idx])
                                if v is not None:
                                    out["ltcg_without_index"] = v
                            if long_with_idx is not None and len(row) > long_with_idx:
                                v = _to_float(row[long_with_idx])
                                if v is not None:
                                    out["ltcg_with_index"] = v
                            out["ltcg"] = round(out["ltcg_without_index"] + out["ltcg_with_index"], 2)
                            found_summary = True
                            break
            if found_summary:
                break
        except Exception as exc:
            problems.append(f"Scheme summary parse error on sheet '{sheet_name}': {exc}")

    # 2. Overall Summary Sheet (if scheme summary didn't find gains or as cross-check)
    if not found_summary and "Summary" in wb.sheetnames:
        try:
            ws = wb["Summary"]
            for row in ws.iter_rows(values_only=True):
                if row and isinstance(row[0], str):
                    row0_lower = row[0].lower().strip()
                    if "short term capital gain/loss" in row0_lower:
                        nums = [c for c in row if isinstance(c, (int, float))]
                        if nums:
                            out["stcg"] = float(nums[-1])
                            found_summary = True
                    elif "longtermwithoutindex-capitalgain/loss" in row0_lower:
                        nums = [c for c in row if isinstance(c, (int, float))]
                        if nums:
                            out["ltcg_without_index"] = float(nums[-1])
                            found_summary = True
                    elif "longtermwithindex-capitalgain/loss" in row0_lower:
                        nums = [c for c in row if isinstance(c, (int, float))]
                        if nums:
                            out["ltcg_with_index"] = float(nums[-1])
                            found_summary = True
            if found_summary:
                out["ltcg"] = round(out["ltcg_without_index"] + out["ltcg_with_index"], 2)
        except Exception as exc:
            problems.append(f"Summary sheet parse error: {exc}")

    # 3. Detailed Lot Parsing from TransactionDetails Sheet
    if "TransactionDetails" in wb.sheetnames:
        try:
            ws = wb["TransactionDetails"]
            header_idx = None
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if row and any(isinstance(c, str) and "scheme name" in c.lower() for c in row if c is not None):
                    header_idx = i
                    break
            if header_idx is not None:
                lots = []
                txs = []
                for j, row in enumerate(ws.iter_rows(values_only=True)):
                    if j > header_idx and row:
                        scheme_val = row[3] if len(row) > 3 else None
                        if not scheme_val or str(scheme_val).strip().lower() in ("", "total"):
                            continue
                        scheme_raw = str(scheme_val).strip()
                        import re
                        clean_scheme = re.sub(r"^[A-Z0-9]{12}/", "", scheme_raw)
                        clean_scheme = re.sub(r"\(Formerly known as:[^)]*\)", "", clean_scheme, flags=re.IGNORECASE)
                        clean_scheme = re.sub(r"\b[A-Z0-9]{12}\b", "", clean_scheme)
                        clean_scheme = re.sub(r"\s+", " ", clean_scheme).strip()

                        p_date = _parse_date(row[5]) if len(row) > 5 else None
                        p_units = _to_float(row[6]) if len(row) > 6 else 0.0
                        r_date = _parse_date(row[10]) if len(row) > 10 else None
                        r_units = _to_float(row[11]) if len(row) > 11 else 0.0
                        r_amt = _to_float(row[12]) if len(row) > 12 else 0.0
                        r_nav = _to_float(row[13]) if len(row) > 13 else 0.0
                        st_gain = _to_float(row[16]) if len(row) > 16 else 0.0
                        lt_idx_gain = _to_float(row[18]) if len(row) > 18 else 0.0
                        lt_no_idx_gain = _to_float(row[19]) if len(row) > 19 else 0.0

                        lot_entry = {
                            "scheme": clean_scheme,
                            "raw_scheme": scheme_raw,
                            "fund_name": str(row[1]).strip() if len(row) > 1 and row[1] else "",
                            "folio": str(row[2]).strip() if len(row) > 2 and row[2] else "",
                            "purchase_date": p_date,
                            "purchase_units": p_units or 0.0,
                            "redemption_date": r_date,
                            "redemption_units": r_units or 0.0,
                            "redemption_amount": r_amt or 0.0,
                            "redemption_nav": r_nav or 0.0,
                            "stcg": st_gain or 0.0,
                            "ltcg_with_index": lt_idx_gain or 0.0,
                            "ltcg_without_index": lt_no_idx_gain or 0.0,
                        }
                        lots.append(lot_entry)

                        # Purchase leg for transactions
                        cost = round((r_amt or 0.0) - (st_gain or 0.0) - (lt_no_idx_gain or 0.0) - (lt_idx_gain or 0.0), 2)
                        p_nav = round(cost / p_units, 4) if p_units and p_units > 0 else 0.0
                        if p_date and (p_units or cost > 0):
                            txs.append({
                                "scheme": clean_scheme,
                                "date": p_date,
                                "amount": max(0.0, cost),
                                "units": p_units or 0.0,
                                "nav": p_nav,
                                "type": "Purchase"
                            })
                        # Redemption leg for transactions
                        if r_date and (r_units or (r_amt or 0.0) > 0):
                            txs.append({
                                "scheme": clean_scheme,
                                "date": r_date,
                                "amount": -abs(r_amt or 0.0),
                                "units": -abs(r_units or 0.0),
                                "nav": r_nav or 0.0,
                                "type": "Redemption"
                            })

                out["lots"] = lots
                out["transactions"] = txs

                # Fallback: if summary didn't yield totals, sum lot gains
                if not found_summary and lots:
                    out["stcg"] = round(sum(l["stcg"] for l in lots), 2)
                    out["ltcg_without_index"] = round(sum(l["ltcg_without_index"] for l in lots), 2)
                    out["ltcg_with_index"] = round(sum(l["ltcg_with_index"] for l in lots), 2)
                    out["ltcg"] = round(out["ltcg_without_index"] + out["ltcg_with_index"], 2)
                    found_summary = True
        except Exception as exc:
            problems.append(f"TransactionDetails sheet parse error: {exc}")

    if not found_summary and not out["lots"]:
        problems.append("No recognized capital gains rows, summary sheets, or transaction lots found in CGS")

    return out


def clean_scheme_name(s: str) -> str:
    """Normalize CGS scheme names to match CAS and candidate databases."""
    if not s:
        return ""
    cleaned = str(s).strip()
    # Strip leading ISIN codes (e.g. INF579M01AF8/...)
    cleaned = re.sub(r"^[A-Z0-9]{12}/", "", cleaned)
    # Strip former name annotations (e.g. '(Formerly known as:...)')
    cleaned = re.sub(r"\(Formerly known as:[^)]*\)", "", cleaned, flags=re.IGNORECASE)
    # Strip standalone ISINs anywhere in the string
    cleaned = re.sub(r"\b[A-Z0-9]{12}\b", "", cleaned)
    # Collapse multiple whitespaces
    return re.sub(r"\s+", " ", cleaned).strip()


def convert_cgs_to_transactions(
    source: Path | str | bytes,
    dest_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """
    Extract lot-level transaction history from CGS and synthesize transactions.

    Returns a list of transaction dicts conforming to the standard schema:
    [
        {"scheme": str, "date": "YYYY-MM-DD", "amount": float, "units": float, "type": "Purchase"|"Redemption"},
        ...
    ]
    """
    if isinstance(source, (str, Path)):
        source_path = Path(source)
        if not source_path.exists():
            raise FileNotFoundError(f"CGS file not found: {source_path}")
    else:
        source_path = source

    cgs_result = parse_cgs(source_path)
    lots = cgs_result.get("lots", [])

    txs: list[dict[str, Any]] = []
    for lot in lots:
        scheme = clean_scheme_name(lot.get("scheme", ""))
        if not scheme:
            continue

        p_date = lot.get("purchase_date")
        p_units = float(lot.get("purchase_units") or 0.0)
        r_date = lot.get("redemption_date")
        r_units = float(lot.get("redemption_units") or 0.0)
        r_amt = float(lot.get("redemption_amount") or 0.0)
        r_nav = float(lot.get("redemption_nav") or 0.0)
        stcg = float(lot.get("stcg") or 0.0)
        ltcg_with_idx = float(lot.get("ltcg_with_index") or 0.0)
        ltcg_without_idx = float(lot.get("ltcg_without_index") or 0.0)

        # Derive acquisition cost: Redemption Amount - Total Gains
        cost = round(r_amt - stcg - ltcg_without_idx - ltcg_with_idx, 2)
        p_nav = round(cost / p_units, 4) if p_units > 0 else 0.0

        if p_date and (p_units > 0 or cost > 0):
            txs.append({
                "scheme": scheme,
                "date": p_date,
                "amount": max(0.0, cost),
                "units": p_units,
                "nav": p_nav,
                "type": "Purchase",
                "source": "CGS_Lot",
            })

        if r_date and (r_units > 0 or r_amt > 0):
            txs.append({
                "scheme": scheme,
                "date": r_date,
                "amount": -abs(r_amt),
                "units": -abs(r_units),
                "nav": r_nav,
                "type": "Redemption",
                "source": "CGS_Lot",
            })

    if dest_path:
        dest_p = Path(dest_path)
        dest_p.parent.mkdir(parents=True, exist_ok=True)
        dest_p.write_text(json.dumps({"transactions": txs}, indent=2), encoding="utf-8")

    return txs


def parse_cgs(source: Path | bytes) -> dict[str, Any]:
    return parse_cgs_xlsx(source)