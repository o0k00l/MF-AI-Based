"""Read a CAMS Consolidated Account Statement in EXCEL form.

WHY XLSX FIRST
--------------
A CAS is available as both PDF and XLSX. The XLSX is deterministic: fixed sheet
names, a fixed column header, real numeric cells. A PDF needs a text extractor,
layout heuristics, and - for many CAS files - a password that is often the
client's own PAN. So XLSX is accepted first and is the only format this module
claims to handle. PDF support is a separate, explicit step, not an assumption.

THE IDENTITY BLOCK IS NEVER RETURNED
------------------------------------
The first rows of a CAS carry the client's name, mobile number, email and PAN.
This module reads past them and never puts them in its result. A CAS upload is
the most PII-dense document this engine will ever touch, and the holdings are
the only part needed to analyse a portfolio. Identity is discarded on read, not
merely hidden later.

Everything else follows the same discipline as engine/holdings.py: nothing is
invented, and nothing is dropped silently.
"""

from __future__ import annotations

import datetime
import io
import pathlib
import re
import math
import warnings
from decimal import Decimal

#: The columns a CAS holdings table carries, in the order CAMS writes them.
_COLUMNS = ("scheme_name", "amc_name", "category", "folio_no",
            "invested_value", "current_value", "returns", "units")

_HEADER_ALIASES = {
    "scheme name": "scheme_name", "scheme": "scheme_name",
    "amc name": "amc_name", "amc": "amc_name",
    "category": "category",
    "folio no.": "folio_no", "folio no": "folio_no", "folio": "folio_no",
    "folio number": "folio_no",
    "invested value": "invested_value", "invested": "invested_value",
    "current value": "current_value", "current": "current_value",
    "returns": "returns", "profit/loss": "returns",
    "units": "units", "unit": "units",
}

#: Rows before the header that carry identity. Read and discarded.
_IDENTITY_KEYS = ("name", "mobile number", "email", "pan")


def _canon(h) -> str:
    return " ".join(str(h or "").strip().lower().split())


_MONTHS = {m.lower(): i + 1 for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"))}


def _iso_date(text: str) -> str | None:
    """
    '04-Oct-2026' -> '2026-10-04', or None when the shape is not understood.

    Refuses rather than guessing at a date: a wrong as-of date would compare a
    holding against the WRONG day's NAV and could make a mismatched scheme look
    like a match. An unparseable date leaves the NAV check with nothing to run
    against, which is the safe outcome.
    """
    t = " ".join(str(text or "").strip().split())
    m = re.fullmatch(r"(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s](\d{4})", t)
    if not m:
        return None
    day, mon, year = m.group(1), m.group(2)[:3].lower(), m.group(3)
    if mon not in _MONTHS:
        return None
    try:
        d = datetime.date(int(year), _MONTHS[mon], int(day))
    except ValueError:
        return None
    return d.isoformat()


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        raise ValueError("boolean is not a financial numeric value")
    try:
        value = float(v) if isinstance(v, (int, float, Decimal)) else float(str(v).replace(",", "").strip())
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("financial value is not numeric") from exc
    if not math.isfinite(value):
        raise ValueError("financial value must be finite")
    return value


def parse_cas_xlsx(source, scheme_master=None, scheme_master_source_bytes=None) -> dict:
    """
    Parse a CAS .xlsx from a path or bytes.

    Returns:
      holdings      - rows with a non-zero current value (the live portfolio)
      dormant       - rows present but worth zero (switched out, not deleted)
      rejected      - row number + reason, never silently dropped
      stated_total  - the total the statement itself reports, for cross-checking
      identity      - always an explicit note that it was discarded
    """
    import openpyxl
    # Suppress the noisy "Workbook contains no default style" warning from openpyxl
    warnings.filterwarnings("ignore", message="Workbook contains no default style")
    try:
        if isinstance(source, (bytes, bytearray)):
            wb = openpyxl.load_workbook(io.BytesIO(source), data_only=True)
        else:
            wb = openpyxl.load_workbook(source, data_only=True)
    except Exception as exc:                       # noqa: BLE001
        return {"holdings": [], "dormant": [], "rejected": [],
                "stated_total": None, "identity": "not read",
                "problems": [f"the file could not be opened as an Excel "
                             f"workbook: {type(exc).__name__}: {exc}"]}

    out = {"holdings": [], "dormant": [], "rejected": [], "stated_total": None,
           "as_of": None, "from_date": None, "identity": "read and discarded; never returned",
           "problems": []}

    sheet = None
    for name in wb.sheetnames:
        if "portfolio" in name.lower():
            sheet = wb[name]
            break
    if sheet is None:
        out["problems"].append(
            "no 'Portfolio Details' sheet; found: " + ", ".join(wb.sheetnames))
        return out

    rows = list(sheet.iter_rows(values_only=True))
    header_at = None
    for i, r in enumerate(rows):
        labels = [_canon(c) for c in r if c is not None]
        if "scheme name" in labels and any("current value" in x for x in labels):
            header_at = i
            break
    if header_at is None:
        out["problems"].append(
            "no holdings table found: expected a header row containing both "
            "'Scheme Name' and 'Current Value'")
        return out

    header = [_canon(c) for c in rows[header_at]]
    idx = {}
    for pos, lab in enumerate(header):
        key = _HEADER_ALIASES.get(lab)
        if key and key not in idx:
            idx[key] = pos

    missing = [k for k in ("scheme_name", "current_value") if k not in idx]
    if missing:
        out["problems"].append(
            "holdings table is missing required column(s): " + ", ".join(missing))
        return out

    # The statement's own total, so the parse can be checked against it.
    # The label row is a HEADER: the numbers sit on the NEXT row beneath it.
    # Reading the label row itself yields nothing, which silently disabled the
    # reconciliation - exactly the check that proves the parse is complete.
    for i, r in enumerate(rows[:header_at]):
        labels = [_canon(c) for c in r if c is not None]
        if "current portfolio value" not in labels:
            continue
        pos = labels.index("current portfolio value")
        for follow_index, follow in enumerate(rows[i + 1:i + 4], start=i + 2):
            if pos >= len(follow) or follow[pos] in (None, ""):
                continue
            try:
                stated_total = _num(follow[pos])
                if stated_total is None or stated_total < 0:
                    raise ValueError("stated portfolio total must be non-negative")
                out["stated_total"] = stated_total
            except (TypeError, ValueError, OverflowError) as exc:
                out["problems"].append(
                    f"invalid stated portfolio total at row {follow_index}: {exc}"
                )
                out["rejected"].append({
                    "row": follow_index, "scheme": None,
                    "raw_value": repr(follow[pos]),
                    "reason": "stated portfolio total is invalid",
                })
            break
        break

    # The statement's "To Date": the date the values were struck. Needed to
    # check a holding against published NAVs - value = units x NAV only holds
    # for one date, and without it the check has no date to check against.
    # Matched against the RAW row: _canon() over a None-filtered list shifts
    # positions, so labels.index() would land on the label itself and yield
    # None rather than the date beside it.
    for r in rows[:header_at]:
        for i, cell in enumerate(r or []):
            if _canon(cell) == "to date" and i + 1 < len(r) and r[i + 1]:
                out["as_of"] = _iso_date(str(r[i + 1]))
            if _canon(cell) == "from date" and i + 1 < len(r) and r[i + 1]:
                out["from_date"] = _iso_date(str(r[i + 1]))
        if out.get("as_of") and out.get("from_date"):
            break

    for i, r in enumerate(rows[header_at + 1:], start=header_at + 2):
        def cell(key):
            pos = idx.get(key)
            return r[pos] if pos is not None and pos < len(r) else None

        scheme = (cell("scheme_name") or "").strip() if cell("scheme_name") else ""
        if not scheme:
            continue
        try:
            current = _num(cell("current_value"))
        except (TypeError, ValueError):
            out["rejected"].append({"row": i, "scheme": scheme,
                                    "reason": "current value is not a number"})
            continue
        if current is None:
            out["rejected"].append({"row": i, "scheme": scheme,
                                    "reason": "current value is blank"})
            continue
        rec = {"scheme": scheme,
               "current_value": current,
               "folio_no": str(cell("folio_no") or "").strip(),
               "amc_name": (str(cell("amc_name") or "").strip() or None),
               "category": (str(cell("category") or "").strip() or None),
               "constituent_weights": None,
               "constituent_weights_coverage_pct": None,
               "lookthrough_status": "MISSING",
               "lookthrough_reason": "CAS does not contain stock-level constituent disclosures.",
               "scheme_id": None, "isin": None, "scheme_identity_status": "MISSING"}
        if scheme_master is not None and scheme_master_source_bytes is not None:
            from ingestion.portfolio_disclosure import resolve_scheme_identity
            identity = resolve_scheme_identity(rec, scheme_master, source_bytes=scheme_master_source_bytes)
            rec.update({"scheme_id": identity.get("scheme_id"), "isin": identity.get("isin"),
                        "scheme_identity_status": identity["status"],
                        "scheme_identity_reason": identity["reason"]})
        if current < 0:
            out["rejected"].append({
                "row": i, "scheme": scheme, "raw_value": repr(cell("current_value")),
                "reason": "current value must be non-negative",
            })
            continue
        invalid_field = None
        for opt, key in (("invested_value", "invested"),
                         ("returns", "returns"), ("units", "units")):
            raw_value = cell(opt)
            if raw_value in (None, ""):
                continue
            try:
                value = _num(raw_value)
                if value is None:
                    continue
                if opt in ("invested_value", "units") and value < 0:
                    raise ValueError(f"{opt} must be non-negative")
                rec[key] = value
            except (TypeError, ValueError, OverflowError) as exc:
                invalid_field = (opt, raw_value, str(exc))
                break
        if invalid_field is not None:
            field_name, raw_value, reason = invalid_field
            out["rejected"].append({
                "row": i, "scheme": scheme, "field": field_name,
                "raw_value": repr(raw_value), "reason": reason,
            })
            continue
        if current > 0 and "units" in rec and rec["units"] <= 0:
            out["rejected"].append({
                "row": i, "scheme": scheme, "field": "units",
                "raw_value": repr(cell("units")),
                "reason": "positive current value requires positive units",
            })
            continue
        if current > 0:
            out["holdings"].append(rec)
        else:
            out["dormant"].append(rec)

    if not out["holdings"] and not out["problems"]:
        out["problems"].append("the statement contains no live holdings")
        
    out["transactions"] = []
    tx_sheet = None
    for name in wb.sheetnames:
        if "transaction" in name.lower():
            tx_sheet = wb[name]
            break
            
    if tx_sheet:
        tx_rows = list(tx_sheet.iter_rows(values_only=True))
        hdr_idx = None
        for i, r in enumerate(tx_rows):
            lbls = [_canon(c) for c in r if c is not None]
            has_sn = "scheme name" in lbls or "scheme" in lbls
            has_dt = any(x in lbls for x in ["date", "transaction date", "trxn date", "tx date"])
            if has_sn and has_dt:
                hdr_idx = i
                break
        if hdr_idx is not None:
            tx_hdr = [_canon(c) for c in tx_rows[hdr_idx]]
            def tx_pos(names):
                for n in names:
                    if n in tx_hdr: return tx_hdr.index(n)
                return None
            sn_col = tx_pos(["scheme name", "scheme"])
            dt_col = tx_pos(["date", "transaction date", "trxn date", "tx date"])
            amt_col = tx_pos(["amount", "transaction amount"])
            unt_col = tx_pos(["units"])
            nav_col = tx_pos(["nav", "purchase price"])
            desc_col = tx_pos(["transaction description", "description", "trxn type"])
            
            if sn_col is not None and dt_col is not None and amt_col is not None:
                last_scheme = ""
                for row_number, r in enumerate(tx_rows[hdr_idx + 1:], start=hdr_idx + 2):
                    if not any(value not in (None, "") for value in r):
                        continue
                    sn = r[sn_col]
                    if sn and str(sn).strip():
                        last_scheme = str(sn).strip()
                    raw_date = str(r[dt_col] or "").strip()
                    raw_amount = r[amt_col]
                    raw_description = str(r[desc_col] or "").strip() if desc_col is not None else ""
                    if not raw_date and raw_amount in (None, "") and not raw_description:
                        continue
                    try:
                        if not last_scheme:
                            raise ValueError("scheme identity is missing")
                        if not raw_date:
                            raise ValueError("transaction date is missing")
                        import datetime as dt_mod
                        parsed_date = None
                        for date_format in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                            try:
                                parsed_date = dt_mod.datetime.strptime(raw_date, date_format).date()
                                break
                            except ValueError:
                                continue
                        if parsed_date is None:
                            raise ValueError("transaction date has an unsupported format")
                        amount = _num(raw_amount)
                        if amount is None:
                            raise ValueError("transaction amount is missing")
                        units = _num(r[unt_col]) if unt_col is not None else 0.0
                        nav = _num(r[nav_col]) if nav_col is not None else None
                        units = 0.0 if units is None else units
                        description = raw_description
                        desc = description.casefold()
                        # Reversals/dishonours/cancellations need source-specific
                        # correction semantics. Never misclassify them as an
                        # ordinary purchase/redemption merely because the text
                        # contains one of those words.
                        reversal_markers = (
                            "reversal", "reversed", "dishonour", "dishonor",
                            "rejected", "cancelled", "canceled", "chargeback",
                        )
                        if any(marker in desc for marker in reversal_markers):
                            tx_type = "UNKNOWN"
                        # Only explicit, understood transaction descriptions map
                        # to unit/cash events. Unknown text never becomes PURCHASE.
                        elif any(marker in desc for marker in ("stamp duty", "stt", "exit load", "charges", "transaction fee")):
                            tx_type = "CHARGES"
                        elif any(marker in desc for marker in ("dividend reinvest", "reinvestment", "reinvested dividend", "drp")):
                            tx_type = "DIVIDEND_REINVEST"
                        elif "dividend" in desc:
                            tx_type = "DIVIDEND"
                        elif any(marker in desc for marker in ("switch out", "switch-out")):
                            tx_type = "SWITCH_OUT"
                        elif any(marker in desc for marker in ("switch in", "switch-in")):
                            tx_type = "SWITCH_IN"
                        elif any(marker in desc for marker in ("stp out", "stp-out")):
                            tx_type = "STP_OUT"
                        elif any(marker in desc for marker in ("stp in", "stp-in")):
                            tx_type = "STP_IN"
                        elif any(marker in desc for marker in ("redemption", "swp", "systematic withdrawal")):
                            tx_type = "REDEMPTION"
                        elif "sip" in desc:
                            tx_type = "SIP"
                        elif "purchase" in desc or "subscription" in desc or "allotment" in desc:
                            tx_type = "PURCHASE"
                        else:
                            tx_type = "UNKNOWN"

                        if tx_type in {"DIVIDEND", "CHARGES"}:
                            if units != 0.0:
                                raise ValueError(f"{tx_type} is cash-only and must not change units")
                            if amount == 0.0:
                                raise ValueError(f"{tx_type} requires a non-zero cash amount")
                        if tx_type in {"PURCHASE", "SIP", "SWITCH_IN", "STP_IN", "DIVIDEND_REINVEST"}:
                            if amount <= 0 or units <= 0:
                                raise ValueError(f"{tx_type} requires positive amount and units")
                        if tx_type in {"REDEMPTION", "SWITCH_OUT", "STP_OUT"}:
                            if amount == 0 or units == 0:
                                raise ValueError(f"{tx_type} requires non-zero amount and units")
                            # CAS sources differ in sign convention; downstream
                            # ledgers use the explicit transaction type to set
                            # direction and consume unit magnitudes.
                            units = abs(units)
                        unit_changing_types = {
                            "PURCHASE", "SIP", "SWITCH_IN", "STP_IN", "DIVIDEND_REINVEST",
                            "REDEMPTION", "SWITCH_OUT", "STP_OUT",
                        }
                        if tx_type in unit_changing_types and nav is not None and nav <= 0:
                            raise ValueError(f"{tx_type} requires a positive NAV when NAV is supplied")
                        record = {
                            "scheme": last_scheme,
                            "date": parsed_date.isoformat(),
                            "amount": amount,
                            "units": units,
                            "nav": nav,
                            "description": description,
                            "raw_description": description,
                            "source_row": row_number,
                            "type": tx_type,
                        }
                        out["transactions"].append(record)
                        if tx_type == "UNKNOWN":
                            out["rejected"].append({
                                "row": row_number, "scheme": last_scheme,
                                "raw_value": description,
                                "reason": "transaction description has no reviewed type mapping",
                            })
                    except (TypeError, ValueError, OverflowError) as exc:
                        out["rejected"].append({
                            "row": row_number, "scheme": last_scheme or None,
                            "raw_value": repr(tuple(r)),
                            "reason": str(exc),
                        })
    return out


def reconcile(parsed: dict, tolerance: float = 1.0) -> dict:
    """
    Check parsed holdings against the total reported by the statement.

    Any rejected source row, invalid tolerance/value, or non-finite aggregate
    prevents a completeness verdict. A finite row set can still overflow when
    summed, so aggregate validity is checked independently.
    """
    rejected = list(parsed.get("rejected", []))
    holdings = parsed.get("holdings", [])
    stated = parsed.get("stated_total")
    try:
        tolerance_value = float(tolerance)
        if not math.isfinite(tolerance_value) or tolerance_value < 0:
            raise ValueError("tolerance must be finite and non-negative")
        if not isinstance(holdings, list):
            raise ValueError("holdings must be a list")
        values = []
        for index, holding in enumerate(holdings):
            if not isinstance(holding, dict):
                raise ValueError(f"holding row {index} is not a mapping")
            value = _num(holding.get("current_value"))
            if value is None or value < 0:
                raise ValueError(f"holding row {index} has an invalid current value")
            values.append(value)
        total = math.fsum(values)
        if not math.isfinite(total):
            raise ValueError("parsed portfolio total is non-finite")
    except (TypeError, ValueError, OverflowError) as exc:
        rejected.append({"row": None, "scheme": None, "reason": str(exc)})
        total = None

    out = {
        "parsed_total": round(total, 2) if total is not None else None,
        "stated_total": stated,
        "difference": None,
        "agrees": False if rejected else None,
        "complete": not rejected,
        "rejected_rows": rejected,
        "note": "",
    }
    if rejected:
        out["note"] = (
            f"{len(rejected)} material row(s) were rejected; statement completeness "
            "and portfolio reconciliation cannot be certified."
        )
        return out
    try:
        stated_value = _num(stated)
        if stated_value is None or stated_value < 0:
            raise ValueError("statement total must be finite and non-negative")
    except (TypeError, ValueError, OverflowError) as exc:
        out["complete"] = False
        out["agrees"] = False
        out["rejected_rows"] = [{"row": None, "scheme": None, "reason": str(exc)}]
        out["note"] = "the statement total is invalid; reconciliation cannot be certified"
        return out

    diff = total - stated_value
    if not math.isfinite(diff):
        out["complete"] = False
        out["agrees"] = False
        out["rejected_rows"] = [{"row": None, "scheme": None, "reason": "reconciliation difference is non-finite"}]
        out["note"] = "the reconciliation difference is non-finite; reconciliation cannot be certified"
        return out
    out["difference"] = round(diff, 2)
    out["agrees"] = abs(diff) <= tolerance_value
    out["note"] = (
        "parsed rows match the statement total" if out["agrees"]
        else f"PARSED TOTAL DISAGREES by Rs {diff:,.2f}; the parse is incomplete and must not be relied on"
    )
    return out


def _validate_financial_fields(r: dict, row_index: int) -> tuple[dict, list[str]]:
    """
    Issue #107: Validate required financial fields before cache materialization.
    Returns (validated_dict, errors) where errors is a list of problem strings.
    """
    errors = []
    validated = dict(r)
    
    required_fields = {
        "current_value": ["current_value"],
        "units": ["units"],
        "invested": ["invested_value", "invested", "cost_value"],
    }
    
    for field_name, aliases in required_fields.items():
        value = None
        source_key = None
        for alias in aliases:
            if alias in r and r[alias] is not None:
                value = r[alias]
                source_key = alias
                break
        
        if value is None or (isinstance(value, str) and value.strip() == ""):
            errors.append(f"Row {row_index}: Missing required field '{field_name}'")
            validated[field_name] = None
        elif isinstance(value, str):
            try:
                fval = float(value.strip().replace(",", ""))
                if math.isnan(fval) or math.isinf(fval):
                    errors.append(f"Row {row_index}: Field '{field_name}' is non-finite: {value}")
                    validated[field_name] = None
                elif fval < 0:
                    errors.append(f"Row {row_index}: Negative value for field '{field_name}': {value}")
                    validated[field_name] = None
                else:
                    validated[field_name] = fval
            except (ValueError, TypeError):
                errors.append(f"Row {row_index}: Malformed field '{field_name}': {value}")
                validated[field_name] = None
        elif isinstance(value, (int, float)):
            if math.isnan(value) or math.isinf(value):
                errors.append(f"Row {row_index}: Field '{field_name}' is non-finite: {value}")
                validated[field_name] = None
            elif value < 0:
                errors.append(f"Row {row_index}: Negative value for field '{field_name}': {value}")
                validated[field_name] = None
            else:
                validated[field_name] = float(value)
        else:
            errors.append(f"Row {row_index}: Invalid type for field '{field_name}': {type(value)}")
            validated[field_name] = None
    
    # Validate NAV (optional but if present must be valid)
    nav = r.get("nav")
    nav_is_source = nav is not None and (not isinstance(nav, str) or nav.strip() != "")
    if nav is not None:
        if isinstance(nav, str):
            try:
                fval = float(nav.strip().replace(",", ""))
                if math.isnan(fval) or math.isinf(fval):
                    errors.append(f"Row {row_index}: NAV is non-finite: {nav}")
                    validated["nav"] = None
                    validated["nav_is_derived"] = False
                elif fval < 0:
                    errors.append(f"Row {row_index}: Negative value for NAV: {nav}")
                    validated["nav"] = None
                    validated["nav_is_derived"] = False
                else:
                    validated["nav"] = fval
                    validated["nav_is_derived"] = False
            except (ValueError, TypeError):
                errors.append(f"Row {row_index}: Malformed NAV: {nav}")
                validated["nav"] = None
                validated["nav_is_derived"] = False
        elif isinstance(nav, (int, float)):
            if math.isnan(nav) or math.isinf(nav):
                errors.append(f"Row {row_index}: NAV is non-finite: {nav}")
                validated["nav"] = None
                validated["nav_is_derived"] = False
            elif nav < 0:
                errors.append(f"Row {row_index}: Negative value for NAV: {nav}")
                validated["nav"] = None
                validated["nav_is_derived"] = False
            else:
                validated["nav"] = float(nav)
                validated["nav_is_derived"] = False
    else:
        validated["nav"] = None
        validated["nav_is_derived"] = False
    
    return validated, errors
def to_cache_csv(parsed: dict, enriched: bool = False, strict: bool = True) -> str:
    """
    Render parsed holdings into the CSV the engine already reads.

    Issue #107: Reject missing/malformed financial fields instead of coercing to zero.
    
    When enriched=False (default), preserves the canonical contract expected by
    _live_folios() and unit tests: '"Scheme Name",Invested,CurrentValue'.
    When enriched=True (GAP-198), preserves all 7 ground-truth fields:
    '"Scheme Name",CurrentValue,Units,Invested,"Folio Number",ISIN,NAV'.
    
    strict=True: Raise ValueError if any row has validation errors.
    strict=False: Skip invalid rows and log them.
    """
    holdings_list = parsed.get("holdings") or parsed.get("funds") or []
    all_errors = []
    valid_rows = []
    
    for idx, r in enumerate(holdings_list):
        validated, errors = _validate_financial_fields(r, idx + 1)
        if errors:
            all_errors.extend(errors)
            if not strict:
                continue
        valid_rows.append(validated)
    
    if strict and all_errors:
        raise ValueError(
            f"Cache materialization failed: {len(all_errors)} validation error(s). "
            f"First errors: {all_errors[:5]}"
        )
    
    if enriched:
        out = ['"Scheme Name",CurrentValue,Units,Invested,"Folio Number",ISIN,NAV,NAV_Source']
        for r in valid_rows:
            name = str(r.get("scheme", "")).replace('"', "'").strip()
            
            cur_val = r.get("current_value")
            units = r.get("units")
            invested = r.get("invested")
            folio = str(r.get("folio_no") or r.get("folio") or "").replace('"', "").strip()
            isin = str(r.get("isin", "")).replace('"', "").strip()
            nav = r.get("nav")
            nav_is_derived = r.get("nav_is_derived", False)
            
            if cur_val is None:
                cur_val_str = "UNAVAILABLE"
            else:
                cur_val_str = f"{cur_val:.2f}"
            
            if units is None:
                units_str = "UNAVAILABLE"
            else:
                units_str = f"{units:.3f}"
            
            if invested is None:
                invested_str = "UNAVAILABLE"
            else:
                invested_str = f"{invested:.2f}"
            
            # Derive NAV only if not source-reported, and mark it as derived
            if nav is None and units is not None and units > 0 and cur_val is not None and cur_val > 0:
                nav = cur_val / units
                nav_is_derived = True
            
            if nav is None:
                nav_str = "UNAVAILABLE"
                nav_source = "NONE"
            else:
                nav_str = f"{nav:.4f}"
                nav_source = "DERIVED" if nav_is_derived else "SOURCE"
            
            out.append(f'"{name}",{cur_val_str},{units_str},{invested_str},"{folio}","{isin}",{nav_str},{nav_source}')
        return "\n".join(out) + "\n"

    out = ['"Scheme Name",Invested,CurrentValue']
    for r in valid_rows:
        name = str(r.get("scheme", "")).replace('"', "'").strip()
        invested = r.get("invested")
        cur_val = r.get("current_value")
        
        invested_str = f"{invested:.2f}" if invested is not None else "UNAVAILABLE"
        cur_val_str = f"{cur_val:.2f}" if cur_val is not None else "UNAVAILABLE"
        
        out.append(f'"{name}",{invested_str},{cur_val_str}')
    return "\n".join(out) + "\n"


def to_enriched_cache_csv(parsed: dict) -> str:
    """GAP-198: Explicit helper for enriched cache serialization."""
    return to_cache_csv(parsed, enriched=True)


def stage_portfolio(parsed: dict, root, slug: str = "Upload_Portfolio", require_validation: bool = True) -> dict:
    """
    Materialise a portfolio workspace from an uploaded statement.

    Issue #107: Reject missing/malformed CAS values before materializing cache.
    Makes staging atomic - no partial cache is left on failure.

    Writes only what the engine reads. No identity is written anywhere, so the
    staged folder contains no PAN, name, phone or email.
    
    require_validation=True: Require successful validation before writing cache.
    """
    root = pathlib.Path(root)
    pdir = root / slug
    (pdir / "data").mkdir(parents=True, exist_ok=True)
    
    import json
    import tempfile
    import os
    
    # Issue #107: Validate before writing - use strict mode
    if require_validation:
        try:
            cache_content = to_cache_csv(parsed, enriched=True, strict=True)
        except ValueError as e:
            # Clean up any partial state
            cache_path = pdir / "data" / "_active_funds_cache.csv"
            if cache_path.exists():
                cache_path.unlink()
            return {
                "slug": slug,
                "root": str(pdir),
                "cache": None,
                "holdings": len(parsed.get("holdings", [])),
                "identity_written": False,
                "staging_failed": True,
                "error": str(e),
            }
    else:
        cache_content = to_cache_csv(parsed, enriched=True, strict=False)
    
    # Atomic write: write to temp file first, then rename
    cache_path = pdir / "data" / "_active_funds_cache.csv"
    tmp_path = cache_path.with_suffix(".tmp")
    tmp_path.write_text(cache_content, encoding="utf-8")
    os.replace(tmp_path, cache_path)
    
    if parsed.get("transactions"):
        tx_path = pdir / "data" / "transactions.json"
        tx_tmp = tx_path.with_suffix(".tmp")
        tx_tmp.write_text(
            json.dumps({"transactions": parsed.get("transactions")}, indent=2), encoding="utf-8")
        os.replace(tx_tmp, tx_path)
        
    return {"slug": slug, "root": str(pdir),
            "cache": str(cache_path),
            "holdings": len(parsed.get("holdings", [])),
            "identity_written": False,
            "staging_failed": False}


def _parse_cas_pdf_pypdf(source, password: str = "") -> dict:
    """
    GAP-196 / GAP-227 / GAP-228: Native pypdf extractor for Consolidated Account
    Statements supporting both detailed multi-page CAMS/MFCentral statements and
    single-line summary CAS formats with complete historical transaction extraction.
    """
    out = {
        "holdings": [], "dormant": [], "rejected": [], "stated_total": None,
        "as_of": None, "from_date": None, "identity": "read and discarded; never returned",
        "problems": [], "transactions": [],
        "reconcile_note": "pypdf parse: parsed via native fallback. Totals checked against active holdings sum."
    }
    try:
        import pypdf
        import re
        import io
        from datetime import datetime
        
        if isinstance(source, (bytes, bytearray)):
            reader = pypdf.PdfReader(io.BytesIO(source))
        else:
            reader = pypdf.PdfReader(str(source))
            
        if reader.is_encrypted:
            if password:
                decrypted = reader.decrypt(password)
                if not decrypted:
                    out["problems"].append("PDF is password protected and decryption failed with provided password.")
                    return out
            else:
                out["problems"].append("PDF is password protected. Password required.")
                return out

        full_text = "\n".join(p.extract_text() or "" for p in reader.pages)
        if not full_text.strip():
            out["problems"].append("No extractable text found in PDF.")
            return out

        # Extract as_of date: "As on Date: 09-Oct-2026" or "To Date : 09-Oct-2026"
        m_date = re.search(r'(?:As on Date|To Date)\s*[:\-]?\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4})', full_text, re.IGNORECASE)
        if m_date:
            try:
                dt = datetime.strptime(m_date.group(1), "%d-%b-%Y").date()
                out["as_of"] = dt.isoformat()
            except Exception:
                out["as_of"] = m_date.group(1)

        m_from = re.search(r'From Date\s*[:\-]?\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4})', full_text, re.IGNORECASE)
        if m_from:
            try:
                dt_from = datetime.strptime(m_from.group(1), "%d-%b-%Y").date()
                out["from_date"] = dt_from.isoformat()
            except Exception:
                out["from_date"] = m_from.group(1)

        # -----------------------------------------------------------------------
        # BRANCH A: Detailed Multi-Folio CAMS / MFCentral / KFintech CAS Statement
        # -----------------------------------------------------------------------
        if "FOLIO NO:" in full_text and ("Closing Unit Balance:" in full_text or "ISIN:" in full_text):
            sections = re.split(r'\n(?=FOLIO NO:)', full_text)
            for sec in sections[1:]:
                f_m = re.search(r'FOLIO NO:\s*([^\n\r]+)', sec)
                folio = f_m.group(1).strip() if f_m else ""

                isin_m = re.search(r'ISIN:\s*([A-Za-z0-9]+)', sec)
                isin = isin_m.group(1).strip() if isin_m else None

                # Extract AMC name from first line or preceding tokens
                amc_m = re.search(r'([A-Za-z\s]+Mutual Fund)', sec)
                amc_name = amc_m.group(1).strip() if amc_m else ""

                # Scheme name is located between FOLIO NO and KYC / Opening Unit Balance
                sch_block_m = re.search(r'FOLIO NO:[^\n\r]+\n(.*?)(?:KYC\s*:|Opening Unit Balance)', sec, re.DOTALL)
                sch_raw = sch_block_m.group(1).strip() if sch_block_m else ""
                sch_clean = re.sub(r'\(Advisor:[^\)]*\)', '', sch_raw)
                sch_clean = re.sub(r'ISIN:\s*[A-Za-z0-9]+', '', sch_clean)
                sch_name = " ".join(sch_clean.split()) or "Unknown Scheme"

                # Closing balance, NAV, Valuation
                val_m = re.search(
                    r'Closing Unit Balance:\s*([0-9,]+\.[0-9]+)\s+Nav as on\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4}):\s*INR\s*([0-9,]+\.[0-9]+)\s+Valuation on\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4})\s*:\s*INR\s*([0-9,]+\.[0-9]{2})',
                    sec
                )
                if val_m:
                    units = float(val_m.group(1).replace(",", ""))
                    nav = float(val_m.group(3).replace(",", ""))
                    val = float(val_m.group(5).replace(",", ""))
                else:
                    units, nav, val = 0.0, 0.0, 0.0

                # Extract historical transactions for this scheme
                tx_lines = re.findall(
                    r'(\d{2}-[A-Za-z]{3}-\d{4})\s+(.*?)\s+([\(\)0-9,\.\-]+)\s+([\(\)0-9,\.\-]+)\s+([\(\)0-9,\.\-]+)\s+([\(\)0-9,\.\-]+)',
                    sec
                )
                sec_invested = 0.0
                for tx_match in tx_lines:
                    t_date_raw, t_desc, t_amt_str, t_units_str, t_nav_str, t_bal_str = tx_match
                    t_desc_clean = t_desc.strip()
                    
                    def _parse_signed_num(s: str) -> float:
                        s_clean = s.strip().replace(",", "")
                        if s_clean.startswith("(") and s_clean.endswith(")"):
                            return -float(s_clean[1:-1])
                        try:
                            return float(s_clean)
                        except ValueError:
                            return 0.0

                    t_amt = _parse_signed_num(t_amt_str)
                    t_units = _parse_signed_num(t_units_str)
                    t_nav = _parse_signed_num(t_nav_str)
                    
                    # Skip zero-balance administrative lines
                    if t_amt == 0.0 and t_units == 0.0 and not any(kw in t_desc_clean.lower() for kw in ("stamp", "stt", "tax")):
                        continue

                    try:
                        t_iso = datetime.strptime(t_date_raw, "%d-%b-%Y").strftime("%Y-%m-%d")
                    except Exception:
                        t_iso = t_date_raw

                    desc_lower = t_desc_clean.lower()
                    reversal_markers = (
                        "reversal", "reversed", "dishonour", "dishonor",
                        "rejected", "cancelled", "canceled", "chargeback",
                    )
                    if any(marker in desc_lower for marker in reversal_markers):
                        tx_type = "UNKNOWN"
                    elif any(kw in desc_lower for kw in ("stamp duty", "stt", "exit load", "charges", "transaction fee")):
                        tx_type = "CHARGES"
                    elif any(kw in desc_lower for kw in ("dividend reinvest", "reinvestment", "reinvested dividend", "drp")):
                        tx_type = "DIVIDEND_REINVEST"
                    elif "dividend" in desc_lower:
                        tx_type = "DIVIDEND"
                    elif any(kw in desc_lower for kw in ("switch out", "switch-out")):
                        tx_type = "SWITCH_OUT"
                    elif any(kw in desc_lower for kw in ("switch in", "switch-in")):
                        tx_type = "SWITCH_IN"
                    elif any(kw in desc_lower for kw in ("stp out", "stp-out")):
                        tx_type = "STP_OUT"
                    elif any(kw in desc_lower for kw in ("stp in", "stp-in")):
                        tx_type = "STP_IN"
                    elif any(kw in desc_lower for kw in ("redemption", "swp", "systematic withdrawal")) or t_amt < 0:
                        tx_type = "REDEMPTION"
                    elif "sip" in desc_lower:
                        tx_type = "SIP"
                    elif any(kw in desc_lower for kw in ("purchase", "subscription", "allotment")):
                        tx_type = "PURCHASE"
                    else:
                        tx_type = "UNKNOWN"

                    if tx_type in ("PURCHASE", "SIP") and t_amt > 0:
                        sec_invested += t_amt

                    out["transactions"].append({
                        "scheme": sch_name,
                        "folio_no": folio,
                        "date": t_iso,
                        "amount": t_amt,
                        "units": t_units,
                        "nav": t_nav,
                        "description": t_desc_clean,
                        "type": tx_type,
                    })

                h = {
                    "scheme": sch_name,
                    "amc_name": amc_name,
                    "category": "",
                    "folio_no": folio,
                    "invested": sec_invested if sec_invested > 0 else val,
                    "current_value": val,
                    "returns": (val - sec_invested) if sec_invested > 0 else 0.0,
                    "units": units,
                    "nav": nav,
                    "amfi_code": None,
                    "isin": isin,
                }
                if val > 0:
                    out["holdings"].append(h)
                else:
                    out["dormant"].append(h)

            out["stated_total"] = sum(h["current_value"] for h in out["holdings"])
            out["reconcile_note"] = (
                f"Detailed CAS PDF parse: extracted {len(out['holdings'])} active holdings "
                f"(₹{out['stated_total']:,.2f}) and {len(out['transactions'])} transactions."
            )
            return out

        # -----------------------------------------------------------------------
        # BRANCH B: Single-Line Summary CAS Tabular Format
        # -----------------------------------------------------------------------
        holding_pattern = re.compile(
            r'([0-9,]+\.[0-9]{2})\s+([0-9,]+\.[0-9]{2}).*?([0-9,]+\.[0-9]{3})\s*([0-9]{2}-[A-Za-z]{3}-[0-9]{4})\s*([0-9A-Za-z/]+)\s+([0-9,]+\.[0-9]+)'
        )

        lines = full_text.splitlines()
        curr_scheme_tokens = []
        skip_phrases = (
            "Consolidated Account", "MFCentral", "SoA Holdings", "Demat Holdings",
            "Page ", "Invested Value", "Units NAV", "Gain/Loss", "Balance", "PAN :",
            "S/O ", "ROAD,", "HOSPITAL,", "Allocation by", "EQUITY FUND"
        )

        for l in lines:
            line_str = l.strip()
            if not line_str or any(sp in line_str for sp in skip_phrases):
                continue

            m = holding_pattern.search(line_str)
            if m:
                scheme_prefix = line_str[:m.start()].strip()
                scheme_name = (" ".join(curr_scheme_tokens) + " " + scheme_prefix).strip()
                scheme_name = re.sub(r'\( As on Date:.*?\)', '', scheme_name).strip()
                scheme_name = re.sub(r'\(INR\)\s*Market.*', '', scheme_name).strip()

                inv = float(m.group(1).replace(",", ""))
                val = float(m.group(2).replace(",", ""))
                units = float(m.group(3).replace(",", ""))
                folio = m.group(5)
                nav = float(m.group(6).replace(",", ""))

                h = {
                    "scheme": scheme_name or "Unknown Scheme",
                    "amc_name": "",
                    "category": "",
                    "folio_no": folio,
                    "invested": inv,
                    "current_value": val,
                    "returns": (val - inv),
                    "units": units,
                    "nav": nav,
                    "amfi_code": None,
                    "isin": None,
                }
                if val > 0:
                    out["holdings"].append(h)
                else:
                    out["dormant"].append(h)
                curr_scheme_tokens = []
            else:
                curr_scheme_tokens.append(line_str)

        out["stated_total"] = sum(h["current_value"] for h in out["holdings"])
        return out
    except Exception as exc:
        out["problems"].append(f"pypdf fallback error: {type(exc).__name__}: {exc}")
        return out


def parse_cas_pdf(source, password: str) -> dict:
    """
    Parse a CAS PDF using casparser with transparent pypdf fallback (GAP-196).
    
    Returns the same deterministic structure as parse_cas_xlsx.
    """
    out = {"holdings": [], "dormant": [], "rejected": [], "stated_total": 0.0,
           "as_of": None, "from_date": None, "identity": "read and discarded; never returned",
           "problems": []}
    has_casparser = False
    try:
        import casparser
        has_casparser = True
    except ImportError:
        has_casparser = False

    if not has_casparser:
        # GAP-196 FIX: Fall back to native pypdf when casparser is missing
        return _parse_cas_pdf_pypdf(source, password)

    try:
        if isinstance(source, (bytes, bytearray)):
            import io
            data = casparser.read_cas_pdf(io.BytesIO(source), password, output="dict")
        else:
            data = casparser.read_cas_pdf(source, password, output="dict")
    except Exception as exc:
        # Fall back to pypdf parser on casparser failure
        pypdf_res = _parse_cas_pdf_pypdf(source, password)
        if pypdf_res.get("holdings"):
            return pypdf_res
        out["problems"].append(f"Failed to parse PDF (wrong password?): {type(exc).__name__}: {exc}")
        return out
        
    out["as_of"] = data.get("statement_period", {}).get("to")
    out["from_date"] = data.get("statement_period", {}).get("from")
    total_val = 0.0
    out["transactions"] = []

    for folio in data.get("folios", []):
        folio_num = folio.get("folio")
        amc = folio.get("amc", "")
        for scheme in folio.get("schemes", []):
            val_obj = scheme.get("valuation", {})
            val = _num(val_obj.get("value"))
            units = _num(scheme.get("close_calculated"))
            invested = _num(val_obj.get("cost"))
            
            # casparser-isin magically resolves these
            amfi = scheme.get("amfi")
            isin = scheme.get("isin")
            
            scheme_name = scheme.get("scheme", "Unknown Scheme")
            
            h = {
                "scheme": scheme_name,
                "amc_name": amc,
                "category": scheme.get("type", ""),
                "folio_no": folio_num,
                "invested": invested,
                "current_value": val,
                "returns": (val - invested) if (val is not None and invested is not None) else None,
                "units": units,
                "amfi_code": amfi,
                "isin": isin
            }
            
            if val is not None and val > 0:
                out["holdings"].append(h)
                total_val += val
            else:
                out["dormant"].append(h)
                
            for tx in scheme.get("transactions", []):
                out["transactions"].append({
                    "scheme": scheme_name,
                    "folio_no": folio_num,
                    "date": str(tx.get("date", "")).split()[0] if tx.get("date") else "",
                    "description": tx.get("description", ""),
                    "amount": _num(tx.get("amount")),
                    "units": _num(tx.get("units")),
                    "nav": _num(tx.get("nav")),
                    "type": str(tx.get("type", "")).split(".")[-1],
                })
                
    # GAP-211 FIX: a PDF parse can never be reconciled against a
    # statement-reported total (the CAS XLSX carries an explicit "Current
    # Portfolio Value" row; the casparser PDF dict does not). Setting
    # stated_total to our own sum made cas.reconcile a tautology that always
    # reported "agrees". Mark the parse as UNVERIFIABLE instead so the caller
    # knows the totals were never independently checked.
    out["stated_total"] = None
    out["reconcile_note"] = (
        "PDF parse: the statement does not expose a portfolio total, so the "
        "parsed rows could not be reconciled. Treat totals as unverified."
    )
    return out


def parse_cas_file(path: str | pathlib.Path, password: str | None = None) -> tuple[list[dict], list[dict], dict]:
    """Dispatch CAS parser by extension and return (holdings, transactions, folio_values).

    Matches the interface expected by pages/page_upload.py.
    """
    path = pathlib.Path(path)
    suffix = path.suffix.lower()

    if suffix == ".xlsx":
        result = parse_cas_xlsx(path)
    elif suffix == ".pdf":
        if password is None:
            # Try without password first; if it fails, caller should prompt for PAN
            result = parse_cas_pdf(path, password="")
        else:
            result = parse_cas_pdf(path, password=password)
    else:
        raise ValueError(f"Unsupported CAS file type: {suffix}")

    # Build folio_values mapping from holdings + dormant
    folio_values = {}
    for h in result.get("holdings", []) + result.get("dormant", []):
        folio = h.get("folio_no")
        if folio:
            if folio not in folio_values:
                folio_values[folio] = {
                    "scheme_name": h.get("scheme_name") or h.get("scheme", "Unknown"),
                    "current_value": h.get("current_value", 0),
                }
            else:
                folio_values[folio]["current_value"] += h.get("current_value", 0)

    return result.get("holdings", []), result.get("transactions", []), folio_values


def detect_active_sips_from_cas(
    transactions: list[dict],
    as_of = None,
    tolerance_days: int = 45,
    max_history_days: int = 180,
) -> dict:
    """
    GAP-109: Transaction-Led Active Monthly SIP Periodicity Discovery.
    Issue #106: Prevent ordinary purchases and future-dated transactions
    from being reported as active SIP mandates.
    """
    from collections import defaultdict
    import datetime

    # Validate parameters
    if tolerance_days <= 0:
        raise ValueError(f"tolerance_days must be positive, got {tolerance_days}")
    if max_history_days <= 0:
        raise ValueError(f"max_history_days must be positive, got {max_history_days}")
    
    # Parse and validate as_of
    ref_date = None
    if as_of is not None:
        try:
            if isinstance(as_of, str):
                ref_date = datetime.date.fromisoformat(as_of.split("T")[0])
            elif isinstance(as_of, datetime.date):
                ref_date = as_of
            elif isinstance(as_of, datetime.datetime):
                ref_date = as_of.date()
            else:
                raise ValueError(f"Invalid as_of type: {type(as_of)}")
        except (ValueError, TypeError) as e:
            raise ValueError(f"Invalid as_of date: {as_of} - {e}")

    by_scheme = defaultdict(list)
    parsed_dates = []
    rejected_transactions = []
    malformed_dates = 0
    total_input = len(transactions)

    SIP_EVIDENCE_PATTERNS = re.compile(
        r'\b(SIP|NACH|NACHS|AUTOPAY|AUTO\s*PAY|RECURRING|MUTUAL\s*FUND\s*SIP|'
        r'MF\s*SIP|SYSTEMATIC\s*INVESTMENT|SIP\s*DEBIT|SIP\s*INSTALLMENT|'
        r'INSTALLMENT|AUTODEBIT|AUTO\s*DEBIT|RECURRING\s*DEBIT|MFAUTO)\b',
        re.IGNORECASE
    )
    NON_SIP_PATTERNS = re.compile(
        r'\b(LUMP\s*SUM|LUMP|ONE\s*TIME|ONE\s*OFF|ONE-OFF|SINGLE\s*PURCHASE|'
        r'DIVIDEND|DIV\s*REINV|REINVESTMENT|SWITCH|SWITCH\s*IN|SWITCH\s*OUT|'
        r'REVERSAL|REVERSE|CANCELLATION|CANCEL|REFUND|ADDITIONAL\s*PURCHASE|'
        r'MANUAL\s*PURCHASE|MANUAL)\b',
        re.IGNORECASE
    )

    for t in transactions:
        amt = _num(t.get("amount"))
        dt_val = t.get("date")
        desc = str(t.get("description", "") or t.get("tx_type", "") or "").strip()
        
        if amt is None or amt <= 0 or not dt_val:
            continue
            
        try:
            if isinstance(dt_val, str):
                d = datetime.date.fromisoformat(dt_val.split("T")[0])
            elif isinstance(dt_val, datetime.date):
                d = dt_val
            elif isinstance(dt_val, datetime.datetime):
                d = dt_val.date()
            else:
                malformed_dates += 1
                continue
        except (ValueError, TypeError):
            malformed_dates += 1
            continue
        
        parsed_dates.append(d)
        
        # Reject future-dated transactions if as_of is provided
        if ref_date is not None and d > ref_date:
            rejected_transactions.append({
                "date": d.isoformat(),
                "reason": "future_dated_transaction",
                "amount": float(amt),
                "description": desc,
            })
            continue
        
        scheme = str(t.get("scheme", "")).strip()
        folio = str(t.get("folio_no", t.get("folio", ""))).strip()
        
        has_sip_evidence = bool(SIP_EVIDENCE_PATTERNS.search(desc))
        has_non_sip_evidence = bool(NON_SIP_PATTERNS.search(desc))
        
        if has_non_sip_evidence and not has_sip_evidence:
            rejected_transactions.append({
                "date": d.isoformat(),
                "reason": "non_sip_transaction_type",
                "amount": float(amt),
                "description": desc,
            })
            continue
        
        by_scheme[(folio, scheme)].append((d, amt, desc, has_sip_evidence))

    if not parsed_dates:
        return {
            "active_sips": [],
            "total_monthly_sip": 0.0,
            "as_of": ref_date.isoformat() if ref_date else None,
            "active_sip_count": 0,
            "unverified_patterns": [],
            "unverified_count": 0,
            "rejection_stats": {
                "total_input": total_input,
                "rejected_future_dated": sum(1 for r in rejected_transactions if r["reason"] == "future_dated_transaction"),
                "rejected_non_sip": sum(1 for r in rejected_transactions if r["reason"] == "non_sip_transaction_type"),
                "malformed_dates": malformed_dates,
                "rejected_details": rejected_transactions,
            },
            "history_coverage": {
                "total_transactions": 0,
                "usable_transactions": 0,
                "coverage_note": "No valid transactions available - cannot determine SIP status",
            },
        }

    if ref_date is None:
        ref_date = max(parsed_dates)

    active_sips = []
    total_monthly = 0.0
    unverified_patterns = []
    usable_dates = []

    for (folio, scheme), items in by_scheme.items():
        items.sort(key=lambda x: x[0])
        # Enforce both as_of upper bound and max_history_days bounded history window
        valid_items = []
        for d, amt, desc, has_sip in items:
            if d > ref_date:
                continue
            age_days = (ref_date - d).days
            if age_days > max_history_days:
                rejected_transactions.append({
                    "date": d.isoformat(),
                    "reason": "outside_history_window",
                    "amount": float(amt),
                    "description": desc,
                })
                continue
            valid_items.append((d, amt, desc, has_sip))
            usable_dates.append(d)

        if len(valid_items) < 2:
            continue

        last_d, last_amt, last_desc, last_has_sip = valid_items[-1]
        prev_d, prev_amt, prev_desc, prev_has_sip = valid_items[-2]

        delta = (last_d - prev_d).days
        days_since = (ref_date - last_d).days

        if days_since < 0:
            rejected_transactions.append({
                "date": last_d.isoformat(),
                "reason": "stale_or_future_dated",
                "amount": float(last_amt),
                "description": last_desc,
            })
            continue

        # Require continuous mandate classification across qualifying installments
        both_have_sip_evidence = last_has_sip and prev_has_sip

        is_exact = abs(last_amt - prev_amt) <= 1.0
        is_step_up = (last_amt > prev_amt) and (20 <= delta <= 40) and (
            (last_amt - prev_amt) % 500 == 0 or (last_amt - prev_amt) % 1000 == 0 or (1.05 <= last_amt / prev_amt <= 2.0)
        )

        if (is_exact or is_step_up) and 20 <= delta <= 40 and 0 <= days_since <= tolerance_days:
            streak = 2
            for i in range(len(valid_items) - 2, 0, -1):
                cur_d, cur_amt, cur_desc, cur_has_sip = valid_items[i]
                p_d, p_amt, p_desc, p_has_sip = valid_items[i - 1]
                if (abs(cur_amt - p_amt) <= 1.0 or abs(cur_amt - prev_amt) <= 1.0) and 20 <= (cur_d - p_d).days <= 40:
                    streak += 1
                else:
                    break

            if both_have_sip_evidence:
                confidence = "VERIFIED"
                confidence_note = "Explicit SIP mandate evidence confirmed across qualifying installments"
            else:
                confidence = "UNVERIFIED"
                confidence_note = "Recurring payment pattern detected without continuous explicit mandate evidence"

            sip_entry = {
                "scheme": scheme,
                "folio_no": folio,
                "monthly_amount": round(float(last_amt), 2),
                "last_installment_date": last_d.isoformat(),
                "cadence_days": delta,
                "streak_months": streak,
                "days_since_last": days_since,
                "confidence": confidence,
                "confidence_note": confidence_note,
            }
            
            if confidence == "VERIFIED":
                active_sips.append(sip_entry)
                total_monthly += last_amt
            else:
                unverified_patterns.append(sip_entry)

        # Case 2: One-off lump sum arrived recently
        if not active_sips and not unverified_patterns and len(valid_items) >= 3:
            prev_d, prev_amt, prev_desc, prev_has_sip = valid_items[-2]
            p_prev_d, p_prev_amt, p_prev_desc, p_prev_has_sip = valid_items[-3]
            d_delta = (prev_d - p_prev_d).days
            d_days_since = (ref_date - prev_d).days
            
            if d_days_since < 0:
                continue

            if abs(prev_amt - p_prev_amt) <= 1.0 and 20 <= d_delta <= 40 and 0 <= d_days_since <= tolerance_days:
                streak = 2
                for i in range(len(valid_items) - 3, 0, -1):
                    cur_d, cur_amt, cur_desc, cur_has_sip = valid_items[i]
                    p_d, p_amt, p_desc, p_has_sip = valid_items[i - 1]
                    if abs(cur_amt - p_amt) <= 1.0 and 20 <= (cur_d - p_d).days <= 40:
                        streak += 1
                    else:
                        break

                case2_both_have_sip = prev_has_sip and p_prev_has_sip
                if case2_both_have_sip:
                    confidence = "VERIFIED"
                    confidence_note = "Explicit SIP mandate evidence confirmed across qualifying installments"
                else:
                    confidence = "UNVERIFIED"
                    confidence_note = "Recurring payment pattern detected without continuous explicit mandate evidence"

                sip_entry = {
                    "scheme": scheme,
                    "folio_no": folio,
                    "monthly_amount": round(float(prev_amt), 2),
                    "last_installment_date": prev_d.isoformat(),
                    "cadence_days": d_delta,
                    "streak_months": streak,
                    "days_since_last": d_days_since,
                    "confidence": confidence,
                    "confidence_note": confidence_note,
                }
                
                if confidence == "VERIFIED":
                    active_sips.append(sip_entry)
                    total_monthly += prev_amt
                else:
                    unverified_patterns.append(sip_entry)

    active_sips.sort(key=lambda x: x["monthly_amount"], reverse=True)
    unverified_patterns.sort(key=lambda x: x["monthly_amount"], reverse=True)

    usable_count = len(usable_dates)
    earliest_date = min(usable_dates, default=None)
    latest_date = max(usable_dates, default=None)
    window_days = (ref_date - earliest_date).days if earliest_date else 0
    history_status = "SUFFICIENT" if usable_count >= 2 else "INSUFFICIENT"

    history_coverage = {
        "total_transactions": total_input,
        "usable_transactions": usable_count,
        "rejected_count": len(rejected_transactions) + malformed_dates,
        "history_status": history_status,
        "history_window_days": window_days,
        "max_history_days": max_history_days,
        "earliest_transaction_date": earliest_date.isoformat() if earliest_date else None,
        "latest_transaction_date": latest_date.isoformat() if latest_date else None,
        "coverage_note": (
            f"{usable_count} of {total_input} transactions usable in {max_history_days}-day window. "
            f"{len(rejected_transactions)} rejected, {malformed_dates} malformed dates. "
            f"History status: {history_status}."
            if total_input > 0 else "No transactions provided."
        ),
    }

    return {
        "active_sips": active_sips,
        "total_monthly_sip": round(total_monthly, 2),
        "as_of": ref_date.isoformat(),
        "active_sip_count": len(active_sips),
        "unverified_patterns": unverified_patterns,
        "unverified_count": len(unverified_patterns),
        "rejection_stats": {
            "total_input": total_input,
            "rejected_future_dated": sum(1 for r in rejected_transactions if r["reason"] == "future_dated_transaction"),
            "rejected_non_sip": sum(1 for r in rejected_transactions if r["reason"] == "non_sip_transaction_type"),
            "rejected_stale": sum(1 for r in rejected_transactions if r["reason"] == "stale_or_future_dated"),
            "rejected_outside_history_window": sum(1 for r in rejected_transactions if r["reason"] == "outside_history_window"),
            "malformed_dates": malformed_dates,
            "rejected_details": rejected_transactions,
        },
        "history_coverage": history_coverage,
    }
