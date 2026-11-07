"""CAS Excel parser service.

Parses any user-uploaded CAS file dynamically. No hardcoded fund names,
scheme codes, or portfolio values. Every CAS is different per user.
"""
from __future__ import annotations

import io
import math
from typing import BinaryIO

from openpyxl import load_workbook


def classify_fund_by_name(scheme_name: str) -> dict:
    """Classify fund allocation by scheme name at runtime.

    Uses AMFI category conventions:
    - Flexi Cap / Multi Cap: ~2% internal debt
    - Mid Cap: ~2% debt
    - Balanced Advantage / Dynamic: 35% debt, 65% equity
    - ELSS / Tax Saver: 0% debt
    - Large Cap: ~5% debt
    - Debt / Income / Fixed Income: 100% debt
    - Default equity: ~2% debt
    """
    nl = scheme_name.lower()

    if "flexi cap" in nl or "multicap" in nl or "multi cap" in nl:
        return {"eq": 100.0, "debt": 2.0, "lc": 60.0, "mc": 30.0, "sc": 10.0}
    if "mid cap" in nl or "midcap" in nl:
        return {"eq": 100.0, "debt": 2.0, "lc": 15.0, "mc": 70.0, "sc": 15.0}
    if "small cap" in nl or "smallcap" in nl:
        return {"eq": 100.0, "debt": 2.0, "lc": 5.0, "mc": 15.0, "sc": 80.0}
    if "balanced advantage" in nl or "dynamic asset allocation" in nl:
        return {"eq": 65.0, "debt": 35.0, "lc": 30.0, "mc": 25.0, "sc": 10.0}
    if "elss" in nl or "tax saver" in nl:
        return {"eq": 100.0, "debt": 0.0, "lc": 55.0, "mc": 25.0, "sc": 20.0}
    if "large cap" in nl:
        return {"eq": 100.0, "debt": 5.0, "lc": 75.0, "mc": 15.0, "sc": 10.0}
    if "debt" in nl or "fixed income" in nl or "income" in nl or "liquid" in nl or "overnight" in nl:
        return {"eq": 0.0, "debt": 100.0, "lc": 0.0, "mc": 0.0, "sc": 0.0}
    if "contra" in nl or "value" in nl:
        return {"eq": 100.0, "debt": 0.0, "lc": 40.0, "mc": 35.0, "sc": 25.0}
    # Default: generic equity
    return {"eq": 100.0, "debt": 2.0, "lc": 30.0, "mc": 40.0, "sc": 30.0}


def parse_cas_file(file_obj: BinaryIO) -> list[dict]:
    """Parse an uploaded CAS Excel file and return fund records.

    Works with ANY user's CAS — no hardcoded scheme names.
    Looks for a sheet containing 'portfolio' or 'details' in its name.
    Aggregates multiple folios belonging to the same scheme name.
    """
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)

    try:
        wb = load_workbook(file_obj, data_only=True, read_only=True)
    except Exception:
        return []

    # Find the portfolio sheet dynamically
    sheet_name = None
    _KEYWORDS = ("portfolio", "details", "holding", "holdings", "consolidated", "scheme")
    for name in wb.sheetnames:
        if any(kw in name.lower() for kw in _KEYWORDS):
            sheet_name = name
            break
    if not sheet_name:
        wb.close()
        return []
    if not sheet_name:
        wb.close()
        return []

    sheet = wb[sheet_name]
    schemes_seen: list[str] = []
    values_map: dict[str, float] = {}
    invested_map: dict[str, float] = {}
    units_map: dict[str, float] = {}
    nav_map: dict[str, float] = {}
    folios_map: dict[str, list[str]] = {}

    # Common header / non-scheme labels to skip
    _SKIP_LABELS = frozenset({
        "scheme", "scheme name", "fund", "fund name", "name",
        "folio", "folio number", "folio no", "folio no.", "amc", "rta", "type", "plan",
        "option", "units", "nav", "current value", "value",
        "total", "subtotal", "summary", "statement", "account",
        "investor", "holder", "address", "email", "phone",
        "pan", "nominee", "guardian", "date", "transaction",
        "amount", "price", "return", "returns", "xirr", "absolute return",
        "invested value", "invested", "cost value", "cost", "market value",
    })

    # First pass: detect header row to find column indices
    scheme_col_idx: int = 0
    value_col_idx: int | None = None
    invested_col_idx: int | None = None
    units_col_idx: int | None = None
    nav_col_idx: int | None = None
    folio_col_idx: int | None = None

    _SCHEME_HEADERS = (
        "scheme", "scheme name", "fund", "fund name", "name",
        "scheme description", "scheme / plan", "scheme/plan", "fund/scheme"
    )
    _VALUE_HEADERS = (
        "current value", "value", "market value", "closing value",
        "valuation", "total value", "current", "current value (inr)",
        "current value (rs.)", "valuation (inr)", "valuation (rs.)",
        "market value (inr)", "market value (rs.)"
    )
    _INVESTED_HEADERS = (
        "invested value", "invested", "cost value", "cost",
        "purchase value", "invested amount", "cost basis",
        "cost (inr)", "cost (rs.)", "invested (inr)", "invested (rs.)"
    )
    _UNITS_HEADERS = (
        "units", "closing units", "balance units", "unit balance",
        "total units", "unit", "cumulative units"
    )
    _NAV_HEADERS = (
        "nav", "latest nav", "nav on date", "price",
        "nav/price", "nav (rs.)", "nav (inr)"
    )
    _FOLIO_HEADERS = (
        "folio no.", "folio no", "folio number", "folio",
        "account no.", "account no", "folio/account"
    )

    for row in sheet.iter_rows(values_only=True):
        if not row:
            continue
        row_str = [str(c).strip().lower() if c is not None else "" for c in row]
        if any(h in row_str for h in _SCHEME_HEADERS):
            for idx, cell_str in enumerate(row_str):
                if cell_str in _SCHEME_HEADERS:
                    scheme_col_idx = idx
                elif cell_str in _VALUE_HEADERS:
                    value_col_idx = idx
                elif cell_str in _INVESTED_HEADERS:
                    invested_col_idx = idx
                elif cell_str in _UNITS_HEADERS:
                    units_col_idx = idx
                elif cell_str in _NAV_HEADERS:
                    nav_col_idx = idx
                elif cell_str in _FOLIO_HEADERS:
                    folio_col_idx = idx
            if value_col_idx is not None:
                break

    for row in sheet.iter_rows(values_only=True):
        if not row or len(row) <= scheme_col_idx or not row[scheme_col_idx]:
            continue
        scheme = str(row[scheme_col_idx]).strip()
        if not scheme:
            continue
        # Skip header rows and common non-scheme labels
        if scheme.lower() in _SKIP_LABELS:
            continue

        # Extract current value
        value = 0.0
        if value_col_idx is not None and value_col_idx < len(row):
            cell = row[value_col_idx]
            if cell is not None:
                try:
                    val_str = str(cell).replace(",", "").replace("\u20b9", "").strip()
                    val_f = float(val_str)
                    if math.isfinite(val_f) and val_f > 0:
                        value = val_f
                except (ValueError, TypeError):
                    value = 0.0
        else:
            # Fallback: take the LAST positive number in the row
            for cell in reversed(row[1:]):
                if cell is not None:
                    try:
                        cand_str = str(cell).replace(",", "").replace("\u20b9", "").strip()
                        cand_f = float(cand_str)
                        if math.isfinite(cand_f) and cand_f > 0:
                            value = cand_f
                            break
                    except (ValueError, TypeError):
                        continue

        # Extract invested value
        invested = 0.0
        if invested_col_idx is not None and invested_col_idx < len(row):
            cell = row[invested_col_idx]
            if cell is not None:
                try:
                    inv_str = str(cell).replace(",", "").replace("\u20b9", "").strip()
                    inv_f = float(inv_str)
                    if math.isfinite(inv_f) and inv_f > 0:
                        invested = inv_f
                except (ValueError, TypeError):
                    invested = 0.0

        # Extract units
        units = 0.0
        if units_col_idx is not None and units_col_idx < len(row):
            cell = row[units_col_idx]
            if cell is not None:
                try:
                    units_str = str(cell).replace(",", "").strip()
                    units_f = float(units_str)
                    if math.isfinite(units_f) and units_f > 0:
                        units = units_f
                except (ValueError, TypeError):
                    units = 0.0

        # Extract NAV
        nav = 0.0
        if nav_col_idx is not None and nav_col_idx < len(row):
            cell = row[nav_col_idx]
            if cell is not None:
                try:
                    nav_str = str(cell).replace(",", "").replace("\u20b9", "").strip()
                    nav_f = float(nav_str)
                    if math.isfinite(nav_f) and nav_f > 0:
                        nav = nav_f
                except (ValueError, TypeError):
                    nav = 0.0

        # Derived values when one is missing
        if nav <= 0.0 and units > 0.0 and value > 0.0:
            nav = round(value / units, 4)
        elif units <= 0.0 and nav > 0.0 and value > 0.0:
            units = round(value / nav, 4)

        # Extract folio
        folio_str = ""
        if folio_col_idx is not None and folio_col_idx < len(row) and row[folio_col_idx]:
            folio_str = str(row[folio_col_idx]).strip()

        # Aggregate multiple folios of the same scheme
        if scheme not in schemes_seen:
            schemes_seen.append(scheme)
            values_map[scheme] = value
            invested_map[scheme] = invested
            units_map[scheme] = units
            nav_map[scheme] = nav
            folios_map[scheme] = [folio_str] if folio_str else []
        else:
            values_map[scheme] += value
            invested_map[scheme] += invested
            units_map[scheme] += units
            if nav > 0.0:
                nav_map[scheme] = nav
            elif units_map[scheme] > 0.0:
                nav_map[scheme] = round(values_map[scheme] / units_map[scheme], 4)
            if folio_str and folio_str not in folios_map[scheme]:
                folios_map[scheme].append(folio_str)

    wb.close()

    if not schemes_seen:
        return []

    funds: list[dict] = []
    for scheme in schemes_seen:
        val = values_map.get(scheme, 0.0)
        inv = invested_map.get(scheme, 0.0)
        u = units_map.get(scheme, 0.0)
        n = nav_map.get(scheme, 0.0)
        folios = folios_map.get(scheme, [])

        # Skip closed folios with 0 balance and 0 units
        if val <= 0.0 and u <= 0.0 and inv <= 0.0:
            continue

        alloc = classify_fund_by_name(scheme)
        category = "Debt" if alloc["eq"] == 0 else ("Hybrid" if alloc["debt"] > 10 else "Equity")
        plan_type = "Direct" if "direct" in scheme.lower() else "Regular"
        option_type = "IDCW" if "idcw" in scheme.lower() else "Growth"

        unrealized_gain = round(val - inv, 2) if inv > 0.0 else 0.0
        gain_pct = round((unrealized_gain / inv) * 100, 2) if inv > 0.0 else 0.0

        funds.append({
            "scheme": scheme,
            "category": category,
            "plan_type": plan_type,
            "option_type": option_type,
            "eq": alloc["eq"],
            "debt": alloc["debt"],
            "lc": alloc["lc"],
            "mc": alloc["mc"],
            "sc": alloc["sc"],
            "current_value": val,
            "invested_value": inv,
            "unrealized_gain": unrealized_gain,
            "gain_pct": gain_pct,
            "units": u,
            "nav": n,
            "folio_no": ", ".join(folios) if folios else "",
        })

    return funds
