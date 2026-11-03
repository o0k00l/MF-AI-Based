import pathlib

p = pathlib.Path('core/fund_classifier.py')
t = p.read_text()

start = t.find('def is_verified_passive_scheme(')
end = t.find('\n\nFUND_CATEGORY_TAXONOMY')

if start >= 0 and end >= 0:
    new_func = open('fix_passive_func.txt', 'r', encoding='utf-8').read()
    t = t[:start] + new_func + t[end:]
    p.write_text(t)
    print("Done - passive verification fixed")
else:
    print("Function not found")
    print("start:", start, "end:", end)