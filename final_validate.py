import json, subprocess

result = subprocess.run(['python', 'advisor_lean.py', '--no-ai'], capture_output=True, text=True, timeout=30)
facts = json.loads(result.stdout)

print('=== CORE VALIDATION ===')
print('Total Value:', facts.get('total_value'))
print('Invested:', facts.get('invested'))
print('Gain:', facts.get('gain'))
print('XIRR:', facts.get('xirr_pct'))
print('Benchmark:', facts.get('benchmark_xirr_pct'))
print('Alpha:', facts.get('alpha_pct'))
print('Fee Bleed:', facts.get('fee_bleed',{}).get('annual_bleed'))
print('Regular Funds:', facts.get('fee_bleed',{}).get('n_funds'))
print('Overlap:', facts.get('overlap',{}).get('avg_overlap'))
print('SAA Breach:', facts.get('saa',{}).get('breach'))
print('Cash Deployable:', facts.get('cash',{}).get('deployable'))
print('Holdings:', len(facts.get('holdings',[])))
regular = [h for h in facts.get('holdings',[]) if 'direct' not in h.get('scheme','').lower()]
print('Regular Funds:', len(regular))
print('XIRR:', facts.get('xirr_pct'))
print('Benchmark:', facts.get('benchmark_xirr_pct'))
print('Alpha:', facts.get('alpha_pct'))