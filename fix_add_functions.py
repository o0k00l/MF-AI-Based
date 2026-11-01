new_content = open('core/math_engine.py', 'r', encoding='utf-8').read()

# Read all the functions from backup
with open('core/math_engine.py.backup', 'r', encoding='utf-8') as f:
    backup = f.read()

import re

# Extract functions from backup
funcs_to_copy = [
    'calculate_xirr',
    'calculate_portfolio_xirr',
    'load_holdings_from_cas_excel',
    '_find_matching_metric',
    '_infer_asset_class',
    'calculate_fee_bleed',
    'calculate_overlap_matrix',
    'calculate_saa_drift',
    'calculate_cash_deployment',
    'aggregate_fiduciary_facts'
]

for func_name in funcs_to_copy:
    # Find the function in backup
    pattern = r'^def ' + func_name + r'\(.*?(?=\n^def |\n^class |\n@dataclass|\Z)'
    match = re.search(pattern, backup, re.MULTILINE | re.DOTALL)
    if match:
        new_content += '\n' + match.group(0)
        print(f'Added {func_name}')
    else:
        print(f'NOT FOUND: {func_name}')

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('All functions added')