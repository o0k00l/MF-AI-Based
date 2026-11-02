with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    text = f.read()

# Replace the static selection_dossier in generate_cash_and_sip_plan
old_dossier_block = """    # Rich Fiduciary Fund Selection Dossier
    selection_dossier = \"\"\"
### FUND SELECTION DOSSIER & PEER REJECTION MATRIX:
1. Slot 1: Core Flexi-Cap Compounder (40% / INR 40,000/mo) -> 50:50 Core Blend [Recommended Fiduciary Strategy] vs Standalone PPFAS / HDFC Flexi Cap
   • The Fiduciary Audit of Parag Parikh Flexi Cap Fund (PPFAS Direct, 0.69% TER):
     - Strengths: Industry-lowest TER (0.69%), Rajeev Thakkar's disciplined Graham-Dodd value philosophy, high promoter/employee skin-in-the-game (>INR 400 Cr), and a defensive 15-18% cash/arbitrage cushion.
     - Headwind 1 (AUM Bloat Drag >INR 85,000-90,000 Cr): Massive institutional size restricts agile participation in mid- and small-caps; fund increasingly resembles a mega-cap giant.
     - Headwind 2 (Frozen RBI Foreign Investment Cap): Due to the industry-wide $7B overseas ceiling, fresh inflows cannot buy Alphabet, Meta, or Microsoft; foreign equity has diluted from ~28% down to ~12-14%.
     - Headwind 3 (Cash Drag in Raging Bull Runs): The 15-18% cash/arbitrage ballast causes tracking underperformance in liquidity-fueled domestic momentum rallies.
     - Headwind 4 (Client Portfolio Concentration Trap): Lalit already holds INR 5,34,145 in PPFAS (Folio #14596617). Channeling all INR 40k/mo SIP + INR 1.60L lumpsum into PPFAS balloons single-fund exposure past INR 11.7 Lakhs (>22% of total net worth)!
   • The Fiduciary Solution: The 50:50 Core Blend (20% PPFAS Direct + 20% HDFC Flexi Cap Direct):
     - Parag Parikh Flexi Cap Direct (20% / INR 20,000/mo, Folio #14596617): Preserves global tech moat and conservative downside preservation.
     - HDFC Flexi Cap Direct (20% / INR 20,000/mo, Folio #44678193): Managed by Roshi Jain; delivers pure domestic cyclical alpha (+5.27% 3Y alpha, 0.83% TER) with zero foreign remittance bottlenecks, balancing PPFAS's cash drag.
   • Standalone Alternatives:
     - Pure HDFC Flexi Cap Direct: For investors seeking unconstrained domestic multi-cap momentum (+5.27% 3Y alpha; reuses active Direct Folio #44678193).
     - JM Flexi Cap Direct: Agile small-AUM (~INR 5,000 Cr, lowest 0.45% TER) for aggressive alpha seekers without size drag.

2. Slot 2: Mid-Cap Alpha Engine (30% / INR 30,000/mo) -> HDFC Mid-Cap Opportunities Direct [Fiduciary Default] vs Motilal Oswal Midcap Direct [High-Beta Alternative]
   • Quantitative Profile (HDFC Mid-Cap Direct): Direct TER 0.76% (saves 15 bps/yr vs Motilal's 0.91%), Sharpe Ratio 0.62 (superior risk-adjusted return), 3Y Alpha +2.44%, 80-stock diversification (prevents concentration blowups), Top-10 concentration only 37.05%.
   • Operational Continuity: Reuses verified HDFC Folio #22403163, seamlessly consolidating the client's existing INR 1.39L Regular holding into Direct at zero friction.
   • The Fiduciary Case vs Motilal Oswal Midcap:
     - While Motilal Oswal delivers high trailing 3Y alpha (+4.11%), it carries severe structural risks: hyper-concentration (54.61% of fund in just 10 stocks across only 31 holdings), a steep 0.91% TER, and heavy momentum valuation exposure.
     - Most importantly, the client ALREADY holds INR 3.68 Lakhs in Motilal Midcap (INR 3.10L Regular + INR 58k Direct). Adding an ongoing INR 30,000/month fresh SIP into Motilal balloons exposure to >14% of portfolio net worth in a single volatile fund.
     - Therefore, HDFC Mid-Cap Opportunities Direct is the recommended institutional core ballast, while Motilal Oswal Midcap Direct remains selectable for aggressive momentum seekers who accept 55% top-10 concentration.
   • Other Peers Evaluated & Rejected:
     - Nippon India Growth Fund: AUM swollen past INR 35,000+ Cr, creating severe liquidity drag and forced large-cap dilution.
     - Kotak Emerging Equity: Over-diversified (75+ holdings) with lower active conviction.
     - Nifty Midcap 150 Index: Pure beta with zero downside protection in midcap drawdowns; active mid-cap management adds +2.4% to +4.1% true alpha.

3. Slot 3: Large-Cap Bluechip Anchor (15% / INR 15,000/mo) -> HDFC Nifty 50 Index Direct [Fiduciary Default] vs Nippon India Large Cap Direct [Active Alpha Alternative]
   • Quantitative Profile (HDFC Nifty 50 Index Direct): Direct TER 0.18% (saves 70 bps/yr vs Nippon Large Cap's 0.88%), tracking error <0.05%, zero manager key-man risk.
   • The Fiduciary Case vs Active Nippon Large Cap:
     - The SPIVA Reality: Over 85% to 90% of active large-cap mutual funds fail to beat the Nifty 50 TRI over 5-10 year rolling cycles due to the hyper-efficiency of India's top 100 stocks.
     - Look-Through Index Hugging: Nippon Large Cap's top holdings (HDFC Bank, ICICI Bank, Reliance, Infosys, TCS, L&T, SBI) are virtually identical to the Nifty 50 index weights (44.7% in top 10). Paying an active 0.88% TER to hold the index creates structural fee drag.
     - Eliminating Nippon AMC Concentration: Lalit already holds INR 7.85 Lakhs (15.2% of his total net worth) in Nippon India across 4 separate folios (Nippon Multi Cap INR 5.30L + Nippon Large Cap INR 2.55L). Recommending both Nippon Large Cap AND Nippon Pharma would channel 30% of fresh monthly savings into a single AMC. Switching large-cap fresh money to HDFC Nifty 50 Index reuses verified Folio #44678193 and eliminates single-AMC concentration.
     - Active Alternative Retained: For investors seeking active tactical rotation, Nippon India Large Cap Direct (+1.99% 3Y alpha, 0.88 beta) remains selectable and reuses Direct Folio #477486710296.
   • Other Peers Evaluated & Rejected:
     - Nifty Next 50 Index: Available as an alternative for investors seeking higher large-cap growth without manager risk (0.28% TER).
     - SBI Bluechip / ICICI Bluechip: Flatter 3-year risk-adjusted returns and higher fee friction.

4. Slot 4: Tactical Thematic Satellite (15% / INR 15,000/mo) -> Nippon India Pharma / Healthcare Fund - Direct Plan
   • Quantitative Profile: Direct TER 0.82%, Forward P/E ~28x (attractive valuation).
   • Fiduciary Mandate: Tactical satellite capturing structural valuation mispricing. Fills a severe portfolio gap identified in look-through diagnostics where the client holds only 1.55% in Pharma/Healthcare.
   • Secular Tailwinds: US generic price stabilization, expanding domestic chronic therapy formulations (>12% CAGR), and the CDMO/GLP-1 outsourcing boom.
   • Exhaustive Exclusion & Rejection of Other 4 Themes:
     - Defence Thematic (HDFC Defence / Motilal Index): STRICTLY EXCLUDED FOR FRESH SIP. Portfolio already carries 5.98% dedicated exposure (INR 3.09 Lakhs) plus 3.5% look-through bluechips. The sector trades at a nosebleed 80x-85x P/E (>2.5x historical median). Pouring fresh SIP capital at peak euphoria creates extreme drawdown risk.
     - Commodities / Metals: EXCLUDED (By-design minimal at 2.4%). Commodity producers are cyclical price-takers with zero pricing power.
     - PSU & CPSE Themes: EXCLUDED FOR FRESH SIP. Client already holds 6.19% look-through exposure via SBI, Coal India, NTPC, and BEL inside core holdings. Adding a dedicated PSU fund creates redundant stock duplication.
     - Power & Infrastructure: EXCLUDED FOR FRESH SIP. Client already holds 5.11% look-through exposure in L&T, NTPC, Power Grid, and Bharti Airtel.
\"\"\""""

new_dossier_call = """    # Rich Fiduciary Fund Selection Dossier (Dynamically Generated)
    selection_dossier = _build_dynamic_selection_dossier(facts)"""

assert old_dossier_block in text, "old_dossier_block not found in prompt_advisor.py!"
text = text.replace(old_dossier_block, new_dossier_call, 1)

# Also clean up the line in section 5 deep dive:
text = text.replace(
    "eliminating Lalit's 15.2% Nippon AMC overconcentration",
    "eliminating single-AMC overconcentration"
)

with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: prompt_advisor.py cleaned of all static dossier text and hardcoded numbers!")

