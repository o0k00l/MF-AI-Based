from pathlib import Path
from core.eligibility import load_candidate_universe, check_eligibility_gates
from core.math_engine import load_holdings_from_cas_excel

cas_path = Path("data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx")
metrics_path = Path("data/lalit_portfolio/fund_metrics.json")

holdings = load_holdings_from_cas_excel(cas_path)
candidates = load_candidate_universe(metrics_path)

def compute_multi_horizon_fiduciary_score(c):
    alpha_3y = float(c.get("alpha_3y", c.get("alpha", 0.0)) or 0.0)
    sharpe_3y = float(c.get("sharpe_3y", c.get("sharpe", 0.5)) or 0.5)
    sharpe_1y = float(c.get("sharpe_1y", 0.5) or 0.5)
    ret_1y = float(c.get("return_1y", c.get("ret_1y", 0.0)) or 0.0)
    ret_6m = float(c.get("return_6m", c.get("ret_6m", 0.0)) or 0.0)
    ter = float(c.get("er", c.get("ter_direct_pct", 0.75)) or 0.75)
    top10 = float(c.get("top10_concentration_pct", c.get("top10", 40.0)) or 40.0)
    conc_penalty = max(0.0, top10 - 40.0) * 0.15

    score = (alpha_3y * 8.0) + (sharpe_3y * 15.0) + (sharpe_1y * 10.0) + (ret_1y * 5.0) + (ret_6m * 3.0) - (ter * 25.0) - conc_penalty
    return round(score, 2)

pharma_cands = [
    c for c in candidates
    if any(kw in c.get("category", "").lower() or kw in c.get("fund_name", "").lower() for kw in ("pharma", "health"))
]

print(f"Found {len(pharma_cands)} pharma/healthcare candidates:")
for c in pharma_cands:
    g = check_eligibility_gates(c, holdings, client_risk_tier_num=6)
    score = compute_multi_horizon_fiduciary_score(c)
    print(f"- {c['fund_name']}: Score={score:.2f} | 1Y Ret={c.get('return_1y')}% | 3Y CAGR={c.get('return_3y')}% | 3Y Sharpe={c.get('sharpe_3y')} | TER={c.get('ter_direct_pct')}% | Gates Passed={g.passed}")

