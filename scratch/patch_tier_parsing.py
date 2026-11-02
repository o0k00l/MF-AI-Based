with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Update aggregate_fiduciary_facts call
old_agg = """    det_lumpsum_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=lumpsum_budget,
        bank_cash_total=bank_cash_cfg,
        emergency_reserve=emergency_reserve_cfg,
        holdings=holdings,
    )"""

new_agg = """    det_lumpsum_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=lumpsum_budget,
        bank_cash_total=bank_cash_cfg,
        emergency_reserve=emergency_reserve_cfg,
        holdings=holdings,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
    )"""

if old_agg not in text:
    print("ERROR: old_agg not found!")
else:
    text = text.replace(old_agg, new_agg, 1)

# 2. Add _parse_sebi_risk_tier and update compute_deterministic_lumpsum_blueprint & compute_deterministic_sip_blueprint
helper_and_lump_start = """def _parse_sebi_risk_tier(risk_tier: str) -> int:
    \"\"\"Safely parses SEBI risk tier 1-6 avoiding substring collisions (e.g. 'moderate high' matching 'high').\"\"\"
    lvl = str(risk_tier).lower()
    if "6" in lvl or "very high" in lvl:
        return 6
    if "4" in lvl or "moderate high" in lvl or "moderately high" in lvl:
        return 4
    if "5" in lvl or "high" in lvl:
        return 5
    if "3" in lvl or "moderate" in lvl:
        return 3
    if "2" in lvl or "low" in lvl:
        return 2
    if "1" in lvl or "preservation" in lvl:
        return 1
    return 6


def compute_deterministic_lumpsum_blueprint("""

target_lump_def = "def compute_deterministic_lumpsum_blueprint("
text = text.replace(target_lump_def, helper_and_lump_start, 1)

old_lump_tier_logic = """    # 1. Asset Class SAA Target based on Risk Tier
    lvl = str(risk_tier).lower()
    if "tier 6" in lvl or "level 6" in lvl or "very high" in lvl:
        debt_target_pct = 0.0 if stability_buffer_pct >= 5.0 else 5.0
    elif "tier 5" in lvl or "level 5" in lvl or "high" in lvl:
        debt_target_pct = 15.0
    elif "tier 4" in lvl or "level 4" in lvl or "moderate high" in lvl:
        debt_target_pct = 30.0
    elif "tier 3" in lvl or "level 3" in lvl or "moderate" in lvl:
        debt_target_pct = 50.0
    elif "tier 2" in lvl or "level 2" in lvl or "low" in lvl:
        debt_target_pct = 80.0
    else:
        debt_target_pct = 100.0"""

new_lump_tier_logic = """    # 1. Asset Class SAA Target based on Risk Tier
    tier_num = _parse_sebi_risk_tier(risk_tier)
    if tier_num == 6:
        debt_target_pct = 0.0 if stability_buffer_pct >= 5.0 else 5.0
    elif tier_num == 5:
        debt_target_pct = 15.0
    elif tier_num == 4:
        debt_target_pct = 30.0
    elif tier_num == 3:
        debt_target_pct = 50.0
    elif tier_num == 2:
        debt_target_pct = 80.0
    else:
        debt_target_pct = 100.0"""

if old_lump_tier_logic not in text:
    print("ERROR: old_lump_tier_logic not found!")
else:
    text = text.replace(old_lump_tier_logic, new_lump_tier_logic, 1)

old_sip_tier_logic = """    # 1. Target Asset Allocation by Risk Level
    lvl = str(risk_tier).lower()
    if "tier 6" in lvl or "level 6" in lvl or "very high" in lvl:
        if stability_buffer_pct >= 5.0:
            target_eq, target_debt = 100.0, 0.0
        else:
            target_eq, target_debt = 95.0, 5.0
    elif "tier 5" in lvl or "level 5" in lvl or "high" in lvl:
        target_eq, target_debt = 85.0, 15.0
    elif "tier 4" in lvl or "level 4" in lvl or "moderate high" in lvl:
        target_eq, target_debt = 70.0, 30.0
    elif "tier 3" in lvl or "level 3" in lvl or "moderate" in lvl:
        target_eq, target_debt = 50.0, 50.0
    elif "tier 2" in lvl or "level 2" in lvl or "low" in lvl:
        target_eq, target_debt = 20.0, 80.0
    else: # Tier 1
        target_eq, target_debt = 0.0, 100.0"""

new_sip_tier_logic = """    # 1. Target Asset Allocation by Risk Level
    tier_num = _parse_sebi_risk_tier(risk_tier)
    if tier_num == 6:
        if stability_buffer_pct >= 5.0:
            target_eq, target_debt = 100.0, 0.0
        else:
            target_eq, target_debt = 95.0, 5.0
    elif tier_num == 5:
        target_eq, target_debt = 85.0, 15.0
    elif tier_num == 4:
        target_eq, target_debt = 70.0, 30.0
    elif tier_num == 3:
        target_eq, target_debt = 50.0, 50.0
    elif tier_num == 2:
        target_eq, target_debt = 20.0, 80.0
    else: # Tier 1
        target_eq, target_debt = 0.0, 100.0"""

if old_sip_tier_logic not in text:
    print("ERROR: old_sip_tier_logic not found!")
else:
    text = text.replace(old_sip_tier_logic, new_sip_tier_logic, 1)

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: core/math_engine.py cleanly patched with safe tier parsing!")

