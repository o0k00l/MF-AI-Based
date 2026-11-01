import warnings
warnings.filterwarnings('ignore')
from core.math_engine import calculate_switch_cost_analysis
from core.models import HoldingItem, PlanType, AssetClass

h = HoldingItem(
    fund_id='TEST_FUND',
    scheme='Test Fund',
    fund_name='Test Fund',
    folio='F1',
    is_direct=False,
    plan=PlanType.REGULAR,
    asset_class=AssetClass.EQUITY,
    equity_pct=95.0,
    debt_pct=5.0,
    hybrid_pct=0.0,
    international_pct=0.0,
    current_value_inr=1000000.0,
    invested_value_inr=800000.0,
    units=1000.0,
    nav=1000.0,
    top_holdings=['ICICI', 'HDFC'],
    expense_ratio_pct=1.5,
    risk_tier='3'
)

switch = calculate_switch_cost_analysis(
    source_fund='TEST_FUND',
    target_fund='TEST_FUND Direct',
    source_holding=h,
    target_fund_ter=0.5,
    is_intra_amc=True,
    holding_period_days=200,
    current_nav=1000.0,
    purchase_nav=800.0
)
print('Switch cost:', switch)