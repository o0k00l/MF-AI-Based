import json
data = json.load(open('data/lalit_portfolio/fund_metrics.json'))
for f in data.get('funds', []):
    fid = f.get('id', '')
    cat = f.get('category', f.get('cat', ''))
    aum = f.get('aum_crore', f.get('aum_cr', 0))
    er = f.get('ter_direct_pct', f.get('er', 0))
    sharpe = f.get('sharpe_3y', f.get('sharpe', None))
    alpha = f.get('alpha', None)
    print(f"{fid:<35} | cat: {cat:<20} | aum: {aum:>8} | er: {er} | sharpe: {sharpe} | alpha: {alpha}")
