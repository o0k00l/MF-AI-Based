with open("validate_final_logics.py", "r", encoding="utf-8") as f:
    text = f.read()

test7_code = """
# =====================================================================
# TEST 7: All 6 SEBI Regulatory Risk Tiers (Dynamic SIP & Lumpsum Scaling)
# =====================================================================
print("\\n>> [TEST 7] All 6 SEBI Regulatory Risk Tiers (Dynamic SIP & Lumpsum Scaling):")

tier_targets = [
    ("Tier 6 (Very High)", 100.0, 0.0),
    ("Tier 5 (High)", 85.0, 15.0),
    ("Tier 4 (Moderate High)", 70.0, 30.0),
    ("Tier 3 (Moderate)", 50.0, 50.0),
    ("Tier 2 (Low)", 20.0, 80.0),
    ("Tier 1 (Capital Preservation)", 0.0, 100.0)
]

for t_name, exp_eq, exp_debt in tier_targets:
    # 7A: SIP Dynamic Scaling
    sip_tier = compute_deterministic_sip_blueprint(
        monthly_budget=50000.0,
        risk_tier=t_name,
        stability_buffer_pct=7.54
    )
    check(
        f"{t_name} SIP SAA Precision",
        sip_tier.equity_sip_pct == exp_eq and sip_tier.debt_sip_pct == exp_debt,
        f"-> Eq: {sip_tier.equity_sip_pct}% | Debt: {sip_tier.debt_sip_pct}%"
    )
    sip_tot = sum(it.monthly_inr for it in sip_tier.items)
    check(
        f"{t_name} SIP Total Sums Exactly to Budget",
        abs(sip_tot - 50000.0) < 0.01,
        f"Sum: INR {sip_tot:,.2f}"
    )

    # 7B: Lumpsum Dynamic Scaling (INR 10 Lakhs Big-Ticket)
    lump_tier = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=1000000.0,
        risk_tier=t_name,
        stability_buffer_pct=7.54,
        bank_cash_total=1200000.0,
        emergency_reserve=200000.0
    )
    lump_tot = sum(tr.amount_inr for tr in lump_tier.tranches)
    check(
        f"{t_name} Big Lumpsum Tranches Sum Exactly to Budget",
        abs(lump_tot - 1000000.0) < 0.01,
        f"Sum: INR {lump_tot:,.2f}"
    )
    debt_tranche_amt = sum(tr.amount_inr for tr in lump_tier.tranches if "Debt" in tr.role or "Preservation" in tr.role)
    exp_debt_amt = round(1000000.0 * (exp_debt / 100.0), 2)
    check(
        f"{t_name} Big Lumpsum Debt Allocation Matches SAA",
        abs(debt_tranche_amt - exp_debt_amt) < 0.01,
        f"Debt: INR {debt_tranche_amt:,.0f} (Expected: INR {exp_debt_amt:,.0f})"
    )
"""

old_marker = "FINAL SCORECARD:"
idx = text.find(old_marker)
if idx != -1:
    line_start = text.rfind("\nprint(", 0, idx)
    if line_start != -1:
        text = text[:line_start] + "\n" + test7_code + text[line_start:]

with open("validate_final_logics.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: TEST 7 injected into validate_final_logics.py")

