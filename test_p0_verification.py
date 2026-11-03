from core.math_engine import select_autonomous_blueprint_funds
from core.eligibility import load_candidate_universe
from pathlib import Path

# Test 1: Thematic ceiling enforcement
metrics_path = Path('data/lalit_portfolio/fund_metrics.json')
candidates = load_candidate_universe(metrics_path)
blueprint = select_autonomous_blueprint_funds(candidate_universe=candidates, thematic_deficit_theme='Healthcare')
slot4 = blueprint['Slot 4: Tactical Thematic Satellite']
print('=== Thematic Ceiling Test ===')
print(f'Scheme: {slot4["scheme"]}')
print(f'Ceiling Guard: {slot4.get("ceiling_guard", {})}')
print()

# Test 2: Benchmark freshness
from core.math_engine import aggregate_fiduciary_facts
from pathlib import Path
cas = Path('data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx')
metrics = Path('data/lalit_portfolio/fund_metrics.json')
config = Path('data/lalit_portfolio/config.json')
aliases = Path('data/lalit_portfolio/fund_aliases.json')
from core.math_engine import aggregate_fiduciary_facts
facts = aggregate_fiduciary_facts(cas, metrics, config, Path('data/lalit_portfolio/fund_aliases.json'))
print('=== Benchmark Freshness Test ===')
print(f'Benchmark XIRR: {facts.benchmark_xirr_pct}')
print(f'Alpha: {facts.alpha_pct}')
print()

# Test 3: Passive fallback consistency
print('=== Passive Fallback Test (empty universe) ===')
from core.math_engine import select_autonomous_blueprint_funds
empty_bp = select_autonomous_blueprint_funds(candidate_universe=[])
for k, v in empty_bp.items():
    print(f'{k}: {v["scheme"]} (gate={v["gate_passed"]})')