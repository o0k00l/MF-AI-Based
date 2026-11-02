from pathlib import Path
from core.eligibility import load_candidate_universe, check_eligibility_gates
from core.math_engine import load_holdings_from_cas_excel, find_client_direct_folio

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

print(f"Total candidates loaded: {len(candidates)}")

# Test Flexi Cap
flexi_cands = [c for c in candidates if "flexi" in c.get("category", "").lower()]
print(f"Flexi candidates: {[c['fund_name'] for c in flexi_cands]}")
for c in flexi_cands:
    g = check_eligibility_gates(c, holdings, client_risk_tier_num=6)
    s = compute_multi_horizon_fiduciary_score(c)
    print(f"  - {c['fund_name']}: Score={s} | Passed={g.passed}")

# Test Mid Cap
mid_cands = [c for c in candidates if "mid" in c.get("category", "").lower() and "large" not in c.get("category", "").lower() and "multi" not in c.get("category", "").lower()]
print(f"\nMid candidates: {[c['fund_name'] for c in mid_cands]}")
for c in mid_cands:
    g = check_eligibility_gates(c, holdings, client_risk_tier_num=6)
    s = compute_multi_horizon_fiduciary_score(c)
    print(f"  - {c['fund_name']}: Score={s} | Passed={g.passed} | AUM={c.get('aum_crore')}")

# Test Large Cap
large_cands = [c for c in candidates if "large" in c.get("category", "").lower() and "mid" not in c.get("category", "").lower() and "multi" not in c.get("category", "").lower()]
print(f"\nLarge candidates: {[c['fund_name'] for c in large_cands]}")
for c in large_cands:
    g = check_eligibility_gates(c, holdings, client_risk_tier_num=6)
    s = compute_multi_horizon_fiduciary_score(c)
    print(f"  - {c['fund_name']}: Score={s} | Passed={g.passed} | Alpha={c.get('alpha_3y')}")

# Test Healthcare
health_cands = [c for c in candidates if "health" in c.get("category", "").lower() or "pharma" in c.get("category", "").lower()]
print(f"\nHealthcare candidates: {[c['fund_name'] for c in health_cands]}")
for c in health_cands:
    g = check_eligibility_gates(c, holdings, client_risk_tier_num=6)
    s = compute_multi_horizon_fiduciary_score(c)
    print(f"  - {c['fund_name']}: Score={s} | Passed={g.passed} | 1Y={c.get('return_1y')}% | TER={c.get('ter_direct_pct')}%")

# Test Debt
debt_cands = [c for c in candidates if "debt" in c.get("category", "").lower()]
print(f"\nDebt candidates: {[c['fund_name'] for c in debt_cands]}")
for c in debt_cands:
    g = check_eligibility_gates(c, holdings, client_risk_tier_num=6)
    s = compute_multi_horizon_fiduciary_score(c)
    print(f"  - {c['fund_name']}: Score={s} | Passed={g.passed} | YTM={c.get('ytm_pct')}%")

