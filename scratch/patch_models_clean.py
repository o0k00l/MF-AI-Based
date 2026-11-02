with open("core/models.py", "r", encoding="utf-8") as f:
    text = f.read()

# Add cas_reconciliation to FiduciaryFactsPayload
target_payload = """    deterministic_sip_plan: Optional[DeterministicSIPPlan] = None
    deterministic_lumpsum_plan: Optional[DeterministicLumpsumPlan] = None"""

replacement_payload = """    deterministic_sip_plan: Optional[DeterministicSIPPlan] = None
    deterministic_lumpsum_plan: Optional[DeterministicLumpsumPlan] = None
    cas_reconciliation: Optional[Dict[str, Any]] = None"""

assert target_payload in text, "target_payload not found"
text = text.replace(target_payload, replacement_payload, 1)

# Clean up circular imports in backward compatibility aliases
target_compat = """# Backward compatibility function aliases
def build_fiduciary_payload(*args, **kwargs):
    \"\"\"Backward compatibility alias for aggregate_fiduciary_facts.\"\"\"
    from core.math_engine import aggregate_fiduciary_facts
    return aggregate_fiduciary_facts(*args, **kwargs)

def calculate_weighted_overlap(fund_a_holdings: Dict[str, float], fund_b_holdings: Dict[str, float]) -> float:
    \"\"\"Backward compatibility alias for calculate_weighted_lookthrough_overlap (pairwise version).\"\"\"
    from core.math_engine import calculate_weighted_lookthrough_overlap
    # This is a simplified pairwise version for backward compatibility
    shared_stocks = set(fund_a_holdings.keys()) & set(fund_b_holdings.keys())
    overlap_weight = sum(min(fund_a_holdings[s], fund_b_holdings[s]) for s in shared_stocks)
    return round(overlap_weight, 2)

def compute_liquidity_waterfall(bank_balance: float, monthly_expenses: float, months_reserve: float = 6.0) -> Tuple[float, float]:
    \"\"\"Backward compatibility alias for calculate_cash_deployment (returns tuple).\"\"\"
    from core.math_engine import calculate_cash_deployment
    from core.models import CashDeploymentPlan
    result = calculate_cash_deployment(bank_cash_inr=bank_balance, emergency_buffer_inr=monthly_expenses * months_reserve)
    return result.emergency_reserve_inr, result.deployable_surplus_inr"""

replacement_compat = """# Self-contained backward compatibility calculation functions (Zero circular imports)
def calculate_weighted_overlap(fund_a_holdings: Dict[str, float], fund_b_holdings: Dict[str, float]) -> float:
    \"\"\"Self-contained pairwise weighted overlap calculation.\"\"\"
    shared_stocks = set(fund_a_holdings.keys()) & set(fund_b_holdings.keys())
    overlap_weight = sum(min(fund_a_holdings[s], fund_b_holdings[s]) for s in shared_stocks)
    return round(overlap_weight, 2)

def compute_liquidity_waterfall(bank_balance: float, monthly_expenses: float, months_reserve: float = 6.0) -> Tuple[float, float]:
    \"\"\"Self-contained cash deployment liquidity calculation.\"\"\"
    emergency_reserve = monthly_expenses * months_reserve
    deployable_surplus = max(0.0, bank_balance - emergency_reserve)
    return round(emergency_reserve, 2), round(deployable_surplus, 2)"""

assert target_compat in text, "target_compat not found"
text = text.replace(target_compat, replacement_compat, 1)

with open("core/models.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully updated core/models.py: added cas_reconciliation and eliminated circular imports")

