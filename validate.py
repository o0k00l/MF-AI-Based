import json, subprocess

result = subprocess.run(['python', 'advisor_lean.py', '--no-ai'], capture_output=True, text=True, timeout=30)
facts = json.loads(result.stdout)

i = facts.get('invested', 0)
t = facts.get('total_value', 0)
g = facts.get('gain', 0)

print('=== VALIDATION REPORT ===')
print('Invested:', i)
print('Total:', t)
print('Gain:', g)
print('Simple Return%:', g/i*100 if i else 0)
print('XIRR:', facts.get('xirr_pct',0)*100)
print('Benchmark:', facts.get('benchmark_xirr_pct',0)*100)
print('Alpha:', facts.get('alpha_pct',0))

fb = facts.get('fee_bleed', {})
rv = fb.get('regular_value', 0)
ab = fb.get('annual_bleed', 0)
print('RegVal:', rv)
print('AnnualBleed:', ab)
print('Premium%:', ab/rv*100 if rv else 0)

c = facts.get('cash', {})
tc = c.get('total', 0)
res = c.get('reserve', 0)
dep = c.get('deployable', 0)
print('Cash:', tc, 'Res:', res, 'Dep:', dep, 'CalcDep:', tc-res)

h = facts.get('holdings', [])
reg = [h for h in facts.get('holdings', []) if 'direct' not in h.get('scheme', '').lower()]
rv2 = sum(h.get('value', 0) for h in facts.get('holdings', []) if 'direct' not in h.get('scheme', '').lower())
print('RegularVal2:', rv2)