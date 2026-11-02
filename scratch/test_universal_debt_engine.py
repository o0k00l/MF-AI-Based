import json
from pathlib import Path

def get_tier_saa_targets(tier_num: int):
    # (Target Debt, Tolerance Band, Baseline SIP Debt Allocation)
    if tier_num == 6:
        return 5.0, 5.0, 0.0
    elif tier_num == 5:
        return 10.0, 5.0, 5.0
    elif tier_num == 4:
        return 15.0, 5.0, 15.0
    elif tier_num == 3:
        return 30.0, 5.0, 40.0
    elif tier_num == 2:
        return 60.0, 4.0, 70.0
    else: # Tier 1
        return 80.0, 3.0, 100.0

def calculate_universal_tier_split(tier_num: int, stability_buffer_pct: float = None):
    target_debt, tol, default_sip_debt = get_tier_saa_targets(tier_num)
    if stability_buffer_pct is not None and stability_buffer_pct > 0:
        threshold = max(0.0, target_debt - tol)
        if stability_buffer_pct >= threshold:
            debt_pct = 0.0
        else:
            net_gap = round(target_debt - stability_buffer_pct, 1)
            debt_pct = min(default_sip_debt, net_gap)
    else:
        debt_pct = default_sip_debt
    eq_pct = round(100.0 - debt_pct, 1)
    return eq_pct, debt_pct

print("=== LALIT PORTFOLIO (Stability Buffer = 7.54%) ===")
for t in range(6, 0, -1):
    eq, debt = calculate_universal_tier_split(t, 7.54)
    print(f"Tier {t}: Equity = {eq}%, Debt = {debt}%")

print("\n=== DEFICIENT BUFFER (Stability Buffer = 2.0%) ===")
for t in range(6, 0, -1):
    eq, debt = calculate_universal_tier_split(t, 2.0)
    print(f"Tier {t}: Equity = {eq}%, Debt = {debt}%")

print("\n=== ZERO BUFFER / STARTER (Stability Buffer = 0.0%) ===")
for t in range(6, 0, -1):
    eq, debt = calculate_universal_tier_split(t, 0.0)
    print(f"Tier {t}: Equity = {eq}%, Debt = {debt}%")

