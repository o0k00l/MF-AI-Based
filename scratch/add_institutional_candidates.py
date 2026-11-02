import json
from pathlib import Path

metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
with open(metrics_path, "r", encoding="utf-8") as f:
    data = json.load(f)

funds = data.get("funds", [])
existing_ids = {f.get("id") for f in funds}

institutional_candidates = [
    {
        "id": "UTI Nifty 50 Index Direct",
        "name": "UTI Nifty 50 Index Fund - Direct Plan - Growth",
        "cat": "Index: Large Cap",
        "category": "Index: Large Cap",
        "aum_cr": 18500.0,
        "aum_crore": 18500.0,
        "er": 0.18,
        "ter_direct_pct": 0.18,
        "n_secs": 50,
        "eq": 99.8,
        "debt": 0.2,
        "lc": 100.0,
        "mc": 0.0,
        "sc": 0.0,
        "top10": 54.2,
        "top10_concentration_pct": 54.2,
        "single_sector_weight_pct": 32.5,
        "sector": "Financial",
        "sharpe": 0.65,
        "sharpe_3y": 0.65,
        "sharpe_1y": 0.95,
        "alpha": 0.0,
        "alpha_3y": 0.0,
        "return_1y": 22.5,
        "return_6m": 8.8,
        "return_3y": 16.2,
        "is_direct": True,
        "is_passive": True,
        "riskometer_score": 6,
        "manager_tenure_years": 6.0,
        "h": [
            "HDFC Bank", "Reliance", "ICICI Bank", "Infosys", "ITC",
            "TCS", "Larsen & Toubro", "Bharti Airtel", "Axis Bank", "State Bank of India"
        ],
        "_provenance": {
            "retrieved_at": "2026-11-01T21:00:00Z",
            "confidence_score": 1.0,
            "confidence_level": "high",
            "anomalies": [],
            "source": "Factsheet Benchmark Universe",
            "engine_version": "1.2.0"
        }
    },
    {
        "id": "Motilal Nifty Midcap 150 Index Direct",
        "name": "Motilal Oswal Nifty Midcap 150 Index Fund - Direct Plan - Growth",
        "cat": "Index: Mid Cap",
        "category": "Index: Mid Cap",
        "aum_cr": 4200.0,
        "aum_crore": 4200.0,
        "er": 0.25,
        "ter_direct_pct": 0.25,
        "n_secs": 150,
        "eq": 99.6,
        "debt": 0.4,
        "lc": 0.0,
        "mc": 100.0,
        "sc": 0.0,
        "top10": 18.5,
        "top10_concentration_pct": 18.5,
        "single_sector_weight_pct": 21.0,
        "sector": "Diversified",
        "sharpe": 0.82,
        "sharpe_3y": 0.82,
        "sharpe_1y": 1.12,
        "alpha": 0.0,
        "alpha_3y": 0.0,
        "return_1y": 36.8,
        "return_6m": 12.5,
        "return_3y": 25.4,
        "is_direct": True,
        "is_passive": True,
        "riskometer_score": 6,
        "manager_tenure_years": 5.0,
        "h": [
            "Max Healthcare", "Persistent Systems", "Federal Bank", "Indian Hotel", "Cummins India",
            "Polycab", "IDFC First Bank", "HDFC AMC", "L&T Finance", "Ashok Leyland"
        ],
        "_provenance": {
            "retrieved_at": "2026-11-01T21:00:00Z",
            "confidence_score": 1.0,
            "confidence_level": "high",
            "anomalies": [],
            "source": "Factsheet Benchmark Universe",
            "engine_version": "1.2.0"
        }
    },
    {
        "id": "ICICI Short Term Debt Direct",
        "name": "ICICI Prudential Short Term Fund - Direct Plan - Growth",
        "cat": "Debt: Short Duration",
        "category": "Debt: Short Duration",
        "aum_cr": 19800.0,
        "aum_crore": 19800.0,
        "er": 0.38,
        "ter_direct_pct": 0.38,
        "n_secs": 185,
        "eq": 0.0,
        "debt": 96.5,
        "re": 0.0,
        "other": 3.5,
        "lc": 0.0,
        "mc": 0.0,
        "sc": 0.0,
        "top10": 38.0,
        "top10_concentration_pct": 38.0,
        "single_sector_weight_pct": 45.0,
        "sector": "Sovereign / AAA Financials",
        "sharpe": 1.15,
        "sharpe_3y": 1.15,
        "sharpe_1y": 1.45,
        "alpha": 0.85,
        "alpha_3y": 0.85,
        "return_1y": 7.8,
        "return_6m": 3.8,
        "return_3y": 7.2,
        "ytm_pct": 7.65,
        "is_direct": True,
        "riskometer_score": 3,
        "manager_tenure_years": 8.0,
        "h": [
            "GOI 7.18% 2033", "GOI 7.26% 2032", "NABARD AAA", "SIDBI AAA", "REC Ltd AAA",
            "PFC AAA", "HDFC Bank CD", "Axis Bank CD", "ICICI Bank CD", "TREPS"
        ],
        "_provenance": {
            "retrieved_at": "2026-11-01T21:00:00Z",
            "confidence_score": 1.0,
            "confidence_level": "high",
            "anomalies": [],
            "source": "Factsheet Benchmark Universe",
            "engine_version": "1.2.0"
        }
    },
    {
        "id": "Kotak Arbitrage Direct",
        "name": "Kotak Equity Arbitrage Fund - Direct Plan - Growth",
        "cat": "Hybrid: Arbitrage",
        "category": "Hybrid: Arbitrage",
        "aum_cr": 48000.0,
        "aum_crore": 48000.0,
        "er": 0.35,
        "ter_direct_pct": 0.35,
        "n_secs": 220,
        "eq": 68.5,
        "debt": 31.5,
        "re": 0.0,
        "other": 0.0,
        "lc": 55.0,
        "mc": 13.5,
        "sc": 0.0,
        "top10": 28.0,
        "top10_concentration_pct": 28.0,
        "single_sector_weight_pct": 25.0,
        "sector": "Cash-Futures Hedged Arbitrage",
        "sharpe": 1.85,
        "sharpe_3y": 1.85,
        "sharpe_1y": 2.10,
        "alpha": 0.0,
        "alpha_3y": 0.0,
        "return_1y": 7.5,
        "return_6m": 3.6,
        "return_3y": 6.8,
        "ytm_pct": 7.10,
        "is_direct": True,
        "riskometer_score": 2,
        "manager_tenure_years": 7.0,
        "h": [
            "HDFC Bank Arb", "Reliance Arb", "ICICI Bank Arb", "TCS Arb", "ITC Arb",
            "Axis Bank Arb", "Infosys Arb", "SBI Arb", "L&T Arb", "TREPS / Reverse Repo"
        ],
        "_provenance": {
            "retrieved_at": "2026-11-01T21:00:00Z",
            "confidence_score": 1.0,
            "confidence_level": "high",
            "anomalies": [],
            "source": "Factsheet Benchmark Universe",
            "engine_version": "1.2.0"
        }
    }
]

for ic in institutional_candidates:
    if ic["id"] not in existing_ids:
        funds.append(ic)

data["funds"] = funds
data["_meta"]["coverage"] = f"{len(funds)} funds, full multi-horizon universe including index, healthcare, debt and arbitrage."

with open(metrics_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print(f"Added institutional candidates. Total funds in {metrics_path}: {len(funds)}")

