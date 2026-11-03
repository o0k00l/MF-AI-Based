import pathlib

p = pathlib.Path('test_p0_fiduciary_invariants.py')
t = p.read_text()

# Fix test_p0_3 base_good_fund - add ISIN
old = '        "is_direct": True\n    }\n\n    # Clean pass\n    res_clean = check_eligibility_gates(base_good_fund)'
new = '        "is_direct": True,\n        "isin": "TEST001",\n        "_provenance": {"confidence_score": 0.95}\n    }\n\n    # Clean pass\n    res_clean = check_eligibility_gates(base_good_fund)'

if old in t:
    t = t.replace(old, new)
    p.write_text(t)
    print('Fixed test_p0_3 base_good_fund')
else:
    print('Pattern not found for base_good_fund')
    idx = t.find('base_good_fund = {')
    if idx >= 0:
        end = t.find('\n    }', t.find('is_direct', idx))
        print('Block:', repr(t[idx:end+10]))

# Fix test_p0_6 - add ISIN to base_active
old2 = '        "is_direct": True\n    }\n\n    # 1. Clean pass baseline\n    res_clean = check_eligibility_gates(base_active)\n    assert res_clean.sharpe_alpha_gate is True\n    assert res_clean.passed is True'
new2 = '        "is_direct": True,\n        "isin": "TEST002",\n        "_provenance": {"confidence_score": 0.95}\n    }\n\n    # 1. Clean pass baseline\n    res_clean = check_eligibility_gates(base_active)\n    assert res_clean.sharpe_alpha_gate is True\n    assert res_clean.passed is True'

if old2 in t:
    t = t.replace(old2, new2)
    p.write_text(t)
    print('Fixed test_p0_6 base_active')
else:
    print('Pattern not found for base_active')
    idx = t.find('base_active = {')
    if idx >= 0:
        end = t.find('\n    }', t.find('is_direct', idx))
        print('Block:', repr(t[idx:end+10]))

# Fix test_p0_10 - add ISIN to base_active
old3 = '        "manager_tenure_years": 4.0,\n        "track_record_years": 5.0,\n        "mandate_suitable": True,\n        "aum_stable": True,\n        "is_direct": True,\n        "_provenance": {"confidence_score": 0.95}\n    }\n\n    # 1. Clean pass baseline\n    res_clean = check_eligibility_gates(base_active)'
new3 = '        "manager_tenure_years": 4.0,\n        "track_record_years": 5.0,\n        "mandate_suitable": True,\n        "aum_stable": True,\n        "is_direct": True,\n        "isin": "TEST003",\n        "_provenance": {"confidence_score": 0.95}\n    }\n\n    # 1. Clean pass baseline\n    res_clean = check_eligibility_gates(base_active)'

if old3 in t:
    t = t.replace(old3, new3)
    p.write_text(t)
    print('Fixed test_p0_10 base_active')
else:
    print('Pattern not found for test_p0_10 base_active')
    idx = t.find('base_active = {')
    if idx >= 0:
        end = t.find('\n    }', t.find('is_direct', idx))
        print('Block:', repr(t[idx:end+10]))