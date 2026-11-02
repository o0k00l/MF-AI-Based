with open("core/math_engine.py", "r", encoding="utf-8") as f:
    content = f.read()

target = """    L = float(lumpsum_amount)
    deployable_surplus = max(0.0, bank_cash_total - emergency_reserve)"""

replacement = """    L = float(lumpsum_amount)
    deployable_surplus = max(0.0, bank_cash_total - emergency_reserve)
    if bank_cash_total > 0:
        cash_ok = deployable_surplus >= L
        if cash_ok:
            msg = f"Bank cash verification passed: Deployable surplus of INR {deployable_surplus:,.2f} fully covers proposed lumpsum of INR {L:,.2f}."
        else:
            msg = f"Bank cash verification warning: Proposed lumpsum of INR {L:,.2f} exceeds deployable surplus of INR {deployable_surplus:,.2f} (Bank balance INR {bank_cash_total:,.2f} less INR {emergency_reserve:,.2f} emergency reserve)."
    else:
        cash_ok = True
        msg = f"No bank cash data provided. Proposed lumpsum: INR {L:,.2f}." """

assert target in content, "Target not found"
content = content.replace(target, replacement, 1)
with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Successfully patched math_engine.py")

