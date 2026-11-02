import re

with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Purge "balanced advantage" from debt keyword in find_client_direct_folio
old_baf_match = 'if any(k in s_lower for k in ("debt", "short term", "liquid", "bond", "banking & psu", "balanced advantage")):'
new_baf_match = 'if any(k in s_lower for k in ("debt", "short term", "liquid", "bond", "banking & psu")) and "balanced advantage" not in s_lower:'
assert old_baf_match in content, "old_baf_match not found"
content = content.replace(old_baf_match, new_baf_match, 1)

# 2. Update select_autonomous_blueprint_funds Stability Anchor:
# Tier >= 4 (Growth): Equity Arbitrage Direct (avoids Sec 50AA slab tax)
# Tier <= 3 (Conservative): AAA/Sovereign Short-Term Debt
old_debt_anchor = """    # 5. DEBT ANCHOR (FOR TIER 1 TO TIER 5 SAA MANDATES)
    held_debt_scheme, held_debt_folio = find_client_direct_folio(holdings, "debt")
    if not held_debt_folio:
        held_debt_scheme, held_debt_folio = find_client_direct_folio(holdings, "short term")

    debt_cands = [
        c for c in candidate_universe
        if any(kw in c.get("category", "").lower() or kw in c.get("fund_name", "").lower() for kw in ("debt", "short term", "short duration", "bond"))
    ]
    best_debt = debt_cands[0] if debt_cands else None
    if held_debt_folio and held_debt_scheme:
        d_scheme = held_debt_scheme
    elif best_debt:
        d_scheme = best_debt.get("fund_name", best_debt.get("name"))
    else:
        d_scheme = "ICICI Prudential Short Term Fund - Direct Plan - Growth"

    blueprint["High-Grade Debt Anchor"] = {
        "scheme": d_scheme,
        "folio": held_debt_folio,
        "is_passive": False,
        "score": 85.0,
        "gate_passed": True,
        "rationale": f"High-grade AAA short-term debt fulfilling SAA fixed income target; {'reuses active Folio #' + str(held_debt_folio) if held_debt_folio else 'initiates high-grade debt anchor'}."
    }"""

new_debt_anchor = """    # 5. FIDUCIARY STABILITY & DEBT ANCHOR (TIER-AWARE & TAX-OPTIMIZED)
    # Tier 4, 5, 6 (Growth / High Risk): Park in Equity Arbitrage Direct to avoid Section 50AA slab tax (39%).
    # Tier 1, 2, 3 (Moderate / Capital Preservation): Park in High-Grade Sovereign / AAA Short-Term Debt.
    is_growth_tier = client_risk_tier >= 4

    held_stab_scheme, held_stab_folio = None, None
    if is_growth_tier:
        held_stab_scheme, held_stab_folio = find_client_direct_folio(holdings, "arbitrage")
        if not held_stab_folio:
            held_stab_scheme, held_stab_folio = find_client_direct_folio(holdings, "liquid")
    else:
        held_stab_scheme, held_stab_folio = find_client_direct_folio(holdings, "short term")
        if not held_stab_folio:
            held_stab_scheme, held_stab_folio = find_client_direct_folio(holdings, "debt")

    if held_stab_folio and held_stab_scheme:
        d_scheme = held_stab_scheme
        d_folio = held_stab_folio
        d_rat = f"Consolidates active Direct stability folio #{d_folio}."
    elif is_growth_tier:
        arb_cands = [c for c in candidate_universe if "arbitrage" in c.get("category", "").lower() or "arbitrage" in c.get("fund_name", "").lower()]
        d_scheme = arb_cands[0].get("fund_name", arb_cands[0].get("name")) if arb_cands else "Kotak Equity Arbitrage Fund - Direct Plan - Growth"
        d_folio = None
        d_rat = "Tax-shielded stability vehicle (Sections 111A/112A equity taxation) bypassing Section 50AA debt slab taxation while fulfilling stability cushion."
    else:
        debt_cands = [c for c in candidate_universe if any(kw in c.get("category", "").lower() or kw in c.get("fund_name", "").lower() for kw in ("debt", "short term", "short duration", "bond"))]
        d_scheme = debt_cands[0].get("fund_name", debt_cands[0].get("name")) if debt_cands else "ICICI Prudential Short Term Fund - Direct Plan - Growth"
        d_folio = None
        d_rat = "High-grade AAA / Sovereign short-term debt fulfilling SAA fixed income target."

    blueprint["High-Grade Debt Anchor"] = {
        "scheme": d_scheme,
        "folio": d_folio,
        "is_passive": False,
        "score": 85.0,
        "gate_passed": True,
        "rationale": d_rat
    }"""

assert old_debt_anchor in content, "old_debt_anchor not found"
content = content.replace(old_debt_anchor, new_debt_anchor, 1)

# 3. Universal SAA & Stability Offset Calculation Function
universal_func = """def calculate_universal_tier_split(
    tier_num: int,
    stability_buffer_pct: Optional[float] = None
) -> Tuple[float, float]:
    \"\"\"
    UNIVERSAL FIDUCIARY ASSET ALLOCATION & STABILITY OFFSET ENGINE:
    Calculates deterministic Equity and Debt allocation percentages across all 6 SEBI risk tiers,
    grounded in data/policy/asset_allocation.json and offsetting the audited look-through stability buffer.

    Returns: (target_eq_pct, target_debt_pct)
    \"\"\"
    if tier_num == 6:
        base_eq, base_debt, threshold = 95.0, 5.0, 5.0
    elif tier_num == 5:
        base_eq, base_debt, threshold = 85.0, 15.0, 5.0
    elif tier_num == 4:
        base_eq, base_debt, threshold = 70.0, 30.0, 10.0
    elif tier_num == 3:
        base_eq, base_debt, threshold = 50.0, 50.0, 25.0
    elif tier_num == 2:
        base_eq, base_debt, threshold = 20.0, 80.0, 56.0
    else: # Tier 1
        return 0.0, 100.0

    if stability_buffer_pct is not None and stability_buffer_pct >= threshold:
        # Look-through stability buffer satisfies the fixed income ceiling organically!
        return 100.0, 0.0
    else:
        return base_eq, base_debt
"""

# Place universal_func right before compute_deterministic_lumpsum_blueprint
target_place = "def compute_deterministic_lumpsum_blueprint("
assert target_place in content, "target_place not found"
content = content.replace(target_place, universal_func + "\n\n" + target_place, 1)

# 4. In compute_deterministic_lumpsum_blueprint, use calculate_universal_tier_split
old_lump_tiers = """    if tier_num == 6:
        debt_target_pct = 0.0 if (stability_buffer_pct is None or stability_buffer_pct >= 5.0) else 5.0
    elif tier_num == 5:
        debt_target_pct = 15.0
    elif tier_num == 4:
        debt_target_pct = 30.0
    elif tier_num == 3:
        debt_target_pct = 50.0
    elif tier_num == 2:
        debt_target_pct = 80.0
    else:
        debt_target_pct = 100.0

    eq_target_pct = 100.0 - debt_target_pct"""

new_lump_tiers = """    eq_target_pct, debt_target_pct = calculate_universal_tier_split(tier_num, stability_buffer_pct)"""

assert old_lump_tiers in content, "old_lump_tiers not found"
content = content.replace(old_lump_tiers, new_lump_tiers, 1)

# 5. In compute_deterministic_sip_blueprint, use calculate_universal_tier_split
old_sip_tiers = """    if tier_num == 6:
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

new_sip_tiers = """    target_eq, target_debt = calculate_universal_tier_split(tier_num, stability_buffer_pct)"""

assert old_sip_tiers in content, "old_sip_tiers not found"
content = content.replace(old_sip_tiers, new_sip_tiers, 1)

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Cleanly patched core/math_engine.py with Universal Fiduciary Debt Engine!")

