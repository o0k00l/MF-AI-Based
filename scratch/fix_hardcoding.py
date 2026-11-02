with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Replace compute_deterministic_sip_blueprint with fully dynamic version
old_fn = '''def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 6.32,
    holdings: Optional[List[HoldingItem]] = None,
) -> DeterministicSIPPlan:
    """
    Computes deterministic SIP blueprint without LLM intervention.
    Enforces 85% Core + 15% Satellite logic for Tier 6 aggressive clients.
    """
    direct_folios = {}
    if holdings:
        for h in holdings:
            if h.is_direct and h.folio:
                direct_folios[h.fund_name.lower()] = h.folio

    items = []

    # 1. Core Flexi-Cap Compounder (40%)
    ppfas_folio = None
    for k, f in direct_folios.items():
        if "parag parikh" in k:
            ppfas_folio = f
            break
    items.append(
        DeterministicSIPRecommendation(
            category_role="Core Flexi-Cap Compounder",
            scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            folio_target=ppfas_folio,
            monthly_inr=round(monthly_budget * 0.40, 2),
            allocation_pct=40.0,
            rational_code="CORE_COMPOUNDER",
            fiduciary_rationale="Lowest 0.69% TER, international tech diversification (Alphabet/Meta), ~12% organic defensive cash/arbitrage buffer."
        )
    )

    # 2. Mid-Cap Alpha Engine (30%)
    mid_scheme = "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth"
    mid_folio = None
    for k, f in direct_folios.items():
        if "motilal" in k and "midcap" in k:
            mid_scheme = "Motilal Oswal Midcap Fund - Direct Plan Growth"
            mid_folio = f
            break
        elif "hdfc" in k and "mid" in k:
            mid_scheme = "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth"
            mid_folio = f
            break

    items.append(
        DeterministicSIPRecommendation(
            category_role="Mid-Cap Alpha Engine",
            scheme_name=mid_scheme,
            folio_target=mid_folio,
            monthly_inr=round(monthly_budget * 0.30, 2),
            allocation_pct=30.0,
            rational_code="ALPHA_ENGINE",
            fiduciary_rationale="Highest-returning engine over a 10-year horizon; high risk-adjusted Sharpe; institutional active alpha."
        )
    )

    # 3. Large-Cap Bluechip Anchor (15%)
    nippon_large_folio = None
    for k, f in direct_folios.items():
        if "nippon" in k and "large" in k:
            nippon_large_folio = f
            break
    items.append(
        DeterministicSIPRecommendation(
            category_role="Large-Cap Bluechip Anchor",
            scheme_name="NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION",
            folio_target=nippon_large_folio or "401321771817",
            monthly_inr=round(monthly_budget * 0.15, 2),
            allocation_pct=15.0,
            rational_code="CORE_ANCHOR",
            fiduciary_rationale="Top-quartile active large cap (+1.99% 3Y alpha); consolidates active Direct Folio #401321771817; captures banking re-rating."
        )
    )

    # 4. Tactical Thematic Satellite (15%)
    items.append(
        DeterministicSIPRecommendation(
            category_role="Tactical Thematic Satellite",
            scheme_name="Nippon India Pharma / Healthcare Fund - Direct Plan - Growth",
            folio_target=None,
            monthly_inr=round(monthly_budget * 0.15, 2),
            allocation_pct=15.0,
            rational_code="SATELLITE_THEME",
            fiduciary_rationale="Solves portfolio's critical 1.1% healthcare void; fair valuation (~28x P/E); non-cyclical structural tailwind."
        )
    )

    total_allocated = sum(item.monthly_inr for item in items)
    assert abs(total_allocated - monthly_budget) < 1.0, f"SIP blueprint sum ({total_allocated}) != budget ({monthly_budget})"

    return DeterministicSIPPlan(
        total_monthly_budget_inr=monthly_budget,
        equity_sip_pct=100.0,
        debt_sip_pct=0.0,
        items=items
    )'''

new_fn = '''def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
) -> DeterministicSIPPlan:
    """
    Computes deterministic SIP blueprint dynamically without LLM intervention.
    Scales across Starter (< INR 5L AUM) vs Established (> INR 25L AUM) portfolios.
    Reuses existing client Direct folios dynamically; NEVER hardcodes folios.
    """
    direct_folios = {}
    if holdings:
        for h in holdings:
            if h.is_direct and h.folio:
                direct_folios[h.fund_name.lower()] = h.folio

    # Dynamic check for Starter (< INR 5L) vs Established
    is_starter = (client_aum > 0 and client_aum < 500000.0) or (monthly_budget < 15000.0)

    items = []

    # 1. Core Flexi-Cap Compounder
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
                break

        thematic_inr = round(monthly_budget * 0.15, 2)
        items.append(
            DeterministicSIPRecommendation(
                category_role="Tactical Thematic Satellite",
                scheme_name=thematic_scheme,
                folio_target=thematic_folio,
                monthly_inr=thematic_inr,
                allocation_pct=15.0,
                rational_code="SATELLITE_THEME",
                fiduciary_rationale="Forward-looking tactical satellite with reasonable (~28x P/E) valuations and non-cyclical structural tailwinds."
            )
        )

    # Balance rounding discrepancy if any
    total_allocated = sum(item.monthly_inr for item in items)
    diff = monthly_budget - total_allocated
    if abs(diff) > 0.0:
        items[0].monthly_inr = round(items[0].monthly_inr + diff, 2)

    return DeterministicSIPPlan(
        total_monthly_budget_inr=monthly_budget,
        equity_sip_pct=100.0,
        debt_sip_pct=0.0,
        items=items
    )'''

assert old_fn in text, "old_fn not found in core/math_engine.py"
text = text.replace(old_fn, new_fn)

# Update call in aggregate_fiduciary_facts to pass client_aum
old_call = '''    det_sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=monthly_sip,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
        holdings=holdings
    )'''

new_call = '''    det_sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=monthly_sip,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
        holdings=holdings,
        client_aum=tot_cur
    )'''

assert old_call in text, "old_call not found in core/math_engine.py"
text = text.replace(old_call, new_call)

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("core/math_engine.py updated with dynamic blueprint")

