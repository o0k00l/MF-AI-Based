from core.math_engine import calculate_risk_distribution, check_eligibility_gates, evaluate_no_action
from core.models import HoldingItem, PlanType, AssetClass

h1 = HoldingItem(
    fund_id='F1', scheme='Fund A', fund_name='Fund A', folio='F1',
    is_direct=True, plan=PlanType.DIRECT, asset_class=AssetClass.EQUITY,
    equity_pct=95, debt_pct=5, hybrid_pct=0, international_pct=0,
    current_value_inr=1000000, invested_value_inr=800000, units=1000, nav=1000,
    top_holdings=['ICICI', 'HDFC'], risk_tier='3'
)

h2 = HoldingItem(
    fund_id='F2', scheme='Fund B', fund_name='Fund B', folio='F2',
    is_direct=True, plan=PlanType.DIRECT, asset_class=AssetClass.EQUITY,
    equity_pct=95, debt_pct=5, hybrid_pct=0, international_pct=0,
    current_value_inr=1000000, invested_value_inr=800000, units=1000, nav=1000,
    top_holdings=['ICICI', 'SBI'], risk_tier='4'
)

risk = calculate_risk_distribution([h1, h2])
print('Risk distribution:', risk)

fund_data = {
    'fund_id': 'TEST', 'fund_name': 'Test', 'aum_crore': 1000,
    'aum_stable': True, 'concentration_top10_pct': 20,
    'max_sector_concentration_pct': 20, 'mandate_suitable': True,
    'data_complete': True, 'manager_tenure_years': 5
}
gates = check_eligibility_gates(fund_data)
print('Eligibility:', gates)

no_action = evaluate_no_action(
    [h1, h2],
    [{'fund_id': 'C1', 'fund_name': 'C1', 'eligibility': {'passed': True}, 'composite_score': 70}]
)
print('NO Action:', no_action)