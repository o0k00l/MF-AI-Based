import json
from pathlib import Path

metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
with open(metrics_path, "r", encoding="utf-8") as f:
    data = json.load(f)

name_map = {
    "HDFC BAF": "HDFC Balanced Advantage Fund - Direct Plan - Growth Option",
    "HDFC Flexi Cap": "HDFC Flexi Cap Fund - Direct Plan - Growth Option",
    "HDFC Mid Cap": "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth",
    "HDFC Defence": "HDFC Defence Fund - Direct Plan - Growth",
    "SBI Energy Opps": "SBI Energy Opportunities Fund - Direct Plan - Growth",
    "ICICI Pru Large & Mid": "ICICI Prudential Large & Mid Cap Fund - Direct Plan - Growth",
    "PPFAS Flexi Cap": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
    "WhiteOak Special Opps": "WhiteOak Capital Special Opportunities Fund - Direct Plan - Growth",
    "Mirae Multicap": "Mirae Asset Multicap Fund - Direct Plan - Growth",
    "Canara Robeco Multi Cap": "Canara Robeco Multi Cap Fund - Direct Plan - Growth",
    "Edelweiss BAF": "Edelweiss Balanced Advantage Fund - Direct Plan - Growth",
    "Motilal Defence Index": "Motilal Oswal Nifty India Defence Index Fund - Direct Plan - Growth",
    "Motilal Midcap": "Motilal Oswal Midcap Fund - Direct Plan Growth",
    "Quant Multi Cap": "Quant Multi Cap Fund - Direct Plan - Growth",
    "Quant Large & Mid": "Quant Large and Mid Cap Fund - Direct Plan - Growth",
    "Nippon Large Cap": "Nippon India Large Cap Fund - Direct Plan - Growth",
    "Nippon Multi Cap": "Nippon India Multi Cap Fund - Direct Plan - Growth",
    "Kotak Multi Cap": "Kotak Multi Cap Fund - Direct Plan - Growth",
    "Canara Robeco Multi Asset": "Canara Robeco Multi Asset Allocation Fund - Direct Plan - Growth",
}

for f in data.get("funds", []):
    fid = f.get("id")
    if fid in name_map:
        f["name"] = name_map[fid]
        f["scheme_name"] = name_map[fid]

# Also ensure PPFAS has foreign equity and cash buffer metrics populated
for f in data.get("funds", []):
    if "ppfas" in f.get("id", "").lower():
        f["international_equity_pct"] = 15.5
        f["cash_debt_buffer_pct"] = 17.5
    else:
        f["international_equity_pct"] = f.get("international_equity_pct", 0.0)
        f["cash_debt_buffer_pct"] = f.get("cash_debt_buffer_pct", f.get("portfolio_debt_pct", 0.0))

with open(metrics_path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)

print("Updated official names and factor metrics for all funds in fund_metrics.json!")

