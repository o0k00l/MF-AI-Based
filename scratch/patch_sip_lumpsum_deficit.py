import re

with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update compute_deterministic_lumpsum_blueprint signature & slot resolution
old_lumpsum_sig = """def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: Optional[float] = None,
) -> DeterministicLumpsumPlan:"""

new_lumpsum_sig = """def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: Optional[float] = None,
    thematic_deficit_theme: str = "Pharma",
) -> DeterministicLumpsumPlan:"""

assert old_lumpsum_sig in content, "old_lumpsum_sig not found"
content = content.replace(old_lumpsum_sig, new_lumpsum_sig, 1)

old_lumpsum_body = """    # Autonomously resolve reusable direct folios and schemes via the 5-step engine
    slots = select_autonomous_blueprint_funds(holdings=holdings, client_risk_tier=tier_num if 'tier_num' in locals() else _parse_sebi_risk_tier(risk_tier))
    flexi_info = slots["Slot 1: Core Flexi-Cap Compounder"]
    mid_info = slots["Slot 2: Mid-Cap Alpha Engine"]
    large_info = slots["Slot 3: Large-Cap Bluechip Anchor"]
    thematic_info = slots["Slot 4: Tactical Thematic Satellite"]
    debt_info = slots.get("High-Grade Debt Anchor", {})

    direct_large_folio = large_info["folio"]
    direct_mid_folio = mid_info["folio"]
    direct_flexi_folio = flexi_info["folio"]
    direct_debt_folio = debt_info.get("folio")

    # 1. Asset Class SAA Target based on Risk Tier
    tier_num = _parse_sebi_risk_tier(risk_tier)"""

new_lumpsum_body = """    # 1. Asset Class SAA Target based on Risk Tier
    tier_num = _parse_sebi_risk_tier(risk_tier)

    # Autonomously resolve reusable direct folios and schemes via the 5-step engine
    slots = select_autonomous_blueprint_funds(
        holdings=holdings,
        client_risk_tier=tier_num,
        thematic_deficit_theme=thematic_deficit_theme
    )
    flexi_info = slots["Slot 1: Core Flexi-Cap Compounder"]
    mid_info = slots["Slot 2: Mid-Cap Alpha Engine"]
    large_info = slots["Slot 3: Large-Cap Bluechip Anchor"]
    thematic_info = slots["Slot 4: Tactical Thematic Satellite"]
    debt_info = slots.get("High-Grade Debt Anchor", {})

    direct_large_folio = large_info["folio"]
    direct_mid_folio = mid_info["folio"]
    direct_flexi_folio = flexi_info["folio"]
    direct_debt_folio = debt_info.get("folio")"""

assert old_lumpsum_body in content, "old_lumpsum_body not found"
content = content.replace(old_lumpsum_body, new_lumpsum_body, 1)

old_eq_slots = """    # B. Equity Tranches (Autonomously Selected)
    if eq_amount > 0:
        slots = select_autonomous_blueprint_funds(holdings=holdings, client_risk_tier=tier_num)"""

new_eq_slots = """    # B. Equity Tranches (Autonomously Selected)
    if eq_amount > 0:"""

assert old_eq_slots in content, "old_eq_slots not found"
content = content.replace(old_eq_slots, new_eq_slots, 1)

# 2. Update compute_deterministic_sip_blueprint signature & slot resolution
old_sip_sig = """def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: Optional[float] = None,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
) -> DeterministicSIPPlan:"""

new_sip_sig = """def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: Optional[float] = None,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
    thematic_deficit_theme: str = "Pharma",
) -> DeterministicSIPPlan:"""

assert old_sip_sig in content, "old_sip_sig not found"
content = content.replace(old_sip_sig, new_sip_sig, 1)

old_sip_slots = """    # Autonomous Fiduciary Slot Selection (Zero Hardcoded Brands)
    slots = select_autonomous_blueprint_funds(holdings=holdings, client_risk_tier=tier_num)"""

new_sip_slots = """    # Autonomous Fiduciary Slot Selection (Zero Hardcoded Brands)
    slots = select_autonomous_blueprint_funds(
        holdings=holdings,
        client_risk_tier=tier_num,
        thematic_deficit_theme=thematic_deficit_theme
    )"""

assert old_sip_slots in content, "old_sip_slots not found"
content = content.replace(old_sip_slots, new_sip_slots, 1)

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Successfully patched math_engine.py")

