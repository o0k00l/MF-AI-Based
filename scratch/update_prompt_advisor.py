with open('core/prompt_advisor.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Update generate_health_audit_report
old_health_start = '''    xirr_val = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "15.82%"
    benchmark_val = f"{facts.benchmark_xirr_pct * 100:.2f}%" if facts.benchmark_xirr_pct is not None else "12.00%"
    alpha_val = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "+3.82%"

    prompt = f"""'''

new_health_start = '''    xirr_val = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "15.82%"
    benchmark_val = f"{facts.benchmark_xirr_pct * 100:.2f}%" if facts.benchmark_xirr_pct is not None else "12.00%"
    alpha_val = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "+3.82%"

    thematic_rows = []
    for t in getattr(facts, "thematic_exposures", []):
        stocks_str = ", ".join(t.key_underlying_holdings[:4]) if t.key_underlying_holdings else "None"
        thematic_rows.append(
            f"| {t.theme_name} | INR {t.dedicated_funds_inr:,.0f} ({t.dedicated_funds_pct:.1f}%) | INR {t.look_through_stocks_inr:,.0f} ({t.look_through_stocks_pct:.1f}%) | {t.coverage_status} | {stocks_str} |"
        )
    thematic_table_str = "\\n".join(thematic_rows) if thematic_rows else "No thematic data"

    stability_info = ""
    if getattr(facts, "stability_buffer", None):
        sb = facts.stability_buffer
        stability_info = f"Total Stability Buffer: {sb.total_stability_buffer_pct:.2f}% (Embedded Debt: INR {sb.embedded_debt_inr:,.0f}, Embedded Cash: INR {sb.embedded_cash_inr:,.0f}). Meets Tier 6 Target: {sb.meets_tier_target}."

    prompt = f"""'''

assert old_health_start in text, "old_health_start not found"
text = text.replace(old_health_start, new_health_start)
print("Updated health audit setup")

# Add thematic table to health audit prompt
old_health_insert_marker = "- Target Allocation: {facts.saa_drift.target_equity_pct}% Equity, {facts.saa_drift.target_debt_pct}% Debt"
new_health_insert = """- Target Allocation: {facts.saa_drift.target_equity_pct}% Equity, {facts.saa_drift.target_debt_pct}% Debt
- Look-Through Stability Buffer: {stability_info}
- 5-Theme Look-Through Matrix:
| Theme Name | Dedicated Funds Held | Look-Through Stock Exposure | Status | Key Underlying Holdings |
|---|---|---|---|---|
{thematic_table_str}"""

assert old_health_insert_marker in text, "old_health_insert_marker not found"
text = text.replace(old_health_insert_marker, new_health_insert)
print("Updated health audit prompt payload")

# 2. Update generate_cash_and_sip_plan
old_sip_fn = '''def generate_cash_and_sip_plan(facts: FiduciaryFactsPayload) -> str:
    """Generates the Monthly SIP and Lumpsum Deployment Plan."""
    lumpsum_amt = getattr(facts, "lumpsum_budget_inr", 200000.0)
    prompt = f"""
Generate Deliverable 3: 'Fresh Money Deployment Plan (SIP & Lumpsum)' for {facts.client_name}.

INPUT FACTS:
- Monthly SIP Budget: INR {facts.monthly_sip_budget_inr:,.2f}
- Fresh Lumpsum Capital Budget: INR {lumpsum_amt:,.2f}
- Portfolio SAA Gap: Current Equity is {facts.saa_drift.current_equity_pct}% vs Target {facts.saa_drift.target_equity_pct}%. Debt/Fixed Income is under-allocated ({facts.saa_drift.current_debt_pct}% vs {facts.saa_drift.target_debt_pct}%).

STRUCTURE YOUR REPORT AS FOLLOWS:
# Fresh Money Deployment Plan (SIP & Lumpsum)

1. Executive Deployment Strategy:
   - Provide a disciplined fiduciary roadmap to deploy new capital without market timing anxiety.

2. Institutional Lumpsum Deployment Strategy (Budget: INR {lumpsum_amt:,.2f}):
   - Provide a disciplined fiduciary allocation table:
     - Fixed income/debt floor allocated immediately (Day 1) to eliminate SAA drift.
     - Equity allocations executed via a 3 to 6-month Systematic Transfer Plan (STP) originating from an ultra-safe Liquid Fund (earning ~6.8% yield) to mitigate entry-point market timing risk.
     - Include exact fund names, allocation %, rupee amounts summing to INR {lumpsum_amt:,.2f}, and execution method.

3. The Optimized Direct SIP Blueprint (Monthly Budget: INR {facts.monthly_sip_budget_inr:,.2f}):
   - Provide an exact compact table of 4-5 Direct funds across asset classes to rebalance the portfolio toward the {facts.saa_drift.target_equity_pct:.0f}:{facts.saa_drift.target_debt_pct:.0f} target.
   - Fund 1: Nippon India Large Cap Direct or Parag Parikh Flexi Cap Direct (Core Equity Anchor) -> Allocate specific ₹ amount
   - Fund 2: Flexi Cap Direct Plan (Alpha Core) -> Allocate specific ₹ amount
   - Fund 3: Mid-Cap Direct Plan (Growth) -> Allocate specific ₹ amount
   - Fund 4: Balanced Advantage / Arbitrage Direct Plan (Safety/Debt cushion to fix the SAA deficit) -> Allocate specific ₹ amount
   - Total must sum to exactly INR {facts.monthly_sip_budget_inr:,.2f}.

4. Discipline & Rebalancing Mandate:
   - Automated UPI Autopay / OTM mandate setup.
   - Annual rebalancing trigger rules.
\"\"\"
    return _call_llm_with_retry(prompt)'''

new_sip_fn = '''def generate_cash_and_sip_plan(facts: FiduciaryFactsPayload) -> str:
    """Generates the Monthly SIP and Lumpsum Deployment Plan with deterministic SIP table."""
    lumpsum_amt = getattr(facts, "lumpsum_budget_inr", 200000.0)
    
    sip_rows = []
    if getattr(facts, "deterministic_sip_plan", None):
        for item in facts.deterministic_sip_plan.items:
            folio_str = item.folio_target if item.folio_target else "New Direct Folio"
            sip_rows.append(
                f"| {item.category_role} | {item.scheme_name} | {folio_str} | INR {item.monthly_inr:,.0f} | {item.allocation_pct:.1f}% | {item.fiduciary_rationale} |"
            )
    sip_table_str = "\\n".join(sip_rows)

    stability_str = ""
    if getattr(facts, "stability_buffer", None):
        sb = facts.stability_buffer
        stability_str = f"Client already possesses {sb.total_stability_buffer_pct:.2f}% look-through stability buffer (Embedded Debt: INR {sb.embedded_debt_inr:,.0f}, Embedded Cash: INR {sb.embedded_cash_inr:,.0f}, Bank Cash: INR {sb.bank_deployable_cash_inr:,.0f}). This fully satisfies the Tier 6 (5% debt ceiling) target without requiring a standalone low-yield debt SIP."

    prompt = f"""
Generate Deliverable 3: 'Fresh Money Deployment Plan (SIP & Lumpsum)' for {facts.client_name}.

INPUT FACTS:
- Monthly SIP Budget: INR {facts.monthly_sip_budget_inr:,.2f}
- Fresh Lumpsum Capital Budget: INR {lumpsum_amt:,.2f}
- Client Risk Profile: Tier 6 (SEBI Very High / Maximum Alpha)
- Target SAA: {facts.saa_drift.target_equity_pct}% Equity / {facts.saa_drift.target_debt_pct}% Debt
- Look-Through Stability Cushion: {stability_str}

CRITICAL FIDUCIARY INSTRUCTION:
You MUST render the verified deterministic SIP table below EXACTLY as provided. You are strictly forbidden from modifying allocation percentages, changing rupee amounts, or introducing debt/arbitrage funds into the SIP table.

STRUCTURE YOUR REPORT AS FOLLOWS:
# Fresh Money Deployment Plan (SIP & Lumpsum)

1. Executive Deployment Strategy:
   - Provide a disciplined fiduciary roadmap explaining why 100% of fresh SIP money is deployed into high-alpha Direct equity engines for a 35-year-old Tier 6 investor with a 10-year horizon.
   - Explain why standalone debt SIPs are omitted: the portfolio already holds {facts.stability_buffer.total_stability_buffer_pct if facts.stability_buffer else 7.54}% in embedded look-through debt & cash + bank cash.

2. Institutional Lumpsum Deployment Strategy (Budget: INR {lumpsum_amt:,.2f}):
   - Provide an institutional deployment table:
     - 20% immediate deployment into core large-cap.
     - 80% deployed via a 6-month Systematic Transfer Plan (STP) originating from an ultra-safe Liquid/Arbitrage Fund (earning ~6.8% yield) to mitigate market timing risk.

3. The Deterministic Direct SIP Blueprint (Monthly Budget: INR {facts.monthly_sip_budget_inr:,.2f}):
RENDER THIS EXACT VERIFIED TABLE (NO DEVIATIONS):
| Category Role | Scheme Name (100% Direct Plans) | Target Folio | Monthly SIP (INR) | Allocation (%) | Fiduciary Rationale |
|---|---|---|---|---|---|
{sip_table_str}
Total Monthly SIP: INR {facts.monthly_sip_budget_inr:,.2f} (100% Equity Compounding per Tier 6 Policy)

Explain the role of each engine:
- Parag Parikh Flexi Cap: Low 0.69% TER, international tech exposure, and built-in ~12% organic cash/arbitrage buffer.
- Mid-Cap Alpha Engine: Proven 10-year multi-bagger wealth creation driver.
- Nippon India Large Cap: Consolidates active Direct Folio #401321771817; steady alpha leader (+1.99% 3Y alpha).
- Nippon India Pharma / Healthcare: Forward-looking tactical satellite solving the 1.1% healthcare void at reasonable (~28x P/E) valuations.

4. Execution & Autopay Checklist:
   - 2-Step Execution: Stop the 3 Regular SIPs (HDFC Flexi Regular, PPFAS Regular, Nippon Multi-Cap Regular) to save fees immediately; start the 4 Direct SIP mandates on MFCentral / AMC portals.
\"\"\"
    return _call_llm_with_retry(prompt)'''

assert old_sip_fn in text, "old_sip_fn not found"
text = text.replace(old_sip_fn, new_sip_fn)
print("Updated generate_cash_and_sip_plan")

with open('core/prompt_advisor.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("core/prompt_advisor.py updated successfully!")

