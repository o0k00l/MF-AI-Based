import sys
from pathlib import Path

advisor_path = Path("advisor.py")
content = advisor_path.read_text(encoding="utf-8")

redemption_func = '''
def run_personal_redemption(client_target: str | None, requested_amount: float, is_net_cash: bool = False):
    cas, metrics, config, aliases, outputs = get_default_paths(client_target)
    print("=" * 75, flush=True)
    print("  FIDUCIARY PERSONAL CASH REDEMPTION PLANNER", flush=True)
    print("=" * 75, flush=True)
    facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)

    tx_path = cas.parent.parent / "transactions.json"
    if not tx_path.exists():
        tx_path = cas.parent / "transactions.json"

    from core.redemption_engine import compute_personal_redemption_plan
    plan = compute_personal_redemption_plan(
        requested_amount=requested_amount,
        holdings=facts.holdings,
        transactions_path=tx_path if tx_path.exists() else None,
        is_net_cash=is_net_cash,
    )

    print(f"\\nInvestor: {facts.client_name} | Total Portfolio: INR {facts.total_portfolio_value_inr:,.2f}")
    target_type = "NET CASH (in hand)" if is_net_cash else "GROSS WITHDRAWAL"
    print(f"Target Redemption: INR {requested_amount:,.2f} ({target_type})")
    print(f"Operational Tier: {plan.ticket_category} ({plan.funds_liquidated_count} funds, {plan.full_folio_exits_count} complete closures)")
    print(f"Fiduciary Logic: {plan.ticket_rationale}\\n")

    print("-" * 75)
    print("  FINANCIAL IMPACT & TAX SUMMARY")
    print("-" * 75)
    print(f"  • Gross Capital Redeemed:       INR {plan.total_gross_redeemed_inr:>12,.2f}")
    print(f"  • Exit Load Incurred:           INR {plan.total_exit_load_inr:>12,.2f} (0.0% - Immature lots shielded)")
    print(f"  • Realized Capital Gain/(Loss): INR {plan.total_realized_gain_loss_inr:>12,.2f}")
    print(f"  • Tax Sheltered under Sec 112A: INR {plan.total_tax_sheltered_under_112a_inr:>12,.2f} (0% tax-free LTCG)")
    print(f"  • Net Tax Payable (STCG+LTCG):  INR {plan.total_net_tax_inr:>12,.2f}")
    print(f"  • NET CASH CREDITED TO BANK:    INR {plan.total_net_cash_inr:>12,.2f}")
    print(f"  • Annual Commission Bleed Saved:INR {plan.total_annual_commission_saved_inr:>12,.2f} / year permanently!")
    print("-" * 75)

    print("\\n" + "=" * 75)
    print("  TRANCHE-BY-TRANCHE EXECUTION SCHEDULE")
    print("=" * 75)
    for i, t in enumerate(plan.tranches, 1):
        status = "FULL FOLIO CLOSURE" if t.is_full_redemption else "PARTIAL REDEMPTION"
        print(f"\\nTranche {i}: [{t.priority_label}] -> {status}")
        print(f"  Scheme:   {t.scheme_name} (Folio: {t.folio})")
        print(f"  Rationale:{t.fiduciary_reason}")
        print(f"  Units:    {t.units_to_redeem:,.4f} units @ NAV INR {t.nav:.2f}")
        print(f"  Gross:    INR {t.gross_amount_inr:,.2f} | Net Cash: INR {t.net_cash_realized_inr:,.2f}")
        print(f"  Taxes:    Exit Load: INR {t.exit_load_inr:.2f} | LTCG Tax: INR {t.projected_ltcg_tax_inr:.2f} (Sheltered: INR {t.tax_sheltered_under_112a_inr:.2f})")
        if t.annual_commission_saved_inr > 0:
            print(f"  Bleed:    Permanently saves INR {t.annual_commission_saved_inr:,.2f}/yr distributor commission")

    print("\\n" + "=" * 75)
    print("  MFCENTRAL EXECUTION CHECKLIST")
    print("=" * 75)
    for step in plan.execution_steps:
        print(f"  • {step}")

    print("\\n" + "=" * 75)
    print("  FIDUCIARY SAFEGUARDS ENFORCED")
    print("=" * 75)
    for guard in plan.fiduciary_safeguards:
        print(f"  ✓ {guard}")
    print("=" * 75 + "\\n")
'''

old_main = '''def main():
    parser = argparse.ArgumentParser(description="Fiduciary Mutual Funds Copilot")
    parser.add_argument("--client", type=str, default=None, help="Client portfolio name or directory under data/")
    parser.add_argument("--chat", action="store_true", help="Launch interactive chat session")
    parser.add_argument("--stress", action="store_true", help="Run deterministic portfolio stress test simulation")
    parser.add_argument("--query", type=str, help="Ask a single question and exit")
    args = parser.parse_args()

    if args.chat:
        run_interactive_chat(args.client)
    elif args.stress:
        from stress_test import print_cli_report
        print_cli_report()
    elif args.query:
        cas, metrics, config, aliases, _ = get_default_paths(args.client)
        facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)
        ans = answer_interactive_query(facts, args.query)
        print(f"\\n{ans}\\n", flush=True)
    else:
        run_full_audit(args.client)'''

new_main = '''def main():
    parser = argparse.ArgumentParser(description="Fiduciary Mutual Funds Copilot")
    parser.add_argument("--client", type=str, default=None, help="Client portfolio name or directory under data/")
    parser.add_argument("--chat", action="store_true", help="Launch interactive chat session")
    parser.add_argument("--stress", action="store_true", help="Run deterministic portfolio stress test simulation")
    parser.add_argument("--query", type=str, help="Ask a single question and exit")
    parser.add_argument("--redeem", type=float, default=None, help="Compute deterministic personal cash redemption plan for amount in INR")
    parser.add_argument("--net", action="store_true", help="Target net cash in hand (after taxes) for redemption")
    args = parser.parse_args()

    if args.chat:
        run_interactive_chat(args.client)
    elif args.stress:
        from stress_test import print_cli_report
        print_cli_report()
    elif args.query:
        cas, metrics, config, aliases, _ = get_default_paths(args.client)
        facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)
        ans = answer_interactive_query(facts, args.query)
        print(f"\\n{ans}\\n", flush=True)
    elif args.redeem is not None:
        run_personal_redemption(args.client, args.redeem, args.net)
    else:
        run_full_audit(args.client)'''

if "def run_personal_redemption" not in content:
    content = content.replace("def main():", redemption_func + "\ndef main():")
content = content.replace(old_main, new_main)

advisor_path.write_text(content, encoding="utf-8")
print("advisor.py updated successfully!")

