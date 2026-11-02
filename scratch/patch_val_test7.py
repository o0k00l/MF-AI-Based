with open('validate_final_logics.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_test7 = """for t_name, exp_eq, exp_debt in tier_targets:
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
    )"""

new_test7 = """for t_name, exp_eq, exp_debt in tier_targets:
    # 7A: SIP Dynamic Scaling (Testing Baseline Statutory SAA Splits)
    sip_tier = compute_deterministic_sip_blueprint(
        monthly_budget=50000.0,
        risk_tier=t_name,
        stability_buffer_pct=None
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

    # 7B: Lumpsum Dynamic Scaling (INR 10 Lakhs Big-Ticket Baseline SAA)
    lump_tier = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=1000000.0,
        risk_tier=t_name,
        stability_buffer_pct=None,
        bank_cash_total=1200000.0,
        emergency_reserve=200000.0
    )"""

assert old_test7 in content, "old_test7 not found"
content = content.replace(old_test7, new_test7, 1)

with open('validate_final_logics.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Cleanly updated Test 7 in validate_final_logics.py")

