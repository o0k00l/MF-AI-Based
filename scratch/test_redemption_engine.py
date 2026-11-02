import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import date
from advisor import get_default_paths
from core.math_engine import aggregate_fiduciary_facts
from core.redemption_engine import compute_personal_redemption_plan

cas, m, c, a, o = get_default_paths()
facts = aggregate_fiduciary_facts(cas, m, c, a)
tx_path = Path("data/lalit_portfolio/transactions.json")

test_cases = [
    (50000, False),
    (100000, False),
    (300000, False),
    (1000000, False),
    (200000, True),
]

for amt, is_net in test_cases:
    print("\n" + "=" * 75)
    print(f"TEST: INR {amt:,.2f} | Net Cash Target: {is_net}")
    print("=" * 75)
    plan = compute_personal_redemption_plan(
        requested_amount=amt,
        holdings=facts.holdings,
        transactions_path=tx_path,
        is_net_cash=is_net,
    )
    print(f"Ticket Category: {plan.ticket_category}")
    print(f"Rationale: {plan.ticket_rationale}")
    print(f"Funds Count: {plan.funds_liquidated_count} | Full Exits: {plan.full_folio_exits_count}")
    print(f"Gross: INR {plan.total_gross_redeemed_inr:,.2f} -> Net: INR {plan.total_net_cash_inr:,.2f}")
    print(f"Exit Load: INR {plan.total_exit_load_inr:,.2f} | Net Tax: INR {plan.total_net_tax_inr:,.2f}")
    print(f"Tax Sheltered (112A): INR {plan.total_tax_sheltered_under_112a_inr:,.2f}")
    print(f"Annual Commission Saved: INR {plan.total_annual_commission_saved_inr:,.2f}/yr")
    print("\nTranches:")
    for t in plan.tranches:
        full_lbl = "[FULL EXIT]" if t.is_full_redemption else "[PARTIAL]"
        print(f" - {t.priority_label} | {t.scheme_name[:40]} | Gross: INR {t.gross_amount_inr:,.2f} | Net: INR {t.net_cash_realized_inr:,.2f} | Saved: INR {t.annual_commission_saved_inr:,.2f}/yr {full_lbl}")
