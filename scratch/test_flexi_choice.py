import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.math_engine import load_holdings_from_cas_excel

cas_path = Path("data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx")
metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
aliases_path = Path("data/lalit_portfolio/fund_aliases.json")
holdings = load_holdings_from_cas_excel(cas_path, metrics_path, aliases_path)

ppfas_h = [h for h in holdings if "parag" in h.scheme.lower() or "ppfas" in h.scheme.lower()]
hdfc_flexi_h = [h for h in holdings if "hdfc flexi" in h.scheme.lower()]

print("PPFAS Holdings:")
for h in ppfas_h:
    print(f"  {h.scheme} | {h.plan.value} | Folio: {h.folio} | Val: INR {h.current_value_inr:,.0f}")

print("\nHDFC Flexi Holdings:")
for h in hdfc_flexi_h:
    print(f"  {h.scheme} | {h.plan.value} | Folio: {h.folio} | Val: INR {h.current_value_inr:,.0f}")

