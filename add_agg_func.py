with open('core/math_engine.py.backup', 'r', encoding='utf-8') as f:
    backup = f.read()

# Find aggregate_fiduciary_facts
idx = backup.find('def aggregate_fiduciary_facts')
print(f'Found at index: {idx}')

# Find the end of this function - next def
next_def = backup.find('\ndef ', idx + 1)
func_code = backup[idx:next_def]

print(f'Function length: {len(func_code)}')
print(func_code[:500])

# Append to current file
with open('core/math_engine.py', 'a', encoding='utf-8') as f:
    f.write('\n\n' + func_code)
print('Added')