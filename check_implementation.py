import warnings
warnings.filterwarnings('ignore')
from core.math_engine import (
    calculate_weighted_lookthrough_overlap,
    calculate_risk_distribution,
    calculate_switch_cost_analysis,
    calculate_saa_drift_minimizer,
    check_eligibility_gates,
    evaluate_no_action,
    aggregate_fiduciary_facts,
    compute_fifo_tax_lots
)
from core.eligibility import filter_candidates
from core.models import (
    FeeBleedAnalysis, OverlapPair, SAADriftAnalysis, CashDeploymentPlan,
    FiduciaryFactsPayload, HoldingItem, PlanType, AssetClass,
    WeightedOverlapResult, RiskDistribution, SwitchCostAnalysis,
    EligibilityGateResult, NOActionResult, SAA_DriftMinimizer
)
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

cas = Path('data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx')
metrics = Path('data/lalit_portfolio/fund_metrics.json')
config = Path('data/lalit_portfolio/config.json')
aliases = Path('data/lalit_portfolio/fund_aliases.json')
facts = aggregate_fiduciary_facts(cas, metrics, config, Path('data/lalit_portfolio/fund_aliases.json'))

print('=== ACTUAL IMPLEMENTATION STATUS ===')
print(f'Weighted Overlap pairs: {len(facts.weighted_overlap)}')
print(f'Risk Distribution: {facts.risk_distribution}')
print(f'SAA Drift Minimizer: {facts.saa_drift}')
print(f'Switch Costs: {len(facts.switch_costs)} funds')
print(f'Eligibility Results: {len(facts.eligibility_results)} funds')
print(f'NO Action: {facts.no_action.action}')

print()
print('Switch Costs sample:')
for sc in facts.switch_costs[:3]:
    print(f'  {sc["fund_name"]}: cost={sc["switch_cost_inr"]}, pct={sc["switch_cost_pct"]}%')

print()
print('Eligibility gates sample:')
for eg in facts.eligibility_results[:3]:
    print(f'  {eg["fund_id"]}: passed={eg["passed"]}, failed={eg["failed_gates"]}')

print()
print('NO Action:', facts.no_action)
print()
print('SAA Drift Minimizer:', facts.saa_drift)
print()
print('Risk Distribution:', facts.risk_distribution)
print()
print('Weighted Overlap sample:')
for w in facts.weighted_overlap[:3]:
    print(f'  {w.fund_a} vs {w.fund_b}: {w.weighted_overlap_pct}% ({w.verdict})')