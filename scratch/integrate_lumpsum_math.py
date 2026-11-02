import re

with open("core/math_engine.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Import new models if needed
if "DeterministicLumpsumPlan" not in content:
    content = content.replace(
        "DeterministicSIPPlan,",
        "DeterministicSIPPlan, DeterministicLumpsumPlan, LumpsumTrancheItem,"
    )

# 2. Add compute_deterministic_lumpsum_blueprint function
lumpsum_fn = '''

def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
) -> DeterministicLumpsumPlan:
    """
    Computes institutional lumpsum deployment strategy with dynamic duration staggering,
    multi-slot SAA preservation for large amounts (>= INR 5 Lakhs), tax-shielded arbitrage parking,
    and bank cash reality verification.
    """
    deployable_surplus = max(0.0, bank_cash_total - emergency_reserve)

    # Reusable folios
    direct_large_folio = None
    direct_mid_folio = None
    direct_flexi_folio = None
    if holdings:
        for h in holdings:
            if h.is_direct and h.folio:
                s_lower = h.scheme.lower()
                if "large cap" in s_lower and "large and mid" not in s_lower and "multi" not in s_lower:
                    direct_large_folio = h.folio
                elif ("mid cap" in s_lower or "midcap" in s_lower) and "large and mid" not in s_lower and "multi" not in s_lower:
                    direct_mid_folio = h.folio
                elif "parag parikh" in s_lower or "ppfas" in s_lower:
                    direct_flexi_folio = h.folio

    # 1. Horizon Staggering Logic based on Size (Sequence of Returns Risk Mitigation)
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
    monthly_stp_total = round(stp_total / stp_months, 2) if stp_months > 0 else 0.0

    # 2. Parking Vehicle & Tax Arbitrage (Section 50AA Debt vs Section 112A/111A Equity Arbitrage)
    is_big = lumpsum_amount >= 500000.0
    parking_vehicle = "Equity Arbitrage Fund - Direct Plan (e.g. ICICI Pru / Kotak Arbitrage)" if is_big else "Liquid Fund / Arbitrage Fund - Direct Plan"

    # Tax savings calculation on parked capital at ~6.8% yield (31.2% slab debt vs 20% equity STCG)
    annual_yield = 0.068
    parking_interest_est = stp_total * annual_yield * (stp_months / 24.0)
    tax_debt_slab = parking_interest_est * 0.312
    tax_arbitrage_equity = parking_interest_est * 0.20
    tax_savings_inr = max(0.0, round(tax_debt_slab - tax_arbitrage_equity, 2)) if is_big else 0.0

    # 3. Destination Tranches: Day 1 Anchor + STP Legs
    tranches = []
    
    # Day 1 Immediate (20%) -> Large-Cap Bluechip Anchor
    large_folio_str = direct_large_folio if direct_large_folio else "New Direct Folio"
    tranches.append(
        LumpsumTrancheItem(
            role="Day-1 Large-Cap Anchor",
            scheme_name="Nippon India Large Cap Fund - Direct Plan - Growth",
            folio_target=direct_large_folio,
            amount_inr=immediate_amt,
            allocation_pct=20.0,
            timing="Immediate (Day 1)",
            source_vehicle="Bank Deployable Surplus",
            fiduciary_rationale="Anchors baseline portfolio stability with liquid bluechips (+1.99% 3Y alpha, 0.88 beta)."
        )
    )

    flexi_folio_str = direct_flexi_folio if direct_flexi_folio else "New Direct Folio"
    mid_folio_str = direct_mid_folio if direct_mid_folio else "New Direct Folio"

    if not is_big:
        # Standard: 80% STP into single core compounder
        tranches.append(
            LumpsumTrancheItem(
                role="Core Flexi-Cap Compounder",
                scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                folio_target=direct_flexi_folio,
                amount_inr=stp_total,
                monthly_inr=monthly_stp_total,
                allocation_pct=80.0,
                timing=f"{stp_months}-Month STP (INR {monthly_stp_total:,.0f}/mo)",
                source_vehicle=parking_vehicle,
                fiduciary_rationale="Dollar-cost averages into all-weather compounder with built-in cash/global buffer."
            )
        )
    else:
        # Big Ticket Multi-Slot Routing (Preserves 4-Slot SAA, eliminates single-fund concentration)
        flexi_stp = round(stp_total * 0.50, 2)
        mid_stp = round(stp_total * 0.35, 2)
        large_stp = round(stp_total * 0.15, 2)

        tranches.append(
            LumpsumTrancheItem(
                role="Core Flexi-Cap Compounder (STP Leg 1)",
                scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                folio_target=direct_flexi_folio,
                amount_inr=flexi_stp,
                monthly_inr=round(flexi_stp / stp_months, 2),
                allocation_pct=40.0,
                timing=f"{stp_months}-Month STP (INR {round(flexi_stp / stp_months, 2):,.0f}/mo)",
                source_vehicle=parking_vehicle,
                fiduciary_rationale="Primary compounding ballast; prevents single-fund overconcentration on large capital."
            )
        )
        tranches.append(
            LumpsumTrancheItem(
                role="Mid-Cap Alpha Engine (STP Leg 2)",
                scheme_name="Motilal Oswal Midcap Fund - Direct Plan Growth",
                folio_target=direct_mid_folio,
                amount_inr=mid_stp,
                monthly_inr=round(mid_stp / stp_months, 2),
                allocation_pct=28.0,
                timing=f"{stp_months}-Month STP (INR {round(mid_stp / stp_months, 2):,.0f}/mo)",
                source_vehicle=parking_vehicle,
                fiduciary_rationale="Captures 10-year mid-cap alpha; routes to verified active Direct Folio."
            )
        )
        tranches.append(
            LumpsumTrancheItem(
                role="Large-Cap Bluechip Anchor (STP Leg 3)",
                scheme_name="Nippon India Large Cap Fund - Direct Plan - Growth",
                folio_target=direct_large_folio,
                amount_inr=large_stp,
                monthly_inr=round(large_stp / stp_months, 2),
                allocation_pct=12.0,
                timing=f"{stp_months}-Month STP (INR {round(large_stp / stp_months, 2):,.0f}/mo)",
                source_vehicle=parking_vehicle,
                fiduciary_rationale="Reinforces bluechip ballast across corporate earnings cycles."
            )
        )

    # 4. Bank Cash Reality Verification
    cash_ok = lumpsum_amount <= deployable_surplus if deployable_surplus > 0 else True
    if cash_ok and deployable_surplus >= lumpsum_amount:
        msg = f"VALIDATED: Fully backed by bank deployable surplus of INR {deployable_surplus:,.0f} (INR {emergency_reserve:,.0f} emergency reserve preserved)."
    elif deployable_surplus > 0:
        deficit = lumpsum_amount - deployable_surplus
        msg = f"CAPITAL NOTICE: Declared lumpsum (INR {lumpsum_amount:,.0f}) exceeds current bank deployable surplus (INR {deployable_surplus:,.0f}) by INR {deficit:,.0f}. Preserves INR {emergency_reserve:,.0f} emergency reserve. Requires fresh capital transfer to bank account prior to execution."
    else:
        msg = f"Lumpsum budget of INR {lumpsum_amount:,.0f} configured for systematic deployment."

    return DeterministicLumpsumPlan(
        total_lumpsum_inr=lumpsum_amount,
        is_big_ticket=is_big,
        stp_duration_months=stp_months,
        immediate_amount_inr=immediate_amt,
        stp_total_amount_inr=stp_total,
        monthly_stp_total_inr=monthly_stp_total,
        parking_vehicle=parking_vehicle,
        tax_savings_vs_debt_fund_inr=tax_savings_inr,
        cash_validation_passed=cash_ok,
        cash_validation_message=msg,
        tranches=tranches
    )
'''

# Insert compute_deterministic_lumpsum_blueprint right before aggregate_fiduciary_facts or near end
if "def compute_deterministic_lumpsum_blueprint" not in content:
    idx = content.find("def compute_deterministic_sip_blueprint")
    if idx != -1:
        content = content[:idx] + lumpsum_fn + "\n\n" + content[idx:]

# Update aggregate_fiduciary_facts to call compute_deterministic_lumpsum_blueprint
target_call = """    det_sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=monthly_sip,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
        holdings=holdings,
        client_aum=tot_cur
    )"""

replacement_call = """    det_sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=monthly_sip,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
        holdings=holdings,
        client_aum=tot_cur
    )

    det_lumpsum_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=lumpsum_budget,
        bank_cash_total=bank_cash_cfg,
        emergency_reserve=emergency_reserve_cfg,
        holdings=holdings,
    )"""

content = content.replace(target_call, replacement_call, 1)

# Pass deterministic_lumpsum_plan in FiduciaryFactsPayload
target_payload = "        deterministic_sip_plan=det_sip_plan,"
replacement_payload = """        deterministic_sip_plan=det_sip_plan,
        deterministic_lumpsum_plan=det_lumpsum_plan,"""

content = content.replace(target_payload, replacement_payload, 1)

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: Updated core/math_engine.py with compute_deterministic_lumpsum_blueprint!")

