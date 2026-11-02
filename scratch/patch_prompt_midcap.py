with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    text = f.read()

target = """2. Slot 2: Mid-Cap Alpha Engine (30% / INR 30,000/mo) -> Motilal Oswal Midcap Fund - Direct Plan
   • Quantitative Profile: Direct TER 0.91%, 3Y Alpha +4.11% to +6.5% vs Nifty Midcap 150 TRI, Sharpe Ratio >0.61-0.85 (top decile).
   • Fiduciary Mandate: High-conviction QGLP framework focusing on pricing-power leaders with high ROCE (>20%) such as Trent, Dixon Technologies, Persistent Systems, and Coforge.
   • Overlap Synergy: Pairwise stock overlap with Parag Parikh Flexi Cap is under 5.0%, ensuring true style diversification rather than duplicate holdings.
   • Operational Continuity: Reuses the client's verified existing Direct Folio #910168305634 on MFCentral, enabling instant 1-click execution.
   • Peers Evaluated & Rejected:
     - Nippon India Growth Fund (Midcap): Rejected because AUM has ballooned past INR 35,000+ Crores, creating severe liquidity drag and forcing the manager to hold large-cap proxies.
     - HDFC Mid-Cap Opportunities: Already held in regular plan (INR 1.39L); Motilal offers higher active share and alpha density.
     - Kotak Emerging Equity: Over-diversified (75+ holdings), diluting conviction and active alpha potential."""

replacement = """2. Slot 2: Mid-Cap Alpha Engine (30% / INR 30,000/mo) -> HDFC Mid-Cap Opportunities Direct [Fiduciary Default] vs Motilal Oswal Midcap Direct [High-Beta Alternative]
   • Quantitative Profile (HDFC Mid-Cap Direct): Direct TER 0.76% (saves 15 bps/yr vs Motilal's 0.91%), Sharpe Ratio 0.62 (superior risk-adjusted return), 3Y Alpha +2.44%, 80-stock diversification (prevents concentration blowups), Top-10 concentration only 37.05%.
   • Operational Continuity: Reuses verified HDFC Folio #22403163, seamlessly consolidating the client's existing INR 1.39L Regular holding into Direct at zero friction.
   • The Fiduciary Case vs Motilal Oswal Midcap:
     - While Motilal Oswal delivers high trailing 3Y alpha (+4.11%), it carries severe structural risks: hyper-concentration (54.61% of fund in just 10 stocks across only 31 holdings), a steep 0.91% TER, and heavy momentum valuation exposure.
     - Most importantly, the client ALREADY holds INR 3.68 Lakhs in Motilal Midcap (INR 3.10L Regular + INR 58k Direct). Adding an ongoing INR 30,000/month fresh SIP into Motilal balloons exposure to >14% of portfolio net worth in a single volatile fund.
     - Therefore, HDFC Mid-Cap Opportunities Direct is the recommended institutional core ballast, while Motilal Oswal Midcap Direct remains selectable for aggressive momentum seekers who accept 55% top-10 concentration.
   • Other Peers Evaluated & Rejected:
     - Nippon India Growth Fund: AUM swollen past INR 35,000+ Cr, creating severe liquidity drag and forced large-cap dilution.
     - Kotak Emerging Equity: Over-diversified (75+ holdings) with lower active conviction.
     - Nifty Midcap 150 Index: Pure beta with zero downside protection in midcap drawdowns; active mid-cap management adds +2.4% to +4.1% true alpha."""

if target not in text:
    print("ERROR: Target text not found in core/prompt_advisor.py!")
else:
    text = text.replace(target, replacement, 1)
    with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("SUCCESS: core/prompt_advisor.py updated with HDFC vs Motilal fiduciary analysis!")

