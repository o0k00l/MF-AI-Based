import sys
from pathlib import Path

# Add root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.math_engine import compute_deterministic_sip_blueprint, compute_deterministic_lumpsum_blueprint, load_holdings_from_cas_excel

cas_path = Path("data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx")
metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
aliases_path = Path("data/lalit_portfolio/fund_aliases.json")
holdings = load_holdings_from_cas_excel(cas_path, metrics_path, aliases_path)

print("=== DEFAULT (HDFC MID-CAP) ===")
sip_hdfc = compute_deterministic_sip_blueprint(100000, risk_tier="Tier 6 (Very High)", stability_buffer_pct=7.54, holdings=holdings, client_aum=5170000.0)
for it in sip_hdfc.items:
    print(f"  * {it.category_role:30}: {it.scheme_name} | Folio: {it.folio_target} | INR {it.monthly_inr:,.0f} ({it.allocation_pct}%)")

