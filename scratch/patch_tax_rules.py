import json

with open("data/policy/tax_rules.json", "r", encoding="utf-8") as f:
    d = json.load(f)

d["exit_load_schedules"] = {
    "equity_oriented": { "threshold_days": 365, "rate_pct": 1.0 },
    "debt_short_term": { "threshold_days": 30, "rate_pct": 0.25 },
    "debt_liquid": { "threshold_days": 7, "rate_pct": 0.0070 },
    "arbitrage": { "threshold_days": 30, "rate_pct": 0.25 }
}

d["section_194k_tds"] = {
    "description": "TDS on income in respect of units of a Mutual Fund under Section 194K of Income Tax Act",
    "rate_pct": 10.0,
    "threshold_inr": 5000.0,
    "applies_to": "IDCW_dividend_payouts_and_reinvestments",
    "exemption": "Dividends up to INR 5,000 per financial year per AMC are exempt from TDS (though taxable in slab)"
}

with open("data/policy/tax_rules.json", "w", encoding="utf-8") as f:
    json.dump(d, f, indent=2)

print("Successfully updated data/policy/tax_rules.json with non-equity exit loads and Section 194K TDS")

