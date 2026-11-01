import re
import shutil

# Load current file
with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    current = f.read()

# Load backup
with open('core/math_engine.py.backup', 'r', encoding='utf-8') as f:
    backup = f.read()

# Find all function definitions in backup
func_pattern = r'^def ([a-zA-Z_][a-zA-Z0-9_]*)\([^)]*\) -> [^(]+\n(?:.*\n)*?(?=^def |^class |\Z)'
functions = re.findall(func_pattern, backup, re.MULTILINE)

print(f'Found functions in backup: {len(functions)}')

# Get all function names
func_names = []
for match in re.finditer(r'^def ([a-zA-Z_][a-zA-Z0-9_]*)\(', backup, re.MULTILINE):
    func_names.append(match.group(1))

print(f'Function names: {func_names}')

# Check which are missing
current_funcs = re.findall(r'^def ([a-zA-Z_][a-zA-Z0-9_]*)\(', current, re.MULTILINE)

missing = [f for f in func_names if f not in current_funcs]
print(f'Missing functions: {missing}')

# Now extract each missing function properly
for func_name in missing:
    # Find the function in backup
    pattern = rf'^def {func_name}\(.*?\)( -> [^\n]*)?\n(.*?)(?=^\n(?:def |class |@|\Z))'
    match = re.search(pattern, backup, re.MULTILINE | re.DOTALL)
    if match:
        func_code = match.group(0)
        current += '\n\n' + func_code
        print(f'Added {func_name}')

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(current)
print('Done')