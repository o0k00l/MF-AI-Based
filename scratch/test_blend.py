import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from advisor import get_default_paths
from core.math_engine import (
    aggregate_fiduciary_facts,
    compute_deterministic_sip_blueprint,
    compute_deterministic_lumpsum_blueprint,
)

cas, metrics, config, aliases, outputs = get_default_paths()
facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)

print("--- TESTING SIP WITH BLEND_50_50 ---")
sip = compute_deterministic_sip_blueprint(
    monthly_budget=100000.0,
    risk_tier="Tier 6 (Very High)",
    stability_buffer_pct=7.54,
    holdings=facts.holdings,
    client_aum=facts.total_portfolio_value_inr,
    flexi_choice="blend_50_50",
    mid_choice="hdfc_midcap",
    large_choice="nifty50_index"
)
print(f"Total Monthly SIP: INR {sip.total_monthly_budget_inr:,.0f} | Items: {len(sip.items)}")
for it in sip.items:
    print(f"  [{it.allocation_pct:4.1f}%] {it.category_role:35} | INR {it.monthly_inr:>8,.0f}/mo | Folio: {it.folio_target} | {it.scheme_name}")
    print(f"        -> Rationale: {it.fiduciary_rationale[:100]}...")

print("\n--- TESTING LUMPSUM WITH BLEND_50_50 ---")
lump = compute_deterministic_lumpsum_blueprint(
    lumpsum_amount=1000000.0,
    bank_cash_total=435000.0,
    emergency_reserve=115000.0,
    holdings=facts.holdings,
    risk_tier="Tier 6 (Very High)",
    stability_buffer_pct=7.54,
    flexi_choice="blend_50_50",
    mid_choice="hdfc_midcap",
    large_choice="nifty50_index"
)
print(f"Total Lumpsum: INR {lump.total_lumpsum_inr:,.0f} | Tranches: {len(lump.tranches)}")
for tr in lump.tranches:
    print(f"  [{tr.allocation_pct:4.1f}%] {tr.role:35} | INR {tr.amount_inr:>9,.0f} | Folio: {tr.folio_target} | {tr.scheme_name}")
    print(f"        -> Timing: {tr.timing} | Rationale: {tr.fiduciary_rationale[:80]}...")

