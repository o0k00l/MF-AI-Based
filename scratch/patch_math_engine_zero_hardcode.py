with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Update compute_deterministic_lumpsum_blueprint to remove manual loop
old_lump_folios = '''    # Reusable folios
    direct_large_folio = None
    direct_mid_folio = None
    direct_flexi_folio = None
    direct_debt_folio = None
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
                elif any(k in s_lower for k in ("debt", "short term", "liquid", "bond", "banking & psu", "balanced advantage")):
                    direct_debt_folio = h.folio'''

new_lump_folios = '''    # Autonomously resolve reusable direct folios and schemes via the 5-step engine
    slots = select_autonomous_blueprint_funds(holdings=holdings, client_risk_tier=tier_num if 'tier_num' in locals() else _parse_sebi_risk_tier(risk_tier))
    flexi_info = slots["Slot 1: Core Flexi-Cap Compounder"]
    mid_info = slots["Slot 2: Mid-Cap Alpha Engine"]
    large_info = slots["Slot 3: Large-Cap Bluechip Anchor"]
    thematic_info = slots["Slot 4: Tactical Thematic Satellite"]
    debt_info = slots.get("High-Grade Debt Anchor", {})

    direct_large_folio = large_info["folio"]
    direct_mid_folio = mid_info["folio"]
    direct_flexi_folio = flexi_info["folio"]
    direct_debt_folio = debt_info.get("folio")'''

# 2. Update debt tranche in compute_deterministic_lumpsum_blueprint
old_lump_debt = '''    # A. Debt Tranche (Day 1 upfront)
    if debt_amount > 0:
        tranches.append(
            LumpsumTrancheItem(
                role="High-Grade Debt Cushion (Day 1 Upfront)",
                scheme_name="ICICI Prudential Short Term Fund - Direct Plan - Growth",
                folio_target=direct_debt_folio,
                amount_inr=debt_amount,
                allocation_pct=debt_target_pct,
                timing="Immediate (Day 1)",
                source_vehicle="Bank Deployable Surplus",
                fiduciary_rationale="High-grade debt has zero equity bubble risk; builds required safety cushion upfront."
            )
        )'''

new_lump_debt = '''    # A. Debt Tranche (Day 1 upfront)
    if debt_amount > 0:
        debt_scheme_name = debt_info.get("scheme", "ICICI Prudential Short Term Fund - Direct Plan - Growth")
        tranches.append(
            LumpsumTrancheItem(
                role="High-Grade Debt Cushion (Day 1 Upfront)",
                scheme_name=debt_scheme_name,
                folio_target=direct_debt_folio,
                amount_inr=debt_amount,
                allocation_pct=debt_target_pct,
                timing="Immediate (Day 1)",
                source_vehicle="Bank Deployable Surplus",
                fiduciary_rationale="High-grade debt has zero equity bubble risk; builds required safety cushion upfront."
            )
        )'''

# 3. Update compute_deterministic_sip_blueprint manual loop
old_sip_folios = '''    direct_flexi_folio = None
    direct_mid_folio = None
    direct_large_folio = None
    direct_debt_folio = None
    direct_pharma_folio = None

    if holdings:
        for h in holdings:
            if h.is_direct and h.folio:
                s_lower = h.scheme.lower()
                if "parag parikh" in s_lower or "ppfas" in s_lower:
                    direct_flexi_folio = h.folio
                elif ("mid cap" in s_lower or "midcap" in s_lower) and "large and mid" not in s_lower and "multi" not in s_lower:
                    direct_mid_folio = h.folio
                elif "large cap" in s_lower and "large and mid" not in s_lower and "multi" not in s_lower:
                    direct_large_folio = h.folio
                elif "pharma" in s_lower or "health" in s_lower:
                    direct_pharma_folio = h.folio
                elif any(k in s_lower for k in ("debt", "short term", "liquid", "bond", "banking & psu", "balanced advantage")):
                    direct_debt_folio = h.folio'''

new_sip_folios = '''    # Resolved dynamically through select_autonomous_blueprint_funds below'''

# 4. Update Slot 4 rationale in compute_deterministic_sip_blueprint
old_slot4_item = '''            # Slot 4: Tactical Thematic Satellite
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Tactical Thematic Satellite",
                    scheme_name=pharma_scheme,
                    folio_target=direct_pharma_folio,
                    monthly_inr=round(b * (thematic_pct / 100.0), 2),
                    allocation_pct=thematic_pct,
                    rational_code="SATELLITE_THEME",
                    fiduciary_rationale="Forward-looking tactical satellite with reasonable (~28x P/E) valuations and non-cyclical structural tailwinds."
                )
            )'''

new_slot4_item = '''            # Slot 4: Tactical Thematic Satellite
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Tactical Thematic Satellite",
                    scheme_name=pharma_scheme,
                    folio_target=direct_pharma_folio,
                    monthly_inr=round(b * (thematic_pct / 100.0), 2),
                    allocation_pct=thematic_pct,
                    rational_code="SATELLITE_THEME",
                    fiduciary_rationale=pharma_rat
                )
            )'''

# 5. In aggregate_fiduciary_facts pass deficit_theme
old_agg = '''    det_sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=monthly_sip,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
        holdings=holdings,
        client_aum=tot_cur
    )'''

new_agg = '''    deficit_theme = "Pharma"
    for th in thematic_exps:
        if th.coverage_status == "NEGLECTED":
            deficit_theme = th.theme_name
            break

    det_sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=monthly_sip,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
        holdings=holdings,
        client_aum=tot_cur,
        thematic_deficit_theme=deficit_theme
    )'''

patches = [
    (old_lump_folios, new_lump_folios, "Lumpsum Folios"),
    (old_lump_debt, new_lump_debt, "Lumpsum Debt"),
    (old_sip_folios, new_sip_folios, "SIP Folios"),
    (old_slot4_item, new_slot4_item, "Slot 4 Rationale"),
    (old_agg, new_agg, "Aggregate Fiduciary Deficit Theme"),
]

for old_s, new_s, label in patches:
    if old_s in text:
        text = text.replace(old_s, new_s)
        print(f"{label}: replaced (LF)")
    elif old_s.replace("\n", "\r\n") in text:
        text = text.replace(old_s.replace("\n", "\r\n"), new_s.replace("\n", "\r\n"))
        print(f"{label}: replaced (CRLF)")
    else:
        print(f"ERROR: {label} not found")

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Updated core/math_engine.py successfully!")

