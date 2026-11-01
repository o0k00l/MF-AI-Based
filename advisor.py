#!/usr/bin/env python3
"""
advisor.py - Fiduciary Mutual Funds Copilot (Prompt-First & Lean Engine).

Usage:
    python advisor.py                # Generate all 3 fiduciary deliverables into outputs/
    python advisor.py --chat         # Enter interactive conversational copilot mode
    python advisor.py --query "..."  # Ask a one-off question about your portfolio
"""

import sys
import argparse
from pathlib import Path
from core.math_engine import aggregate_fiduciary_facts
from core.prompt_advisor import (
    generate_health_audit_report,
    generate_switch_and_consolidation_plan,
    generate_cash_and_sip_plan,
    answer_interactive_query,
)


def discover_client_portfolios(base_dir: Path | None = None) -> dict[str, Path]:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data"
    portfolios = {}
    if not data_dir.exists():
        return portfolios
    for p in sorted(data_dir.iterdir()):
        if p.is_dir() and p.name not in ("policy", "cache", "__pycache__"):
            if (p / "config.json").exists() or (p / "statements").exists() or list(p.glob("*.xlsx")):
                portfolios[p.name] = p
    return portfolios


def get_default_paths(client_target: str | Path | None = None):
    base = Path(__file__).resolve().parent
    ports = discover_client_portfolios(base)

    if client_target:
        client_path = Path(client_target)
        if not client_path.is_dir() and client_target in ports:
            client_path = ports[client_target]
        elif not client_path.is_dir() and (base / "data" / client_target).is_dir():
            client_path = base / "data" / client_target
    else:
        if "lalit_portfolio" in ports:
            client_path = ports["lalit_portfolio"]
        elif ports:
            client_path = next(iter(ports.values()))
        else:
            client_path = base / "data" / "lalit_portfolio"

    if not client_path.exists():
        raise FileNotFoundError(f"Client portfolio directory not found: {client_path}")

    # Look for statements in statements/ subdir or root of client dir
    stmts = sorted((client_path / "statements").glob("cas_detailed_report_*.xlsx"))
    if not stmts:
        stmts = sorted((client_path / "statements").glob("*.xlsx"))
    if not stmts:
        stmts = sorted(client_path.glob("cas_detailed_report_*.xlsx"))
    if not stmts:
        stmts = sorted(client_path.glob("*.xlsx"))

    if not stmts:
        raise FileNotFoundError(f"No CAS Excel statements found in {client_path}")

    cas = stmts[-1]
    metrics = client_path / "fund_metrics.json"
    config = client_path / "config.json"
    aliases = client_path / "fund_aliases.json"
    outputs = base / "outputs"
    return cas, metrics, config, aliases, outputs


def run_full_audit(client_target: str | None = None):
    cas, metrics, config, aliases, outputs = get_default_paths(client_target)
    outputs.mkdir(parents=True, exist_ok=True)

    print("=" * 70, flush=True)
    print("  FIDUCIARY MUTUAL FUNDS COPILOT - FULL PORTFOLIO AUDIT", flush=True)
    print("=" * 70, flush=True)
    print(">> Step 1/4: Running deterministic financial mathematics engine...", flush=True)
    facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)

    print(f"   [OK] Portfolio: {facts.client_name} | {facts.holdings_count} active funds", flush=True)
    print(f"   [OK] Total Value: INR {facts.total_portfolio_value_inr:,.2f} | Gain: INR {facts.total_unrealized_gain_inr:,.2f}", flush=True)
    if facts.xirr_pct is not None:
        print(f"   [OK] True Portfolio XIRR: {facts.xirr_pct * 100:.2f}% (Benchmark: 12.00% | Alpha: {facts.alpha_pct:+.2f}%)", flush=True)
    print(f"   [OK] Regular Plan Bleed: INR {facts.fee_bleed.annual_bleed_inr:,.2f}/yr across {facts.fee_bleed.regular_funds_count} schemes", flush=True)
    print(f"   [OK] 10Y Compounded Loss: INR {facts.fee_bleed.ten_year_compounded_loss_inr:,.2f}", flush=True)
    print(f"   [OK] Asset Mix: {facts.saa_drift.current_equity_pct}% Equity / {facts.saa_drift.current_debt_pct}% Debt (Target: {facts.saa_drift.target_equity_pct}% Equity / {facts.saa_drift.target_debt_pct}% Debt)", flush=True)

    from core.pdf_exporter import convert_markdown_file_to_pdf

    print("\n>> Step 2/4: Generating Deliverable 1 (Portfolio Health & Commission Audit)...", flush=True)
    health_report = generate_health_audit_report(facts)
    p1 = outputs / "Portfolio_Health_Audit.md"
    p1.write_text(health_report, encoding="utf-8")
    pdf1 = convert_markdown_file_to_pdf(p1)
    print(f"   [OK] Saved Markdown: {p1.name} & PDF: {pdf1.name}", flush=True)

    print("\n>> Step 3/4: Generating Deliverable 2 (Fund-by-Fund Switch & Consolidation Plan)...", flush=True)
    switch_report = generate_switch_and_consolidation_plan(facts)
    p2 = outputs / "Switch_and_Consolidation_Plan.md"
    p2.write_text(switch_report, encoding="utf-8")
    pdf2 = convert_markdown_file_to_pdf(p2)
    print(f"   [OK] Saved Markdown: {p2.name} & PDF: {pdf2.name}", flush=True)

    print("\n>> Step 4/4: Generating Deliverable 3 (Fresh Money Deployment Plan: SIP & Lumpsum)...", flush=True)
    cash_report = generate_cash_and_sip_plan(facts)
    p3 = outputs / "Fresh_Money_Deployment_Plan.md"
    p3.write_text(cash_report, encoding="utf-8")
    pdf3 = convert_markdown_file_to_pdf(p3)
    print(f"   [OK] Saved Markdown: {p3.name} & PDF: {pdf3.name}", flush=True)

    print("\n" + "=" * 70, flush=True)
    print(f"  SUCCESS: All 3 Fiduciary Deliverables generated in: {outputs.resolve()}", flush=True)
    print("=" * 70, flush=True)
    print("To chat interactively with your portfolio copilot, run: python advisor.py --chat\n", flush=True)


def run_interactive_chat(client_target: str | None = None):
    cas, metrics, config, aliases, _ = get_default_paths(client_target)
    print("Loading portfolio facts...", flush=True)
    facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)

    print("\n" + "=" * 70, flush=True)
    print(f"  MUTUAL FUNDS COPILOT - INTERACTIVE CHAT (Client: {facts.client_name})", flush=True)
    print("=" * 70, flush=True)
    print("Ask any question about your mutual funds, switch plan, taxes, or idle cash.", flush=True)
    print("Type 'exit' or 'quit' to end the session.\n", flush=True)

    chat_history = []

    while True:
        try:
            query = input("You > ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "q"):
                print("\nGoodbye and happy compounding!", flush=True)
                break

            print("\nCopilot > Thinking...\n", flush=True)
            ans = answer_interactive_query(facts, query, chat_history)
            print(f"Copilot >\n{ans}\n", flush=True)
            print("-" * 70, flush=True)

            chat_history.append({"role": "user", "content": query})
            chat_history.append({"role": "assistant", "content": ans})

        except KeyboardInterrupt:
            print("\nExiting session.", flush=True)
            break
        except Exception as e:
            print(f"\n[Error]: {e}\n", flush=True)


def main():
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
        print(f"\n{ans}\n", flush=True)
    else:
        run_full_audit(args.client)


if __name__ == "__main__":
    main()
