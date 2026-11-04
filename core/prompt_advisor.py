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
You are an analytical assistant supporting a mutual-fund decision-support workflow. You are not a substitute for a SEBI-registered investment adviser, tax professional or legal reviewer.

CRITICAL OPERATIONAL RULES:
1. GROUNDING: Use only facts and calculations explicitly present in the supplied payload. Never invent, estimate, interpolate or silently substitute missing values.
2. NO GUARANTEED OUTCOMES: Direct-plan expense differences are not guaranteed returns or risk-free gains. Explain costs only when supported by current, scheme-specific evidence.
3. PORTFOLIO OVERLAP: Overlap alone does not mandate consolidation. Discuss look-through exposure, mandate, tax, exit load, costs and investor constraints; do not prescribe a switch from overlap alone.
4. TAX AND EXIT LOAD: Do not state a tax rate, exemption, holding period, statutory section or exit-load outcome unless the applicable transfer date, instrument classification and source-backed rule are supplied and validated. Otherwise state that tax treatment is unverified and make no tax-saving claim.
5. FAIL-CLOSED: Missing, stale, conflicting or incomplete inputs must be explicitly identified. Do not conceal unavailable data. If a required input or validated plan is absent, state NO ACTION / HOLD and leave the relevant budget unallocated.
6. DEPLOYMENT: Never invent a lumpsum split, immediate-deployment percentage, STP duration, parking vehicle, yield, tax saving or fund destination. Present only supplied deterministic plan tranches and clearly show any unallocated amount.
7. SIP ALLOCATION: Never infer that a budget is fully allocated, equity-only or compliant with a target allocation unless the supplied deterministic plan explicitly establishes it and reconciles the total.
8. TABLE FORMATTING: Use compact Markdown tables and preserve exact supplied values. Do not fill missing cells with estimates.
9. NARRATIVE: Explain the financial reasoning and trade-offs, distinguishing verified facts, calculations, assumptions, research interpretation and unavailable evidence. Do not create comparative metrics that are absent from the payload.
10. AUTHORITY: Outputs are non-executable decision support. Never imply that an order, switch, redemption or transfer is authorized. Preserve the supplied mandate state and authorization flags.
11. DISCLAIMER: State that mutual fund investments are subject to market risks, past performance does not guarantee future returns, and tax/legal treatment requires review by an appropriately qualified professional. Do not cite statutory provisions unless verified source evidence is supplied.
"""


from core.ai_engine import call_llm as _engine_call_llm

def _clean_markdown(text: str) -> str:
    """Removes excessive whitespace and fences."""
    cleaned = re.sub(r' {4,}', ' ', text)
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
    
    weighted_overlap = getattr(facts, 'weighted_overlap', [])
    risk_distribution = getattr(facts, 'risk_distribution', None)
    switch_costs = getattr(facts, 'switch_costs', [])
    eligibility_results = getattr(facts, 'eligibility_results', [])
    no_action = getattr(facts, 'no_action', None)
    
    xirr_val = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "N/A"
    benchmark_val = f"{facts.benchmark_xirr_pct * 100:.2f}%" if facts.benchmark_xirr_pct is not None else "N/A"
    alpha_val = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "N/A"

    # Mandate state for report transparency
    mandate_state = facts.mandate_state.value if hasattr(facts.mandate_state, 'value') else str(facts.mandate_state)
    is_execution_authorized = getattr(facts, 'is_execution_authorized', False)
    is_actionable_order = getattr(facts, 'is_actionable_order', False)

    thematic_rows = []
    for t in getattr(facts, "thematic_exposures", []):
        stocks_str = ", ".join(t.key_underlying_holdings[:4]) if t.key_underlying_holdings else "None"
        thematic_rows.append(
            f"| {t.theme_name} | INR {t.dedicated_funds_inr:,.0f} ({t.dedicated_funds_pct:.1f}%) | INR {t.look_through_stocks_inr:,.0f} ({t.look_through_stocks_pct:.1f}%) | {t.coverage_status} | {stocks_str} |"
        )
    thematic_table_str = "\n".join(thematic_rows) if thematic_rows else "No thematic data"

    stability_info = "NOT AVAILABLE — do not infer that an allocation target is satisfied."
    if getattr(facts, "stability_buffer", None):
        sb = facts.stability_buffer
        stability_info = f"Total Stability Buffer: {sb.total_stability_buffer_pct:.2f}% (Embedded Debt: INR {sb.embedded_debt_inr:,.0f}, Embedded Cash: INR {sb.embedded_cash_inr:,.0f}). Meets Tier 6 Target: {sb.meets_tier_target}."

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
- 10-Year Fee-Difference Scenario Estimate: INR {facts.fee_bleed.ten_year_compounded_loss_inr:,.2f} (scenario only; do not present as guaranteed loss or realized saving)
- Current Asset Allocation: {facts.saa_drift.current_equity_pct}% Equity, {facts.saa_drift.current_debt_pct}% Debt, {facts.saa_drift.current_cash_pct}% Cash
- Target Allocation: {facts.saa_drift.target_equity_pct}% Equity, {facts.saa_drift.target_debt_pct}% Debt
- Look-Through Stability Buffer: {stability_info}
- 5-Theme Look-Through Matrix:
| Theme Name | Dedicated Funds Held | Look-Through Stock Exposure | Status | Key Underlying Holdings |
|---|---|---|---|---|
{thematic_table_str}
- Rebalance Required: {facts.saa_drift.rebalance_required} (Equity drift: {facts.saa_drift.current_equity_pct - facts.saa_drift.target_equity_pct:+.1f}%, Debt drift: {facts.saa_drift.current_debt_pct - facts.saa_drift.target_debt_pct:+.1f}%)

# ARCHITECTURAL CORRECTION DATA:
- Weighted Look-Through Overlap: {len(getattr(facts, 'weighted_overlap', []))} high-overlap pairs identified
- Weighted Overlap Details: {[{'fund_a': p.fund_a, 'fund_b': p.fund_b, 'weighted_overlap_pct': p.weighted_overlap_pct, 'verdict': p.verdict} for p in getattr(facts, 'weighted_overlap', [])[:5]]}
- Risk Distribution (Ordinal SEBI Tiers): {getattr(facts, 'risk_distribution', None).model_dump() if getattr(facts, 'risk_distribution', None) else 'Not available'}
- Switch Cost Evidence: {len(getattr(facts, 'switch_costs', []))} scheme-level cost records supplied; do not infer missing exit-load or tax values
- Switch Cost Details: {[{'fund': s['fund_name'], 'cost_inr': s['switch_cost_inr'], 'cost_pct': s['switch_cost_pct'], 'warning': s['warning']} for s in getattr(facts, 'switch_costs', [])[:5]]}
- Eligibility Gates Results: {len(getattr(facts, 'eligibility_results', []))} candidate funds evaluated with binary gates
- NO ACTION Decision: {getattr(facts, 'no_action', None).action if getattr(facts, 'no_action', None) else 'N/A'} - {getattr(facts, 'no_action', None).reason if getattr(facts, 'no_action', None) else 'N/A'}
- Mandate Execution State: {mandate_state}
- Is Execution Authorized: {is_execution_authorized}
- Is Actionable Order: {is_actionable_order}

TOP REGULAR COMMISSION LEAKS:
{top_bleed_schemes}

TOP STOCK OVERLAPS:
{str([{'fund_a': p.fund_a, 'fund_b': p.fund_b, 'overlap_pct': p.overlap_pct, 'shared_stocks': p.shared_stocks[:4]} for p in high_overlap_pairs])}

STRUCTURE YOUR REPORT AS FOLLOWS:
# Comprehensive Portfolio Health & Commission Audit

**0. Mandate State & Execution Status (MANDATORY):**
- **Mandate Execution State:** {mandate_state}
- **Is Execution Authorized:** {is_execution_authorized}
- **Is Actionable Order:** {is_actionable_order}
- **Interpretation:** Explain what this means for the investor — e.g., "HOLD_PENDING_TRI_VALIDATION means all audit findings and recommendations are PROPOSED ONLY and require explicit written client authorization before execution."

1. Executive Summary: Describe supplied performance, cost, overlap and risk facts. Do not invent a composite score or ranking unless a validated scoring output is explicitly supplied.
2. Regular-plan Expense Difference: Explain the reported INR {facts.fee_bleed.annual_bleed_inr:,.2f}/yr estimate and the INR {facts.fee_bleed.ten_year_compounded_loss_inr:,.2f} 10-year scenario estimate. Clearly label both as estimates, not guaranteed savings or realized losses. Include the supplied scheme details only.
3. Weighted Look-Through Overlap Analysis: Contrast the weighted look-through overlap methodology against naive Jaccard. Report the top weighted overlap pairs and shared stocks.
4. Ordinal Risk Distribution: Report SEBI risk-o-meter tier distribution (explaining why cardinal averages like 5.84/6.00 are mathematically invalid for ordinal data).
5. Scheme Overlap & Duplication Analysis: Use the actual holdings count and supplied overlap evidence. Do not assume that overlap is high or that consolidation is required.
6. Asset Mix Analysis & Look-Through Stability Buffer: Contrast supplied current allocation vs target. If stability-buffer evidence is absent, state unavailable rather than substituting 0.00%.
7. Switch Cost Analysis: Report only the supplied scheme-level cost records. Do not infer tax treatment or cite statutory sections without validated source evidence.
8. Immediate Diagnostic Summary: Clear, actionable summary for the investor.
    """
    return _call_llm_with_retry(prompt)


def generate_switch_and_consolidation_plan(facts: FiduciaryFactsPayload) -> str:
    """Generate a source-grounded review register; never invent switch or tax instructions."""
    from core.models import PlanType

    direct_holdings = [holding for holding in facts.holdings if holding.plan == PlanType.DIRECT]
    regular_holdings = [holding for holding in facts.holdings if holding.plan == PlanType.REGULAR]

    fee_details = getattr(facts.fee_bleed, "details", []) or []
    fee_by_name = {
        str(item.get("fund_name", "")).strip().casefold(): item
        for item in fee_details
        if item.get("fund_name")
    }

    regular_rows = []
    for holding in regular_holdings:
        fee_detail = fee_by_name.get(holding.fund_name.strip().casefold(), {})
        annual_difference = fee_detail.get("annual_bleed_inr")
        fee_text = (
            f"reported annual expense difference INR {float(annual_difference):,.2f}"
            if annual_difference is not None
            else "scheme-level annual expense difference unavailable"
        )
        regular_rows.append(
            f"- {holding.fund_name}: current value INR {holding.current_value_inr:,.2f}; "
            f"{fee_text}; review only — no switch is authorized."
        )

    direct_rows = [
        f"- {holding.fund_name}: current value INR {holding.current_value_inr:,.2f}; "
        "existing Direct holding; retain status must be assessed against the investor mandate."
        for holding in direct_holdings
    ]

    overlap_rows = []
    for pair in getattr(facts, "overlap_matrix", []) or []:
        shared = getattr(pair, "shared_stocks", []) or []
        overlap_rows.append(
            f"- {pair.fund_a} / {pair.fund_b}: reported overlap "
            f"{pair.overlap_pct:.2f}%; shared holdings supplied: "
            f"{', '.join(shared[:10]) if shared else 'not supplied'}."
        )
    if not overlap_rows:
        overlap_rows.append("- NO DATA: no pairwise overlap evidence supplied.")

    weighted_rows = []
    for pair in getattr(facts, "weighted_overlap", []) or []:
        shared = getattr(pair, "shared_stocks", []) or []
        weighted_rows.append(
            f"- {pair.fund_a} / {pair.fund_b}: weighted overlap "
            f"{pair.weighted_overlap_pct:.2f}%; verdict supplied: "
            f"{getattr(pair, 'verdict', 'not supplied')}; "
            f"shared holdings: {', '.join(shared[:10]) if shared else 'not supplied'}."
        )
    if not weighted_rows:
        weighted_rows.append("- NO DATA: no weighted look-through overlap evidence supplied.")

    switch_costs = getattr(facts, "switch_costs", []) or []
    switch_cost_rows = [
        f"- {item.get('fund_name', 'Unidentified scheme')}: "
        f"reported cost INR {item.get('switch_cost_inr', 'not supplied')}; "
        f"reported cost ratio {item.get('switch_cost_pct', 'not supplied')}; "
        f"warning: {item.get('warning', 'not supplied')}."
        for item in switch_costs
    ]
    if not switch_cost_rows:
        switch_cost_rows.append("- NO ACTION: scheme-level exit-load and tax cost evidence is unavailable.")

    tax_lots = getattr(facts, "tax_lots_summary", None)
    if tax_lots is not None and hasattr(tax_lots, "model_dump"):
        tax_lot_summary = tax_lots.model_dump()
    elif isinstance(tax_lots, dict):
        tax_lot_summary = tax_lots
    else:
        tax_lot_summary = None

    mandate_state = facts.mandate_state.value if hasattr(facts.mandate_state, "value") else str(facts.mandate_state)
    is_execution_authorized = getattr(facts, "is_execution_authorized", False)
    is_actionable_order = getattr(facts, "is_actionable_order", False)
    no_action = getattr(facts, "no_action", None)
    no_action_text = (
        f"{getattr(no_action, 'action', 'NO ACTION')}: {getattr(no_action, 'reason', 'No reason supplied.')}"
        if no_action is not None
        else "No separate NO ACTION decision object supplied."
    )

    prompt = f"""
Generate a fund-by-fund Regular-versus-Direct and portfolio-overlap review for {facts.client_name}.
This is a review, not an instruction to switch, redeem, consolidate or transact.

VERIFIED PORTFOLIO FACTS:
- Reported portfolio value: INR {facts.total_portfolio_value_inr:,.2f}
- Reported holdings count: {facts.holdings_count}
- Regular-plan holdings: {len(regular_holdings)}
- Direct-plan holdings: {len(direct_holdings)}
- Reported annual Regular-plan expense difference estimate: INR {facts.fee_bleed.annual_bleed_inr:,.2f}
- Reported 10-year fee-difference scenario estimate: INR {facts.fee_bleed.ten_year_compounded_loss_inr:,.2f}
  Treat this only as the supplied scenario estimate. Do not call it a guaranteed loss or realized saving.
- Total unrealized gain supplied: INR {facts.total_unrealized_gain_inr:,.2f}

REGULAR-PLAN HOLDINGS — REVIEW ONLY:
{chr(10).join(regular_rows) if regular_rows else "None supplied."}

DIRECT-PLAN HOLDINGS:
{chr(10).join(direct_rows) if direct_rows else "None supplied."}

PAIRWISE OVERLAP EVIDENCE:
{chr(10).join(overlap_rows)}

WEIGHTED LOOK-THROUGH OVERLAP EVIDENCE:
{chr(10).join(weighted_rows)}

SCHEME-LEVEL SWITCH-COST EVIDENCE:
{chr(10).join(switch_cost_rows)}

TAX-LOT SUMMARY:
{tax_lot_summary if tax_lot_summary is not None else "UNAVAILABLE — tax-lot conclusions and tax-optimized switch schedules are NO ACTION."}

MANDATE AND CONTROL STATE:
- Mandate state: {mandate_state}
- Execution authorized: {is_execution_authorized}
- Actionable order: {is_actionable_order}
- Separate NO ACTION result: {no_action_text}

REPORT REQUIREMENTS:
1. Do not invent scheme metrics, peer comparisons, AUM, TER, P/E, beta, alpha, return, overlap, shared stocks, exit-load rates, tax rates, exemption amounts, holding periods or statutory sections.
2. Do not divide holdings arbitrarily between switch and consolidation buckets. A Regular-to-Direct conversion and a scheme exit are distinct decisions.
3. Overlap is diagnostic evidence, not an automatic sell trigger. Do not infer that any holding must be consolidated or exited solely because overlap exists.
4. If tax-lot or scheme-level switch-cost evidence is missing, state NO ACTION for any tax-optimized switch schedule. Do not create default lot counts, 1% exit loads, Day-366 instructions or phased dates.
5. Distinguish reported expense-difference estimates from guaranteed savings or investment returns.
6. Show unavailable evidence explicitly and retain all holdings pending independent review where required.
7. Preserve the mandate state. No action is executable unless all external authorization controls are independently satisfied.
"""
    return _call_llm_with_retry(prompt)

def _build_dynamic_selection_dossier(facts: FiduciaryFactsPayload) -> str:
    """Build a dossier only from supplied deterministic plans and eligibility evidence."""
    lines = ["### FUND SELECTION DOSSIER & PEER ELIGIBILITY EVIDENCE"]

    sip_plan = getattr(facts, "deterministic_sip_plan", None)
    sip_items = getattr(sip_plan, "items", []) if sip_plan is not None else []
    if sip_items:
        lines.append("Selected SIP candidates (selection rationale is copied from the deterministic plan):")
        for index, item in enumerate(sip_items, start=1):
            lines.append(
                f"{index}. {item.category_role}: {item.scheme_name} | "
                f"{item.allocation_pct:.2f}% | INR {item.monthly_inr:,.2f}/month"
            )
            lines.append(f"   Target folio: {item.folio_target or 'Not specified'}")
            lines.append(f"   Supplied rationale: {item.fiduciary_rationale or 'Not supplied'}")
    else:
        lines.append("NO ACTION: no deterministic SIP selections were supplied.")

    eligibility_results = getattr(facts, "eligibility_results", None) or []
    if eligibility_results:
        lines.append("")
        lines.append("Candidate eligibility outcomes (these are gate results, not performance rankings):")
        for candidate in eligibility_results:
            name = candidate.get("fund_name") or candidate.get("fund_id") or "Unidentified candidate"
            passed = candidate.get("passed")
            failed_gates = candidate.get("failed_gates") or []
            status = "PASSED" if passed is True else "FAILED" if passed is False else "UNKNOWN"
            lines.append(f"- {name}: {status}")
            if failed_gates:
                lines.append(f"  Failed gates: {', '.join(str(gate) for gate in failed_gates)}")
    else:
        lines.append("")
        lines.append(
            "Peer eligibility comparison unavailable: no candidate-level eligibility evidence was supplied. "
            "Do not invent peer names, rejection reasons, performance metrics, TER, AUM or rankings."
        )

    thematic_exposures = getattr(facts, "thematic_exposures", None) or []
    if thematic_exposures:
        lines.append("")
        lines.append("Supplied thematic look-through observations:")
        for exposure in thematic_exposures:
            lines.append(
                f"- {exposure.theme_name}: dedicated {exposure.dedicated_funds_pct:.2f}%; "
                f"look-through stocks {exposure.look_through_stocks_pct:.2f}%; "
                f"coverage status {exposure.coverage_status}."
            )
    else:
        lines.append("")
        lines.append("Thematic look-through evidence unavailable; no thematic deficit or satellite is inferred.")

    return "\n".join(lines)


def generate_cash_and_sip_plan(facts: FiduciaryFactsPayload) -> str:
    """Generate a grounded SIP/lumpsum report; absent plans remain NO ACTION."""
    lumpsum_amt = getattr(facts, "lumpsum_budget_inr", 0.0)
    lump_plan = getattr(facts, "deterministic_lumpsum_plan", None)

    lump_rows = []
    if lump_plan is not None:
        for tranche in lump_plan.tranches:
            folio = tranche.folio_target or "Not specified"
            lump_rows.append(
                f"| {tranche.role} | {tranche.scheme_name} | {folio} | "
                f"INR {tranche.amount_inr:,.2f} | {tranche.allocation_pct:.2f}% | "
                f"{tranche.timing} | {tranche.source_vehicle} | {tranche.fiduciary_rationale} |"
            )

    if lump_plan is None:
        lumpsum_status = (
            "NO ACTION: no deterministic lumpsum plan was supplied. "
            "Do not propose a split, parking vehicle, STP duration or tax treatment. "
            "The full requested lumpsum budget remains unallocated."
        )
    else:
        unallocated = float(lump_plan.unallocated_amount_inr)
        lumpsum_status = (
            f"Plan status: {lump_plan.execution_status}. "
            f"Requested amount: INR {lump_plan.total_lumpsum_inr:,.2f}. "
            f"Unallocated amount: INR {unallocated:,.2f}. "
            f"Cash validation passed: {lump_plan.cash_validation_passed}. "
            f"Validation: {lump_plan.cash_validation_message or 'No validation message supplied.'} "
            "No tax-saving or tax-classification conclusion is asserted."
        )
        if not lump_rows:
            lumpsum_status += (
                " NO ACTION: the plan contains no validated deployment tranches; "
                "the entire requested amount remains unallocated."
            )
            lump_rows.append("| NO ACTION | No validated destination | — | "
                             f"INR {lump_plan.total_lumpsum_inr:,.2f} | — | Not authorized | — | "
                             "No qualifying tranche supplied |")
        if unallocated > 0:
            lump_rows.append(
                f"| UNALLOCATED | No destination | — | INR {unallocated:,.2f} | — | HOLD | — | "
                "No qualifying allocation; do not redistribute |"
            )

    lumpsum_table_str = "\n".join(lump_rows) if lump_rows else (
        "| NO ACTION | No validated destination | — | — | — | HOLD | — | "
        "No deterministic plan supplied |"
    )

    sip_plan = getattr(facts, "deterministic_sip_plan", None)
    sip_rows = []
    if sip_plan is not None:
        for item in sip_plan.items:
            folio = item.folio_target or "Not specified"
            sip_rows.append(
                f"| {item.category_role} | {item.scheme_name} | {folio} | "
                f"INR {item.monthly_inr:,.2f} | {item.allocation_pct:.2f}% | "
                f"{item.fiduciary_rationale} |"
            )
        if sip_plan.unallocated_budget_inr > 0:
            sip_rows.append(
                f"| UNALLOCATED | No destination | — | INR {sip_plan.unallocated_budget_inr:,.2f} | — | "
                "No qualifying candidate; do not redistribute |"
            )
    if not sip_rows:
        sip_rows.append(
            "| NO ACTION | No validated destination | — | — | — | "
            "No deterministic SIP plan supplied; requested budget remains unallocated |"
        )
    sip_table_str = "\n".join(sip_rows)

    stability_str = "NOT AVAILABLE — do not infer the stability buffer or claim that an allocation target is satisfied."
    stability = getattr(facts, "stability_buffer", None)
    if stability is not None:
        stability_str = (
            f"Reported stability buffer: {stability.total_stability_buffer_pct:.2f}% "
            f"(embedded debt INR {stability.embedded_debt_inr:,.2f}; "
            f"embedded cash INR {stability.embedded_cash_inr:,.2f}; "
            f"bank deployable cash INR {stability.bank_deployable_cash_inr:,.2f}). "
            "Do not infer that this satisfies any target unless a separate validated policy check is supplied."
        )

    selection_dossier = _build_dynamic_selection_dossier(facts)
    mandate_state = facts.mandate_state.value if hasattr(facts.mandate_state, "value") else str(facts.mandate_state)
    is_execution_authorized = getattr(facts, "is_execution_authorized", False)
    is_actionable_order = getattr(facts, "is_actionable_order", False)

    prompt = f"""
Generate Deliverable 3: Fresh Money Deployment Plan (SIP & Lumpsum) for {facts.client_name}.
This is non-executable decision support. Do not fill gaps with customary allocations or assumptions.

INPUT FACT PAYLOAD:
- Investor: {facts.client_name} (Age: {facts.client_age}, Horizon: {facts.horizon_years} Years)
- Risk Profile: {facts.risk_tier_name}
- Target Asset Allocation: {facts.saa_drift.target_equity_pct}% Equity / {facts.saa_drift.target_debt_pct}% Debt
- Look-Through Stability Buffer: {stability_str}
- Monthly SIP Budget: INR {facts.monthly_sip_budget_inr:,.2f}
- Fresh Lumpsum Budget: INR {lumpsum_amt:,.2f}

LUMPSUM PLAN STATUS:
{lumpsum_status}

DETERMINISTIC LUMPSUM TRANCHES (show only these supplied rows):
| Deployment Leg | Destination Scheme | Target Folio | Amount (INR) | Allocation (%) | Timing | Source Vehicle | Rationale |
|---|---|---|---|---|---|---|---|
{lumpsum_table_str}

DETERMINISTIC SIP PLAN (show only these supplied rows):
| Category Role | Scheme Name | Target Folio | Monthly SIP (INR) | Allocation (%) | Rationale |
|---|---|---|---|---|---|
{sip_table_str}

FUND SELECTION DOSSIER & PEER REJECTION MATRIX:
{selection_dossier}

MANDATE STATE:
- Mandate Execution State: {mandate_state}
- Is Execution Authorized: {is_execution_authorized}
- Is Actionable Order: {is_actionable_order}

REPORT REQUIREMENTS:
1. State that all proposals are non-executable unless the supplied mandate and authorization controls explicitly establish otherwise.
2. Reconcile allocated and unallocated SIP/lumpsum amounts. If a plan or candidate is missing, say NO ACTION and retain the amount as unallocated.
3. Do not invent or recommend an immediate-deployment percentage, STP duration, parking vehicle, tax saving, yield, scheme, fund split or target allocation.
4. Do not assert that the stability buffer satisfies a debt target unless a separate validated policy result is supplied.
5. Separate verified facts, deterministic calculations, research interpretation and unavailable evidence.
6. Do not add unsupported TER, alpha, Sharpe, overlap, tax or statutory claims.
7. Include a concise risk and statutory disclaimer; do not present this report as an order or tax opinion.
"""
    return _call_llm_with_retry(prompt)

def answer_interactive_query(facts: FiduciaryFactsPayload, user_query: str, chat_history: Optional[List[Dict[str, str]]] = None) -> str:
    """Answers ad-hoc interactive questions from the user using full verified context and canonical intent routing."""
    q_lower = user_query.strip().lower()

    # Intent 1: Switch / Transition / Commission Bleed
    if any(k in q_lower for k in ("should i switch", "is switching worth it", "switch plan", "commission bleed", "broker fee", "regular vs direct", "switch cost")):
        f1 = facts.fee_bleed
        top_leaks = "\n".join(
            f"- **{item.get('fund_name', 'Scheme')}**: "
            f"INR {item.get('annual_bleed_inr', 0):,.2f}/yr (current value "
            f"INR {item.get('current_value_inr', 0):,.2f})"
            for item in f1.details[:4]
        )
        return (
            "### Regular-versus-Direct review\n\n"
            f"- Regular-plan holdings reported: {f1.regular_funds_count}.\n"
            f"- Reported Regular-plan value: INR {f1.regular_portfolio_value_inr:,.2f}.\n"
            f"- Estimated annual expense difference in supplied analysis: INR {f1.annual_bleed_inr:,.2f}.\n"
            f"- Largest reported differences:\n{top_leaks}\n\n"
            "These figures are estimates from the supplied fee analysis, not guaranteed returns or "
            "risk-free gains. A switch must be evaluated scheme-by-scheme for current Direct/Regular "
            "TER evidence, exit load, tax lots, transaction costs, mandate and investor constraints. "
            "No automatic switch schedule or tax outcome is prescribed."
        )

    # Intent 2: Fresh Money / SIP / Lumpsum Blueprint
    if any(k in q_lower for k in ("sip plan", "fresh money", "where should i invest", "fresh sip", "sip blueprint", "4-slot", "lumpsum deployment", "fresh deployment")):
        sip = getattr(facts, "deterministic_sip_plan", None)
        lump = getattr(facts, "deterministic_lumpsum_plan", None)

        sip_rows = []
        if sip is not None:
            sip_rows.extend(
                f"- **{item.category_role}**: {item.scheme_name} | "
                f"{item.allocation_pct:.2f}% | INR {item.monthly_inr:,.2f}/month"
                for item in sip.items
            )
            if sip.unallocated_budget_inr > 0:
                sip_rows.append(f"- **UNALLOCATED:** INR {sip.unallocated_budget_inr:,.2f}/month")
        if not sip_rows:
            sip_rows.append(
                f"- **NO ACTION:** No deterministic SIP plan supplied. "
                f"INR {facts.monthly_sip_budget_inr:,.2f}/month remains unallocated."
            )

        if lump is None:
            lump_status = (
                f"NO ACTION: no deterministic lumpsum plan supplied. "
                f"INR {facts.lumpsum_budget_inr:,.2f} remains unallocated. "
                "No split, STP duration, parking vehicle or tax treatment is inferred."
            )
            lump_rows = []
        else:
            lump_status = (
                f"Plan status: {lump.execution_status}; requested INR {lump.total_lumpsum_inr:,.2f}; "
                f"unallocated INR {lump.unallocated_amount_inr:,.2f}; "
                f"cash validation passed: {lump.cash_validation_passed}. "
                f"{lump.cash_validation_message}"
            )
            lump_rows = [
                f"- {tr.role}: {tr.scheme_name} | INR {tr.amount_inr:,.2f} | "
                f"{tr.allocation_pct:.2f}% | {tr.timing}"
                for tr in lump.tranches
            ]
            if not lump_rows:
                lump_rows.append("- NO ACTION: no validated deployment tranche supplied.")
            if lump.unallocated_amount_inr > 0:
                lump_rows.append(f"- UNALLOCATED: INR {lump.unallocated_amount_inr:,.2f}")
            lump_status += " No tax-saving or statutory tax conclusion is asserted."

        return (
            "### Fresh-money deployment review\n\n"
            "**Monthly SIP plan:**\n" + "\n".join(sip_rows) + "\n\n"
            "**Lumpsum plan:**\n" + lump_status + "\n"
            + ("\n".join(lump_rows) if lump_rows else "- NO ACTION: no validated tranche supplied.")
            + "\n\nAll figures are proposals only. Do not infer a deployment split, STP, parking "
            "instrument, tax benefit, destination scheme or execution authority beyond the supplied "
            "deterministic plan and mandate controls."
        )

    # Intent 3: Redemption / Withdrawal / Cash Out
    if any(k in q_lower for k in ("redeem", "redemption", "withdraw", "need cash", "take out money", "emergency withdrawal")):
        sb = facts.stability_buffer
        cash_avail = sb.bank_deployable_cash_inr if sb else 0.0
        return (
            f"### 💧 Fiduciary Personal Redemption Framework\n\n"
            f"Capital withdrawals are executed via a strict **4-Stage Tax-Minimizing Waterfall**:\n\n"
            f"1. **Stage 1 (Organic Cash):** Draw from deployable bank cash (INR {cash_avail:,.0f} available above emergency buffer) $\\rightarrow$ **INR 0 tax, INR 0 exit load**.\n"
            f"2. **Stage 2 (Tactical Regular Bleed):** Liquidate underperforming Regular plans with capital losses (loss-harvesting) or mature LTCG within the INR 1,25,000 exemption $\\rightarrow$ **Eliminates fee drag, INR 0 exit load**.\n"
            f"3. **Stage 3 (Thematic Trim):** Trim over-allocated or peak-valuation thematic holdings (e.g. Defence at 80x+ P/E).\n"
            f"4. **Stage 4 (Core Equity Siphon):** Siphon long-term Direct equity compounders held >365 days.\n\n"
            f"*To calculate an exact redemption schedule with lot-by-lot exit loads and taxes, run:* `python advisor.py --redeem <amount> [--net]`"
        )

    # Intent 4: Stability Buffer / Debt Cushion
    if any(k in q_lower for k in ("stability buffer", "debt cushion", "how much debt", "debt allocation", "cash buffer")):
        sb = facts.stability_buffer
        if sb:
            return (
                f"### 🛡️ Look-Through Stability Cushion Analysis\n\n"
                f"- **Total Look-Through Stability Buffer:** **{sb.total_stability_buffer_pct:.2f}%** of portfolio net worth.\n"
                f"- **Embedded Debt:** INR {sb.embedded_debt_inr:,.2f} ({sb.embedded_debt_pct:.2f}%) held inside hybrid/flexi-cap funds.\n"
                f"- **Embedded Cash:** INR {sb.embedded_cash_inr:,.2f} ({sb.embedded_cash_pct:.2f}%) held as fund manager dry powder.\n"
                f"- **Bank Deployable Cash:** INR {sb.bank_deployable_cash_inr:,.2f} (above emergency reserves).\n\n"
                f"**Fiduciary Impact:** This organic {sb.total_stability_buffer_pct:.2f}% stability cushion fully satisfies your **Tier 6 (5% debt ceiling)** target without requiring low-yielding standalone debt SIPs."
            )
    holdings_ledger = "\n".join(
        f"- {h.fund_name} (Folio: {h.folio}) | {h.plan.value} | Val: INR {h.current_value_inr:,.0f} | Inv: INR {h.invested_value_inr:,.0f} | Gain: INR {h.current_value_inr - h.invested_value_inr:+,.0f}"
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

Provide an authoritative, practical, and mathematically grounded fiduciary response. Quote exact rupee amounts and fund names where relevant. Explain the underlying financial reasoning clearly.
"""
    return _call_llm_with_retry(prompt)


def generate_fiduciary_report(payload: FiduciaryFactsPayload) -> str:
    """Generates the comprehensive Fiduciary Fact Sheet report."""
    return generate_health_audit_report(payload)
