import json
with open('data/lalit_portfolio/transactions.json') as f:
    d = json.load(f)
txns = d.get('transactions', [])
real_txns = [t for t in txns if t.get('amount', 0) > 0 and t.get('units', 0) > 0]
print(f'Total: {len(txns)}')
print(f'Real txns (amount>0, units>0): {len(real_txns)}')
for t in real_txns[:10]:
    print(t)