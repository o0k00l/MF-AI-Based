"""CGS (Capital Gains Statement) parser service for the UI layer.

Adheres strictly to the repository architecture:
- Wraps ingestion.cgs_parser.parse_cgs_excel
- Enforces fail-closed trust boundaries
- Preserves raw source-reported figures without fabricating tax advice
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, BinaryIO

from ingestion.cgs_parser import parse_cgs_excel

logger = logging.getLogger(__name__)


def parse_cgs_file(file_obj: BinaryIO | bytes | Path) -> dict[str, Any]:
    """Parse an uploaded Capital Gains Statement (.xlsx) from CAMS/KFintech/MFCentral.

    Returns structured summary of realized STCG, LTCG, scheme breakdown, and lot history.
    """
    if isinstance(file_obj, (str, Path)):
        return parse_cgs_excel(file_obj)

    # Uploaded bytes are parsed directly in memory. Never stage investor
    # statements in a named temporary file, which can survive process failure.
    if hasattr(file_obj, "read"):
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
        content = file_obj.read()
        if hasattr(file_obj, "seek"):
            file_obj.seek(0)
    elif isinstance(file_obj, (bytes, bytearray, memoryview)):
        content = bytes(file_obj)
    else:
        raise ValueError(f"Unsupported file object type: {type(file_obj)}")

    return parse_cgs_excel(content)


def evaluate_tax_harvesting_strategy(
    cgs_data: dict[str, Any] | None,
    portfolio: list[dict[str, Any]] | None = None,
    use_live_ai: bool = False,
    external_processing_consent: bool = False,
) -> dict[str, Any]:
    """Evaluate Section 112A annual tax harvesting, loss set-off, and tax-efficient rebalancing.

    Statutory Framework (Budget 2024 / Section 112A & 111A):
    - Section 112A: INR 1,25,000 annual exemption limit for LTCG on equity mutual funds.
    - Long-term equity gains taxed at 12.5% above exemption limit.
    - Short-term equity gains under Section 111A taxed at 20.0%.
    - Tax-harvesting: Realizing up to remaining exemption headroom each FY permanently steps up cost basis.
    - Set-off: LTCL can only offset LTCG. STCL can offset both STCG and LTCG.
    """
    summary = (cgs_data or {}).get("summary", {}) if isinstance(cgs_data, dict) else {}
    realized_ltcg = float(summary.get("ltcg_inr") or 0.0)
    realized_stcg = float(summary.get("stcg_inr") or 0.0)

    annual_exemption_limit = 125_000.0
    remaining_headroom = max(0.0, annual_exemption_limit - max(0.0, realized_ltcg))

    portfolio_funds = portfolio or []
    unrealized_equity_gain = 0.0
    unrealized_equity_loss = 0.0
    harvestable_schemes: list[dict[str, Any]] = []
    loss_schemes: list[dict[str, Any]] = []

    for f in portfolio_funds:
        c_val = float(f.get("current_value", 0.0) or 0.0)
        i_val = float(f.get("invested_value", 0.0) or 0.0)
        gain = c_val - i_val
        is_equity = (
            str(f.get("category", "")).strip().lower() in ("equity", "hybrid")
            or float(f.get("eq", 0.0) or 0.0) >= 50.0
        )
        if is_equity and gain > 0:
            unrealized_equity_gain += gain
            harvestable_schemes.append({
                "scheme": f.get("scheme", "Equity Scheme"),
                "unrealized_gain": round(gain, 2),
                "plan_type": f.get("plan_type", "Direct"),
            })
        elif is_equity and gain < 0:
            unrealized_equity_loss += abs(gain)
            loss_schemes.append({
                "scheme": f.get("scheme", "Equity Scheme"),
                "unrealized_loss": round(abs(gain), 2),
                "plan_type": f.get("plan_type", "Direct"),
            })

    harvestable_amount = min(remaining_headroom, unrealized_equity_gain)
    potential_tax_saving = round(harvestable_amount * 0.125, 2)

    loss_setoff_insights: list[str] = []
    if realized_ltcg < 0:
        loss_setoff_insights.append(
            f"Realized Long-Term Capital Loss of INR {abs(realized_ltcg):,.2f} can only be set off against Long-Term Capital Gains and can be carried forward for up to 8 assessment years."
        )
    if realized_stcg < 0:
        loss_setoff_insights.append(
            f"Realized Short-Term Capital Loss of INR {abs(realized_stcg):,.2f} can be set off against both STCG and LTCG, reducing current tax liability."
        )
    if unrealized_equity_loss > 0 and (realized_ltcg > 0 or realized_stcg > 0):
        loss_setoff_insights.append(
            f"Tax-Loss Harvesting Potential: Portfolio holds INR {unrealized_equity_loss:,.2f} in unrealized losses across {len(loss_schemes)} schemes that can be booked to offset realized taxable gains."
        )

    rebalancing_recommendations: list[str] = []
    # Identify Regular plan holdings that can be switched to Direct without paying any tax
    regular_funds = [f for f in portfolio_funds if str(f.get("plan_type", "")).strip().upper() == "REGULAR"]
    regular_gains = sum(max(0.0, float(f.get("current_value", 0)) - float(f.get("invested_value", 0))) for f in regular_funds)
    if regular_gains > 0 and remaining_headroom > 0:
        switch_capacity = min(remaining_headroom, regular_gains)
        rebalancing_recommendations.append(
            f"Zero-Tax Regular to Direct Conversion: Up to INR {switch_capacity:,.2f} of Regular plan capital gains can be switched immediately to Direct Growth plans without triggering any capital gains tax under Section 112A."
        )
    rebalancing_recommendations.append(
        "Holding Period Discipline: Strictly avoid rebalancing equity lots held for less than 365 days to prevent the 20.0% short-term capital gains tax under Section 111A."
    )

    # Generate AI / Institutional Synthesis Narrative
    ai_narrative = ""
    if use_live_ai and external_processing_consent is True:
        try:
            from core.ai_engine import call_llm
            prompt = f"""You are a SEBI-registered Research Analyst and Tax-Efficient Wealth Advisor.
Analyze the following Capital Gains Statement (CGS) and portfolio holdings for Section 112A tax optimization:
- Realized LTCG: INR {realized_ltcg:,.2f}
- Realized STCG: INR {realized_stcg:,.2f}
- Annual Section 112A Exemption Limit: INR {annual_exemption_limit:,.2f}
- Remaining Tax-Free LTCG Headroom: INR {remaining_headroom:,.2f}
- Total Portfolio Unrealized Equity Gains: INR {unrealized_equity_gain:,.2f}
- Max Harvestable Amount this FY: INR {harvestable_amount:,.2f} (Potential tax saving: INR {potential_tax_saving:,.2f} @ 12.5%)
- Regular Plan Switch Capacity: INR {regular_gains:,.2f}

Provide a concise, institutional tax optimization action plan covering:
1. Section 112A Tax-Harvesting Strategy (how and when to harvest)
2. Loss Set-Off & Carry-Forward Strategy
3. Tax-Efficient Regular-to-Direct Switching Guidance
Tone: Objective, fiduciary, statutory compliance-focused."""
            from core.prompt_advisor import collect_sensitive_identifiers, sanitize_prompt_for_privacy
            minimized_prompt = sanitize_prompt_for_privacy(
                prompt,
                sensitive_identifiers=collect_sensitive_identifiers(cgs_data, portfolio_funds),
            )
            res = call_llm(
                minimized_prompt,
                external_processing_consent=external_processing_consent,
                use_cache=False,
            )
            if res and len(res.strip()) > 50:
                ai_narrative = res.strip()
        except Exception as exc:
            logger.debug("Live AI tax narrative generation unavailable (%s)", type(exc).__name__)

    if not ai_narrative:
        ai_narrative = (
            f"Under Section 112A (amended Budget 2024), you have **INR {remaining_headroom:,.2f}** in remaining tax-exempt headroom "
            f"out of the annual INR 1,25,000 threshold. With INR {unrealized_equity_gain:,.2f} in unrealized equity gains across your portfolio, "
            f"you can harvest up to **INR {harvestable_amount:,.2f}** before the financial year end by redeeming and immediately reinvesting "
            f"in Direct Growth plans, permanently stepping up your cost basis and saving an estimated **INR {potential_tax_saving:,.2f}** in future LTCG taxes."
        )

    return {
        "status": "ANALYZED",
        "annual_exemption_limit_inr": annual_exemption_limit,
        "realized_ltcg_inr": realized_ltcg,
        "realized_stcg_inr": realized_stcg,
        "remaining_headroom_inr": remaining_headroom,
        "unrealized_equity_gain_inr": unrealized_equity_gain,
        "unrealized_equity_loss_inr": unrealized_equity_loss,
        "harvestable_amount_inr": harvestable_amount,
        "potential_tax_saving_inr": potential_tax_saving,
        "loss_setoff_insights": loss_setoff_insights,
        "rebalancing_recommendations": rebalancing_recommendations,
        "ai_tax_narrative": ai_narrative,
    }


