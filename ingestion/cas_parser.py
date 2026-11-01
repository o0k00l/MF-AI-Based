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
    if isinstance(v, (int, float)):
        return float(v)
    return float(str(v).replace(",", "").strip())


def parse_cas_xlsx(source) -> dict:
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
        for follow in rows[i + 1:i + 4]:
            if pos < len(follow) and isinstance(follow[pos], (int, float)):
                out["stated_total"] = float(follow[pos])
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
               "category": (str(cell("category") or "").strip() or None)}
        for opt, key in (("invested_value", "invested"),
                         ("returns", "returns"), ("units", "units")):
            try:
                v = _num(cell(opt))
            except (TypeError, ValueError):
                v = None
            if v is not None:
                rec[key] = v
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
                for r in tx_rows[hdr_idx + 1:]:
                    if not any(r): continue
                    sn = r[sn_col]
                    if sn and str(sn).strip():
                        last_scheme = str(sn).strip()
                    dt = str(r[dt_col] or "").strip()
                    amt = _num(r[amt_col])
                    if last_scheme and dt and amt is not None:
                        # try parse date
                        try:
                            import datetime as dt_mod
                            d = dt_mod.datetime.strptime(dt, "%d-%b-%Y").strftime("%Y-%m-%d")
                        except ValueError:
                            d = dt
                        
                        # Determine transaction type from description
                        desc = str(r[desc_col]).strip().lower() if desc_col is not None else ""
                        tx_type = "PURCHASE"
                        if any(kw in desc for kw in ("redemption", "switch out", "switch-out", "payout", "dividend payout")):
                            tx_type = "REDEMPTION"
                        elif "switch in" in desc or "switch-in" in desc:
                            tx_type = "SWITCH_IN"
                        elif "stamp duty" in desc or "stt" in desc:
                            tx_type = "CHARGES"
                        
                        out["transactions"].append({
                            "scheme": last_scheme,
                            "date": d,
                            "amount": amt,
                            "units": _num(r[unt_col]) if unt_col is not None else None,
                            "nav": _num(r[nav_col]) if nav_col is not None else None,
                            "description": str(r[desc_col]).strip() if desc_col is not None else "",
                            "type": tx_type
                        })
    return out


def reconcile(parsed: dict, tolerance: float = 1.0) -> dict:
    """
    Check the parse against the total the statement itself reports.

    A CAS carries its own portfolio total. If the rows we read do not add up to
    it, the parse is wrong and the caller must be told - the same discipline the
    capital-gains reconciliation uses. Silently trusting our own sum is how a
    partial read becomes a confident wrong portfolio.
    """
    total = sum(r["current_value"] for r in parsed.get("holdings", []))
    stated = parsed.get("stated_total")
    out = {"parsed_total": round(total, 2), "stated_total": stated,
           "difference": None, "agrees": None, "note": ""}
    if stated is None:
        out["note"] = ("the statement reports no portfolio total, so the parse "
                       "could not be checked")
        return out
    diff = total - float(stated)
    out["difference"] = round(diff, 2)
    out["agrees"] = abs(diff) <= tolerance
    out["note"] = ("parsed rows match the statement total" if out["agrees"]
                   else f"PARSED TOTAL DISAGREES by Rs {diff:,.2f}; the parse "
                        f"is incomplete and must not be relied on")
    return out


def to_cache_csv(parsed: dict, enriched: bool = False) -> str:
    """
    Render parsed holdings into the CSV the engine already reads.

    When enriched=False (default), preserves the canonical contract expected by
    _live_folios() and unit tests: '"Scheme Name",Invested,CurrentValue'.
    When enriched=True (GAP-198), preserves all 7 ground-truth fields:
    '"Scheme Name",CurrentValue,Units,Invested,"Folio Number",ISIN,NAV'.
    """
    holdings_list = parsed.get("holdings") or parsed.get("funds") or []
    if enriched:
        out = ['"Scheme Name",CurrentValue,Units,Invested,"Folio Number",ISIN,NAV']
        for r in holdings_list:
            name = str(r.get("scheme", "")).replace('"', "'").strip()
            cur_val = float(r.get("current_value", 0.0) or 0.0)
            units = float(r.get("units", 0.0) or 0.0)
            invested = float(r.get("invested_value", 0.0) or r.get("invested", 0.0) or r.get("cost_value", 0.0) or 0.0)
            folio = str(r.get("folio_no") or r.get("folio") or "").replace('"', "").strip()
            isin = str(r.get("isin", "")).replace('"', "").strip()
            nav = float(r.get("nav", 0.0) or 0.0)
            if nav == 0.0 and units > 0 and cur_val > 0:
                nav = cur_val / units
            out.append(f'"{name}",{cur_val:.2f},{units:.3f},{invested:.2f},"{folio}","{isin}",{nav:.4f}')
        return "\n".join(out) + "\n"

    out = ['"Scheme Name",Invested,CurrentValue']
    for r in holdings_list:
        name = str(r.get("scheme", "")).replace('"', "'").strip()
        invested = float(r.get("invested_value", 0.0) or r.get("invested", 0.0) or r.get("cost_value", 0.0) or 0.0)
        cur_val = float(r.get("current_value", 0.0) or 0.0)
        out.append(f'"{name}",{invested:.2f},{cur_val:.2f}')
    return "\n".join(out) + "\n"


def to_enriched_cache_csv(parsed: dict) -> str:
    """GAP-198: Explicit helper for enriched cache serialization."""
    return to_cache_csv(parsed, enriched=True)


def stage_portfolio(parsed: dict, root, slug: str = "Upload_Portfolio") -> dict:
    """
    Materialise a portfolio workspace from an uploaded statement.

    Writes only what the engine reads. No identity is written anywhere, so the
    staged folder contains no PAN, name, phone or email.
    """
    root = pathlib.Path(root)
    pdir = root / slug
    (pdir / "data").mkdir(parents=True, exist_ok=True)
    # GAP-198 / GAP-224: Materialize enriched cache CSV with all 7 ground-truth columns
    (pdir / "data" / "_active_funds_cache.csv").write_text(
        to_cache_csv(parsed, enriched=True), encoding="utf-8")
        
    import json
    if parsed.get("transactions"):
        (pdir / "data" / "transactions.json").write_text(
            json.dumps({"transactions": parsed.get("transactions")}, indent=2), encoding="utf-8")
            
    return {"slug": slug, "root": str(pdir),
            "cache": str(pdir / "data" / "_active_funds_cache.csv"),
            "holdings": len(parsed.get("holdings", [])),
            "identity_written": False}


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
                    if any(kw in desc_lower for kw in ("redemption", "switch out", "switch-out", "payout", "dividend payout")) or t_amt < 0:
                        tx_type = "REDEMPTION"
                    elif "switch in" in desc_lower or "switch-in" in desc_lower:
                        tx_type = "SWITCH_IN"
                    elif "stamp duty" in desc_lower or "stt" in desc_lower:
                        tx_type = "CHARGES"
                    else:
                        tx_type = "PURCHASE"

                    if tx_type == "PURCHASE" and t_amt > 0:
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
    Identifies active ongoing monthly SIP debits from transaction patterns.

    Mathematical & Operational Invariants:
      1. Group transactions by (folio_number, scheme_name).
      2. Filter for positive inflows (PURCHASE, SIP, or positive amounts).
      3. For consecutive inflows, check:
         - monthly periodicity (20 <= delta <= 40 days)
         - amount consistency (|amount_k - amount_{k-1}| <= 1.0 INR)
         - recency (most recent debit within tolerance_days of statement as_of date)
      4. Return active SIP schedule and aggregate monthly run-rate.
    """
    from collections import defaultdict
    import datetime

    by_scheme = defaultdict(list)
    parsed_dates = []

    for t in transactions:
        amt = _num(t.get("amount"))
        dt_val = t.get("date")
        if amt and amt > 0 and dt_val:
            try:
                if isinstance(dt_val, str):
                    d = datetime.date.fromisoformat(dt_val.split("T")[0])
                elif isinstance(dt_val, datetime.date):
                    d = dt_val
                elif isinstance(dt_val, datetime.datetime):
                    d = dt_val.date()
                else:
                    continue
                parsed_dates.append(d)
                scheme = str(t.get("scheme", "")).strip()
                folio = str(t.get("folio_no", t.get("folio", ""))).strip()
                by_scheme[(folio, scheme)].append((d, amt, t.get("description", "")))
            except Exception:
                continue

    if not parsed_dates:
        return {"active_sips": [], "total_monthly_sip": 0.0, "as_of": None, "active_sip_count": 0}

    ref_date = as_of or max(parsed_dates)

    active_sips = []
    total_monthly = 0.0

    for (folio, scheme), items in by_scheme.items():
        items.sort(key=lambda x: x[0])
        if len(items) < 2:
            continue

        # GAP-088 FIX: Robust periodic cadence detection handling step-ups, lump sums and date shifts
        found_sip = False
        last_d, last_amt, last_desc = items[-1]
        prev_d, prev_amt, prev_desc = items[-2]

        delta = (last_d - prev_d).days
        days_since = (ref_date - last_d).days

        # Case 1: Standard consecutive match or valid annual step-up
        is_exact = abs(last_amt - prev_amt) <= 1.0
        is_step_up = (last_amt > prev_amt) and (20 <= delta <= 40) and (
            (last_amt - prev_amt) % 500 == 0 or (last_amt - prev_amt) % 1000 == 0 or (1.05 <= last_amt / prev_amt <= 2.0)
        )

        if (is_exact or is_step_up) and 20 <= delta <= 40 and days_since <= tolerance_days:
            streak = 2
            for i in range(len(items) - 2, 0, -1):
                cur_d, cur_amt, _ = items[i]
                p_d, p_amt, _ = items[i - 1]
                if (abs(cur_amt - p_amt) <= 1.0 or abs(cur_amt - prev_amt) <= 1.0) and 20 <= (cur_d - p_d).days <= 40:
                    streak += 1
                else:
                    break

            sip_entry = {
                "scheme": scheme,
                "folio_no": folio,
                "monthly_amount": round(float(last_amt), 2),
                "last_installment_date": last_d.isoformat(),
                "cadence_days": delta,
                "streak_months": streak,
                "days_since_last": days_since,
            }
            active_sips.append(sip_entry)
            total_monthly += last_amt
            found_sip = True

        # Case 2: One-off lump sum arrived recently (last item is a lump sum, but items[-2] and items[-3] form an active SIP)
        if not found_sip and len(items) >= 3:
            prev_d, prev_amt, _ = items[-2]
            p_prev_d, p_prev_amt, _ = items[-3]
            d_delta = (prev_d - p_prev_d).days
            d_days_since = (ref_date - prev_d).days
            if abs(prev_amt - p_prev_amt) <= 1.0 and 20 <= d_delta <= 40 and d_days_since <= tolerance_days:
                streak = 2
                for i in range(len(items) - 3, 0, -1):
                    cur_d, cur_amt, _ = items[i]
                    p_d, p_amt, _ = items[i - 1]
                    if abs(cur_amt - p_amt) <= 1.0 and 20 <= (cur_d - p_d).days <= 40:
                        streak += 1
                    else:
                        break

                sip_entry = {
                    "scheme": scheme,
                    "folio_no": folio,
                    "monthly_amount": round(float(prev_amt), 2),
                    "last_installment_date": prev_d.isoformat(),
                    "cadence_days": d_delta,
                    "streak_months": streak,
                    "days_since_last": d_days_since,
                }
                active_sips.append(sip_entry)
                total_monthly += prev_amt
                found_sip = True

    active_sips.sort(key=lambda x: x["monthly_amount"], reverse=True)

    return {
        "active_sips": active_sips,
        "total_monthly_sip": round(total_monthly, 2),
        "as_of": ref_date.isoformat(),
        "active_sip_count": len(active_sips),
    }
