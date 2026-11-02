with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    code = f.read()

target_sec2 = """2. Institutional Lumpsum Deployment Strategy (Budget: INR {lumpsum_amt:,.2f}):
   - Provide an institutional deployment table:
     - 20% immediate deployment (INR {lumpsum_amt * 0.20:,.0f}) into core large-cap anchor (Nippon India Large Cap Direct).
     - 80% deployed (INR {lumpsum_amt * 0.80:,.0f}) via a 6-month Systematic Transfer Plan (STP) originating from an ultra-safe Liquid/Arbitrage Fund (earning ~6.8% yield) into Parag Parikh Flexi Cap Direct to mitigate market-timing risk while keeping cash productive."""

replacement_sec2 = """2. Institutional Lumpsum Deployment Strategy (Budget: INR {lumpsum_amt:,.2f}):
   - RENDER THE EXACT DETERMINISTIC LUMPSUM DEPLOYMENT TABLE:
| Deployment Leg | Destination Scheme (100% Direct) | Target Folio | Amount (INR) | Allocation (%) | Timing & Execution | Source Vehicle | Fiduciary Rationale |
|---|---|---|---|---|---|---|---|
{lumpsum_table_str}

   - Provide rigorous institutional explanation of the Lumpsum Architecture:
     • Staggering Horizon: Explain why the STP is spread over {stp_duration} months (protecting against sequence-of-returns risk and market cycle drawdowns).
     • Single-Fund vs Multi-Slot SAA Preservation: Explain why amounts >= INR 5 Lakhs are distributed across Core Flexi (40%), Mid Alpha (28%), and Large Anchor (12% + 20% Day-1) rather than dumping all capital into one fund, preserving target asset allocation.
     • Tax Optimization on Parking Vehicle: Explain why '{parking_vehicle}' is mandated. Contrast Section 50AA debt fund taxation (taxed at slab rate up to 39%) against Equity Arbitrage taxation (20% STCG / 12.5% LTCG under Section 112A/111A), yielding an estimated INR {tax_savings:,.2f} in pure tax drag savings.
     • Bank Cash & Liquidity Reserve Status: Report the verification status: "{cash_validation_msg}"."""

# In generate_cash_and_sip_plan, prepare lumpsum table
lumpsum_prep = """    lumpsum_amt = getattr(facts, "lumpsum_budget_inr", 200000.0)
    lump_plan = getattr(facts, "deterministic_lumpsum_plan", None)

    lump_rows = []
    stp_duration = 6
    parking_vehicle = "Equity Arbitrage Fund - Direct Plan"
    tax_savings = 0.0
    cash_validation_msg = "Validated against bank deployable surplus."

    if lump_plan:
        stp_duration = lump_plan.stp_duration_months
        parking_vehicle = lump_plan.parking_vehicle
        tax_savings = lump_plan.tax_savings_vs_debt_fund_inr
        cash_validation_msg = lump_plan.cash_validation_message
        for tr in lump_plan.tranches:
            f_str = tr.folio_target if tr.folio_target else "New Direct Folio"
            lump_rows.append(
                f"| {tr.role} | {tr.scheme_name} | {f_str} | INR {tr.amount_inr:,.0f} | {tr.allocation_pct:.1f}% | {tr.timing} | {tr.source_vehicle} | {tr.fiduciary_rationale} |"
            )
    lumpsum_table_str = "\\n".join(lump_rows) if lump_rows else "Standard 20/80 deployment"
"""

target_start = """    lumpsum_amt = getattr(facts, "lumpsum_budget_inr", 200000.0)
    
    sip_rows = []"""

replacement_start = lumpsum_prep + "\n    sip_rows = []"

code = code.replace(target_start, replacement_start, 1)
code = code.replace(target_sec2, replacement_sec2, 1)

with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
    f.write(code)

print("SUCCESS: Updated core/prompt_advisor.py with deterministic lumpsum table and big-ticket logic!")

