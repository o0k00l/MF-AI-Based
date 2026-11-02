with open("tax/transition_planner.py", "r", encoding="utf-8") as f:
    text = f.read()

target = """    def calculate_exit_load(lot, units_sold, fy_start, current_nav, exit_load_pct):
        \"\"\"Calculate exit load based on holding period.\"\"\"
        sale_date = date(fy_start, 4, 1)
        holding_days = (sale_date - lot.purchase_date).days
        exit_load_rate = exit_load_pct if holding_days < 365 else 0.0
        sale_value = units_sold * current_nav
        exit_load_amount = sale_value * exit_load_rate / 100.0
        net_amount = sale_value - exit_load_amount
        return exit_load_amount, net_amount, holding_days"""

replacement = """    def calculate_exit_load(lot, units_sold, fy_start, current_nav, exit_load_pct, fund_id=""):
        \"\"\"Calculate category-aware exit load based on holding period.\"\"\"
        sale_date = date(fy_start, 4, 1)
        holding_days = (sale_date - lot.purchase_date).days
        f_lower = str(fund_id).lower()
        if any(k in f_lower for k in ("liquid", "overnight")):
            exit_load_rate = 0.0070 if holding_days < 7 else 0.0
        elif any(k in f_lower for k in ("short term", "debt", "money market", "banking & psu", "arbitrage")):
            exit_load_rate = 0.25 if holding_days < 30 else 0.0
        else:
            exit_load_rate = exit_load_pct if holding_days < 365 else 0.0
        sale_value = units_sold * current_nav
        exit_load_amount = sale_value * exit_load_rate / 100.0
        net_amount = sale_value - exit_load_amount
        return exit_load_amount, net_amount, holding_days"""

assert target in text, "target not found"
text = text.replace(target, replacement, 1)

# Pass fund_id in loss_lots loop
target_loss = """        exit_load_amount, net_amount, holding_days = calculate_exit_load(
            lot_info["lot"], lot_info["units"], current_fy_start, lot_info["current_nav"], exit_load_pct
        )"""

replacement_loss = """        exit_load_amount, net_amount, holding_days = calculate_exit_load(
            lot_info["lot"], lot_info["units"], current_fy_start, lot_info["current_nav"], exit_load_pct, lot_info.get("fund_id", "")
        )"""

assert target_loss in text, "target_loss not found"
text = text.replace(target_loss, replacement_loss, 1)

# Pass fund_id in gain_lots loop
target_gain = """                    exit_load_amount, net_amount, holding_days = calculate_exit_load(
                        lot_info["lot"], units_to_sell, fy_ptr, current_nav, exit_load_pct
                    )"""

replacement_gain = """                    exit_load_amount, net_amount, holding_days = calculate_exit_load(
                        lot_info["lot"], units_to_sell, fy_ptr, current_nav, exit_load_pct, lot_info.get("fund_id", "")
                    )"""

assert target_gain in text, "target_gain not found"
text = text.replace(target_gain, replacement_gain, 1)

with open("tax/transition_planner.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Successfully updated calculate_exit_load in tax/transition_planner.py")

