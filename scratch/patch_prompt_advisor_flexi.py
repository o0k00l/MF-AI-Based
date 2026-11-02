with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    text = f.read()

# Replace Slot 1 in dossier:
target_dossier = """1. Slot 1: Core Flexi-Cap Compounder (40% / INR 40,000/mo) -> Parag Parikh Flexi Cap Fund - Direct Plan
   • Quantitative Profile: Direct TER 0.69% (saves 1.05%/yr vs Regular TER 1.74%), 3Y Alpha +3.83%, Sharpe Ratio 0.64.
   • Fiduciary Mandate: Unconstrained domestic multi-cap compounding anchor with a proven ~15-18% cash, arbitrage, and international tech equity allocation (Alphabet, Microsoft, Meta) that provides an organic drawdown cushion. Managed by Rajeev Thakkar since inception.
   • Overlap Synergy: Baseline core holding with low correlation to pure mid-caps.
   • Peers Evaluated & Rejected:
     - HDFC Flexi Cap: Rejected for fresh SIP because the client already holds INR 6.18L in HDFC Flexi Cap (Regular); adding more increases single-AMC and single-manager concentration risk.
     - Quant Flexi Cap: Rejected due to hyper-turnover (>150% portfolio turnover ratio), aggressive momentum rotation, and high drawdown volatility unsuitable for the primary 40% ballast.
     - JM Flexi Cap: Shorter track record through a full market cycle; lacks PPFAS's downside cash/global buffer."""

replacement_dossier = """1. Slot 1: Core Flexi-Cap Compounder (40% / INR 40,000/mo) -> 50:50 Core Blend [Recommended Fiduciary Strategy] vs Standalone PPFAS / HDFC Flexi Cap
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
     - JM Flexi Cap Direct: Agile small-AUM (~INR 5,000 Cr, lowest 0.45% TER) for aggressive alpha seekers without size drag."""

assert target_dossier in text, "target_dossier not found in prompt_advisor.py!"
text = text.replace(target_dossier, replacement_dossier, 1)

# Also update section 5 deep dive:
target_dive = """   - **Parag Parikh Flexi Cap Fund (Direct):** Core compounding mandate, low 0.69% TER (1.05% fee alpha), 15-18% cash/arbitrage/US equity drawdown cushion, and why HDFC Flexi Cap and Quant Flexi Cap were rejected.
   - **Motilal Oswal Midcap Fund (Direct):** Pure alpha engine, +4.11% to +6.5% 3Y alpha, QGLP high ROCE stock selection, <5% pairwise overlap with PPFAS, existing Direct Folio #910168305634 continuity, and why Nippon Midcap and Kotak Emerging were rejected.
   - **Nippon India Large Cap Fund (Direct):** Large-cap anchor, +1.99% active alpha, low beta ballast (0.88), consolidation of Direct Folio #477486710296, and why passive Nifty 50 was rejected."""

replacement_dive = """   - **Core Flexi-Cap Compounder (50:50 Blend vs Standalone PPFAS):** Objective fiduciary evaluation detailing the 0.69% TER and global tech ballast of Parag Parikh Flexi Cap Direct, alongside its real headwinds (AUM bloat >INR 85,000 Cr, frozen RBI foreign remittance cap, and client overconcentration risk). Explain the mathematical rationale for blending 20% PPFAS Direct with 20% HDFC Flexi Cap Direct (+5.27% domestic alpha, Roshi Jain, Folio #44678193).
   - **Mid-Cap Alpha Engine (HDFC Mid-Cap Direct vs Motilal Oswal Midcap Direct):** Fiduciary core recommendation of HDFC Mid-Cap Opportunities Direct (0.76% TER, 80 stocks, Sharpe 0.62, Folio #22403163) vs Motilal Oswal Midcap Direct (0.91% TER, 31 stocks, 55% top-10 concentration, high momentum alpha).
   - **Large-Cap Bluechip Anchor (HDFC Nifty 50 Index Direct vs Nippon India Large Cap Direct):** Fiduciary core recommendation of HDFC Nifty 50 Index Direct (0.18% TER, saving 70 bps/yr, SPIVA alignment, eliminating Lalit's 15.2% Nippon AMC overconcentration) vs active Nippon India Large Cap Direct (0.88% TER, Folio #477486710296)."""

assert target_dive in text, "target_dive not found in prompt_advisor.py!"
text = text.replace(target_dive, replacement_dive, 1)

with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: prompt_advisor.py updated with objective PPFAS audit and multi-strategy options!")

