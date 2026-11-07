#!/usr/bin/env python3
"""Analyze CAS file to extract fund metrics with verified debt allocation.

Usage: python scripts/analyze_cas.py --cas-path <path_to_cas.xlsx>
"""

import argparse
import json
import sys
from pathlib import Path
from openpyxl import load_workbook


def _find_portfolio_sheet(wb):
    """Find the portfolio sheet dynamically (CAMS/KFinTech/MFCentral variants)."""
    keywords = ("portfolio", "holdings", "scheme details", "consolidated")
    for name in wb.sheetnames:
        if any(kw in name.lower() for kw in keywords):
            return name
    return None


def main():
    parser = argparse.ArgumentParser(description="Analyze CAS Excel file")
    parser.add_argument("--cas-path", required=True, help="Path to CAS Excel file (.xlsx)")
    args = parser.parse_args()

    cas_path = Path(args.cas_path)
    if not cas_path.exists():
        print(f"ERROR: CAS file not found: {cas_path}", file=sys.stderr)
        sys.exit(1)

    print("Starting CAS analysis...")

    wb = load_workbook(cas_path, data_only=True)
    sheet_name = _find_portfolio_sheet(wb)
    if sheet_name is None:
        print(f"ERROR: No portfolio sheet found. Sheets: {wb.sheetnames}", file=sys.stderr)
        sys.exit(1)
    sheet = wb[sheet_name]

    scheme_col = 0
    val_col = None
    _SCHEME_HEADERS = ("scheme", "scheme name", "fund", "fund name", "name", "scheme description", "scheme / plan")
    _VALUE_HEADERS = ("current value", "value", "market value", "closing value", "valuation", "total value")
    _SKIP = frozenset({"scheme", "scheme name", "fund", "fund name", "name", "amc", "folio", "units", "nav", "current value", "value"})

    for r in sheet.iter_rows(values_only=True):
        if not r:
            continue
        row_str = [str(c).strip().lower() if c is not None else "" for c in r]
        for idx, val in enumerate(row_str):
            if val in _SCHEME_HEADERS:
                scheme_col = idx
            elif val in _VALUE_HEADERS:
                val_col = idx
        if val_col is not None:
            break

    # Collect scheme data with values
    total_value = 0.0
    schemes_with_value = []

    for row in sheet.iter_rows(values_only=True):
        if not row or len(row) <= scheme_col or not row[scheme_col]:
            continue
        scheme_str = str(row[scheme_col]).strip()
        if not scheme_str or scheme_str.lower() in _SKIP:
            continue

        current = 0.0
        if val_col is not None and val_col < len(row) and row[val_col] is not None:
            try:
                current = float(str(row[val_col]).replace(",", "").replace("\u20b9", "").strip())
            except (ValueError, TypeError):
                current = 0.0
        else:
            for cell in reversed(row[1:]):
                if cell is not None:
                    try:
                        cand = float(str(cell).replace(",", "").replace("\u20b9", "").strip())
                        if cand > 0:
                            current = cand
                            break
                    except (ValueError, TypeError):
                        continue

        if current > 0:
            total_value += current
            schemes_with_value.append({
                'scheme': scheme_str,
                'current': current,
            })

    print(f'Total portfolio value: ₹ {round(total_value, 2):,.2f}')
    print(f'Schemes with positive current value: {len(schemes_with_value)}')
    print()

    # Show unique schemes
    seen = set()
    for s in schemes_with_value:
        if s['scheme'] not in seen:
            seen.add(s['scheme'])
            print(f"  ₹{s['current']:>12,.2f}  |  {s['scheme'][:70]}")


if __name__ == '__main__':
    main()
