#!/usr/bin/env python3
"""Fix the disclosures section in report_generator.py"""
import re

FILE_PATH = r'C:\Users\l9999\Documents\VSworks\Mutual funds only prompt Based\services\report_generator.py'

with open(FILE_PATH, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the line with "disclosures = [" in the _build_fiduciary_disclosures function
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    # In _build_fiduciary_disclosures, add integrity_info before disclosures
    if 'disclosures = [' in line and i > 550:
        # Check if this is the right section (has Integrity Hash nearby or not yet added)
        # Add integrity_info line before this
        indent = '    '
        new_lines.append(indent + '# Build disclosures with integrity hash\n')
        new_lines.append(indent + 'integrity_info = f"Integrity Hash: {payload_hash or \'N/A\'} · " if payload_hash else ""\n')
    # Update the Data Provenance line to include integrity_info
    if '("Data Provenance", f"Portfolio data sourced from CAS' in line and 'integrity_info' not in line and i > 550:
        line = line.replace('("Data Provenance", f"Portfolio data sourced from CAS', '("Data Provenance", f"{integrity_info}Portfolio data sourced from CAS')
    
    new_lines.append(line)
    i += 1

with open(FILE_PATH, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('DONE')