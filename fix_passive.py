import pathlib
p = pathlib.Path('fix_passive.txt')
if p.exists():
    content = p.read_text()
    p2 = pathlib.Path('fix_passive_func.txt')
    p2.write_text(content)
    print('Wrote fix_passive_func.txt')
else:
    print('fix_passive.txt does not exist')
