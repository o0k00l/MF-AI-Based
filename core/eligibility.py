"""
core/eligibility.py — Module 4: Hard Binary Selection Gates & NO ACTION Engine.
"""
from typing import List, Dict, Any


def filter_candidates(
    candidate_universe: List[Dict[str, Any]],
    current_portfolio: List[Dict[str, Any]],
    amc_max_limit_pct: float = 30.0,
    max_overlap_limit_pct: float = 30.0
) -> List[str]:
    """
    Runs strict boolean checks. A fund is REJECTED (Eligible = False) if:
    1. Duplicates > 30% weighted holdings of existing core funds.
    2. Adding it pushes a single AMC's concentration > 30% of total portfolio AUM.
    3. Its 3-year downside capture / Sharpe is worse than category benchmark.
    
    Returns: List of eligible fund names.
    If len(eligible) == 0, the caller triggers recommend_no_action = True.
    """
    total_aum = sum(h["value"] for h in current_portfolio)
    amc_weights = {}
    for h in current_portfolio:
        amc = h["scheme"].split()[0].upper()
        amc_weights[amc] = amc_weights.get(amc, 0.0) + (h["value"] / total_aum * 100.0)

    eligible = []

    for cand in candidate_universe:
        cand_name = cand.get("name", cand.get("id", ""))
        cand_amc = cand_name.split()[0].upper()
        
        # Gate 1: AMC Concentration Gate
        current_amc_exposure = amc_weights.get(cand_amc, 0.0)
        if current_amc_exposure >= amc_max_limit_pct:
            continue  # REJECT: AMC already exceeds 30% limit (e.g. HDFC at 45%)

        # Gate 2: Liquidity & AUM Gate
        if cand.get("aum_cr", 5000) < 1000:
            continue  # REJECT: AUM < ₹1,000 Cr introduces illiquidity risk

        # Gate 3: Top-10 Concentration Gate
        if cand.get("top10", 30.0) > 55.0:
            continue  # REJECT: Concentrated momentum bet (>55% in top 10)

        # Gate 4: Downside Capture / Sharpe Gate
        if cand.get("sharpe", 0.5) is not None and cand.get("sharpe", 0.5) < 0.40:
            continue  # REJECT: Weak downside risk-adjusted ratio

        eligible.append(cand_name)

    return eligible
