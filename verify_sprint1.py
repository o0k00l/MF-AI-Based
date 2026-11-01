from pathlib import Path
from core.math_engine import aggregate_fiduciary_facts

def main():
    cas_path = Path("data/lalit_portfolio/statements/cas_detailed_report_2026_10_09_174452.xlsx")
    metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
    config_path = Path("data/lalit_portfolio/config.json")
    aliases_path = Path("data/lalit_portfolio/fund_aliases.json")

    facts = aggregate_fiduciary_facts(cas_path, metrics_path, config_path, aliases_path)

    print("=" * 60)
    print("FIDUCIARY FACTS SUMMARY (DETERMINISTIC MATH ENGINE)")
    print("=" * 60)
    print(f"Client: {facts.client_name}")
    print(f"Holdings Count: {facts.holdings_count}")
    print(f"Total Invested: INR {facts.total_invested_value_inr:,.2f}")
    print(f"Current Value:  INR {facts.total_portfolio_value_inr:,.2f}")
    print(f"Total Gain:     INR {facts.total_unrealized_gain_inr:,.2f}")
    if facts.xirr_pct is not None:
        print(f"Portfolio XIRR: {facts.xirr_pct * 100:.2f}% (Benchmark: 12.00% | Alpha: {facts.alpha_pct:+.2f}%)")
    print("-" * 60)
    print("REGULAR PLAN FEE BLEED ANALYSIS:")
    print(f"  Regular Holdings Count: {facts.fee_bleed.regular_funds_count}")
    print(f"  Regular Value:          INR {facts.fee_bleed.regular_portfolio_value_inr:,.2f}")
    print(f"  Annual Commission Drag: INR {facts.fee_bleed.annual_bleed_inr:,.2f} / year")
    print(f"  10Y Compounded Loss:    INR {facts.fee_bleed.ten_year_compounded_loss_inr:,.2f} (at 12% CAGR)")
    print("-" * 60)
    print("STRATEGIC ASSET ALLOCATION (SAA) DRIFT:")
    print(f"  Current Split: {facts.saa_drift.current_equity_pct}% Equity | {facts.saa_drift.current_debt_pct}% Debt | {facts.saa_drift.current_cash_pct}% Cash")
    print(f"  Target Split:  {facts.saa_drift.target_equity_pct}% Equity | {facts.saa_drift.target_debt_pct}% Debt")
    print(f"  Rebalance Required: {facts.saa_drift.rebalance_required}")
    print("-" * 60)
    print(f"HIGH OVERLAP SCHEME PAIRS (>= 25% overlap): {len(facts.overlap_matrix)} pairs")
    for op in facts.overlap_matrix[:5]:
        print(f"  {op.fund_a} <-> {op.fund_b}: {op.overlap_pct}% [{op.verdict}] (Shared: {', '.join(op.shared_stocks[:3])}...)")
    print("-" * 60)
    print("IDLE CASH WATERFALL:")
    print(f"  Bank Cash:          INR {facts.cash_plan.total_bank_cash_inr:,.2f}")
    print(f"  Emergency Buffer:   INR {facts.cash_plan.emergency_buffer_inr:,.2f}")
    print(f"  Deployable Surplus: INR {facts.cash_plan.deployable_surplus_inr:,.2f}")
    print(f"  STP Recommendation: INR {facts.cash_plan.stp_monthly_amount_inr:,.2f} / mo for {facts.cash_plan.stp_duration_months} months")
    print("=" * 60)

if __name__ == "__main__":
    main()

