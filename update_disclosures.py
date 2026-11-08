#!/usr/bin/env python3
import re

FILE_PATH = r'C:\Users\l9999\Documents\VSworks\Mutual funds only prompt Based\services\report_generator.py'

with open(FILE_PATH, 'r', encoding='utf-8') as f:
    content = f.read()

# Use regex to find and replace the disclosures section
# Pattern to match the disclosures list in _build_fiduciary_disclosures
pattern = r'(\s+)disclosures = \[\s*\n\s*\("Statutory Mandate".*?\)\s*\n\s*\s*\n\s*\("Direct Plan Enforcement".*?\)\s*\n\s*\("Conflict of Interest Prohibition".*?\)\s*\n\s*\("Non-Execution Authority".*?\)\s*\n\s*\("Fee Transparency".*?\)\s*\n\s*\("Data Provenance".*?\)\s*\n\s*\]'

replacement = r'''\1# Build disclosures with integrity hash
\1integrity_info = f"Integrity Hash: {payload_hash or \'N/A\'} · " if payload_hash else ""
\1disclosures = [
\1    ("Statutory Mandate", "SEBI (Investment Advisers) Regulations, 2013 — Regulation 15(1) & Schedule III Code of Conduct."),
\1    ("Direct Plan Enforcement", "All proposed switches and SIP allocations strictly mandate Direct Plans to eliminate intermediary commissions and distributor trail leakage."),
\1    ("Conflict of Interest Prohibition", "The adviser receives zero consideration, referral fees, or commissions from any Asset Management Company (AMC) or intermediary."),
\1    ("Non-Execution Authority", "The adviser operates solely on a fee-only, non-execution advisory basis; order execution remains exclusively in client control via MFCentral, AMC portals, or RTAs."),
\1    ("Fee Transparency", "Advisory fees are agreed in writing upfront, deducted only from client's bank account — never from portfolio assets."),
\1    ("Data Provenance", f"{integrity_info}Portfolio data sourced from CAS (CAMS/Karvy) with integrity verification. Report generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC."),
\1]'''

if re.search(pattern, content, re.DOTALL):
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    with open(FILE_PATH, 'w', encoding='utf-8') as f:
        f.write(content)
    print('SUCCESS: Updated disclosures section with regex')
else:
    print('WARNING: Pattern not found')