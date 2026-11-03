import pathlib

p = pathlib.Path('test_p0_fiduciary_invariants.py')
t = p.read_text()

# Fix test_p0_10 base_active fixture - add missing fields
old = '        "manager_tenure_years": 4.0,\n        "is_direct": True\n    }\n\n    # 1. Clean pass baseline\n    res_clean = check_eligibility_gates(base_active)'

new = '        "manager_tenure_years": 4.0,\n        "track_record_years": 5.0,\n        "mandate_suitable": True,\n        "aum_stable": True,\n        "is_direct": True,\n        "_provenance": {"confidence_score": 0.95}\n    }\n\n    # 1. Clean pass baseline\n    res_clean = check_eligibility_gates(base_active)'

if old in t:
    t = t.replace(old, new)
    p.write_text(t)
    print('Fixed test_p0_10 base_active')
else:
    print('Pattern not found')
    idx = t.find('base_active = {')
    if idx >= 0:
        end = t.find('"is_direct"', idx)
        end2 = t.find('\n', t.find('True', end))
        print('Block:', repr(t[idx:end2+10]))