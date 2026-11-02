with open("core/prompt_advisor.py", "r", encoding="utf-8") as f:
    text = f.read()

target = """3. Slot 3: Large-Cap Bluechip Anchor (15% / INR 15,000/mo) -> Nippon India Large Cap Fund - Direct Plan
   • Quantitative Profile: Direct TER 0.88%, 3Y Alpha +1.99% vs Nifty 100 TRI, Beta 0.88.
   • Fiduciary Mandate: Rare active large-cap fund consistently outperforming its benchmark in a category where >85% of active funds fail. Provides liquidity ballast and low-volatility stability during market corrections.
   • Operational Continuity: Consolidates and scales the client's existing verified Direct Folio #477486710296.
   • Peers Evaluated & Rejected:
     - Passive Nifty 50 Index / ETF: Passive funds hold overvalued index heavyweights with zero downside protection; Nippon active large cap delivers consistent +1.99% alpha through defensive sector rotation.
     - SBI Bluechip / ICICI Bluechip: Flatter 3-year risk-adjusted returns and lower active share."""

replacement = """3. Slot 3: Large-Cap Bluechip Anchor (15% / INR 15,000/mo) -> HDFC Nifty 50 Index Direct [Fiduciary Default] vs Nippon India Large Cap Direct [Active Alpha Alternative]
   • Quantitative Profile (HDFC Nifty 50 Index Direct): Direct TER 0.18% (saves 70 bps/yr vs Nippon Large Cap's 0.88%), tracking error <0.05%, zero manager key-man risk.
   • The Fiduciary Case vs Active Nippon Large Cap:
     - The SPIVA Reality: Over 85% to 90% of active large-cap mutual funds fail to beat the Nifty 50 TRI over 5-10 year rolling cycles due to the hyper-efficiency of India's top 100 stocks.
     - Look-Through Index Hugging: Nippon Large Cap's top holdings (HDFC Bank, ICICI Bank, Reliance, Infosys, TCS, L&T, SBI) are virtually identical to the Nifty 50 index weights (44.7% in top 10). Paying an active 0.88% TER to hold the index creates structural fee drag.
     - Eliminating Nippon AMC Concentration: Lalit already holds INR 7.85 Lakhs (15.2% of his total net worth) in Nippon India across 4 separate folios (Nippon Multi Cap INR 5.30L + Nippon Large Cap INR 2.55L). Recommending both Nippon Large Cap AND Nippon Pharma would channel 30% of fresh monthly savings into a single AMC. Switching large-cap fresh money to HDFC Nifty 50 Index reuses verified Folio #44678193 and eliminates single-AMC concentration.
     - Active Alternative Retained: For investors seeking active tactical rotation, Nippon India Large Cap Direct (+1.99% 3Y alpha, 0.88 beta) remains selectable and reuses Direct Folio #477486710296.
   • Other Peers Evaluated & Rejected:
     - Nifty Next 50 Index: Available as an alternative for investors seeking higher large-cap growth without manager risk (0.28% TER).
     - SBI Bluechip / ICICI Bluechip: Flatter 3-year risk-adjusted returns and higher fee friction."""

if target not in text:
    print("ERROR: Target text not found in core/prompt_advisor.py!")
else:
    text = text.replace(target, replacement, 1)
    with open("core/prompt_advisor.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("SUCCESS: core/prompt_advisor.py updated with Large Cap fiduciary analysis!")

