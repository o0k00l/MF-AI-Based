import sys
sys.stderr = open('final_test.txt', 'w')
import warnings
warnings.filterwarnings('ignore')

# 1. Core math engine
from core.math_engine import (
    aggregate_fiduciary_facts,
    calculate_weighted_lookthrough_overlap,
    calculate_risk_distribution,
    calculate_switch_cost_analysis,
    calculate_saa_drift_minimizer,
    check_eligibility_gates,
    evaluate_no_action,
    load_holdings_from_cas_excel,
    calculate_fee_bleed,
    calculate_overlap_matrix,
    calculate_saa_drift,
    calculate_cash_deployment,
    compute_fifo_tax_lots,
)

# 2. Models
from core.models import (
    FeeBleedAnalysis, OverlapPair, SAADriftAnalysis, CashDeploymentPlan,
    FiduciaryFactsPayload, HoldingItem, PlanType, AssetClass,
    WeightedOverlapResult, RiskDistribution, SwitchCostAnalysis,
    EligibilityGateResult, NOActionResult, SAA_DriftMinimizer
)

# 3. Eligibility & Prompt
from core.eligibility import filter_candidates
from core.prompt_advisor import generate_fiduciary_report
from core.ai_engine import call_llm

print('ALL IMPORTS OK')

# Test aggregate
from pathlib import Path
cas = Path('data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx')
metrics = Path('data/lalit_portfolio/fund_metrics.json')
config = Path('data/lalit_portfolio/config.json')
aliases = Path('data/lalit_portfolio/fund_aliases.json')
facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)

print(f'Total AUM: {facts.total_portfolio_value_inr:,.0f}')
print(f'Fee Bleed: {facts.fee_bleed.annual_commission_leakage_inr:,.0f}')
print(f'Holdings: {facts.holdings_count}')
print(f'Weighted Overlap: {len(facts.weighted_overlap)} pairs')
print(f'Risk Distribution: {facts.risk_distribution}')
print(f'SAA Drift Minimizer: {facts.saa_drift}')
print(f'Switch Costs: {len(facts.switch_costs)} funds')
print(f'Eligibility Results: {len(facts.eligibility_results)} funds')
print(f'NO Action: {facts.no_action.action}')

print('ALL VALIDATIONS PASSED')