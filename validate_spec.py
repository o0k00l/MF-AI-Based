# Validation script for specification compliance
import inspect
from pathlib import Path

# Test imports
try:
    from core.math_engine import (
        parse_cas, calculate_fee_bleed, calculate_risk_distribution, 
        compute_fifo_tax_lots, calculate_overlap_matrix, compute_liquidity_waterfall
    )
    from core.eligibility import filter_candidates
    from core.models import FeeBleed, OverlapMetric, TaxLedger, FiduciaryPayload
    print("✅ All imports successful")
except Exception as e:
    print(f"❌ Import error: {e}")
    exit(1)

print("=== FUNCTION SIGNATURE VALIDATION ===")

# Check parse_cas
sig = inspect.signature(parse_cas)
print(f"parse_cas: {sig}")
params = list(sig.parameters.keys())
if 'xlsx_path' in params:
    print("  ✅ Has xlsx_path parameter")
else:
    print("  ❌ Missing xlsx_path parameter")

# Check calculate_fee_bleed
sig = inspect.signature(calculate_fee_bleed)
print(f"calculate_fee_bleed: {sig}")
params = list(sig.parameters.keys())
if 'holdings' in params and 'default_delta_ter' in params:
    print("  ✅ Has holdings and default_delta_ter parameters")
else:
    print("  ❌ Missing expected parameters")

# Check calculate_risk_distribution
sig = inspect.signature(calculate_risk_distribution)
print(f"calculate_risk_distribution: {sig}")
params = list(sig.parameters.keys())
if 'holdings' in params:
    print("  ✅ Has holdings parameter")
else:
    print("  ❌ Missing holdings parameter")

# Check compute_liquidity_waterfall
sig = inspect.signature(compute_liquidity_waterfall)
print(f"compute_liquidity_waterfall: {sig}")
params = list(sig.parameters.keys())
if 'bank_balance' in params and 'monthly_expenses' in params and 'months_reserve' in params:
    print("  ✅ Has expected parameters")
else:
    print("  ❌ Missing expected parameters")

# Check compute_fifo_tax_lots
sig = inspect.signature(compute_fifo_tax_lots)
print(f"compute_fifo_tax_lots: {sig}")
params = list(sig.parameters.keys())
if 'transactions' in params and 'holdings' in params and 'as_of_date' in params:
    print("  ✅ Has expected parameters")
else:
    print("  ❌ Missing expected parameters")

# Check filter_candidates
sig = inspect.signature(filter_candidates)
print(f"filter_candidates: {sig}")
params = list(sig.parameters.keys())
expected = ['candidate_universe', 'current_portfolio', 'amc_max_limit_pct', 'max_overlap_limit_pct']
if all(p in params for p in expected):
    print("  ✅ Has all expected parameters")
else:
    print(f"  ❌ Missing parameters. Has: {params}")

print("\n=== MODEL VALIDATION ===")
try:
    from core.models import FeeBleed, OverlapMetric, TaxLedger, FiduciaryPayload
    
    fb = FeeBleed(annual_bleed_inr=1000, regular_funds_count=2)
    print(f"FeeBleed: ✅")
except Exception as e:
    print(f"FeeBleed: ❌ {e}")

try:
    om = OverlapMetric(fund_pair='A vs B', weighted_overlap_pct=25.0)
    print(f"OverlapMetric: ✅")
except Exception as e:
    print(f"OverlapMetric: ❌ {e}")

try:
    tl = TaxLedger(immature_locked_value_inr=100000, mature_switchable_value_inr=200000, projected_ltcg_inr=50000, stagger_required=True)
    print(f"TaxLedger: ✅")
except Exception as e:
    print(f"TaxLedger: ❌ {e}")

try:
    fp = FiduciaryPayload(
        portfolio_valuation_date='2024-10-09',
        total_aum_inr=5000000,
        deployable_cash_surplus_inr=100000,
        risk_distribution_pct={'Tier 6': 40},
        fee_bleed=FeeBleed(annual_bleed_inr=40000, regular_funds_count=14),
        top_overlaps=[OverlapMetric(fund_pair='A vs B', weighted_overlap_pct=30)],
        tax_ledger=TaxLedger(immature_locked_value_inr=100000, mature_switchable_value_inr=200000, projected_ltcg_inr=50000, stagger_required=True),
        eligible_new_funds=['Fund A'],
        recommend_no_action=False
    )
    print(f"FiduciaryPayload: ✅")
except Exception as e:
    print(f"FiduciaryPayload: ❌ {e}")

print("\n=== SPEC COMPLIANCE CHECK ===")
print("Original spec required:")
print("  - FeeBleed(annual_bleed_inr, regular_funds_count)")
print("  - OverlapMetric(fund_pair, weighted_overlap_pct)")
print("  - TaxLedger(immature_locked_value_inr, mature_switchable_value_inr, projected_ltcg_inr, stagger_required)")
print("  - FiduciaryPayload with all fields")
print("  - parse_cas(xlsx_path) -> Tuple[str, List[Dict]]")
print("  - calculate_fee_bleed(holdings, default_delta_ter=1.0) -> Tuple[float, int]")
print("  - calculate_risk_distribution(holdings) -> Dict[str, float]")
print("  - compute_liquidity_waterfall(bank_balance, monthly_expenses, months_reserve=6.0) -> Tuple[float, float]")
print("  - compute_fifo_tax_lots(transactions, holdings, as_of_date) -> Dict")
print("  - filter_candidates(candidate_universe, current_portfolio, amc_max_limit_pct=30.0, max_overlap_limit_pct=30.0) -> List[str]")
print("  - generate_fiduciary_report(payload) -> str (in prompt_advisor)")
print("  - advisor.py CLI with --no-ai, --chat, --stress, --query")