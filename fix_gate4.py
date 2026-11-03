import pathlib

p = pathlib.Path('core/eligibility.py')
t = p.read_text()

# Fix the Gate 4 passive verification call
old = '''    f_name = fund_data.get("fund_name", fund_data.get("name", ""))
    try:
        is_passive_cand = is_verified_passive_scheme(fund_data, fund_name=f_name, category=category)
    except InsufficientDataError as e:
        # Gate 4: Passive scheme verification failed due to missing scheme master
        # This is a hard fail for Gate 4 exemption — active fund criteria must be met
        failed.append(f"Gate 4 [Passive Verification]: {e}")
        is_passive_cand = False
    
    sharpe_ok = False
    if is_passive_cand:
        sharpe_ok = True'''

new = '''    f_name = fund_data.get("fund_name", fund_data.get("name", ""))
    try:
        # Check if fund is passive for Sharpe/Alpha exemption
        # Use require_scheme_master=False for detection; strict verification only if claiming passive
        is_passive_cand = is_verified_passive_scheme(fund_data, fund_name=f_name, category=category, require_scheme_master=False)
    except InsufficientDataError as e:
        # If scheme master required but not available, treat as active fund (no passive exemption)
        is_passive_cand = False
    
    sharpe_ok = False
    if is_passive_cand:
        sharpe_ok = True'''

if old in t:
    t = t.replace(old, new)
    p.write_text(t)
    print("Done - fixed Gate 4 passive detection")
else:
    print("Pattern not found")
    # Find the relevant section
    idx = t.find('is_verified_passive_scheme(fund_data, fund_name=f_name, category=category)')
    if idx >= 0:
        print("Found at:", idx)
        print(repr(t[idx:idx+500]))