with open("validate_final_logics.py", "r", encoding="utf-8") as f:
    val_code = f.read()

# Import compute_deterministic_lumpsum_blueprint
if "compute_deterministic_lumpsum_blueprint" not in val_code:
    val_code = val_code.replace(
        "compute_deterministic_sip_blueprint,",
        "compute_deterministic_sip_blueprint, compute_deterministic_lumpsum_blueprint,"
    )

test1_target = """# =====================================================================
# TEST 1: Universal 20/80 Lumpsum Equation
# =====================================================================
print("\\n>> [TEST 1] Universal 20/80 Lumpsum Deployment Formula:")
test_lumpsums = [100000.0, 500000.0, 2000000.0, 5000000.0]
for L in test_lumpsums:
    day1 = L * 0.20
    liquid_parking = L * 0.80
    stp_monthly = liquid_parking / 6.0
    check(
        f"Lumpsum INR {L:,.0f} Math",
        (day1 + (stp_monthly * 6.0)) == L and day1 == L * 0.20,
        f"-> Day 1: INR {day1:,.0f} | 6-Mo STP: INR {stp_monthly:,.0f}/mo"
    )"""

test1_replacement = """# =====================================================================
# TEST 1: Universal 20/80 Lumpsum Equation & Big-Ticket Scaling
# =====================================================================
print("\\n>> [TEST 1] Universal 20/80 Lumpsum Deployment & Big-Ticket Scaling:")
test_lumpsums = [100000.0, 500000.0, 1000000.0, 2500000.0, 5000000.0]
for L in test_lumpsums:
    lp = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=L,
        bank_cash_total=435000.0,
        emergency_reserve=115000.0
    )
    # Check 1: 20/80 split holds perfectly
    check(
        f"Lumpsum INR {L:,.0f} Math (20/80 Split)",
        lp.immediate_amount_inr == round(L * 0.20, 2) and lp.stp_total_amount_inr == round(L * 0.80, 2),
        f"-> Day 1: INR {lp.immediate_amount_inr:,.0f} | STP ({lp.stp_duration_months}M): INR {lp.monthly_stp_total_inr:,.0f}/mo"
    )
    # Check 2: Sum of all tranches equals exactly L
    tranche_sum = sum(t.amount_inr for t in lp.tranches)
    check(
        f"Lumpsum INR {L:,.0f} Tranche Integrity",
        abs(tranche_sum - L) < 0.01,
        f"Tranches sum to INR {tranche_sum:,.0f}"
    )
    # Check 3: Big ticket handling for L >= 5L
    if L >= 500000.0:
        check(
            f"Lumpsum INR {L:,.0f} Big-Ticket Arbitrage Mandate",
            lp.is_big_ticket and "Arbitrage" in lp.parking_vehicle,
            f"Vehicle: {lp.parking_vehicle}"
        )
        check(
            f"Lumpsum INR {L:,.0f} Multi-Slot SAA Preservation",
            len(lp.tranches) >= 4,
            f"Tranches: {len(lp.tranches)} legs across Flexi, Mid & Large"
        )
        check(
            f"Lumpsum INR {L:,.0f} Tax Savings vs Debt Liquid",
            lp.tax_savings_vs_debt_fund_inr > 0,
            f"Saved: INR {lp.tax_savings_vs_debt_fund_inr:,.2f}"
        )
    else:
        check(
            f"Lumpsum INR {L:,.0f} Agile Single-Destination STP",
            len(lp.tranches) == 2 and lp.stp_duration_months == 6,
            f"Tranches: {len(lp.tranches)} legs"
        )"""

if test1_target in val_code:
    val_code = val_code.replace(test1_target, test1_replacement, 1)
    with open("validate_final_logics.py", "w", encoding="utf-8") as f:
        f.write(val_code)
    print("SUCCESS: Replaced TEST 1 in validate_final_logics.py!")
else:
    print("ERROR: test1_target still not found")

