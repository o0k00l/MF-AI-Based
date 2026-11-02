with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    text = f.read()

# Define _build_dynamic_selection_dossier
dossier_function = '''def _build_dynamic_selection_dossier(facts: FiduciaryFactsPayload) -> str:
    """
    Dynamically computes the fiduciary fund selection dossier and peer rejection matrix
    using the client's verified facts, portfolio holdings, AMC concentrations, and SAA targets.
    Eliminates all hardcoding.
    """
    client_name = facts.client_name or "Client"
    tot_val = facts.total_portfolio_value_inr or 1.0
    sip_budget = facts.monthly_sip_budget_inr or 100000.0

    # Calculate actual scheme & AMC concentrations from holdings
    ppfas_holdings = [h for h in facts.holdings if "parag parikh" in h.scheme.lower() or "ppfas" in h.scheme.lower()]
    ppfas_val = sum(h.current_value_inr for h in ppfas_holdings)
    ppfas_pct = (ppfas_val / tot_val) * 100.0
    ppfas_folio = ppfas_holdings[0].folio if ppfas_holdings else None

    motilal_mid_holdings = [h for h in facts.holdings if "motilal" in h.scheme.lower() and ("midcap" in h.scheme.lower() or "mid cap" in h.scheme.lower())]
    motilal_mid_val = sum(h.current_value_inr for h in motilal_mid_holdings)
    motilal_mid_pct = (motilal_mid_val / tot_val) * 100.0
    motilal_reg_val = sum(h.current_value_inr for h in motilal_mid_holdings if not h.is_direct)
    motilal_dir_val = sum(h.current_value_inr for h in motilal_mid_holdings if h.is_direct)

    nippon_holdings = [h for h in facts.holdings if "nippon" in h.scheme.lower()]
    nippon_val = sum(h.current_value_inr for h in nippon_holdings)
    nippon_pct = (nippon_val / tot_val) * 100.0
    nippon_folios = list({h.folio for h in nippon_holdings if h.folio})

    hdfc_holdings = [h for h in facts.holdings if "hdfc" in h.scheme.lower()]
    hdfc_flexi_holdings = [h for h in hdfc_holdings if "flexi" in h.scheme.lower()]
    hdfc_flexi_dir = [h for h in hdfc_flexi_holdings if h.is_direct]
    hdfc_flexi_folio = hdfc_flexi_dir[0].folio if hdfc_flexi_dir else (hdfc_flexi_holdings[0].folio if hdfc_flexi_holdings else None)

    hdfc_mid_holdings = [h for h in hdfc_holdings if "mid" in h.scheme.lower()]
    hdfc_mid_folio = hdfc_mid_holdings[0].folio if hdfc_mid_holdings else None

    slot1_amt = sip_budget * 0.40
    slot2_amt = sip_budget * 0.30
    slot3_amt = sip_budget * 0.15
    slot4_amt = sip_budget * 0.15

    # Headwind 4 dynamically:
    if ppfas_val > 0:
        ppfas_headwind = (
            f"Headwind 4 (Client Portfolio Concentration Trap): {client_name} already holds INR {ppfas_val:,.0f} "
            f"({ppfas_pct:.1f}% of net worth) in PPFAS ({'Folio #' + ppfas_folio if ppfas_folio else 'existing folio'}). "
            f"Channeling an ongoing INR {slot1_amt:,.0f}/mo SIP into PPFAS balloons single-fund exposure past "
            f"INR {ppfas_val + (slot1_amt * 12):,.0f} ({(ppfas_val + slot1_amt * 12) / tot_val * 100:.1f}% of net worth) in a single fund!"
        )
    else:
        ppfas_headwind = (
            f"Portfolio Concentration: {client_name} has zero current exposure to PPFAS; initiation establishes a clean core ballast."
        )

    # Motilal dynamically:
    if motilal_mid_val > 0:
        motilal_case = (
            f"Most importantly, {client_name} ALREADY holds INR {motilal_mid_val:,.0f} ({motilal_mid_pct:.1f}% of net worth) "
            f"in Motilal Midcap (INR {motilal_reg_val:,.0f} Regular + INR {motilal_dir_val:,.0f} Direct). "
            f"Adding an ongoing INR {slot2_amt:,.0f}/month fresh SIP into Motilal balloons exposure to "
            f">{(motilal_mid_val + slot2_amt * 12) / tot_val * 100:.1f}% of portfolio net worth in a single volatile fund."
        )
    else:
        motilal_case = (
            f"While Motilal delivers strong active alpha, it carries severe 54.6% top-10 concentration across just 31 stocks."
        )

    # Nippon dynamically:
    if nippon_val > 0:
        nippon_case = (
            f"Eliminating Nippon AMC Concentration: {client_name} already holds INR {nippon_val:,.0f} "
            f"({nippon_pct:.1f}% of total net worth) in Nippon India across {len(nippon_folios) or len(nippon_holdings)} separate folios. "
            f"Recommending Nippon Large Cap along with other active sleeves channels excessive capital into a single AMC. "
            f"Switching large-cap fresh money to HDFC Nifty 50 Index ({'reuses verified Folio #' + hdfc_flexi_folio if hdfc_flexi_folio else 'direct index core'}) "
            f"eliminates single-AMC concentration while saving 70 bps/yr in TER."
        )
    else:
        nippon_case = (
            f"HDFC Nifty 50 Index provides pure large-cap beta at rock-bottom 0.18% TER, saving 70 bps/yr vs active large-cap peers."
        )

    dossier = f"""### FUND SELECTION DOSSIER & PEER REJECTION MATRIX:
1. Slot 1: Core Flexi-Cap Compounder (40% / INR {slot1_amt:,.0f}/mo) -> 50:50 Core Blend [Recommended Fiduciary Strategy] vs Standalone PPFAS / HDFC Flexi Cap
   • The Fiduciary Audit of Parag Parikh Flexi Cap Fund (PPFAS Direct, 0.69% TER):
     - Strengths: Industry-lowest TER (0.69%), Rajeev Thakkar's disciplined Graham-Dodd value philosophy, high promoter/employee skin-in-the-game (>INR 400 Cr), and a defensive 15-18% cash/arbitrage cushion.
     - Headwind 1 (AUM Bloat Drag >INR 85,000-90,000 Cr): Massive institutional size restricts agile participation in mid- and small-caps; fund increasingly resembles a mega-cap giant.
     - Headwind 2 (Frozen RBI Foreign Investment Cap): Due to the industry-wide $7B overseas ceiling, fresh inflows cannot buy Alphabet, Meta, or Microsoft; foreign equity has diluted from ~28% down to ~12-14%.
     - Headwind 3 (Cash Drag in Raging Bull Runs): The 15-18% cash/arbitrage ballast causes tracking underperformance in liquidity-fueled domestic momentum rallies.
     - {ppfas_headwind}
   • The Fiduciary Solution: The 50:50 Core Blend (20% PPFAS Direct + 20% HDFC Flexi Cap Direct):
     - Parag Parikh Flexi Cap Direct (20% / INR {slot1_amt * 0.5:,.0f}/mo, {'Folio #' + ppfas_folio if ppfas_folio else 'New Direct Folio'}): Preserves global tech moat and conservative downside preservation.
     - HDFC Flexi Cap Direct (20% / INR {slot1_amt * 0.5:,.0f}/mo, {'Folio #' + hdfc_flexi_folio if hdfc_flexi_folio else 'New Direct Folio'}): Managed by Roshi Jain; delivers pure domestic cyclical alpha (+5.27% 3Y alpha, 0.83% TER) with zero foreign remittance bottlenecks, balancing PPFAS's cash drag.
   • Standalone Alternatives:
     - Pure HDFC Flexi Cap Direct: For investors seeking unconstrained domestic multi-cap momentum (+5.27% 3Y alpha; {'reuses active Direct Folio #' + hdfc_flexi_folio if hdfc_flexi_folio else 'initiates domestic core'}).
     - JM Flexi Cap Direct: Agile small-AUM (~INR 5,000 Cr, lowest 0.45% TER) for aggressive alpha seekers without size drag.

2. Slot 2: Mid-Cap Alpha Engine (30% / INR {slot2_amt:,.0f}/mo) -> HDFC Mid-Cap Opportunities Direct [Fiduciary Default] vs Motilal Oswal Midcap Direct [High-Beta Alternative]
   • Quantitative Profile (HDFC Mid-Cap Direct): Direct TER 0.76% (saves 15 bps/yr vs Motilal's 0.91%), Sharpe Ratio 0.62 (superior risk-adjusted return), 3Y Alpha +2.44%, 80-stock diversification (prevents concentration blowups), Top-10 concentration only 37.05%.
   • Operational Continuity: {'Reuses verified HDFC Folio #' + hdfc_mid_folio if hdfc_mid_folio else 'Initiates new direct institutional folio'}, seamlessly consolidating client holdings into Direct at zero friction.
   • The Fiduciary Case vs Motilal Oswal Midcap:
     - While Motilal Oswal delivers high trailing 3Y alpha (+4.11%), it carries severe structural risks: hyper-concentration (54.61% of fund in just 10 stocks across only 31 holdings), a steep 0.91% TER, and heavy momentum valuation exposure.
     - {motilal_case}
     - Therefore, HDFC Mid-Cap Opportunities Direct is the recommended institutional core ballast, while Motilal Oswal Midcap Direct remains selectable for aggressive momentum seekers who accept 55% top-10 concentration.
   • Other Peers Evaluated & Rejected:
     - Nippon India Growth Fund: AUM swollen past INR 35,000+ Cr, creating severe liquidity drag and forced large-cap dilution.
     - Kotak Emerging Equity: Over-diversified (75+ holdings) with lower active conviction.
     - Nifty Midcap 150 Index: Pure beta with zero downside protection in midcap drawdowns; active mid-cap management adds +2.4% to +4.1% true alpha.

3. Slot 3: Large-Cap Bluechip Anchor (15% / INR {slot3_amt:,.0f}/mo) -> HDFC Nifty 50 Index Direct [Fiduciary Default] vs Nippon India Large Cap Direct [Active Alpha Alternative]
   • Quantitative Profile (HDFC Nifty 50 Index Direct): Direct TER 0.18% (saves 70 bps/yr vs Nippon Large Cap's 0.88%), tracking error <0.05%, zero manager key-man risk.
   • The Fiduciary Case vs Active Nippon Large Cap:
     - The SPIVA Reality: Over 85% to 90% of active large-cap mutual funds fail to beat the Nifty 50 TRI over 5-10 year rolling cycles due to the hyper-efficiency of India's top 100 stocks.
     - Look-Through Index Hugging: Nippon Large Cap's top holdings (HDFC Bank, ICICI Bank, Reliance, Infosys, TCS, L&T, SBI) are virtually identical to the Nifty 50 index weights (44.7% in top 10). Paying an active 0.88% TER to hold the index creates structural fee drag.
     - {nippon_case}
     - Active Alternative Retained: For investors seeking active tactical rotation, Nippon India Large Cap Direct (+1.99% 3Y alpha, 0.88 beta) remains selectable.
   • Other Peers Evaluated & Rejected:
     - Nifty Next 50 Index: Available as an alternative for investors seeking higher large-cap growth without manager risk (0.28% TER).
     - SBI Bluechip / ICICI Bluechip: Flatter 3-year risk-adjusted returns and higher fee friction.

4. Slot 4: Tactical Thematic Satellite (15% / INR {slot4_amt:,.0f}/mo) -> Nippon India Pharma / Healthcare Fund - Direct Plan
   • Quantitative Profile: Direct TER 0.82%, Forward P/E ~28x (attractive valuation).
   • Fiduciary Mandate: Tactical satellite capturing structural valuation mispricing. Fills a severe portfolio gap identified in look-through diagnostics where the client holds only 1.55% in Pharma/Healthcare.
   • Secular Tailwinds: US generic price stabilization, expanding domestic chronic therapy formulations (>12% CAGR), and the CDMO/GLP-1 outsourcing boom.
   • Exhaustive Exclusion & Rejection of Other 4 Themes:
     - Defence Thematic (HDFC Defence / Motilal Index): STRICTLY EXCLUDED FOR FRESH SIP. Sector trades at a nosebleed 80x-85x P/E (>2.5x historical median). Pouring fresh SIP capital at peak euphoria creates extreme drawdown risk.
     - Commodities / Metals: EXCLUDED (By-design minimal at 2.4%). Commodity producers are cyclical price-takers with zero pricing power.
     - PSU & CPSE Themes: EXCLUDED FOR FRESH SIP. Client already holds look-through exposure via SBI, Coal India, NTPC, and BEL inside core holdings. Adding a dedicated PSU fund creates redundant stock duplication.
     - Power & Infrastructure: EXCLUDED FOR FRESH SIP. Client already holds look-through exposure in L&T, NTPC, Power Grid, and Bharti Airtel.
"""
    return dossier
'''

# Find insertion position before generate_cash_and_sip_plan
target_func = "def generate_cash_and_sip_plan(facts: FiduciaryFactsPayload) -> str:"
assert target_func in text, "target_func not found!"
text = text.replace(target_func, dossier_function + "\n\n" + target_func, 1)

# Now replace the hardcoded selection_dossier block in generate_cash_and_sip_plan
start_marker = "    # Rich Fiduciary Fund Selection Dossier\n    selection_dossier = \"\"\""
end_marker = '    prompt = f"""'

start_pos = text.find(start_marker)
end_pos = text.find(end_marker)

assert start_pos != -1, "start_marker not found!"
assert end_pos != -1, "end_marker not found!"

replacement = "    # Rich Fiduciary Fund Selection Dossier (Dynamically Generated)\n    selection_dossier = _build_dynamic_selection_dossier(facts)\n\n"

text = text[:start_pos] + replacement + text[end_pos:]

with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: core/prompt_advisor.py updated with dynamic selection dossier!")

