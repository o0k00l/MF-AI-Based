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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

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


from core.ai_engine import ProviderError, call_llm as _engine_call_llm

def _fmt_inr(value: Any) -> str:
    """Format verified INR; an unavailable value is not zero."""
    if value is None:
        return "UNAVAILABLE"
    return f"INR {float(value):,.2f}"

def _fmt_num(value: Any, suffix: str = "") -> str:
    """Format verified numeric facts without inventing a zero."""
    if value is None:
        return "UNAVAILABLE"
    return f"{float(value):,.2f}{suffix}"

def _clean_markdown(text: str) -> str:
    """Removes excessive whitespace and fences."""
    cleaned = re.sub(r' {4,}', ' ', text)
    cleaned = re.sub(r'^```markdown\s*', '', cleaned)
    cleaned = re.sub(r'```\s*$', '', cleaned)
    return cleaned.strip()


def _sensitive_identifiers_from_facts(facts: Any) -> list[str]:
    """Collect investor/portfolio identifiers from every outbound narrative context."""
    identifiers: set[str] = set()

    def add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            identifiers.add(value.strip())
        elif isinstance(value, int) and not isinstance(value, bool):
            identifiers.add(str(value))

    def field(record: Any, name: str) -> Any:
        return record.get(name) if isinstance(record, dict) else getattr(record, name, None)

    add(getattr(facts, "client_name", None))

    # Holdings are investor-specific even when their scheme identifiers are not
    # personally identifying in isolation. Never disclose a client's exact
    # scheme/folio/security ledger to an external narrative provider.
    holding_fields = (
        "fund_name", "scheme_name", "scheme", "folio", "folio_no",
        "folio_number", "account_id", "account_number", "scheme_id",
        "fund_id", "isin", "security_id",
    )
    for holding in getattr(facts, "holdings", None) or []:
        for name in holding_fields:
            add(field(holding, name))

    # Scheme names in fee-drag and overlap records must be redacted even when a
    # caller supplied an incomplete holdings list.
    fee_bleed = getattr(facts, "fee_bleed", None)
    for detail in field(fee_bleed, "details") or []:
        add(field(detail, "fund_name"))
        add(field(detail, "scheme_name"))
    for collection_name in ("overlap_matrix", "weighted_overlap"):
        for pair in getattr(facts, collection_name, None) or []:
            add(field(pair, "fund_a"))
            add(field(pair, "fund_b"))
            for stock in field(pair, "shared_stocks") or []:
                add(stock)

    # Theme/stock names and deterministic destination names can reveal the
    # investor's portfolio composition just as directly as holding rows.
    for exposure in getattr(facts, "thematic_exposures", None) or []:
        add(field(exposure, "theme_name"))
        for stock in field(exposure, "key_underlying_holdings") or []:
            add(stock)
    for plan_name in ("deterministic_sip_plan", "deterministic_lumpsum_plan"):
        plan = getattr(facts, plan_name, None)
        rows = field(plan, "items" if plan_name.endswith("sip_plan") else "tranches") or []
        for row in rows:
            add(field(row, "scheme_name"))
            add(field(row, "fund_name"))
            add(field(row, "folio"))
            add(field(row, "account_id"))

    return sorted(identifiers, key=len, reverse=True)


def collect_sensitive_identifiers(*records: Any) -> list[str]:
    """Extract known investor/holding identifiers from nested input records."""
    sensitive_fields = {
        "client_name", "investor_name", "account_holder", "holder_name",
        "beneficiary_name", "goal_name", "goal_description", "goal_title", "goal",
        "name", "title", "description", "fund_name", "scheme_name", "scheme", "fund_id",
        "scheme_id", "folio", "folio_no", "folio_number", "account_id",
        "account_number", "bank_account", "isin", "security_id", "security_name",
        "stock_name", "theme_name", "key_underlying_holdings", "underlying_holdings",
        "transaction_description", "transaction_narration", "narration", "payee",
        "beneficiary", "merchant", "client_id", "investor_id", "user_id", "customer_id", "holder_id",
        "scheme_code", "transaction_id", "reference_number", "upi_id", "date_of_birth", "dob",
        "address", "residential_address", "postal_address", "postal_code", "pin_code",
        "pan", "pan_number", "aadhaar", "aadhaar_number",
        "email", "phone", "ifsc",
    }
    found: set[str] = set()

    def add_sensitive_values(item: Any) -> None:
        if isinstance(item, (str, int)) and not isinstance(item, bool):
            candidate = str(item).strip()
            if len(candidate) > 1:
                found.add(candidate)
        elif isinstance(item, (list, tuple, set)):
            for nested in item:
                add_sensitive_values(nested)

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized_key = str(key).strip().lower()
                if normalized_key in sensitive_fields:
                    add_sensitive_values(item)
                if isinstance(item, (dict, list, tuple)):
                    visit(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)

    for record in records:
        visit(record)
    return sorted(found, key=len, reverse=True)


def sanitize_prompt_for_privacy(
    text: str,
    client_name: Optional[str] = None,
    sensitive_identifiers: Optional[list[str]] = None,
) -> str:
    """Remove direct identifiers, investor-specific holdings and rupee balances."""
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", "[REDACTED_PAN]", s, flags=re.IGNORECASE)
    s = re.sub(r"\b\d{4}\s?\d{4}\s?\d{4}\b", "[REDACTED_AADHAAR]", s)
    s = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[REDACTED_EMAIL]", s)
    s = re.sub(r"(?:\+91[\-\s]?)?[6789]\d{9}\b", "[REDACTED_PHONE]", s)
    s = re.sub(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", "[REDACTED_IFSC]", s, flags=re.IGNORECASE)
    s = re.sub(r"(?i)\b(?:account|acct|a/c|bank account)\s*[:#-]?\s*(\d{9,18})\b", "[REDACTED_ACCOUNT]", s)
    s = re.sub(r"(?i)\b(?:folio(?:\s*(?:no\.?|number))?|acct|account|acc)\s*[:#-]?\s*[A-Z0-9/-]{4,24}\b", "[REDACTED_FOLIO]", s)
    s = re.sub(r"(?i)(?:₹|INR|Rs\.?)\s*[-+]?\s*\d[\d,]*(?:\.\d{1,2})?", "[REDACTED_FINANCIAL_AMOUNT]", s)
    s = re.sub(
        r"(?i)\b(?:portfolio value|invested value|current value|monthly sip|lumpsum budget|annual bleed|commission leakage|unrealized gain|investment amount)\b\s*[:=-]?\s*[-+]?\d[\d,]*(?:\.\d{1,2})?",
        "[REDACTED_FINANCIAL_AMOUNT]",
        s,
    )
    if client_name and len(client_name.strip()) > 1:
        s = re.sub(
            re.escape(client_name.strip()),
            "the supplied investor portfolio",
            s,
            flags=re.IGNORECASE,
        )
    identifiers = [
        value for value in (sensitive_identifiers or [])
        if isinstance(value, str)
        and len(value.strip()) > 1
        and (not client_name or value.strip().casefold() != client_name.strip().casefold())
    ]
    for identifier in sorted({value.strip() for value in identifiers}, key=len, reverse=True):
        s = re.sub(re.escape(identifier), "[REDACTED_PORTFOLIO_DETAIL]", s, flags=re.IGNORECASE)

    # Numeric facts (including percentages, ages, returns, units, NAVs and
    # values without an explicit INR label) are not needed by the qualitative
    # external narrative layer. Keep all financial arithmetic local.
    s = re.sub(
        r"(?<![A-Za-z])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*%?",
        "[REDACTED_NUMERIC_DETAIL]",
        s,
    )
    return s


def _call_llm_with_retry(
    prompt: str,
    model_name: str = "",
    max_retries: int = 3,
    *,
    external_processing_consent: bool = False,
    client_name: Optional[str] = None,
    sensitive_identifiers: Optional[list[str]] = None,
) -> str:
    """Call a free provider only after explicit per-request investor consent and prompt sanitization."""
    if external_processing_consent is not True:
        from core.ai_engine import ProviderError
        raise ProviderError(
            "Privacy",
            "External AI processing is blocked: explicit investor consent is required for this request.",
        )
    sanitized_prompt = sanitize_prompt_for_privacy(
        prompt, client_name=client_name, sensitive_identifiers=sensitive_identifiers,
    )
    res = _engine_call_llm(
        sanitized_prompt,
        system_instruction=SYSTEM_INSTRUCTION,
        use_cache=False,
        external_processing_consent=external_processing_consent,
    )
    return _clean_markdown(res)


def generate_health_audit_report(
    facts: FiduciaryFactsPayload,
    *,
    external_processing_consent: bool = False,
) -> str:
    """Generates the comprehensive Portfolio Health & Commission Bleed Audit."""
    top_bleed_schemes = facts.fee_bleed.details[:8]
    high_overlap_pairs = facts.overlap_matrix[:6]

    weighted_overlap = getattr(facts, 'weighted_overlap', [])
    risk_distribution = getattr(facts, 'risk_distribution', None)
    # Unverified caller-provided cost records are never admitted to investor-facing prompts.
    switch_costs = []
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
        stability_info = f"Total Stability Buffer: {_fmt_num(sb.total_stability_buffer_pct, '%')} (Embedded Debt: {_fmt_inr(sb.embedded_debt_inr)}, Embedded Cash: {_fmt_inr(sb.embedded_cash_inr)}). Meets Tier Target: {sb.meets_tier_target if sb.meets_tier_target is not None else 'UNKNOWN'}."

    prompt = f"""
Generate Deliverable 1: 'Portfolio Health & Commission Bleed Audit' for the supplied investor portfolio.

INPUT FACT PAYLOAD:
- Total Portfolio Value: INR {facts.total_portfolio_value_inr:,.2f}
- Total Invested Value: INR {facts.total_invested_value_inr:,.2f}
- Total Unrealized Gain: INR {facts.total_unrealized_gain_inr:,.2f}
- Portfolio Performance: XIRR {xirr_val} vs Benchmark {benchmark_val} (Jensen's Alpha: {alpha_val})
- Total Holdings Count: {facts.holdings_count} funds
- Regular Plan Count: {facts.fee_bleed.regular_funds_count} funds
- Regular Plan Total Value: {_fmt_inr(facts.fee_bleed.regular_portfolio_value_inr)}
- Annual Commission Drag: {_fmt_inr(facts.fee_bleed.annual_bleed_inr)} per year
- 10-Year Fee-Difference Scenario Estimate: {_fmt_inr(facts.fee_bleed.ten_year_compounded_loss_inr)} (unavailable unless approved scenario assumptions are supplied)
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
- Switch Cost Evidence: UNAVAILABLE — caller-provided cost records are not trusted or displayed.
- Switch Cost Details: NO ACTION — scheme/plan/lot-specific exit-load and independently approved tax evidence is unavailable.
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
2. Regular-plan Cost Evidence: Report commission and future projection as UNAVAILABLE unless the payload includes independently verified plan-/distributor-/effective-date-specific evidence and explicitly approved scenario assumptions. Do not infer a fee advantage from a generic percentage. Include the supplied scheme details only.
3. Weighted Look-Through Overlap Analysis: Contrast the weighted look-through overlap methodology against naive Jaccard. Report the top weighted overlap pairs and shared stocks.
4. Ordinal Risk Distribution: Report SEBI risk-o-meter tier distribution (explaining why cardinal averages like 5.84/6.00 are mathematically invalid for ordinal data).
5. Scheme Overlap & Duplication Analysis: Use the actual holdings count and supplied overlap evidence. Do not assume that overlap is high or that consolidation is required.
6. Asset Mix Analysis & Look-Through Stability Buffer: Contrast supplied current allocation vs target. If stability-buffer evidence is absent, state unavailable rather than substituting 0.00%.
7. Switch Cost Analysis: Report only the supplied scheme-level cost records. Do not infer tax treatment or cite statutory sections without validated source evidence.
8. Immediate Diagnostic Summary: Clear, actionable summary for the investor.
    """
    return _call_llm_with_retry(
        prompt,
        external_processing_consent=external_processing_consent,
        client_name=facts.client_name,
        sensitive_identifiers=_sensitive_identifiers_from_facts(facts),
    )


def generate_switch_and_consolidation_plan(
    facts: FiduciaryFactsPayload,
    *,
    external_processing_consent: bool = False,
) -> str:
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
    # Caller-supplied "available" flags are not evidence of independent
    # approval, lot reconciliation, or scheme-specific exit-load verification.
    # The production tax/switch-cost gate remains closed; never echo amounts.
    switch_cost_rows = [
        "- NO ACTION: switch-cost figures supplied to the report are unverified and are not displayed."
    ] if switch_costs else [
        "- NO ACTION: scheme/plan/lot-specific exit-load and independently approved tax evidence is unavailable."
    ]

    # Tax-lot summaries have no approved provenance contract in this reporting
    # interface. Presence or shape alone must never make them trusted.
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
Generate a fund-by-fund Regular-versus-Direct and portfolio-overlap review for the supplied investor portfolio.
This is a review, not an instruction to switch, redeem, consolidate or transact.

VERIFIED PORTFOLIO FACTS:
- Reported portfolio value: INR {facts.total_portfolio_value_inr:,.2f}
- Reported holdings count: {facts.holdings_count}
- Regular-plan holdings: {len(regular_holdings)}
- Direct-plan holdings: {len(direct_holdings)}
- Reported annual Regular-plan expense difference estimate: {_fmt_inr(facts.fee_bleed.annual_bleed_inr)}
- Reported 10-year fee-difference scenario estimate: {_fmt_inr(facts.fee_bleed.ten_year_compounded_loss_inr)}
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
    return _call_llm_with_retry(
        prompt,
        external_processing_consent=external_processing_consent,
        client_name=facts.client_name,
        sensitive_identifiers=_sensitive_identifiers_from_facts(facts),
    )

def _validate_lumpsum_plan_for_reporting(plan: Any, requested_amount: Any) -> tuple[bool, str]:
    """Validate basic cash gate and amount reconciliation before exposing tranches."""
    try:
        requested = Decimal(str(requested_amount))
        total = Decimal(str(plan.total_lumpsum_inr))
        unallocated = Decimal(str(plan.unallocated_amount_inr))
        tranche_amounts = [Decimal(str(item.amount_inr)) for item in plan.tranches]
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        return False, "Required lumpsum plan amounts are missing or invalid."

    values = [requested, total, unallocated, *tranche_amounts]
    if any(not value.is_finite() or value < 0 for value in values):
        return False, "Lumpsum plan contains a negative or non-finite amount."
    if plan.cash_validation_passed is not True:
        return False, "Independent bank-cash validation has not passed."
    if abs(total - requested) > Decimal("0.01"):
        return False, "Plan total does not match the requested lumpsum budget."
    if abs(total - (sum(tranche_amounts, Decimal("0")) + unallocated)) > Decimal("0.01"):
        return False, "Tranche amounts plus unallocated amount do not reconcile to the plan total."
    return True, ""


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
            lines.append("   Target folio: Redacted for external narrative" if item.folio_target else "   Target folio: Not specified")
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


def generate_cash_and_sip_plan(
    facts: FiduciaryFactsPayload,
    *,
    external_processing_consent: bool = False,
) -> str:
    """Generate a grounded SIP/lumpsum report; absent plans remain NO ACTION."""
    lumpsum_amt = getattr(facts, "lumpsum_budget_inr", 0.0)
    lump_plan = getattr(facts, "deterministic_lumpsum_plan", None)

    lump_rows = []
    if lump_plan is None:
        lumpsum_status = (
            "NO ACTION: no deterministic lumpsum plan was supplied. "
            "Do not propose a split, parking vehicle, STP duration or tax treatment. "
            "The full requested lumpsum budget remains unallocated."
        )
    else:
        plan_valid, validation_reason = _validate_lumpsum_plan_for_reporting(lump_plan, lumpsum_amt)
        if not plan_valid:
            lumpsum_status = (
                "NO ACTION: the deterministic lumpsum plan failed reporting validation. "
                f"{validation_reason} The full requested budget remains on HOLD and unallocated."
            )
            lump_rows.append(
                f"| NO ACTION | No validated destination | — | INR {lumpsum_amt:,.2f} | — | HOLD | — | "
                "Plan failed cash or reconciliation validation |"
            )
        elif not lump_plan.tranches:
            lumpsum_status = (
                f"NO ACTION: no qualifying deployment tranche was supplied. "
                f"INR {lump_plan.total_lumpsum_inr:,.2f} remains unallocated. "
                f"Validation: {lump_plan.cash_validation_message or 'No qualifying candidate.'}"
            )
            lump_rows.append(
                f"| NO ACTION | No validated destination | — | INR {lump_plan.total_lumpsum_inr:,.2f} | — | HOLD | — | "
                "No qualifying tranche supplied |"
            )
        else:
            unallocated = Decimal(str(lump_plan.unallocated_amount_inr))
            lumpsum_status = (
                f"Validated cash gate passed. Requested amount: INR {lump_plan.total_lumpsum_inr:,.2f}. "
                f"Unallocated amount: INR {unallocated:,.2f}. "
                f"Validation: {lump_plan.cash_validation_message or 'No additional message supplied.'} "
                "No tax-saving or tax-classification conclusion is asserted."
            )
            for tranche in lump_plan.tranches:
                folio = "Not transmitted to external narrative provider"
                lump_rows.append(
                    f"| {tranche.role} | {tranche.scheme_name} | {folio} | "
                    f"INR {tranche.amount_inr:,.2f} | {tranche.allocation_pct:.2f}% | "
                    f"{tranche.timing} | {tranche.source_vehicle} | {tranche.fiduciary_rationale} |"
                )
            if unallocated > 0:
                lump_rows.append(
                    f"| UNALLOCATED | No destination | — | INR {unallocated:,.2f} | — | HOLD | — | "
                    "No qualifying allocation; do not redistribute |"
                )

    lumpsum_table_str = "\n".join(lump_rows) if lump_rows else (
        "| NO ACTION | No validated destination | — | INR 0.00 | — | HOLD | — | "
        "No deterministic plan supplied |"
    )

    sip_plan = getattr(facts, "deterministic_sip_plan", None)
    sip_rows = []
    if sip_plan is not None:
        for item in sip_plan.items:
            folio = "Not transmitted to external narrative provider"
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
            f"Reported stability buffer: {_fmt_num(stability.total_stability_buffer_pct, '%')} "
            f"(embedded debt {_fmt_inr(stability.embedded_debt_inr)}; "
            f"embedded cash {_fmt_inr(stability.embedded_cash_inr)}; "
            f"bank deployable cash {_fmt_inr(stability.bank_deployable_cash_inr)}). "
            "Do not infer that this satisfies any target unless a separate validated policy check is supplied."
        )

    selection_dossier = _build_dynamic_selection_dossier(facts)
    mandate_state = facts.mandate_state.value if hasattr(facts.mandate_state, "value") else str(facts.mandate_state)
    is_execution_authorized = getattr(facts, "is_execution_authorized", False)
    is_actionable_order = getattr(facts, "is_actionable_order", False)

    prompt = f"""
Generate Deliverable 3: Fresh Money Deployment Plan (SIP & Lumpsum) for the supplied investor portfolio.
This is non-executable decision support. Do not fill gaps with customary allocations or assumptions.

INPUT FACT PAYLOAD:
- Investor: the supplied investor portfolio (Age: {facts.client_age}, Horizon: {facts.horizon_years} Years)
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
    return _call_llm_with_retry(
        prompt,
        external_processing_consent=external_processing_consent,
        client_name=facts.client_name,
        sensitive_identifiers=_sensitive_identifiers_from_facts(facts),
    )

def answer_interactive_query(
    facts: FiduciaryFactsPayload,
    user_query: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    *,
    external_processing_consent: bool = False,
) -> str:
    """Answers ad-hoc interactive questions from the user using full verified context and canonical intent routing."""
    c_name = getattr(facts, "client_name", None)
    sensitive_identifiers = _sensitive_identifiers_from_facts(facts)
    sanitized_query = sanitize_prompt_for_privacy(
        user_query, client_name=c_name, sensitive_identifiers=sensitive_identifiers,
    )
    q_lower = sanitized_query.strip().lower()

    # Intent 1: Switch / Transition / Commission Bleed
    if any(k in q_lower for k in ("should i switch", "is switching worth it", "switch plan", "commission bleed", "broker fee", "regular vs direct", "switch cost")):
        f1 = facts.fee_bleed
        top_leaks = "\n".join(
            f"- **{item.get('fund_name', 'Scheme')}**: "
            f"{_fmt_inr(item.get('annual_bleed_inr'))}/yr"
            f"INR {item.get('current_value_inr', 0):,.2f})"
            for item in f1.details[:4]
        )
        return (
            "### Regular-versus-Direct review\n\n"
            f"- Regular-plan holdings reported: {f1.regular_funds_count}.\n"
            f"- Reported Regular-plan value: {_fmt_inr(f1.regular_portfolio_value_inr)}.\n"
            f"- Verified annual commission: {_fmt_inr(f1.annual_bleed_inr)}.\n"
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
            plan_valid, validation_reason = _validate_lumpsum_plan_for_reporting(
                lump, facts.lumpsum_budget_inr
            )
            if not plan_valid:
                lump_status = (
                    f"NO ACTION: lumpsum plan failed validation. {validation_reason} "
                    f"INR {facts.lumpsum_budget_inr:,.2f} remains on HOLD and unallocated."
                )
                lump_rows = []
            elif not lump.tranches:
                lump_status = (
                    f"NO ACTION: no qualifying tranche supplied. "
                    f"INR {lump.total_lumpsum_inr:,.2f} remains unallocated."
                )
                lump_rows = []
            else:
                lump_status = (
                    f"Validated cash gate passed; requested INR {lump.total_lumpsum_inr:,.2f}; "
                    f"unallocated INR {lump.unallocated_amount_inr:,.2f}. "
                    "No tax-saving or statutory tax conclusion is asserted."
                )
                lump_rows = [
                    f"- {tr.role}: {tr.scheme_name} | INR {tr.amount_inr:,.2f} | "
                    f"{tr.allocation_pct:.2f}% | {tr.timing}"
                    for tr in lump.tranches
                ]
                if lump.unallocated_amount_inr > 0:
                    lump_rows.append(f"- UNALLOCATED: INR {lump.unallocated_amount_inr:,.2f}")


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
        stability = getattr(facts, "stability_buffer", None)
        # Caller-supplied tax-lot payloads have no approved provenance contract.
        # Never repeat their values in investor-facing redemption responses.
        tax_lot_details = None

        cash_text = (
            f"Reported bank deployable cash: {_fmt_inr(stability.bank_deployable_cash_inr)}."
            if stability is not None
            else "Bank deployable cash: unavailable; do not infer a cash balance."
        )
        tax_text = "Tax-lot evidence unavailable: NO ACTION on tax-optimized redemption or switching."
        return (
            "### Redemption and withdrawal review\n\n"
            f"- {cash_text}\n"
            f"- {tax_text}\n\n"
            "This information is not a withdrawal instruction. Do not assume that bank cash is "
            "available for withdrawal without confirming the emergency reserve and source evidence. "
            "Do not infer tax rates, holding periods, FIFO outcomes, exit loads, exemptions or a "
            "redemption order. Obtain a current lot-level calculation and independent review before "
            "any transaction."
        )

    # Intent 4: Stability Buffer / Debt Cushion
    if any(k in q_lower for k in ("stability buffer", "debt cushion", "how much debt", "debt allocation", "cash buffer")):
        stability = getattr(facts, "stability_buffer", None)
        if stability is None:
            return "Stability-buffer evidence is unavailable. NO ACTION: do not infer debt, cash or allocation-target coverage."

        return (
            "### Look-through stability-buffer observations\n\n"
            f"- Reported total stability buffer: {_fmt_num(stability.total_stability_buffer_pct, '%')}.\n"
            f"- Reported embedded debt: {_fmt_inr(stability.embedded_debt_inr)} "
            f"({stability.embedded_debt_pct:.2f}%).\n"
            f"- Reported embedded cash: {_fmt_inr(stability.embedded_cash_inr)} "
            f"({stability.embedded_cash_pct:.2f}%).\n"
            f"- Reported bank deployable cash: {_fmt_inr(stability.bank_deployable_cash_inr)}.\n\n"
            "These are reported observations, not an automatic debt-target pass or a recommendation "
            "to route new SIPs entirely to equity. Use the separately validated policy result and "
            "investor mandate before drawing an allocation conclusion."
        )
    holdings_ledger = "\n".join(
        f"- {h.fund_name} ({h.plan.value}): approx {h.current_value_inr / facts.total_portfolio_value_inr * 100:.1f}% allocation"
        for h in sorted(facts.holdings, key=lambda x: -x.current_value_inr)
    ) if facts.total_portfolio_value_inr > 0 else "None"

    xirr_str = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "N/A"
    benchmark_str = f"{facts.benchmark_xirr_pct * 100:.2f}%" if facts.benchmark_xirr_pct is not None else "N/A"
    alpha_str = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "N/A"

    context_summary = f"""
CLIENT CONTEXT:
- Name: the supplied investor portfolio
- Total Portfolio: INR {facts.total_portfolio_value_inr:,.2f} ({facts.holdings_count} funds)
- Invested Value: INR {facts.total_invested_value_inr:,.2f} | Unrealized Gain: INR {facts.total_unrealized_gain_inr:,.2f}
- Portfolio XIRR: {xirr_str} | Benchmark: {benchmark_str} | Alpha: {alpha_str}
- Regular Funds: {facts.fee_bleed.regular_funds_count} funds ({_fmt_inr(facts.fee_bleed.regular_portfolio_value_inr)})
- Annual Fee Drag: {_fmt_inr(facts.fee_bleed.annual_bleed_inr)} / year
- 10-Year Compounded Commission Drag: {_fmt_inr(facts.fee_bleed.ten_year_compounded_loss_inr)}
- Current Split: {facts.saa_drift.current_equity_pct}% Equity, {facts.saa_drift.current_debt_pct}% Debt, {facts.saa_drift.current_cash_pct}% Cash
- Target Split: {facts.saa_drift.target_equity_pct}% Equity, {facts.saa_drift.target_debt_pct}% Debt
- Fresh Lumpsum Budget: INR {getattr(facts, 'lumpsum_budget_inr', 200000.0):,.2f}
- Monthly SIP Budget: INR {facts.monthly_sip_budget_inr:,.2f}

ALL ACTIVE HOLDINGS:
{holdings_ledger}
"""

    # Prior conversation turns are intentionally excluded from external calls.
    # Only the current, minimized question is sent.
    history_str = ""

    prompt = f"""
{context_summary}

CONVERSATION HISTORY:
{history_str}

USER QUESTION:
[WITHHELD — arbitrary user-entered text is not sent to third-party AI.]

Provide a qualitative fiduciary explanation only. Do not reconstruct redacted rupee amounts, investor names or scheme identifiers. Numerical financial decisions and figures remain in the deterministic local report.
"""
    return _call_llm_with_retry(
        prompt,
        external_processing_consent=external_processing_consent,
        client_name=c_name,
        sensitive_identifiers=sensitive_identifiers,
    )


def generate_fiduciary_report(
    payload: FiduciaryFactsPayload,
    *,
    external_processing_consent: bool = False,
) -> str:
    """Generates the comprehensive Fiduciary Fact Sheet report."""
    return generate_health_audit_report(payload, external_processing_consent=external_processing_consent)
