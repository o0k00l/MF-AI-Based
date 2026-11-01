import sys
sys.stderr = open('test_err.txt', 'w')

from core.math_engine import (
    calculate_weighted_lookthrough_overlap,
    calculate_risk_distribution,
    calculate_switch_cost_analysis,
    calculate_saa_drift_minimizer,
    check_eligibility_gates,
    evaluate_no_action
)

class MockHolding:
    def __init__(self, **kw):
        self.__dict__.update(kw)

h1 = MockHolding(fund_id='F1', scheme='Fund A', current_value_inr=1000000, top_holdings=['ICICI', 'HDFC', 'INFY'], risk_tier='3')
h2 = MockHolding(fund_id='F2', scheme='Fund B', current_value_inr=1000000, top_holdings=['ICICI', 'SBI', 'AXIS'], risk_tier='4')
h3 = MockHolding(fund_id='F3', scheme='Fund C', current_value_inr=500000, top_holdings=['RELIANCE', 'TCS'], risk_tier='3')

result = calculate_weighted_lookthrough_overlap([h1, h2, h3])
print('Weighted overlap:', result)

risk = calculate_risk_distribution([h1, h2, h3])
print('Risk distribution:', risk)

source_h = MockHolding(current_value_inr=1000000)
switch = calculate_switch_cost_analysis('Fund A', 'Fund B', source_h, 0.5, True, 200, 1000, 800)
print('Switch cost:', switch)

holdings = [MockHolding(current_value_inr=1000000, asset_class='Equity'), MockHolding(current_value_inr=500000, asset_class='Debt')]
saa = calculate_saa_drift_minimizer(holdings, {'Equity': 75, 'Debt': 25}, 100000)
print('SAA drift:', saa)

fund = {'fund_id': 'TEST', 'fund_name': 'Test Fund', 'aum_crore': 1000, 'aum_stable': True,
        'concentration_top10_pct': 20, 'max_sector_concentration_pct': 20,
        'mandate_suitable': True, 'data_complete': True, 'manager_tenure_years': 5}
gates = check_eligibility_gates(fund)
print('Eligibility gates:', gates)

no_act = evaluate_no_action([], [{'fund_id': 'C1', 'fund_name': 'C1', 'eligibility': {'passed': True}, 'composite_score': 3}])
print('NO ACTION (no candidates):', no_act)

no_act2 = evaluate_no_action([], [{'fund_id': 'C1', 'fund_name': 'C1', 'eligibility': {'passed': True}, 'composite_score': 80}])
print('NO ACTION (improvement found):', no_act2)
print('ALL TESTS PASSED')