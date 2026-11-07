#!/usr/bin/env python3
"""Generate fund_metrics.json from CAS sheet with proper name normalization.

Usage: python scripts/update_funds.py --cas-path <path_to_cas.xlsx>
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


def classify(s: str) -> dict:
    """Return equity/debt/lc/mc/sc allocation based on scheme name."""
    nl = s.lower()
    if 'flexi cap' in nl or 'multicap' in nl:
        return {'eq': 100.0, 'debt': 0.0, 'lc': 40.0, 'mc': 30.0, 'sc': 30.0}
    if 'mid cap' in nl or 'midcap' in nl:
        return {'eq': 100.0, 'debt': 0.0, 'lc': 20.0, 'mc': 60.0, 'sc': 20.0}
    if 'small cap' in nl or 'smallcap' in nl:
        return {'eq': 100.0, 'debt': 0.0, 'lc': 5.0, 'mc': 15.0, 'sc': 80.0}
    if 'large cap' in nl or 'largecap' in nl:
        return {'eq': 100.0, 'debt': 0.0, 'lc': 75.0, 'mc': 15.0, 'sc': 10.0}
    if 'elss' in nl or 'tax saver' in nl:
        return {'eq': 100.0, 'debt': 0.0, 'lc': 55.0, 'mc': 25.0, 'sc': 20.0}
    if 'balanced advantage' in nl or 'dynamic asset allocation' in nl:
        return {'eq': 65.0, 'debt': 35.0, 'lc': 30.0, 'mc': 25.0, 'sc': 10.0}
    if 'aggressive hybrid' in nl:
        return {'eq': 75.0, 'debt': 25.0, 'lc': 40.0, 'mc': 30.0, 'sc': 10.0}
    if 'conservative hybrid' in nl:
        return {'eq': 25.0, 'debt': 75.0, 'lc': 10.0, 'mc': 10.0, 'sc': 5.0}
    if any(k in nl for k in ('debt', 'liquid', 'income', 'bond', 'gilt', 'corporate')):
        return {'eq': 0.0, 'debt': 100.0, 'lc': 0.0, 'mc': 0.0, 'sc': 0.0}
    return {'eq': 100.0, 'debt': 0.0, 'lc': 30.0, 'mc': 40.0, 'sc': 30.0}


def clean_name(s: str) -> str:
    """Remove alias info from scheme name."""
    s = re.sub(r'\s*\(formerly.*$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s*\(erstwhile.*$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+\(Formerly.*$', '', s, flags=re.IGNORECASE)
    s = re.sub(r'\s+\(erstwhile.*$', '', s, flags=re.IGNORECASE)
    if ' Option' in s or ' option' in s:
        s = s.replace(' Option', '').replace(' option', '')
    s = re.sub(r'\s+', ' ', s)
    return s.strip()


def get_sector(s: str) -> list:
    """Return sector allocation based on scheme type."""
    nl = s.lower()
    if 'defence' in nl or 'defense' in nl:
        return [{'sector': 'Defense & Aerospace', 'weight': 40.0}]
    if 'pharma' in nl or 'health' in nl:
        return [{'sector': 'Healthcare', 'weight': 45.0}]
    if 'it' in nl or 'technology' in nl:
        return [{'sector': 'Information Technology', 'weight': 50.0}]
    if 'banking' in nl or 'financial' in nl:
        return [{'sector': 'Financial Services', 'weight': 40.0}]
    return [{'sector': 'Financial Services', 'weight': 25.0}]


def main():
    parser = argparse.ArgumentParser(description="Update fund metrics from CAS")
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

    print(f'Found {len(schemes)} unique schemes')

    funds = []
    for i, s in enumerate(schemes):
        a = classify(s)
        plan = 'Direct' if 'direct' in s.lower() else 'Regular'
        clean = clean_name(s)
        sector = get_sector(s)

        fund = {
            'scheme_id': f'SCH_{i+1:04d}',
            'isin': f'ISIN_{i+1:04d}',
            'amc_name': '',
            'category': 'Equity' if a['debt'] < 50 else 'Debt',
            'plan_type': plan,
            'option_type': 'Growth' if 'growth' in s.lower() else 'IDCW',
            'scheme_name': clean,
            'name': clean,
            'id': clean,
            'eq': a['eq'],
            'debt': a['debt'],
            'lc': a['lc'],
            'mc': a['mc'],
            'sc': a['sc'],
            'h': [],
            'sector': sector,
            'effective_date': '2026-10-09',
            'source_ref': 'cas_metrics_v1',
        }
        funds.append(fund)

    out = {'_notice': 'Enriched from CAS', 'funds': funds}
    out_file = Path('data/policy/fund_metrics.json')
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(out, indent=2))
    print(f'Wrote {len(funds)} funds to {out_file}')


if __name__ == '__main__':
    main()
