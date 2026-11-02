with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# We want to replace from lines 2336 to 2560 (approximately)
# Let's find the exact block starting from:
#     # Scheme Identifiers
#     flexi_scheme, flexi_target_folio, flexi_default_rat = _resolve_flexi_details(flexi_choice, holdings, direct_flexi_folio)

target_start = """    # Scheme Identifiers
    flexi_scheme, flexi_target_folio, flexi_default_rat = _resolve_flexi_details(flexi_choice, holdings, direct_flexi_folio)
    large_scheme, large_target_folio, large_default_rat = _resolve_largecap_details(large_choice, holdings, direct_large_folio)
    pharma_scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
    debt_scheme = "ICICI Prudential Short Term Fund - Direct Plan - Growth"
    mid_scheme, mid_target_folio, mid_default_rat = _resolve_midcap_details(mid_choice, holdings, direct_mid_folio)"""

replacement_block = """    # Scheme Identifiers
    flexi_scheme, flexi_target_folio, flexi_default_rat = _resolve_flexi_details(flexi_choice, holdings, direct_flexi_folio)
    large_scheme, large_target_folio, large_default_rat = _resolve_largecap_details(large_choice, holdings, direct_large_folio)
    pharma_scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
    debt_scheme = "ICICI Prudential Short Term Fund - Direct Plan - Growth"
    mid_scheme, mid_target_folio, mid_default_rat = _resolve_midcap_details(mid_choice, holdings, direct_mid_folio)

    is_blend = "blend" in str(flexi_choice).lower()
    ppfas_s, ppfas_f, ppfas_r = _resolve_flexi_details("ppfas_flexi", holdings, direct_flexi_folio)
    hdfc_s, hdfc_f, hdfc_r = _resolve_flexi_details("hdfc_flexi", holdings, direct_flexi_folio)

    def _append_flexi_sip_items(alloc_pct: float):
        if is_blend:
            p_pct = round(alloc_pct / 2.0, 1)
            h_pct = round(alloc_pct - p_pct, 1)
            p_amt = round(b * (p_pct / 100.0), 2)
            h_amt = round(b * (h_pct / 100.0), 2)
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Core Flexi-Cap (Global Anchor)",
                    scheme_name=ppfas_s,
                    folio_target=ppfas_f,
                    monthly_inr=p_amt,
                    allocation_pct=p_pct,
                    rational_code="CORE_COMPOUNDER",
                    fiduciary_rationale=f"Global tech ballast (Alphabet, Meta, Microsoft) + defensive cash buffer; lowest category 0.69% TER; {'reuses Folio #' + ppfas_f if ppfas_f else 'initiates PPFAS'}."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Core Flexi-Cap (Domestic Alpha)",
                    scheme_name=hdfc_s,
                    folio_target=hdfc_f,
                    monthly_inr=h_amt,
                    allocation_pct=h_pct,
                    rational_code="CORE_COMPOUNDER",
                    fiduciary_rationale=f"High-conviction domestic cyclical alpha (+5.27% 3Y alpha, 0.83% TER, Roshi Jain); overcomes PPFAS foreign remit cap and size drag; {'reuses active Direct Folio #' + hdfc_f if hdfc_f else 'initiates HDFC Direct'}."
                )
            )
        else:
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Core Flexi-Cap Compounder",
                    scheme_name=flexi_scheme,
                    folio_target=flexi_target_folio,
                    monthly_inr=round(b * (alloc_pct / 100.0), 2),
                    allocation_pct=alloc_pct,
                    rational_code="CORE_COMPOUNDER",
                    fiduciary_rationale=flexi_default_rat
                )
            )

    if is_starter:
        # Starter Portfolio (< INR 5L AUM): 2 Core Funds
        if target_eq > 0:
            flexi_pct = round(target_eq * 0.60, 1)
            mid_pct = round(target_eq * 0.40, 1)
            _append_flexi_sip_items(flexi_pct)
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=mid_target_folio,
                    monthly_inr=round(b * (mid_pct / 100.0), 2),
                    allocation_pct=mid_pct,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale=mid_default_rat
                )
            )
        if target_debt > 0:
            items.append(
                DeterministicSIPRecommendation(
                    category_role="High-Grade Debt Anchor",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=round(b * (target_debt / 100.0), 2),
                    allocation_pct=target_debt,
                    rational_code="DEBT_ANCHOR",
                    fiduciary_rationale="Preserves capital stability and fulfills SAA fixed income target."
                )
            )
    else:
        # Established Portfolio (>= INR 5L AUM): 4-Slot Sizing Engine + Debt Sleeve
        if target_debt == 0.0:
            # Level 6: 100% Equity Compounding
            _append_flexi_sip_items(40.0)
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=mid_target_folio,
                    monthly_inr=round(b * 0.30, 2),
                    allocation_pct=30.0,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale=mid_default_rat
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=large_target_folio,
                    monthly_inr=round(b * 0.15, 2),
                    allocation_pct=15.0,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale=large_default_rat
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Tactical Thematic Satellite",
                    scheme_name=pharma_scheme,
                    folio_target=direct_pharma_folio,
                    monthly_inr=round(b * 0.15, 2),
                    allocation_pct=15.0,
                    rational_code="SATELLITE_THEME",
                    fiduciary_rationale="Forward-looking tactical satellite with reasonable (~28x P/E) valuations and non-cyclical structural tailwinds."
                )
            )
        elif target_debt == 15.0: # Level 5 (85% Eq / 15% Debt)
            _append_flexi_sip_items(35.0)
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=mid_target_folio,
                    monthly_inr=round(b * 0.25, 2),
                    allocation_pct=25.0,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale=mid_default_rat
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=large_target_folio,
                    monthly_inr=round(b * 0.15, 2),
                    allocation_pct=15.0,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale=large_default_rat
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Tactical Thematic Satellite",
                    scheme_name=pharma_scheme,
                    folio_target=direct_pharma_folio,
                    monthly_inr=round(b * 0.10, 2),
                    allocation_pct=10.0,
                    rational_code="SATELLITE_THEME",
                    fiduciary_rationale="Non-cyclical defensive satellite capturing pharma valuation re-rating."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="High-Grade Debt Cushion",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=round(b * 0.15, 2),
                    allocation_pct=15.0,
                    rational_code="DEBT_CUSHION",
                    fiduciary_rationale="Fulfills 15% debt target under Level 5 SAA mandate without credit risk."
                )
            )
        elif target_debt == 30.0: # Level 4 (70% Eq / 30% Debt)
            _append_flexi_sip_items(30.0)
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=mid_target_folio,
                    monthly_inr=round(b * 0.20, 2),
                    allocation_pct=20.0,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale=mid_default_rat
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=large_target_folio,
                    monthly_inr=round(b * 0.10, 2),
                    allocation_pct=10.0,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale=large_default_rat
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Tactical Thematic Satellite",
                    scheme_name=pharma_scheme,
                    folio_target=direct_pharma_folio,
                    monthly_inr=round(b * 0.10, 2),
                    allocation_pct=10.0,
                    rational_code="SATELLITE_THEME",
                    fiduciary_rationale="Defensive sector allocation."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="High-Grade Debt Anchor",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=round(b * 0.30, 2),
                    allocation_pct=30.0,
                    rational_code="DEBT_ANCHOR",
                    fiduciary_rationale="Fulfills 30% debt target under Level 4 mandate."
                )
            )
        elif target_debt == 50.0: # Level 3 (50% Eq / 50% Debt)
            _append_flexi_sip_items(25.0)
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=large_target_folio,
                    monthly_inr=round(b * 0.15, 2),
                    allocation_pct=15.0,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale=large_default_rat
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=mid_target_folio,
                    monthly_inr=round(b * 0.10, 2),
                    allocation_pct=10.0,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale=mid_default_rat
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Balanced Advantage / Debt",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=round(b * 0.50, 2),
                    allocation_pct=50.0,
                    rational_code="DEBT_ANCHOR",
                    fiduciary_rationale="50% debt foundation for capital stability."
                )
            )"""

# Find end marker in text:
end_marker = "        elif target_debt == 80.0: # Level 2"
start_pos = text.find(target_start)
end_pos = text.find(end_marker)

assert start_pos != -1, "target_start not found!"
assert end_pos != -1, "end_marker not found!"

text = text[:start_pos] + replacement_block + "\n" + text[end_pos:]

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: compute_deterministic_sip_blueprint updated with flexi blend and rationales!")

