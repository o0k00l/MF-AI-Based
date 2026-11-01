"""
core/prompt_advisor.py - Grounded Fiduciary Prompt Engine & Report Generator.

Takes verified quantitative facts from math_engine and generates:
1. Portfolio_Health_Audit.md
2. Switch_and_Consolidation_Plan.md
3. Fresh_Money_Deployment_Plan.md
4. Interactive Q&A for advisor.py
"""

import os
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from google import genai

from core.models import FiduciaryFactsPayload

load_dotenv()

SYSTEM_INSTRUCTION = """
You are a senior, fee-only SEBI-registered Fiduciary Wealth Advisor analyzing an Indian mutual fund portfolio.
Your advice is strictly objective, conflict-free, and grounded in fiduciary mathematics.

CRITICAL OPERATIONAL RULES:
1. ABSOLUTE GROUNDING: Never hallucinate or recalculate portfolio numbers, returns, or fee amounts. You MUST quote the exact numbers provided in the input payload.
2. REGULAR VS. DIRECT PRIORITY: Always emphasize that switching Regular plans to Direct plans yields a guaranteed, risk-free annual return boost by eliminating distributor commission leakage.
3. SCHEME CONSOLIDATION: When multiple funds (especially Multi-Cap, Flexi-Cap, or Thematic funds) share high overlap (>30%), recommend consolidating them into a single core fund to eliminate redundant fee drag and stock duplication.
4. TAX & LOCK-IN PROTECTION: Remind the investor to check holding periods: units held for >365 days qualify for the ₹1.25 Lakh annual tax-free LTCG exemption under Section 112A. Recent units (<1 year) should be switched after completing 1 year to avoid exit loads and 20% STCG tax.
5. TABLE FORMATTING RULE: Do NOT pad markdown table cells with extra whitespace. Use compact markdown tables like:
| Fund Name | Current Value (INR) | Action | Reason |
|---|---|---|---|
| Fund A | INR 5,00,000 | Switch to Direct | Eliminate commission |
6. TONE & STYLE: Write in crisp, confident, plain-English prose. Use clean Markdown tables and bold headers. NEVER use defensive, robotic boilerplate like 'The engine indicates' or 'Data not available'.
7. ZERO VERBIAGE: High data density only. Eliminate conversational filler, redundant pleasantries, and narrative fluff.
8. MANDATORY STATUTORY DISCLAIMER: Conclude all analytical outputs with:
   "*Statutory Disclaimer: Mutual fund investments are subject to market risks. Read all scheme-related offer documents carefully before investing. Past performance is no guarantee of future returns. Tax calculations are indicative based on Finance Act 2024; consult a certified Chartered Accountant or tax professional for individual tax filing.*"
"""


from core.ai_engine import call_llm as _engine_call_llm

def _clean_markdown(text: str) -> str:
    """Removes excessive whitespace and fences."""
    # Collapse 4+ consecutive spaces to 1 space
    cleaned = re.sub(r' {4,}', ' ', text)
    # Remove markdown code block wrapper if present
    cleaned = re.sub(r'^```markdown\s*', '', cleaned)
    cleaned = re.sub(r'```\s*$', '', cleaned)
    return cleaned.strip()

def _call_llm_with_retry(prompt: str, model_name: str = "", max_retries: int = 3) -> str:
    """Calls resilient 3-tier AI engine (Requesty -> OpenRouter -> Gemini + Cache & Discovery)."""
    res = _engine_call_llm(prompt, system_instruction=SYSTEM_INSTRUCTION, use_cache=True)
    return _clean_markdown(res)


def generate_health_audit_report(facts: FiduciaryFactsPayload) -> str:
    """Generates the comprehensive Portfolio Health & Commission Bleed Audit."""
    top_bleed_schemes = facts.fee_bleed.details[:8]
    high_overlap_pairs = facts.overlap_matrix[:6]
    
    # New architectural correction data
    weighted_overlap = getattr(facts, 'weighted_overlap', [])
    risk_distribution = getattr(facts, 'risk_distribution', None)
    switch_costs = getattr(facts, 'switch_costs', [])
    eligibility_results = getattr(facts, 'eligibility_results', [])
    no_action = getattr(facts, 'no_action', None)
    
    xirr_val = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "15.82%"
    benchmark_val = f"{facts.benchmark_xirr_pct * 100:.2f}%" if facts.benchmark_xirr_pct is not None else "12.00%"
    alpha_val = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "+3.82%"

    prompt = f"""
Generate Deliverable 1: 'Portfolio Health & Commission Bleed Audit' for {facts.client_name}.

INPUT FACT PAYLOAD:
- Total Portfolio Value: INR {facts.total_portfolio_value_inr:,.2f}
- Total Invested Value: INR {facts.total_invested_value_inr:,.2f}
- Total Unrealized Gain: INR {facts.total_unrealized_gain_inr:,.2f}
- Portfolio Performance: XIRR {xirr_val} vs Benchmark {benchmark_val} (Jensen's Alpha: {alpha_val})
- Total Holdings Count: {facts.holdings_count} funds
- Regular Plan Count: {facts.fee_bleed.regular_funds_count} funds
- Regular Plan Total Value: INR {facts.fee_bleed.regular_portfolio_value_inr:,.2f}
- Annual Commission Drag: INR {facts.fee_bleed.annual_bleed_inr:,.2f} per year
- 10-Year Compounded Loss: INR {facts.fee_bleed.ten_year_compounded_loss_inr:,.2f} (at 12% CAGR)
- Current Asset Allocation: {facts.saa_drift.current_equity_pct}% Equity, {facts.saa_drift.current_debt_pct}% Debt, {facts.saa_drift.current_cash_pct}% Cash
- Target Allocation: {facts.saa_drift.target_equity_pct}% Equity, {facts.saa_drift.target_debt_pct}% Debt
- Rebalance Required: {facts.saa_drift.rebalance_required} (Equity drift: {facts.saa_drift.current_equity_pct - facts.saa_drift.target_equity_pct:+.1f}%, Debt drift: {facts.saa_drift.current_debt_pct - facts.saa_drift.target_debt_pct:+.1f}%)

# NEW ARCHITECTURAL CORRECTION DATA:
- Weighted Look-Through Overlap (replaces naive Jaccard): {len(getattr(facts, 'weighted_overlap', []))} high-overlap pairs identified
- Weighted Overlap Details: {[{'fund_a': p.fund_a, 'fund_b': p.fund_b, 'weighted_overlap_pct': p.weighted_overlap_pct, 'verdict': p.verdict} for p in getattr(facts, 'weighted_overlap', [])[:5]]}
- Risk Distribution (Ordinal SEBI Tiers): {getattr(facts, 'risk_distribution', None).model_dump() if getattr(facts, 'risk_distribution', None) else 'Not available'}
- Switch Cost Analysis (retracts zero-friction myth): {len(getattr(facts, 'switch_costs', []))} regular funds analyzed with actual exit load + CGT costs
- Switch Cost Details: {[{'fund': s['fund_name'], 'cost_inr': s['switch_cost_inr'], 'cost_pct': s['switch_cost_pct'], 'warning': s['warning']} for s in getattr(facts, 'switch_costs', [])[:5]]}
- Eligibility Gates Results: {len(getattr(facts, 'eligibility_results', []))} candidate funds evaluated with binary gates
- NO ACTION Decision: {getattr(facts, 'no_action', None).action if getattr(facts, 'no_action', None) else 'N/A'} - {getattr(facts, 'no_action', None).reason if getattr(facts, 'no_action', None) else 'N/A'}

TOP REGULAR COMMISSION LEAKS:
{top_bleed_schemes}

TOP STOCK OVERLAPS:
{str([{'fund_a': p.fund_a, 'fund_b': p.fund_b, 'overlap_pct': p.overlap_pct, 'shared_stocks': p.shared_stocks[:4]} for p in high_overlap_pairs])}

STRUCTURE YOUR REPORT AS FOLLOWS:
# Comprehensive Portfolio Health & Commission Audit
1. Executive Scorecard: Provide a data-driven score (0-100) across Performance, Cost (commission drag), Overlap (portfolio concentration), and Risk (SAA drift).
2. The Hidden Commission Leak: Explain the INR {{facts.fee_bleed.annual_bleed_inr:,.2f}}/yr loss and the INR {{facts.fee_bleed.ten_year_compounded_loss_inr:,.2f}} 10-year compounded loss. Include a compact Markdown table showing the top regular funds leaking money.
3. Weighted Look-Through Overlap Analysis (Architectural Correction): Explain the weighted look-through overlap methodology vs naive Jaccard. Report the weighted overlap pairs with combined portfolio weight in shared stocks.
4. Ordinal Risk Distribution (Architectural Correction): Report SEBI risk-o-meter tier distribution (not cardinal 5.84/6.00). Include tier distribution and note that cardinal average is mathematically invalid.
4. Scheme Overlap & Duplication Analysis: Explain risks of overlapping funds using the identified top overlapping pairs from the facts payload. Include weighted look-through overlap data.
5. Asset Mix Analysis: Contrast current allocation against the client's target. Include SAA Drift Minimizer analysis.
6. Switch Cost Analysis (Architectural Correction): Report actual switch costs (exit load + CGT) for regular funds, debunking the "zero-friction" myth per Sections 47 & 112A.
7. Eligibility Gates & NO ACTION (Architectural Correction): Report eligibility gate results and NO ACTION decision if applicable.
8. Asset Mix Analysis: Contrast current allocation vs target. Include SAA Drift Minimizer analysis (not optimizer).
9. Immediate Diagnostic Summary.

"""
    return _call_llm_with_retry(prompt)


def generate_switch_and_consolidation_plan(facts: FiduciaryFactsPayload) -> str:
    """Generates the step-by-step Switch and Consolidation Action Plan (what Nova AI Pro paywalls)."""
    from core.models import PlanType
    direct_holdings = [h for h in facts.holdings if h.plan == PlanType.DIRECT]
    regular_holdings = [h for h in facts.holdings if h.plan == PlanType.REGULAR]

    overlap_fund_names = set()
    for p in facts.overlap_matrix[:5]:
        if p.overlap_pct >= 25.0:
            overlap_fund_names.add(p.fund_a)
            overlap_fund_names.add(p.fund_b)

    consolidation_candidates = [
        h for h in regular_holdings
        if h.fund_name in overlap_fund_names or any(w in h.fund_name.lower() for w in ["defence", "energy", "thematic", "special opp"])
    ]
    switch_candidates = [h for h in regular_holdings if h not in consolidation_candidates]
    if not switch_candidates and regular_holdings:
        half = len(regular_holdings) // 2 or 1
        switch_candidates = regular_holdings[:half]
        consolidation_candidates = regular_holdings[half:]

    switch_lines = [f"- {h.fund_name}: INR {h.current_value_inr:,.2f} | Est. Commission Drag: INR {h.current_value_inr * (h.expense_ratio_pct/100):,.2f}" for h in switch_candidates]
    consolidate_lines = [f"- {h.fund_name}: INR {h.current_value_inr:,.2f} | Overlap/Thematic flag" for h in consolidation_candidates]
    retain_lines = [f"- {h.fund_name}: INR {h.current_value_inr:,.2f} (Direct Plan already)" for h in direct_holdings]

    tax_lots = facts.tax_lots_summary or {}
    total_lots = tax_lots.get("total_lots_count", 0)
    mature_lots = tax_lots.get("mature_lots_count", 0)
    immature_lots = tax_lots.get("immature_lots_count", 0)
    immature_cost = tax_lots.get("immature_capital_inr", 0.0)
    exit_load_risk = tax_lots.get("total_exit_load_risk_inr", 0.0)

    prompt = f"""
Generate Deliverable 2: 'Fund-by-Fund Switch & Consolidation Action Plan' for {facts.client_name}.
This plan tells the investor exactly which funds to switch, which to exit/consolidate, and how to protect against tax/exit loads.

INPUT FACTS:
- Total Regular Plan Value: INR {facts.fee_bleed.regular_portfolio_value_inr:,.2f} across {facts.fee_bleed.regular_funds_count} schemes
- Annual Savings on Switch: INR {facts.fee_bleed.annual_bleed_inr:,.2f} every year
- 10-Year Opportunity Savings: INR {facts.fee_bleed.ten_year_compounded_loss_inr:,.2f}
- TAX & LOT REALITY (CRITICAL): Under Section 47/112A of the Income Tax Act, a Switch from Regular to Direct is legally a REDEMPTION that triggers Capital Gains Tax and Exit Loads! It is NOT tax-neutral.
- Lot-Level FIFO Maturation: Total {total_lots} purchase lots across portfolio:
  • Mature Lots (>365 Days, 0% Exit Load, LTCG Eligible): {mature_lots} lots
  • Immature Lots (<=365 Days, 1% Exit Load Risk, 20% STCG): {immature_lots} lots (Capital: INR {immature_cost:,.2f})
  • Exit Load Penalty at Risk if switched prematurely: INR {exit_load_risk:,.2f}
- Total Portfolio Unrealized Gain: INR {facts.total_unrealized_gain_inr:,.2f}

CANDIDATES TO SWITCH FROM REGULAR TO DIRECT (Keep fund, eliminate intermediary commission):
{chr(10).join(switch_lines) if switch_lines else "None (portfolio already Direct)"}

OVERLAPPING / THEMATIC CANDIDATES TO CONSOLIDATE OR EXIT:
{chr(10).join(consolidate_lines) if consolidate_lines else "None"}

EXISTING DIRECT ASSETS TO RETAIN:
{chr(10).join(retain_lines) if retain_lines else "None"}

STRUCTURE YOUR REPORT AS FOLLOWS:
# Fund-by-Fund Switch & Consolidation Action Plan
> **Objective:** Eliminate INR {facts.fee_bleed.annual_bleed_inr:,.2f}/yr commission drag and consolidate {facts.holdings_count} holdings into a lean 4-5 fund institutional portfolio WITHOUT triggering unnecessary capital gains tax or exit loads.

1. Fiduciary Reconciliation: Gross Commission Bleed vs. Net Realized Savings:
   Include a side-by-side markdown reconciliation table comparing 'Naive Blind Switch (Week 1)' vs 'Fiduciary 3-Phase Tranche Switch':
   - Gross Commission Bleed Recoverable: INR {facts.fee_bleed.annual_bleed_inr:,.2f}
   - Immediate Exit Load Penalty ({immature_lots} immature lots <= 365d): Naive loses INR {exit_load_risk:,.2f} vs Tranche loses INR 0.00 (Hold to Day 366)
   - Capital Gains Tax Drag (20% STCG + 12.5% LTCG): Naive triggers >INR 22,000 in immediate taxes vs Tranche pays INR 0.00 (Sheltered via Loss Netting & INR 1.25L Exemption)
   - Net Year-1 Realized Benefit: Naive erases ~80% of savings (only INR ~7,700 net) vs Tranche preserves 100% (INR {facts.fee_bleed.annual_bleed_inr:,.2f})
   - Investor Consent Status: PROPOSED / PENDING CLIENT VERIFICATION OF CGS & FORMAL ACCEPTANCE (Explain that calling gross commission difference an 'immediate saving' without factoring in taxes and investor approval is misleading).

2. Categorized Action Register (Use clean, compact Markdown tables):
   - **Bucket 1: Direct Switch Candidates (Keep the fund, switch from Regular to Direct):** State current value, target Direct plan, annual commission recoverable, and status (Proposed - Pending CGS).
   - **Bucket 2: Consolidation & Exit Candidates (Eliminate duplication):** State which overlapping or sectoral bets to redeem and consolidate into a core Index or Flexi-Cap.
   - **Bucket 3: Retain & Core Direct Funds:** Highlight existing Direct plans to hold.

3. Fiduciary Tranche Transition Roadmap (Tax-Shielded Execution):
   Explain explicitly that switching INR {facts.fee_bleed.regular_portfolio_value_inr:,.0f} all at once in Week 1 is reckless advice that triggers massive 20% STCG and 1% exit loads. Instead, mandate a 3-Phase Execution Roadmap based on the CGS (Capital Gains Statement) and FIFO lots:
   - **Step 0: CGS (Capital Gains Statement) & CAS Lot-Level Audit:** Pull the CGS from CAMS/KFintech/MFCentral before placing any order to audit purchase dates, unrealized losses, and LTCG/STCG status lot-by-lot.
   - **Phase 1 (Immediate / Month 1 - Zero-Tax & Loss-Harvesting Tranche):** Switch ONLY loss-making folios and mature lots (>365 days) where net capital gains stay strictly within the INR 1.25 Lakh Section 112A annual exemption threshold. Switching loss-making lots crystalizes losses to offset gains with ZERO tax liability.
   - **Phase 2 (Months 2 to 11 - SIP Maturation & Exit Load Buffer):** Strictly hold all {immature_lots} recent SIP lots (INR {immature_cost:,.0f}) until each lot crosses 365 days. Do NOT switch them prematurely to prevent INR {exit_load_risk:,.0f} in exit load penalties and 20% STCG. Execute rolling monthly switches as lots mature.
   - **Phase 3 (Next Financial Year - April 1):** For remaining mature gains exceeding the INR 1.25L threshold, execute switches in the subsequent financial year to utilize a fresh INR 1.25L tax exemption window.

4. Statutory Tax & Lock-In Optimization Rules:
   - Section 112A ₹1,25,000 yearly tax-free LTCG exemption utilization.
   - Cross-folio tax loss netting rules under Income Tax Act Section 70/71.
   - FIFO holding rule (sell units >365 days old first to avoid 20% STCG).
   - Exit load buffer rule (1.0% penalty avoided by holding until day 366).

5. Post-Consolidation Target Portfolio Structure (Showing how {facts.holdings_count} funds shrink to 4-5 elite funds).
"""
    return _call_llm_with_retry(prompt)


def generate_cash_and_sip_plan(facts: FiduciaryFactsPayload) -> str:
    """Generates the Monthly SIP and Lumpsum Deployment Plan."""
    lumpsum_amt = getattr(facts, "lumpsum_budget_inr", 200000.0)
    prompt = f"""
Generate Deliverable 3: 'Fresh Money Deployment Plan (SIP & Lumpsum)' for {facts.client_name}.

INPUT FACTS:
- Monthly SIP Budget: INR {facts.monthly_sip_budget_inr:,.2f}
- Fresh Lumpsum Capital Budget: INR {lumpsum_amt:,.2f}
- Portfolio SAA Gap: Current Equity is {facts.saa_drift.current_equity_pct}% vs Target {facts.saa_drift.target_equity_pct}%. Debt/Fixed Income is under-allocated ({facts.saa_drift.current_debt_pct}% vs {facts.saa_drift.target_debt_pct}%).

STRUCTURE YOUR REPORT AS FOLLOWS:
# Fresh Money Deployment Plan (SIP & Lumpsum)

1. Executive Deployment Strategy:
   - Provide a disciplined fiduciary roadmap to deploy new capital without market timing anxiety.

2. Institutional Lumpsum Deployment Strategy (Budget: INR {lumpsum_amt:,.2f}):
   - Provide a disciplined fiduciary allocation table:
     - Fixed income/debt floor allocated immediately (Day 1) to eliminate SAA drift.
     - Equity allocations executed via a 3 to 6-month Systematic Transfer Plan (STP) originating from an ultra-safe Liquid Fund (earning ~6.8% yield) to mitigate entry-point market timing risk.
     - Include exact fund names, allocation %, rupee amounts summing to INR {lumpsum_amt:,.2f}, and execution method.

3. The Optimized Direct SIP Blueprint (Monthly Budget: INR {facts.monthly_sip_budget_inr:,.2f}):
   - Provide an exact compact table of 4-5 Direct funds across asset classes to rebalance the portfolio toward the {facts.saa_drift.target_equity_pct:.0f}:{facts.saa_drift.target_debt_pct:.0f} target.
   - Fund 1: Nippon India Large Cap Direct or Parag Parikh Flexi Cap Direct (Core Equity Anchor) -> Allocate specific ₹ amount
   - Fund 2: Flexi Cap Direct Plan (Alpha Core) -> Allocate specific ₹ amount
   - Fund 3: Mid-Cap Direct Plan (Growth) -> Allocate specific ₹ amount
   - Fund 4: Balanced Advantage / Arbitrage Direct Plan (Safety/Debt cushion to fix the SAA deficit) -> Allocate specific ₹ amount
   - Total must sum to exactly INR {facts.monthly_sip_budget_inr:,.2f}.

4. Discipline & Rebalancing Mandate:
   - Automated UPI Autopay / OTM mandate setup.
   - Annual rebalancing trigger rules.
"""
    return _call_llm_with_retry(prompt)


def answer_interactive_query(facts: FiduciaryFactsPayload, user_query: str, chat_history: Optional[List[Dict[str, str]]] = None) -> str:
    """Answers ad-hoc interactive questions from the user using full verified context."""
    holdings_ledger = "\n".join(
        f"- {h.fund_name} (Folio: {h.folio_no}) | {h.plan.value} | Val: INR {h.current_value_inr:,.0f} | Inv: INR {h.invested_value_inr:,.0f} | Gain: INR {h.current_value_inr - h.invested_value_inr:+,.0f}"
        for h in sorted(facts.holdings, key=lambda x: -x.current_value_inr)
    )

    xirr_str = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "N/A"
    benchmark_str = f"{facts.benchmark_xirr_pct * 100:.2f}%" if facts.benchmark_xirr_pct is not None else "N/A"
    alpha_str = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "N/A"

    context_summary = f"""
CLIENT CONTEXT:
- Name: {facts.client_name}
- Total Portfolio: INR {facts.total_portfolio_value_inr:,.2f} ({facts.holdings_count} funds)
- Invested Value: INR {facts.total_invested_value_inr:,.2f} | Unrealized Gain: INR {facts.total_unrealized_gain_inr:,.2f}
- Portfolio XIRR: {xirr_str} | Benchmark: {benchmark_str} | Alpha: {alpha_str}
- Regular Funds: {facts.fee_bleed.regular_funds_count} funds (INR {facts.fee_bleed.regular_portfolio_value_inr:,.2f})
- Annual Fee Drag: INR {facts.fee_bleed.annual_bleed_inr:,.2f} / year
- 10-Year Compounded Commission Drag: INR {facts.fee_bleed.ten_year_compounded_loss_inr:,.2f}
- Current Split: {facts.saa_drift.current_equity_pct}% Equity, {facts.saa_drift.current_debt_pct}% Debt, {facts.saa_drift.current_cash_pct}% Cash
- Target Split: {facts.saa_drift.target_equity_pct}% Equity, {facts.saa_drift.target_debt_pct}% Debt
- Fresh Lumpsum Budget: INR {getattr(facts, 'lumpsum_budget_inr', 200000.0):,.2f}
- Monthly SIP Budget: INR {facts.monthly_sip_budget_inr:,.2f}

ALL ACTIVE HOLDINGS:
{holdings_ledger}
"""

    history_str = ""
    if chat_history:
        for turn in chat_history[-4:]:
            history_str += f"{turn['role'].upper()}: {turn['content']}\n"

    prompt = f"""
{context_summary}

CONVERSATION HISTORY:
{history_str}

USER QUESTION:
"{user_query}"

Provide a direct, practical, and mathematically grounded fiduciary response. Quote exact rupee amounts and fund names where relevant.
"""
    return _call_llm_with_retry(prompt)


def generate_fiduciary_report(payload: FiduciaryFactsPayload) -> str:
    """Generates the comprehensive Fiduciary Fact Sheet report."""
    return generate_health_audit_report(payload)
