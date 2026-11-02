import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 435000.0,
    emergency_reserve: float = 115000.0,
    direct_large_folio: str = "477486710296",
    direct_mid_folio: str = "910168305634",
    direct_flexi_folio: str = None
):
    deployable_surplus = max(0.0, bank_cash_total - emergency_reserve)
    
    # 1. Horizon Staggering Logic based on Size
    if lumpsum_amount <= 250000.0:
        stp_months = 6
    elif lumpsum_amount <= 1000000.0:
        stp_months = 6 if lumpsum_amount <= 500000.0 else 9
    elif lumpsum_amount <= 2500000.0:
        stp_months = 12
    else:
        stp_months = 12 if lumpsum_amount <= 5000000.0 else 18

    immediate_amt = round(lumpsum_amount * 0.20, 2)
    stp_total = round(lumpsum_amount * 0.80, 2)
    monthly_stp_total = round(stp_total / stp_months, 2)

    # 2. Parking Vehicle & Tax Arbitrage
    # Liquid funds = Debt taxation (Slab rate up to 39% post-FA 2023)
    # Arbitrage funds = Equity taxation (20% STCG, 12.5% LTCG)
    is_big = lumpsum_amount >= 500000.0
    parking_vehicle = "Equity Arbitrage Fund - Direct Plan" if is_big else "Liquid Fund / Arbitrage Fund - Direct Plan"
    
    # Approx yield 6.8% annualized
    annual_yield = 0.068
    parking_interest_est = stp_total * annual_yield * (stp_months / 24.0) # Average balance half-life
    tax_debt_slab = parking_interest_est * 0.312 # 30% slab + 4% cess
    tax_arbitrage_equity = parking_interest_est * 0.20 # 20% STCG
    tax_savings_inr = max(0.0, round(tax_debt_slab - tax_arbitrage_equity, 2)) if is_big else 0.0

    # 3. Multi-Slot Destination for Large Lumpsums
    # Avoid single-fund concentration if L >= 5L
    tranches = []
    
    # Tranche 1: Day 1 Immediate (20%) -> Large-Cap Bluechip Anchor
    tranches.append({
        "role": "Day-1 Large-Cap Anchor",
        "scheme": "Nippon India Large Cap Fund - Direct Plan",
        "folio": direct_large_folio or "New Direct Folio",
        "amount_inr": immediate_amt,
        "pct": 20.0,
        "timing": "Immediate (Day 1)",
        "source": "Bank Deployable Surplus",
        "rationale": "Anchors baseline portfolio stability with liquid bluechips (+1.99% alpha, 0.88 beta)."
    })

    # STP Tranches (80%)
    if not is_big:
        # Single destination: Parag Parikh Flexi Cap Direct
        tranches.append({
            "role": "Core Flexi-Cap Compounder",
            "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan",
            "folio": direct_flexi_folio or "New Direct Folio",
            "amount_inr": stp_total,
            "monthly_inr": monthly_stp_total,
            "pct": 80.0,
            "timing": f"{stp_months}-Month STP ({monthly_stp_total:,.0f}/mo)",
            "source": parking_vehicle,
            "rationale": "Dollar-cost averages into all-weather compounder with built-in cash/global buffer."
        })
    else:
        # Multi-slot destination: 50% Flexi, 35% Mid Alpha, 15% Large Anchor
        flexi_stp = round(stp_total * 0.50, 2)
        mid_stp = round(stp_total * 0.35, 2)
        large_stp = round(stp_total * 0.15, 2)
        
        tranches.append({
            "role": "Core Flexi-Cap Compounder (STP Leg 1)",
            "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan",
            "folio": direct_flexi_folio or "New Direct Folio",
            "amount_inr": flexi_stp,
            "monthly_inr": round(flexi_stp / stp_months, 2),
            "pct": 40.0, # 50% of 80% = 40% of total
            "timing": f"{stp_months}-Month STP ({round(flexi_stp / stp_months, 2):,.0f}/mo)",
            "source": parking_vehicle,
            "rationale": "Primary compounding ballast; avoids single-fund concentration on large capital."
        })
        tranches.append({
            "role": "Mid-Cap Alpha Engine (STP Leg 2)",
            "scheme": "Motilal Oswal Midcap Fund - Direct Plan",
            "folio": direct_mid_folio or "New Direct Folio",
            "amount_inr": mid_stp,
            "monthly_inr": round(mid_stp / stp_months, 2),
            "pct": 28.0, # 35% of 80% = 28% of total
            "timing": f"{stp_months}-Month STP ({round(mid_stp / stp_months, 2):,.0f}/mo)",
            "source": parking_vehicle,
            "rationale": "Captures 10-year mid-cap alpha; routes to verified active Direct Folio #910168305634."
        })
        tranches.append({
            "role": "Large-Cap Bluechip Anchor (STP Leg 3)",
            "scheme": "Nippon India Large Cap Fund - Direct Plan",
            "folio": direct_large_folio or "New Direct Folio",
            "amount_inr": large_stp,
            "monthly_inr": round(large_stp / stp_months, 2),
            "pct": 12.0, # 15% of 80% = 12% of total
            "timing": f"{stp_months}-Month STP ({round(large_stp / stp_months, 2):,.0f}/mo)",
            "source": parking_vehicle,
            "rationale": "Reinforces bluechip ballast across corporate earnings cycles; routes to Folio #477486710296."
        })

    # 4. Cash Reality Check
    cash_ok = lumpsum_amount <= deployable_surplus
    if cash_ok:
        msg = f"VALIDATED: Fully backed by bank deployable surplus of INR {deployable_surplus:,.0f} (INR {emergency_reserve:,.0f} emergency reserve preserved)."
    else:
        deficit = lumpsum_amount - deployable_surplus
        msg = f"CAPITAL NOTICE: Declared lumpsum (INR {lumpsum_amount:,.0f}) exceeds current bank deployable surplus (INR {deployable_surplus:,.0f}) by INR {deficit:,.0f}. Fresh funds required before execution."

    return {
        "lumpsum_amount": lumpsum_amount,
        "is_big": is_big,
        "stp_months": stp_months,
        "immediate_amt": immediate_amt,
        "stp_total": stp_total,
        "monthly_stp_total": monthly_stp_total,
        "parking_vehicle": parking_vehicle,
        "tax_savings_inr": tax_savings_inr,
        "cash_ok": cash_ok,
        "msg": msg,
        "tranches": tranches
    }

# Run tests
test_cases = [200000.0, 500000.0, 1000000.0, 2500000.0, 5000000.0]
for tc in test_cases:
    res = compute_deterministic_lumpsum_blueprint(tc)
    print(f"\n=======================================================")
    print(f"LUMPSUM: INR {res['lumpsum_amount']:,.0f} (Is Big: {res['is_big']})")
    print(f"STP Duration: {res['stp_months']} Months | Parking: {res['parking_vehicle']}")
    print(f"Estimated Tax Savings vs Debt Liquid: INR {res['tax_savings_inr']:,.2f}")
    print(f"Status: {res['msg']}")
    print(f"Tranches ({len(res['tranches'])} legs):")
    for t in res['tranches']:
        print(f"  * {t['role']}: INR {t['amount_inr']:,.0f} ({t['pct']}%) via {t['timing']} -> {t['scheme']} (Folio: {t['folio']})")

