from core.eligibility import check_eligibility_gates, load_candidate_universe
from pathlib import Path

metrics_path = Path('data/lalit_portfolio/fund_metrics.json')
candidates = load_candidate_universe(metrics_path)
pharma = [c for c in candidates if 'healthcare' in c.get('fund_name','').lower() or 'pharma' in c.get('fund_name','').lower()]
print('Pharma candidates:', len(pharma))
for c in pharma:
    gate = check_eligibility_gates(c, portfolio_holdings=None, client_risk_tier_num=6)
    print(' ', c.get('fund_name'), '| passed=', gate.passed, '| failed=', gate.failed_gates)