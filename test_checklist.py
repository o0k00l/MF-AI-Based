import json
from pathlib import Path
from core.eligibility import check_eligibility_gates, load_candidate_universe

metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
candidates = load_candidate_universe(metrics_path)

# Get healthcare funds
pharma_cands = {c["fund_id"]: c for c in candidates if "health" in c["fund_name"].lower() or "pharma" in c["fund_name"].lower()}
print("Healthcare funds found:", list(pharma_cands.keys()))

# Check gates for ICICI
if "ICICI Healthcare Direct" in pharma_cands:
    icici = pharma_cands["ICICI Healthcare Direct"]
    print("\nICICI Healthcare fund details:")
    print(f"  aum_crore: {icici.get('aum_crore')}")
    print(f"  category: {icici.get('category')}")
    print(f"  fund_name: {icici.get('fund_name')}")
    print(f"  is_direct: {icici.get('is_direct')}")
    print(f"  aum_stable: {icici.get('aum_stable')}")
    print(f"  sharpe_3y: {icici.get('sharpe_3y')}")
    print(f"  alpha_3y: {icici.get('alpha_3y')}")
    print(f"  downside_capture_ratio: {icici.get('downside_capture_ratio')}")
    print(f"  upside_capture_ratio: {icici.get('upside_capture_ratio')}")
    print(f"  manager_tenure_years: {icici.get('manager_tenure_years')}")
    print(f"  track_record_years: {icici.get('track_record_years')}")
    
    gate_result = check_eligibility_gates(icici, portfolio_holdings=[], client_risk_tier_num=6)
    print(f"\nGate result: passed={gate_result.passed}")
    print(f"Failed gates: {gate_result.failed_gates}")
    print(f"Details: {gate_result.details}")