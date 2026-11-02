import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typing import List, Dict, Any, Optional

def compute_all_levels_sip_blueprint(
    monthly_budget: float,
    risk_level: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    holdings: Optional[List[Any]] = None,
    client_aum: float = 5170000.0
):
    b = float(monthly_budget)
    is_starter = (client_aum > 0 and client_aum < 500000.0) or (b < 15000.0)
    
    # Normalize risk level key
    lvl = str(risk_level).lower()
    
    # 1. Determine Target Asset Allocation
    if "tier 6" in lvl or "level 6" in lvl or "very high" in lvl:
        # Tier 6: 95% Eq / 5% Debt
        # If stability cushion >= 5%, omit standalone debt SIP
        if stability_buffer_pct >= 5.0:
            target_eq, target_debt = 100.0, 0.0
        else:
            target_eq, target_debt = 95.0, 5.0
    elif "tier 5" in lvl or "level 5" in lvl or "growth" in lvl or "high" in lvl:
        target_eq, target_debt = 85.0, 15.0
    elif "tier 4" in lvl or "level 4" in lvl or "moderate high" in lvl:
        target_eq, target_debt = 70.0, 30.0
    elif "tier 3" in lvl or "level 3" in lvl or "moderate" in lvl:
        target_eq, target_debt = 50.0, 50.0
    elif "tier 2" in lvl or "level 2" in lvl or "low" in lvl:
        target_eq, target_debt = 20.0, 80.0
    else: # Tier 1
        target_eq, target_debt = 0.0, 100.0

    items = []
    
    # Schemes
    flexi_scheme = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
    mid_scheme = "Motilal Oswal Midcap Fund - Direct Plan Growth"
    large_scheme = "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"
    pharma_scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
    debt_scheme = "ICICI Prudential Short Term Fund - Direct Plan - Growth"

    if is_starter:
        # Starter client: Only 2 funds
        if target_eq > 0:
            flexi_pct = round(target_eq * 0.60, 1)
            mid_pct = round(target_eq * 0.40, 1)
            items.append({"role": "Core Flexi-Cap Compounder", "scheme": flexi_scheme, "pct": flexi_pct, "amount": round(b * flexi_pct / 100, 2)})
            items.append({"role": "Mid-Cap Alpha Engine", "scheme": mid_scheme, "pct": mid_pct, "amount": round(b * mid_pct / 100, 2)})
        if target_debt > 0:
            items.append({"role": "High-Grade Debt Anchor", "scheme": debt_scheme, "pct": target_debt, "amount": round(b * target_debt / 100, 2)})
    else:
        # Established client: 4-slot equity + debt if applicable
        if target_debt == 0.0:
            # 100% Equity (Tier 6 with stability cushion satisfied)
            items.append({"role": "Core Flexi-Cap Compounder", "scheme": flexi_scheme, "pct": 40.0, "amount": round(b * 0.40, 2)})
            items.append({"role": "Mid-Cap Alpha Engine", "scheme": mid_scheme, "pct": 30.0, "amount": round(b * 0.30, 2)})
            items.append({"role": "Large-Cap Bluechip Anchor", "scheme": large_scheme, "pct": 15.0, "amount": round(b * 0.15, 2)})
            items.append({"role": "Tactical Thematic Satellite", "scheme": pharma_scheme, "pct": 15.0, "amount": round(b * 0.15, 2)})
        elif target_debt == 15.0: # Tier 5 (85% Eq / 15% Debt)
            items.append({"role": "Core Flexi-Cap Compounder", "scheme": flexi_scheme, "pct": 35.0, "amount": round(b * 0.35, 2)})
            items.append({"role": "Mid-Cap Alpha Engine", "scheme": mid_scheme, "pct": 25.0, "amount": round(b * 0.25, 2)})
            items.append({"role": "Large-Cap Bluechip Anchor", "scheme": large_scheme, "pct": 15.0, "amount": round(b * 0.15, 2)})
            items.append({"role": "Tactical Thematic Satellite", "scheme": pharma_scheme, "pct": 10.0, "amount": round(b * 0.10, 2)})
            items.append({"role": "High-Grade Debt Cushion", "scheme": debt_scheme, "pct": 15.0, "amount": round(b * 0.15, 2)})
        elif target_debt == 30.0: # Tier 4 (70% Eq / 30% Debt)
            items.append({"role": "Core Flexi-Cap Compounder", "scheme": flexi_scheme, "pct": 30.0, "amount": round(b * 0.30, 2)})
            items.append({"role": "Mid-Cap Alpha Engine", "scheme": mid_scheme, "pct": 20.0, "amount": round(b * 0.20, 2)})
            items.append({"role": "Large-Cap Bluechip Anchor", "scheme": large_scheme, "pct": 10.0, "amount": round(b * 0.10, 2)})
            items.append({"role": "Tactical Thematic Satellite", "scheme": pharma_scheme, "pct": 10.0, "amount": round(b * 0.10, 2)})
            items.append({"role": "High-Grade Debt Anchor", "scheme": debt_scheme, "pct": 30.0, "amount": round(b * 0.30, 2)})
        elif target_debt == 50.0: # Tier 3 (50% Eq / 50% Debt)
            items.append({"role": "Core Flexi-Cap Compounder", "scheme": flexi_scheme, "pct": 25.0, "amount": round(b * 0.25, 2)})
            items.append({"role": "Large-Cap Bluechip Anchor", "scheme": large_scheme, "pct": 15.0, "amount": round(b * 0.15, 2)})
            items.append({"role": "Mid-Cap Alpha Engine", "scheme": mid_scheme, "pct": 10.0, "amount": round(b * 0.10, 2)})
            items.append({"role": "Balanced Advantage / Debt", "scheme": debt_scheme, "pct": 50.0, "amount": round(b * 0.50, 2)})
        elif target_debt == 80.0: # Tier 2 (20% Eq / 80% Debt)
            items.append({"role": "Large-Cap Bluechip Anchor", "scheme": large_scheme, "pct": 20.0, "amount": round(b * 0.20, 2)})
            items.append({"role": "High-Grade Debt Anchor", "scheme": debt_scheme, "pct": 80.0, "amount": round(b * 0.80, 2)})
        else: # Tier 1 (100% Debt)
            items.append({"role": "Capital Preservation Debt", "scheme": debt_scheme, "pct": 100.0, "amount": round(b, 2)})

    # Sum check & adjustment
    tot_alloc = sum(it["amount"] for it in items)
    diff = round(b - tot_alloc, 2)
    if abs(diff) > 0.0 and items:
        items[0]["amount"] = round(items[0]["amount"] + diff, 2)

    return items

def compute_all_levels_lumpsum_blueprint(
    lumpsum_amount: float,
    risk_level: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    bank_cash_total: float = 435000.0,
    emergency_reserve: float = 115000.0
):
    L = float(lumpsum_amount)
    lvl = str(risk_level).lower()

    if "tier 6" in lvl or "level 6" in lvl or "very high" in lvl:
        debt_target_pct = 0.0 if stability_buffer_pct >= 5.0 else 5.0
    elif "tier 5" in lvl or "level 5" in lvl or "growth" in lvl or "high" in lvl:
        debt_target_pct = 15.0
    elif "tier 4" in lvl or "level 4" in lvl or "moderate high" in lvl:
        debt_target_pct = 30.0
    elif "tier 3" in lvl or "level 3" in lvl or "moderate" in lvl:
        debt_target_pct = 50.0
    elif "tier 2" in lvl or "level 2" in lvl or "low" in lvl:
        debt_target_pct = 80.0
    else:
        debt_target_pct = 100.0

    eq_target_pct = 100.0 - debt_target_pct
    debt_amount = round(L * (debt_target_pct / 100.0), 2)
    eq_amount = round(L * (eq_target_pct / 100.0), 2)

    # Staggering duration for equity
    if eq_amount <= 250000.0:
        stp_months = 6
    elif eq_amount <= 1000000.0:
        stp_months = 6 if eq_amount <= 500000.0 else 9
    elif eq_amount <= 2500000.0:
        stp_months = 12
    else:
        stp_months = 12 if eq_amount <= 5000000.0 else 18

    is_big = eq_amount >= 500000.0
    parking_vehicle = "Equity Arbitrage Fund - Direct Plan" if is_big else "Liquid Fund / Arbitrage Fund - Direct Plan"

    tranches = []
    # 1. Debt Tranche (Day 1 upfront)
    if debt_amount > 0:
        tranches.append({
            "role": "High-Grade Debt Cushion (Day 1 Upfront)",
            "scheme": "ICICI Prudential Short Term Fund - Direct Plan - Growth",
            "amount": debt_amount,
            "pct": debt_target_pct,
            "timing": "Immediate (Day 1)",
            "source": "Bank Deployable Surplus",
            "rationale": "High-grade debt has zero equity bubble risk; builds required safety cushion upfront."
        })

    # 2. Equity Tranches
    if eq_amount > 0:
        imm_eq = round(eq_amount * 0.20, 2)
        stp_eq = round(eq_amount * 0.80, 2)
        monthly_stp = round(stp_eq / stp_months, 2)

        # Day 1 Large-Cap Anchor
        imm_pct = round((imm_eq / L) * 100.0, 1)
        tranches.append({
            "role": "Day-1 Large-Cap Anchor",
            "scheme": "Nippon India Large Cap Fund - Direct Plan - Growth",
            "amount": imm_eq,
            "pct": imm_pct,
            "timing": "Immediate (Day 1)",
            "source": "Bank Deployable Surplus",
            "rationale": "Anchors baseline large-cap stability with liquid bluechips (+1.99% alpha, 0.88 beta)."
        })

        if not is_big:
            # Single STP into Flexi Cap
            stp_pct = round((stp_eq / L) * 100.0, 1)
            tranches.append({
                "role": "Core Flexi-Cap Compounder",
                "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                "amount": stp_eq,
                "pct": stp_pct,
                "timing": f"{stp_months}-Month STP ({monthly_stp:,.0f}/mo)",
                "source": parking_vehicle,
                "rationale": "Dollar-cost averages into all-weather compounder with built-in cash/global buffer."
            })
        else:
            # Multi-slot STP for big ticket
            flexi_stp = round(stp_eq * 0.50, 2)
            mid_stp = round(stp_eq * 0.35, 2)
            large_stp = round(stp_eq * 0.15, 2)

            tranches.append({
                "role": "Core Flexi-Cap Compounder (STP Leg 1)",
                "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                "amount": flexi_stp,
                "pct": round((flexi_stp / L) * 100.0, 1),
                "timing": f"{stp_months}-Month STP ({round(flexi_stp/stp_months, 0):,.0f}/mo)",
                "source": parking_vehicle,
                "rationale": "Primary compounding ballast; avoids single-fund concentration on large capital."
            })
            tranches.append({
                "role": "Mid-Cap Alpha Engine (STP Leg 2)",
                "scheme": "Motilal Oswal Midcap Fund - Direct Plan Growth",
                "amount": mid_stp,
                "pct": round((mid_stp / L) * 100.0, 1),
                "timing": f"{stp_months}-Month STP ({round(mid_stp/stp_months, 0):,.0f}/mo)",
                "source": parking_vehicle,
                "rationale": "Captures 10-year mid-cap alpha; routes to verified active Direct Folio #910168305634."
            })
            tranches.append({
                "role": "Large-Cap Bluechip Anchor (STP Leg 3)",
                "scheme": "Nippon India Large Cap Fund - Direct Plan - Growth",
                "amount": large_stp,
                "pct": round((large_stp / L) * 100.0, 1),
                "timing": f"{stp_months}-Month STP ({round(large_stp/stp_months, 0):,.0f}/mo)",
                "source": parking_vehicle,
                "rationale": "Reinforces bluechip ballast across corporate earnings cycles."
            })

    return {
        "lumpsum": L,
        "risk_level": risk_level,
        "stp_months": stp_months if eq_amount > 0 else 0,
        "debt_amount": debt_amount,
        "eq_amount": eq_amount,
        "parking_vehicle": parking_vehicle if eq_amount > 0 else "N/A",
        "tranches": tranches
    }

print("=== TESTING ALL-LEVELS SIP ENGINE ===")
for lvl in ["Tier 6 (Very High)", "Tier 5 (High)", "Tier 4 (Moderate High)", "Tier 3 (Moderate)"]:
    plan = compute_all_levels_sip_blueprint(100000.0, lvl)
    print(f"\nProfile: {lvl} -> {len(plan)} items:")
    for it in plan:
        print(f"  * {it['role']}: {it['pct']}% | INR {it['amount']:,.0f} -> {it['scheme'][:35]}")

print("\n=== TESTING ALL-LEVELS LUMPSUM ENGINE (2L vs 10L) ===")
for L in [200000.0, 1000000.0]:
    for lvl in ["Tier 6 (Very High)", "Tier 5 (High)"]:
        l_res = compute_all_levels_lumpsum_blueprint(L, lvl)
        print(f"\nLumpsum INR {L:,.0f} | Profile: {lvl} | STP: {l_res['stp_months']}M | Parking: {l_res['parking_vehicle']}:")
        for tr in l_res['tranches']:
            print(f"  * {tr['role']}: INR {tr['amount']:,.0f} ({tr['pct']}%) via {tr['timing']}")

