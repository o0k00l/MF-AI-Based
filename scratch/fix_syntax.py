with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if 'return None, Noned' in line:
        new_lines.append('    return None, None\n')
        skip = True
        continue
    if skip:
        if line.strip() == 'return None, None':
            skip = False
            continue
        elif 'def select_autonomous_blueprint_funds' in line:
            skip = False
            new_lines.append(line)
        continue
    new_lines.append(line)

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Done fixing syntax!")

