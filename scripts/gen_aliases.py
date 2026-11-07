#!/usr/bin/env python3
"""Generate fund_aliases.json from CAS scheme names.

Usage: python scripts/gen_aliases.py --cas-path <path_to_cas.xlsx>
"""

import argparse
import json
import re
import sys
from pathlib import Path
from openpyxl import load_workbook


def _find_portfolio_sheet(wb):
    """Find the portfolio sheet dynamically."""
    keywords = ("portfolio", "holdings", "scheme details", "consolidated")
    for name in wb.sheetnames:
        if any(kw in name.lower() for kw in keywords):
            return name
    return None


def clean(s: str) -> str:
    """Remove alias info from scheme name."""
    s = re.sub(r'\s*\(formerly.*$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s*\(erstwhile.*$', '', s, flags=re.IGNORECASE)
    s = s.replace('Option', '')
    return re.sub(r'\s+', ' ', s).strip()


def main():
    parser = argparse.ArgumentParser(description="Generate fund aliases from CAS")
    parser.add_argument("--cas-path", required=True, help="Path to CAS Excel file (.xlsx)")
    args = parser.parse_args()

    ca = Path(args.cas_path)
    if not ca.exists():
        print(f"ERROR: CAS file not found: {ca}", file=sys.stderr)
        sys.exit(1)

    wb = load_workbook(ca, data_only=True)
    sheet_name = _find_portfolio_sheet(wb)
    if sheet_name is None:
        print(f"ERROR: No portfolio sheet found. Sheets: {wb.sheetnames}", file=sys.stderr)
        sys.exit(1)
    sh = wb[sheet_name]

    scheme_col = 0
    _SCHEME_HEADERS = ("scheme", "scheme name", "fund", "fund name", "name", "scheme description", "scheme / plan")
    _SKIP = frozenset({"scheme", "scheme name", "fund", "fund name", "name", "amc", "folio", "units", "nav", "current value", "value"})
    for r in sh.iter_rows(values_only=True):
        if not r:
            continue
        row_str = [str(c).strip().lower() if c is not None else "" for c in r]
        found = False
        for idx, val in enumerate(row_str):
            if val in _SCHEME_HEADERS:
                scheme_col = idx
                found = True
                break
        if found:
            break

    schemes = []
    for r in sh.iter_rows(values_only=True):
        if not r or len(r) <= scheme_col or not r[scheme_col]:
            continue
        s = str(r[scheme_col]).strip()
        if not s or s.lower() in _SKIP:
            continue
        if s not in schemes:
            schemes.append(s)

    aliases = {}
    for s in schemes:
        c = clean(s)
        if s != c:
            aliases[s] = c

    out_file = Path('data/policy/fund_aliases.json')
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(aliases, indent=2))
    print(f'Wrote {len(aliases)} aliases to {out_file}')


if __name__ == '__main__':
    main()
