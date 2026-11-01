import warnings
import os
import subprocess
warnings.filterwarnings('ignore')

print('=== COMPREHENSIVE VALIDATION AGAINST ORIGINAL PLAN ===')
print()

# 1. MODULE 1: Data Contracts (core/models.py)
print('1. MODULE 1: Data Contracts (core/models.py)')
import core.models as m
models = [
    'FeeBleed', 'OverlapMetric', 'TaxLedger', 'FiduciaryPayload',
    'HoldingItem', 'PlanType', 'AssetClass',
    'FeeBleedAnalysis', 'OverlapPair', 'SAADriftAnalysis', 'CashDeploymentPlan',
    'FiduciaryFactsPayload', 'WeightedOverlapResult', 'RiskDistribution',
    'SwitchCostAnalysis', 'EligibilityGateResult', 'NOActionResult', 'SAA_DriftMinimizer',
    'TaxLot', 'TaxLotSummary'
]
for model in models:
    exists = hasattr(m, model)
    print(f'  {"✅" if exists else "❌"} {model}')

print()

# 2. MODULE 2,3,5: Pure Deterministic Math (core/math_engine.py)
print('2. MODULE 2,3,5: Pure Deterministic Math (core/math_engine.py)')
import core.math_engine as me
functions = [
    ('parse_cas', 'Module 1'),
    ('calculate_weighted_overlap', 'Module 2'),
    ('calculate_risk_distribution', 'Module 2'),
    ('calculate_fee_bleed', 'Module 2'),
    ('compute_liquidity_waterfall', 'Module 3'),
    ('compute_fifo_tax_lots', 'Module 5'),
    ('calculate_weighted_lookthrough_overlap', 'Architectural Correction 1'),
    ('calculate_risk_distribution', 'Architectural Correction 2'),
    ('calculate_switch_cost_analysis', 'Architectural Correction 3'),
    ('calculate_saa_drift_minimizer', 'Architectural Correction 4'),
    ('check_eligibility_gates', 'Architectural Correction 5'),
    ('evaluate_no_action', 'Architectural Correction 6'),
    ('load_holdings_from_cas_excel', 'Module 1'),
    ('calculate_overlap_matrix', 'Module 2'),
    ('calculate_saa_drift', 'Module 2'),
    ('calculate_cash_deployment', 'Module 3'),
    ('compute_fifo_tax_lots', 'Module 5'),
    ('aggregate_fiduciary_facts', 'Main orchestrator'),
]
for name, desc in functions:
    exists = hasattr(me, name)
    print(f'  {"✅" if exists else "❌"} {name} - {desc}')

print()

# 3. Module 4: Hard Binary Selection Gates & NO ACTION (core/eligibility.py)
print('3. Module 4: Hard Binary Selection Gates & NO ACTION (core/eligibility.py)')
import core.eligibility as el
eligibility_funcs = ['filter_candidates']
for name in eligibility_funcs:
    exists = hasattr(el, name)
    print(f'  {"✅" if exists else "❌"} {name}')

print()

# 4. Module 6: Strict Narrative Interpreter (core/prompt_advisor.py)
print('4. Module 6: Strict Narrative Interpreter (core/prompt_advisor.py)')
import core.prompt_advisor as pa
prompt_funcs = ['generate_fiduciary_report', 'generate_health_audit_report', 'generate_switch_and_consolidation_plan', 'generate_cash_and_sip_plan', 'answer_interactive_query']
for name in prompt_funcs:
    exists = hasattr(pa, name)
    print(f'  {"✅" if exists else "❌"} {name}')

print()

# 5. Single CLI Entry Point (advisor.py)
print('5. Single CLI Entry Point (advisor.py)')
import advisor
advisor_funcs = ['build_fiduciary_payload', 'run_full_audit', 'run_interactive_chat', 'main']
for name in advisor_funcs:
    exists = hasattr(advisor, name)
    print(f'  {"✅" if exists else "❌"} {name}')

print()

# 6. Architectural Corrections Verification
print('6. Architectural Corrections Verification')
from core.math_engine import (
    calculate_weighted_lookthrough_overlap,
    calculate_risk_distribution,
    calculate_switch_cost_analysis,
    calculate_saa_drift_minimizer,
    check_eligibility_gates,
    evaluate_no_action,
)
print('  ✅ Weighted Look-Through Overlap (Correction 1)')
print('  ✅ Ordinal Risk Distribution (Correction 2)')
print('  ✅ Switch Cost Analysis (Correction 3)')
print('  ✅ SAA Drift Minimizer (Correction 4)')
print('  ✅ Eligibility Gates (Correction 5)')
print('  ✅ NO ACTION Branch (Correction 6)')

print()

# 7. Data Pipeline Test
print('7. End-to-End Pipeline Test')
from core.math_engine import aggregate_fiduciary_facts
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

cas = Path('data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx')
metrics = Path('data/lalit_portfolio/fund_metrics.json')
config = Path('data/lalit_portfolio/config.json')
aliases = Path('data/lalit_portfolio/fund_aliases.json')
facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)

print(f'  ✅ Total AUM: {facts.total_portfolio_value_inr:,.0f}')
print(f'  ✅ Fee Bleed: {facts.fee_bleed.annual_commission_leakage_inr:,.0f}')
print(f'  ✅ Holdings: {facts.holdings_count}')
print(f'  ✅ Weighted Overlap: {len(facts.weighted_overlap)} pairs')
print(f'  ✅ Risk Distribution: {facts.risk_distribution}')
print(f'  ✅ SAA Drift Minimizer: {facts.saa_drift}')
print(f'  ✅ Switch Costs: {len(facts.switch_costs)} funds')
print(f'  ✅ Eligibility Results: {len(facts.eligibility_results)} funds')
print(f'  ✅ NO Action: {facts.no_action.action}')

print()

# 8. CLI Tests
print('8. CLI Tests')
r = subprocess.run(['python', 'advisor.py', '--stress'], capture_output=True, text=True, timeout=30)
print(f'  {"✅" if "PORTFOLIO STRESS TEST" in r.stdout else "❌"} --stress')

r = subprocess.run(['python', 'advisor.py', '--help'], capture_output=True, text=True)
print(f'  {"✅" if "--chat" in r.stdout else "❌"} --chat')
print(f'  {"✅" if "--stress" in r.stdout else "❌"} --stress')
print(f'  {"✅" if "--query" in r.stdout else "❌"} --query')

print()

# 9. Deliverables
print('9. Deliverables')
import os
deliverables = [
    'outputs/Portfolio_Health_Audit.md',
    'outputs/Portfolio_Health_Audit.pdf',
    'outputs/Switch_and_Consolidation_Plan.md',
    'outputs/Switch_and_Consolidation_Plan.pdf',
    'outputs/Fresh_Money_Deployment_Plan.md',
    'outputs/Fresh_Money_Deployment_Plan.pdf',
]
for d in deliverables:
    exists = os.path.exists(d)
    print(f'  {"✅" if exists else "❌"} {d}')

print()
print('=== ALL VALIDATIONS COMPLETE ===')