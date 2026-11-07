"""Create fund_metrics.json from CAS scheme names.

Usage: python scripts/create_fund_metrics.py --cas-path <path_to_cas.xlsx>
"""

import argparse
import json
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


def main():
    parser = argparse.ArgumentParser(description="Create fund metrics from CAS")
    parser.add_argument("--cas-path", required=True, help="Path to CAS Excel file (.xlsx)")
    args = parser.parse_args()

    cas_path = Path(args.cas_path)
    if not cas_path.exists():
        print(f"ERROR: CAS file not found: {cas_path}", file=sys.stderr)
        sys.exit(1)

    wb = load_workbook(cas_path, data_only=True)
    sheet_name = _find_portfolio_sheet(wb)
    if sheet_name is None:
        print(f"ERROR: No portfolio sheet found. Sheets: {wb.sheetnames}", file=sys.stderr)
        sys.exit(1)
    sheet = wb[sheet_name]

    scheme_col = 0
    _SCHEME_HEADERS = ("scheme", "scheme name", "fund", "fund name", "name", "scheme description", "scheme / plan")
    _SKIP = frozenset({"scheme", "scheme name", "fund", "fund name", "name", "amc", "folio", "units", "nav", "current value", "value"})
    for r in sheet.iter_rows(values_only=True):
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
    for row in sheet.iter_rows(values_only=True):
        if not row or len(row) <= scheme_col or not row[scheme_col]:
            continue
        s = str(row[scheme_col]).strip()
        if not s or s.lower() in _SKIP:
            continue
        if s not in schemes:
            schemes.append(s)

    print(f'Found {len(schemes)} unique schemes')

    funds = []
    for i, s in enumerate(schemes):
        nl = s.lower()
        if 'flexi cap' in nl or 'multicap' in nl:
            a = {'eq': 100.0, 'debt': 0.0, 'lc': 40.0, 'mc': 30.0, 'sc': 30.0}
        elif 'mid cap' in nl or 'midcap' in nl:
            a = {'eq': 100.0, 'debt': 0.0, 'lc': 20.0, 'mc': 60.0, 'sc': 20.0}
        elif 'small cap' in nl or 'smallcap' in nl:
            a = {'eq': 100.0, 'debt': 0.0, 'lc': 5.0, 'mc': 15.0, 'sc': 80.0}
        elif 'large cap' in nl or 'largecap' in nl:
            a = {'eq': 100.0, 'debt': 0.0, 'lc': 75.0, 'mc': 15.0, 'sc': 10.0}
        elif 'balanced advantage' in nl or 'dynamic asset allocation' in nl:
            a = {'eq': 65.0, 'debt': 35.0, 'lc': 30.0, 'mc': 25.0, 'sc': 10.0}
        elif any(k in nl for k in ('debt', 'liquid', 'income', 'bond', 'gilt')):
            a = {'eq': 0.0, 'debt': 100.0, 'lc': 0.0, 'mc': 0.0, 'sc': 0.0}
        else:
            a = {'eq': 100.0, 'debt': 0.0, 'lc': 30.0, 'mc': 40.0, 'sc': 30.0}

        plan = 'Direct' if 'direct' in nl else 'Regular'
        opt = 'IDCW' if 'idcw' in nl else 'Growth'

        fund = {
            'scheme_id': f'SCH_{i+1:04d}',
            'isin': f'ISIN_{i+1:04d}',
            'amc_name': '',
            'category': 'Equity' if 'debt' not in nl else 'Debt',
            'plan_type': plan,
            'option_type': opt,
            'scheme_name': s[:100],
            'name': s[:100],
            'eq': a['eq'], 'debt': a['debt'],
            'lc': a['lc'], 'mc': a['mc'], 'sc': a['sc'],
            'h': [], 'sector': {},
            'effective_date': '', 'source_ref': f'cas_parsed_{i}',
        }
        funds.append(fund)

    out = {'_notice': 'Fund metrics derived from CAS scheme names', '_source': 'Name-based classification', 'funds': funds}
    out_path = Path('data/policy/fund_metrics.json')
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    print(f'Wrote {len(funds)} fund entries to {out_path}')


if __name__ == '__main__':
    main()
