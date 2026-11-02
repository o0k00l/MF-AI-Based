with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    text = f.read()

old_block = '''    # 1. Core Flexi-Cap Compounder
    flexi_scheme = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
    flexi_folio = None
    for k, f in direct_folios.items():
        if "flexi" in k or "parag parikh" in k:
            flexi_scheme = next((h.scheme for h in holdings if h.folio == f), flexi_scheme)
            flexi_folio = f
            break

    flexi_pct = 60.0 if is_starter else 40.0
    flexi_inr = round(monthly_budget * (flexi_pct / 100.0), 2)
    items.append(
        DeterministicSIPRecommendation(
            category_role="Core Flexi-Cap Compounder",
            scheme_name=flexi_scheme,
            folio_target=flexi_folio,
            monthly_inr=flexi_inr,
            allocation_pct=flexi_pct,
            rational_code="CORE_COMPOUNDER",
            fiduciary_rationale=f"Core compounding anchor with lowest category TER, global tech diversification, and built-in cash/arbitrage defensive buffer."
        )
    )

    # 2. Mid-Cap Alpha Engine
    mid_scheme = "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth"
    mid_folio = None
    for k, f in direct_folios.items():
        if "mid" in k or "motilal" in k:
            mid_scheme = next((h.scheme for h in holdings if h.folio == f), mid_scheme)
            mid_folio = f
            break

    mid_pct = 40.0 if is_starter else 30.0
    mid_inr = round(monthly_budget * (mid_pct / 100.0), 2)
    items.append(
        DeterministicSIPRecommendation(
            category_role="Mid-Cap Alpha Engine",
            scheme_name=mid_scheme,
            folio_target=mid_folio,
            monthly_inr=mid_inr,
            allocation_pct=mid_pct,
            rational_code="ALPHA_ENGINE",
            fiduciary_rationale="10-Year compounding driver with high risk-adjusted Sharpe and institutional alpha."
        )
    )

    # Slots 3 & 4 only for Established portfolios (>= INR 5 Lakhs)
    if not is_starter:
        # 3. Large-Cap Bluechip Anchor (15%)
        large_scheme = "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"
        large_folio = None
        for k, f in direct_folios.items():
            if "large" in k or "bluechip" in k:
                large_scheme = next((h.scheme for h in holdings if h.folio == f), large_scheme)
                large_folio = f
                break

        large_inr = round(monthly_budget * 0.15, 2)
        large_rat = f"Top-quartile active large cap (+1.99% 3Y alpha); {'consolidates active Direct Folio #' + large_folio if large_folio else 'initiates bluechip stability anchor'}."
        items.append(
            DeterministicSIPRecommendation(
                category_role="Large-Cap Bluechip Anchor",
                scheme_name=large_scheme,
                folio_target=large_folio,
                monthly_inr=large_inr,
                allocation_pct=15.0,
                rational_code="CORE_ANCHOR",
                fiduciary_rationale=large_rat
            )
        )

        # 4. Tactical Thematic Satellite (15%)
        thematic_scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
        thematic_folio = None
        for k, f in direct_folios.items():
            if "pharma" in k or "health" in k:
                thematic_scheme = next((h.scheme for h in holdings if h.folio == f), thematic_scheme)
                thematic_folio = f
                break'''

new_block = '''    # 1. Core Flexi-Cap Compounder (40%)
    flexi_scheme = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
    flexi_folio = None
    if holdings:
        for h in holdings:
            if h.is_direct and ("parag parikh" in h.scheme.lower() or "ppfas" in h.scheme.lower()):
                flexi_scheme = h.scheme
                flexi_folio = h.folio
                break

    flexi_pct = 60.0 if is_starter else 40.0
    flexi_inr = round(monthly_budget * (flexi_pct / 100.0), 2)
    items.append(
        DeterministicSIPRecommendation(
            category_role="Core Flexi-Cap Compounder",
            scheme_name=flexi_scheme,
            folio_target=flexi_folio,
            monthly_inr=flexi_inr,
            allocation_pct=flexi_pct,
            rational_code="CORE_COMPOUNDER",
            fiduciary_rationale="Core compounding anchor with lowest category TER, global tech diversification, and built-in cash/arbitrage defensive buffer."
        )
    )

    # 2. Mid-Cap Alpha Engine (30%)
    mid_scheme = "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth"
    mid_folio = None
    if holdings:
        for h in holdings:
            s_lower = h.scheme.lower()
            if h.is_direct and ("mid cap" in s_lower or "midcap" in s_lower) and "large and mid" not in s_lower and "multi" not in s_lower:
                mid_scheme = h.scheme
                mid_folio = h.folio
                break

    mid_pct = 40.0 if is_starter else 30.0
    mid_inr = round(monthly_budget * (mid_pct / 100.0), 2)
    items.append(
        DeterministicSIPRecommendation(
            category_role="Mid-Cap Alpha Engine",
            scheme_name=mid_scheme,
            folio_target=mid_folio,
            monthly_inr=mid_inr,
            allocation_pct=mid_pct,
            rational_code="ALPHA_ENGINE",
            fiduciary_rationale="10-Year compounding driver with high risk-adjusted Sharpe and institutional alpha."
        )
    )

    # Slots 3 & 4 only for Established portfolios (>= INR 5 Lakhs)
    if not is_starter:
        # 3. Large-Cap Bluechip Anchor (15%)
        large_scheme = "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"
        large_folio = None
        if holdings:
            large_directs = [
                h for h in holdings 
                if h.is_direct and ("large cap" in h.scheme.lower()) and "large and mid" not in h.scheme.lower() and "multi" not in h.scheme.lower()
            ]
            if large_directs:
                best_large = max(large_directs, key=lambda x: x.current_value_inr)
                large_scheme = best_large.scheme
                large_folio = best_large.folio

        large_inr = round(monthly_budget * 0.15, 2)
        large_rat = f"Top-quartile active large cap (+1.99% 3Y alpha); {'consolidates active Direct Folio #' + large_folio if large_folio else 'initiates bluechip stability anchor'}."
        items.append(
            DeterministicSIPRecommendation(
                category_role="Large-Cap Bluechip Anchor",
                scheme_name=large_scheme,
                folio_target=large_folio,
                monthly_inr=large_inr,
                allocation_pct=15.0,
                rational_code="CORE_ANCHOR",
                fiduciary_rationale=large_rat
            )
        )

        # 4. Tactical Thematic Satellite (15%)
        thematic_scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
        thematic_folio = None
        if holdings:
            for h in holdings:
                if h.is_direct and ("pharma" in h.scheme.lower() or "health" in h.scheme.lower()):
                    thematic_scheme = h.scheme
                    thematic_folio = h.folio
                    break'''

assert old_block in text, "old_block not found in math_engine.py"
text = text.replace(old_block, new_block)

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Exact category matching updated in core/math_engine.py")

