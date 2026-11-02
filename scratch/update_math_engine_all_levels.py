with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# Replace compute_deterministic_lumpsum_blueprint and compute_deterministic_sip_blueprint
# with all-levels support

start_marker = "def compute_deterministic_lumpsum_blueprint("
end_marker = "def calculate_weighted_lookthrough_overlap("

idx_start = text.find(start_marker)
idx_end = text.find(end_marker)

if idx_start == -1 or idx_end == -1:
    print("ERROR: Markers not found")
    sys.exit(1)

new_code = '''def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
) -> DeterministicLumpsumPlan:
    """
    Computes institutional lumpsum deployment strategy tailored across all SEBI risk tiers,
    with dynamic duration staggering, multi-slot SAA preservation for large amounts (>= INR 5 Lakhs),
    tax-shielded arbitrage parking, and bank cash reality verification.
    """
    L = float(lumpsum_amount)
    deployable_surplus = max(0.0, bank_cash_total - emergency_reserve)

    # Reusable folios
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
                    direct_debt_folio = h.folio

    # 1. Asset Class SAA Target based on Risk Tier
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
        debt_target_pct = 100.0

    eq_target_pct = 100.0 - debt_target_pct
    debt_amount = round(L * (debt_target_pct / 100.0), 2)
    eq_amount = round(L * (eq_target_pct / 100.0), 2)

    # 2. Equity Horizon Staggering Logic based on Size (Sequence of Returns Risk Mitigation)
    if eq_amount <= 250000.0:
        stp_months = 6
    elif eq_amount <= 1000000.0:
        stp_months = 6 if eq_amount <= 500000.0 else 9
    elif eq_amount <= 2500000.0:
        stp_months = 12
    else:
        stp_months = 12 if eq_amount <= 5000000.0 else 18

    # 3. Parking Vehicle & Tax Arbitrage (Section 50AA Debt vs Section 112A/111A Equity Arbitrage)
    is_big = eq_amount >= 500000.0 or L >= 500000.0
    parking_vehicle = "Equity Arbitrage Fund - Direct Plan (e.g. ICICI Pru / Kotak Arbitrage)" if is_big else "Liquid Fund / Arbitrage Fund - Direct Plan"

    # Tax savings calculation on parked capital at ~6.8% yield (31.2% slab debt vs 20% equity STCG)
    annual_yield = 0.068
    stp_total = round(eq_amount * 0.80, 2) if eq_amount > 0 else 0.0
    immediate_eq = round(eq_amount * 0.20, 2) if eq_amount > 0 else 0.0
    monthly_stp_total = round(stp_total / stp_months, 2) if stp_months > 0 else 0.0

    parking_interest_est = stp_total * annual_yield * (stp_months / 24.0)
    tax_debt_slab = parking_interest_est * 0.312
    tax_arbitrage_equity = parking_interest_est * 0.20
    tax_savings_inr = max(0.0, round(tax_debt_slab - tax_arbitrage_equity, 2)) if is_big else 0.0

    # 4. Tranche Construction
    tranches = []

    # A. Debt Tranche (Day 1 upfront)
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
        )

    # B. Equity Tranches
    if eq_amount > 0:
        # Day 1 Large-Cap Anchor
        imm_pct = round((immediate_eq / L) * 100.0, 1)
        tranches.append(
            LumpsumTrancheItem(
                role="Day-1 Large-Cap Anchor",
                scheme_name="Nippon India Large Cap Fund - Direct Plan - Growth",
                folio_target=direct_large_folio,
                amount_inr=immediate_eq,
                allocation_pct=imm_pct,
                timing="Immediate (Day 1)",
                source_vehicle="Bank Deployable Surplus",
                fiduciary_rationale="Anchors baseline portfolio stability with liquid bluechips (+1.99% 3Y alpha, 0.88 beta)."
            )
        )

        if not is_big:
            # Single destination STP
            stp_pct = round((stp_total / L) * 100.0, 1)
            tranches.append(
                LumpsumTrancheItem(
                    role="Core Flexi-Cap Compounder",
                    scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                    folio_target=direct_flexi_folio,
                    amount_inr=stp_total,
                    monthly_inr=monthly_stp_total,
                    allocation_pct=stp_pct,
                    timing=f"{stp_months}-Month STP (INR {monthly_stp_total:,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale="Dollar-cost averages into all-weather compounder with built-in cash/global buffer."
                )
            )
        else:
            # Multi-slot STP for big-ticket lumpsums
            flexi_stp = round(stp_total * 0.50, 2)
            mid_stp = round(stp_total * 0.35, 2)
            large_stp = round(stp_total * 0.15, 2)

            tranches.append(
                LumpsumTrancheItem(
                    role="Core Flexi-Cap Compounder (STP Leg 1)",
                    scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                    folio_target=direct_flexi_folio,
                    amount_inr=flexi_stp,
                    monthly_inr=round(flexi_stp / stp_months, 2),
                    allocation_pct=round((flexi_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(flexi_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale="Primary compounding ballast; avoids single-fund overconcentration on large capital."
                )
            )
            tranches.append(
                LumpsumTrancheItem(
                    role="Mid-Cap Alpha Engine (STP Leg 2)",
                    scheme_name="Motilal Oswal Midcap Fund - Direct Plan Growth",
                    folio_target=direct_mid_folio,
                    amount_inr=mid_stp,
                    monthly_inr=round(mid_stp / stp_months, 2),
                    allocation_pct=round((mid_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(mid_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale="Captures 10-year mid-cap alpha; routes to verified active Direct Folio."
                )
            )
            tranches.append(
                LumpsumTrancheItem(
                    role="Large-Cap Bluechip Anchor (STP Leg 3)",
                    scheme_name="Nippon India Large Cap Fund - Direct Plan - Growth",
                    folio_target=direct_large_folio,
                    amount_inr=large_stp,
                    monthly_inr=round(large_stp / stp_months, 2),
                    allocation_pct=round((large_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(large_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale="Reinforces bluechip ballast across corporate earnings cycles."
                )
            )

    # 5. Bank Cash Reality Verification
    cash_ok = L <= deployable_surplus if deployable_surplus > 0 else True
    if cash_ok and deployable_surplus >= L:
        msg = f"VALIDATED: Fully backed by bank deployable surplus of INR {deployable_surplus:,.0f} (INR {emergency_reserve:,.0f} emergency reserve preserved)."
    elif deployable_surplus > 0:
        deficit = L - deployable_surplus
        msg = f"CAPITAL NOTICE: Declared lumpsum (INR {L:,.0f}) exceeds current bank deployable surplus (INR {deployable_surplus:,.0f}) by INR {deficit:,.0f}. Preserves INR {emergency_reserve:,.0f} emergency reserve. Requires fresh capital transfer to bank account prior to execution."
    else:
        msg = f"Lumpsum budget of INR {L:,.0f} configured for systematic deployment."

    return DeterministicLumpsumPlan(
        total_lumpsum_inr=L,
        is_big_ticket=is_big,
        stp_duration_months=stp_months if eq_amount > 0 else 0,
        immediate_amount_inr=immediate_eq + debt_amount,
        stp_total_amount_inr=stp_total,
        monthly_stp_total_inr=monthly_stp_total,
        parking_vehicle=parking_vehicle if eq_amount > 0 else "N/A",
        tax_savings_vs_debt_fund_inr=tax_savings_inr,
        cash_validation_passed=cash_ok,
        cash_validation_message=msg,
        tranches=tranches
    )


def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
) -> DeterministicSIPPlan:
    """
    Computes deterministic SIP blueprint dynamically tailored across all SEBI risk tiers
    (Level 1 Capital Preservation to Level 6 Aggressive Equity).
    Scales across Starter (< INR 5L AUM) vs Established (> INR 25L AUM) portfolios.
    Reuses existing client Direct folios dynamically; NEVER hardcodes folios.
    """
    b = float(monthly_budget)
    is_starter = (client_aum > 0 and client_aum < 500000.0) or (b < 15000.0)

    # Dynamic Folio Discovery
    direct_flexi_folio = None
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
                    direct_debt_folio = h.folio

    # 1. Target Asset Allocation by Risk Level
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
        target_eq, target_debt = 0.0, 100.0

    items = []

    # Scheme Identifiers
    flexi_scheme = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
    mid_scheme = "Motilal Oswal Midcap Fund - Direct Plan Growth"
    large_scheme = "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"
    pharma_scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
    debt_scheme = "ICICI Prudential Short Term Fund - Direct Plan - Growth"

    if is_starter:
        # Starter Portfolio (< INR 5L AUM): 2 Core Funds
        if target_eq > 0:
            flexi_pct = round(target_eq * 0.60, 1)
            mid_pct = round(target_eq * 0.40, 1)
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Core Flexi-Cap Compounder",
                    scheme_name=flexi_scheme,
                    folio_target=direct_flexi_folio,
                    monthly_inr=round(b * (flexi_pct / 100.0), 2),
                    allocation_pct=flexi_pct,
                    rational_code="CORE_COMPOUNDER",
                    fiduciary_rationale="Core compounding anchor with lowest category TER, global tech diversification, and built-in cash/arbitrage defensive buffer."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=direct_mid_folio,
                    monthly_inr=round(b * (mid_pct / 100.0), 2),
                    allocation_pct=mid_pct,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale="10-Year compounding driver with high risk-adjusted Sharpe and institutional alpha."
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
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Core Flexi-Cap Compounder",
                    scheme_name=flexi_scheme,
                    folio_target=direct_flexi_folio,
                    monthly_inr=round(b * 0.40, 2),
                    allocation_pct=40.0,
                    rational_code="CORE_COMPOUNDER",
                    fiduciary_rationale="Core compounding anchor with lowest category TER, global tech diversification, and built-in cash/arbitrage defensive buffer."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=direct_mid_folio,
                    monthly_inr=round(b * 0.30, 2),
                    allocation_pct=30.0,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale="10-Year compounding driver with high risk-adjusted Sharpe and institutional alpha; reuses active Direct Folio."
                )
            )
            large_rat = f"Top-quartile active large cap (+1.99% 3Y alpha); {'consolidates active Direct Folio #' + direct_large_folio if direct_large_folio else 'initiates bluechip stability anchor'}."
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=direct_large_folio,
                    monthly_inr=round(b * 0.15, 2),
                    allocation_pct=15.0,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale=large_rat
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
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Core Flexi-Cap Compounder",
                    scheme_name=flexi_scheme,
                    folio_target=direct_flexi_folio,
                    monthly_inr=round(b * 0.35, 2),
                    allocation_pct=35.0,
                    rational_code="CORE_COMPOUNDER",
                    fiduciary_rationale="Core compounding anchor with lowest category TER and global tech diversification."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=direct_mid_folio,
                    monthly_inr=round(b * 0.25, 2),
                    allocation_pct=25.0,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale="High-conviction mid-cap alpha driver targeting pricing-power leaders."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=direct_large_folio,
                    monthly_inr=round(b * 0.15, 2),
                    allocation_pct=15.0,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale="Institutional large-cap anchor providing liquidity and low-volatility stability."
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
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Core Flexi-Cap Compounder",
                    scheme_name=flexi_scheme,
                    folio_target=direct_flexi_folio,
                    monthly_inr=round(b * 0.30, 2),
                    allocation_pct=30.0,
                    rational_code="CORE_COMPOUNDER",
                    fiduciary_rationale="Core compounding foundation."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=direct_mid_folio,
                    monthly_inr=round(b * 0.20, 2),
                    allocation_pct=20.0,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale="Selective mid-cap growth exposure."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=direct_large_folio,
                    monthly_inr=round(b * 0.10, 2),
                    allocation_pct=10.0,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale="Bluechip liquidity ballast."
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
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Core Flexi-Cap Compounder",
                    scheme_name=flexi_scheme,
                    folio_target=direct_flexi_folio,
                    monthly_inr=round(b * 0.25, 2),
                    allocation_pct=25.0,
                    rational_code="CORE_COMPOUNDER",
                    fiduciary_rationale="Balanced equity core."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=direct_large_folio,
                    monthly_inr=round(b * 0.15, 2),
                    allocation_pct=15.0,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale="Bluechip ballast."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=direct_mid_folio,
                    monthly_inr=round(b * 0.10, 2),
                    allocation_pct=10.0,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale="Conservative mid-cap tilt."
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
            )
        elif target_debt == 80.0: # Level 2
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=direct_large_folio,
                    monthly_inr=round(b * 0.20, 2),
                    allocation_pct=20.0,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale="Conservative large-cap equity sleeve."
                )
            )
            items.append(
                DeterministicSIPRecommendation(
                    category_role="High-Grade Debt Anchor",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=round(b * 0.80, 2),
                    allocation_pct=80.0,
                    rational_code="DEBT_ANCHOR",
                    fiduciary_rationale="80% debt anchor for capital preservation."
                )
            )
        else: # Level 1
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Capital Preservation Debt",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=round(b, 2),
                    allocation_pct=100.0,
                    rational_code="DEBT_ANCHOR",
                    fiduciary_rationale="100% low-duration high-grade debt."
                )
            )

    # Balance rounding discrepancy if any
    total_allocated = sum(item.monthly_inr for item in items)
    diff = round(b - total_allocated, 2)
    if abs(diff) > 0.0 and items:
        items[0].monthly_inr = round(items[0].monthly_inr + diff, 2)

    return DeterministicSIPPlan(
        total_monthly_budget_inr=b,
        equity_sip_pct=target_eq,
        debt_sip_pct=target_debt,
        items=items
    )

'''

text = text[:idx_start] + new_code + "\n\n" + text[idx_end:]

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: Fully integrated all-levels SIP & Lumpsum engine into core/math_engine.py!")

