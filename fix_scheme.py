import pathlib

p = pathlib.Path('core/math_engine.py')
t = p.read_text()

# Fix: ensure flexi_scheme is never None
old = 'flexi_scheme = flexi_info.get("scheme")'
new = 'flexi_scheme = flexi_info.get("scheme") or flexi_info.get("fund_name") or "NO_ACTION: No eligible fund selected"'
t = t.replace(old, new)

# Fix: ensure mid_scheme is never None  
old2 = 'mid_scheme = mid_info.get("scheme")'
new2 = 'mid_scheme = mid_info.get("scheme") or mid_info.get("fund_name") or "NO_ACTION: No eligible fund selected"'
t = t.replace(old2, new2)

# Fix: ensure large_scheme is never None
old3 = 'large_scheme = large_info.get("scheme")'
new3 = 'large_scheme = large_info.get("scheme") or large_info.get("fund_name") or "NO_ACTION: No eligible fund selected"'
t = t.replace(old3, new3)

# Fix: ensure pharma_scheme is never None
old4 = 'pharma_scheme = thematic_info.get("scheme")'
new4 = 'pharma_scheme = thematic_info.get("scheme") or thematic_info.get("fund_name") or "NO_ACTION: No eligible fund selected"'
t = t.replace(old4, new4)

# Fix: replace None scheme with fallback in all NO_ACTION blocks
old5 = "'scheme': None,\n                    'folio': None,\n                    'rationale':"
new5 = "'scheme': 'NO_ACTION: No eligible fund selected',\n                    'folio': None,\n                    'rationale':"
t = t.replace(old5, new5)

p.write_text(t)
print("Done - scheme None fixed")