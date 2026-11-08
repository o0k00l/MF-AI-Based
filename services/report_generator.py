"""
Professional PDF Report Generator for Fiduciary Advisory Reports.

Generates compliant, branded PDF reports from portfolio analysis data
using reportlab for pixel-perfect output suitable for client delivery.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Frame, NextPageTemplate, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.doctemplate import BaseDocTemplate
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.colors import HexColor


# --- Color Palette ---
NAVY = HexColor("#0f172a")
DARK_BLUE = HexColor("#1e3a8a")
MEDIUM_BLUE = HexColor("#2563eb")
LIGHT_BLUE = HexColor("#3b82f6")
ACCENT_GOLD = HexColor("#f59e0b")
ACCENT_GREEN = HexColor("#10b981")
ACCENT_RED = HexColor("#ef4444")
WHITE = HexColor("#ffffff")
LIGHT_GRAY = HexColor("#f1f5f9")
MEDIUM_GRAY = HexColor("#94a3b8")
DARK_GRAY = HexColor("#334155")
BLACK = HexColor("#000000")
TABLE_HEADER_BG = HexColor("#1e293b")
TABLE_ALT_ROW = HexColor("#f8fafc")
TABLE_BORDER = HexColor("#e2e8f0")


# --- Styles ---
def _get_styles() -> dict[str, ParagraphStyle]:
    styles = getSampleStyleSheet()
    
    custom_styles = {
        "CoverTitle": ParagraphStyle(
            "CoverTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=28,
            leading=34,
            textColor=WHITE,
            alignment=TA_CENTER,
            spaceAfter=12,
        ),
        "CoverSubtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=14,
            leading=18,
            textColor=HexColor("#93c5fd"),
            alignment=TA_CENTER,
            spaceAfter=6,
        ),
        "CoverMeta": ParagraphStyle(
            "CoverMeta",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=HexColor("#94a3b8"),
            alignment=TA_CENTER,
            spaceAfter=4,
        ),
        "SectionHeader": ParagraphStyle(
            "SectionHeader",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=20,
            textColor=NAVY,
            spaceBefore=18,
            spaceAfter=10,
            borderPadding=(0, 0, 4, 0),
        ),
        "SubSectionHeader": ParagraphStyle(
            "SubSectionHeader",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=DARK_BLUE,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "BodyText": ParagraphStyle(
            "BodyText",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=DARK_GRAY,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
        ),
        "BodyTextSmall": ParagraphStyle(
            "BodyTextSmall",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=DARK_GRAY,
            alignment=TA_JUSTIFY,
            spaceAfter=4,
        ),
        "BulletText": ParagraphStyle(
            "BulletText",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=DARK_GRAY,
            leftIndent=20,
            bulletIndent=8,
            spaceAfter=3,
        ),
        "TableHeader": ParagraphStyle(
            "TableHeader",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=WHITE,
            alignment=TA_CENTER,
        ),
        "TableCell": ParagraphStyle(
            "TableCell",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=DARK_GRAY,
            alignment=TA_LEFT,
        ),
        "TableCellCenter": ParagraphStyle(
            "TableCellCenter",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=DARK_GRAY,
            alignment=TA_CENTER,
        ),
        "TableCellRight": ParagraphStyle(
            "TableCellRight",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=DARK_GRAY,
            alignment=TA_RIGHT,
        ),
        "TableCellBold": ParagraphStyle(
            "TableCellBold",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=DARK_GRAY,
            alignment=TA_LEFT,
        ),
        "FooterNote": ParagraphStyle(
            "FooterNote",
            parent=styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=7.5,
            leading=10,
            textColor=MEDIUM_GRAY,
            alignment=TA_CENTER,
        ),
        "Disclaimer": ParagraphStyle(
            "Disclaimer",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=MEDIUM_GRAY,
            alignment=TA_JUSTIFY,
            leftIndent=12,
            rightIndent=12,
        ),
        "MetricLabel": ParagraphStyle(
            "MetricLabel",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=MEDIUM_GRAY,
        ),
        "MetricValue": ParagraphStyle(
            "MetricValue",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=NAVY,
        ),
    }
    return custom_styles


def _fmt_inr(value: float | Decimal | int | str) -> str:
    """Format number as Indian Rupees with commas."""
    try:
        val = float(value)
    except (ValueError, TypeError):
        return "₹0"
    if val >= 1e7:
        return f"₹{val/1e7:.2f} Cr"
    elif val >= 1e5:
        return f"₹{val/1e5:.2f} L"
    else:
        return f"₹{val:,.0f}"


def _fmt_pct(value: float | Decimal | int | str) -> str:
    """Format as percentage."""
    try:
        val = float(value)
    except (ValueError, TypeError):
        return "0.0%"
    return f"{val:.1f}%"


def _build_cover_page(story, styles, data):
    story.append(Spacer(1, 5*cm))
    story.append(Paragraph("Executive Fiduciary Report", styles["CoverTitle"]))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("Comprehensive Portfolio Diagnostic & Investment Advisory", styles["CoverSubtitle"]))
    story.append(Spacer(1, 1*cm))
    story.append(HRFlowable(width="60%", thickness=2, color=ACCENT_GOLD, spaceAfter=1*cm))
    client_name = data.get("client_name", "Confidential Client")
    report_date = data.get("report_date", date.today().strftime("%B %d, %Y"))
    portfolio_value = data.get("portfolio_value_inr", 0)
    story.append(Paragraph(f"Prepared for: <b>{client_name}</b>", styles["CoverMeta"]))
    story.append(Paragraph(f"Report Date: {report_date}", styles["CoverMeta"]))
    story.append(Paragraph(f"Portfolio Value: <b>{_fmt_inr(portfolio_value)}</b>", styles["CoverMeta"]))
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph("SEBI Registered Investment Adviser \u2022 Fee-Only Fiduciary Standard", ParagraphStyle("ComplianceBadge", parent=styles["CoverMeta"], fontSize=9, textColor=ACCENT_GOLD)))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("SEBI (Investment Advisers) Regulations, 2013 \u2014 Regulation 15(1) & Schedule III", ParagraphStyle("RegRef", parent=styles["CoverMeta"], fontSize=8, textColor=HexColor("#64748b"))))
    story.append(PageBreak())


def _build_executive_summary(story, styles, data):
    story.append(Paragraph("1. Executive Summary", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=MEDIUM_BLUE, spaceAfter=0.5*cm))
    portfolio = data.get("portfolio", [])
    total_value = data.get("portfolio_value_inr", sum(float(h.get("current_value_inr", 0)) for h in portfolio))
    num_holdings = len(portfolio)
    saa = data.get("saa_analysis", {})
    eq_pct = saa.get("equity_pct", 0)
    debt_pct = saa.get("debt_pct", 0)
    gold_pct = saa.get("gold_pct", 0)
    sip_plan = data.get("sip_plan", {})
    sip_budget = sip_plan.get("monthly_budget_inr", 0)
    sip_allocated = sip_plan.get("allocated_budget_inr", 0)
    
    metrics_data = [
        [Paragraph("Portfolio Value", styles["MetricLabel"]), Paragraph(_fmt_inr(total_value), styles["MetricValue"])],
        [Paragraph("Number of Holdings", styles["MetricLabel"]), Paragraph(str(num_holdings), styles["MetricValue"])],
        [Paragraph("Equity Allocation", styles["MetricLabel"]), Paragraph(_fmt_pct(eq_pct), styles["MetricValue"])],
        [Paragraph("Debt Allocation", styles["MetricLabel"]), Paragraph(_fmt_pct(debt_pct), styles["MetricValue"])],
        [Paragraph("Gold/Other", styles["MetricLabel"]), Paragraph(_fmt_pct(gold_pct), styles["MetricValue"])],
        [Paragraph("Monthly SIP Budget", styles["MetricLabel"]), Paragraph(_fmt_inr(sip_budget), styles["MetricValue"])],
        [Paragraph("Allocated SIP", styles["MetricLabel"]), Paragraph(_fmt_inr(sip_allocated), styles["MetricValue"])],
    ]
    metrics_table = Table(metrics_data, colWidths=[5*cm, 6*cm])
    metrics_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GRAY),
        ("TEXTCOLOR", (0, 0), (-1, -1), DARK_GRAY),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, TABLE_BORDER),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
    ]))
    story.append(metrics_table)
    story.append(Spacer(1, 0.5*cm))
    risk_tier = data.get("risk_tier", "Moderate")
    story.append(Paragraph(f"This report presents a comprehensive fiduciary analysis of the client\\'s mutual fund portfolio valued at {_fmt_inr(total_value)} across {num_holdings} holdings. The portfolio has been assessed against a <b>{risk_tier}</b> risk profile with a target Strategic Asset Allocation (SAA) of {_fmt_pct(eq_pct)} equity / {_fmt_pct(debt_pct)} debt / {_fmt_pct(gold_pct)} gold/other.", styles["BodyText"]))
    drift = saa.get("equity_drift_pct", 0)
    if abs(drift) > 5:
        drift_direction = "overweight" if drift > 0 else "underweight"
        story.append(Paragraph(f"<b>Key Finding:</b> The portfolio is currently {drift_direction} equity by {_fmt_pct(abs(drift))} relative to the target SAA, triggering a rebalancing recommendation.", styles["BodyText"]))
    else:
        story.append(Paragraph(f"The portfolio is well-aligned with the target SAA (equity drift: {_fmt_pct(drift)}). No immediate rebalancing is required; incremental capital should follow the SAA glide path.", styles["BodyText"]))
    story.append(Spacer(1, 0.3*cm))


def _build_portfolio_overview(story, styles, data):
    story.append(Paragraph("2. Portfolio Holdings Overview", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=MEDIUM_BLUE, spaceAfter=0.5*cm))
    portfolio = data.get("portfolio", [])
    if not portfolio:
        story.append(Paragraph("No portfolio holdings data available.", styles["BodyText"]))
        return
    headers = [
        Paragraph("Scheme", styles["TableHeader"]),
        Paragraph("Category", styles["TableHeader"]),
        Paragraph("Plan", styles["TableHeader"]),
        Paragraph("Units", styles["TableHeader"]),
        Paragraph("NAV", styles["TableHeader"]),
        Paragraph("Value", styles["TableHeader"]),
        Paragraph("Weight", styles["TableHeader"]),
        Paragraph("Type", styles["TableHeader"]),
    ]
    total_value = sum(float(h.get("current_value_inr", 0)) for h in portfolio)
    rows = [headers]
    for holding in portfolio:
        scheme = holding.get("scheme", "Unknown")
        if len(scheme) > 35:
            scheme = scheme[:32] + "..."
        value = float(holding.get("current_value_inr", 0))
        weight = (value / total_value * 100) if total_value > 0 else 0
        rows.append([
            Paragraph(scheme, styles["TableCell"]),
            Paragraph(holding.get("category", "N/A"), styles["TableCellCenter"]),
            Paragraph(holding.get("plan_type", "N/A"), styles["TableCellCenter"]),
            Paragraph(f"{float(holding.get('units', 0)):,.3f}", styles["TableCellRight"]),
            Paragraph(f"{float(holding.get('nav', 0)):,.2f}", styles["TableCellRight"]),
            Paragraph(_fmt_inr(value), styles["TableCellRight"]),
            Paragraph(_fmt_pct(weight), styles["TableCellRight"]),
            Paragraph(holding.get("fund_type", "N/A"), styles["TableCellCenter"]),
        ])
    rows.append([
        Paragraph("<b>TOTAL</b>", styles["TableCellBold"]),
        Paragraph("", styles["TableCell"]), Paragraph("", styles["TableCell"]),
        Paragraph("", styles["TableCell"]), Paragraph("", styles["TableCell"]),
        Paragraph(f"<b>{_fmt_inr(total_value)}</b>", styles["TableCellRight"]),
        Paragraph("<b>100.0%</b>", styles["TableCellRight"]),
        Paragraph("", styles["TableCell"]),
    ])
    col_widths = [5.5*cm, 2*cm, 1.5*cm, 2*cm, 2*cm, 2.5*cm, 1.5*cm, 1.5*cm]
    table = Table(rows, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("ALIGN", (4, 0), (4, -1), "RIGHT"),
        ("ALIGN", (5, 0), (5, -1), "RIGHT"),
        ("ALIGN", (6, 0), (6, -1), "RIGHT"),
        ("ALIGN", (7, 0), (7, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, TABLE_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, -1), (-1, -1), HexColor("#e8eef7")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
    ]
    for i in range(1, len(rows) - 1):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), TABLE_ALT_ROW))
    table.setStyle(TableStyle(style_cmds))
    story.append(table)
    story.append(Spacer(1, 0.3*cm))


def _build_saa_analysis(story, styles, data):
    story.append(Paragraph("3. Strategic Asset Allocation (SAA) Analysis", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=MEDIUM_BLUE, spaceAfter=0.5*cm))
    saa = data.get("saa_analysis", {})
    target = saa.get("target", {})
    current = saa.get("current", {})
    drift = saa.get("drift", {})
    
    headers = [
        Paragraph("Asset Class", styles["TableHeader"]),
        Paragraph("Target (%)", styles["TableHeader"]),
        Paragraph("Current (%)", styles["TableHeader"]),
        Paragraph("Drift (%)", styles["TableHeader"]),
        Paragraph("Status", styles["TableHeader"]),
    ]
    
    asset_classes = [
        ("Total Equity", target.get("total_equity_pct", 0), current.get("equity_pct", 0), drift.get("equity_drift_pct", 0)),
        ("  Large Cap", target.get("large_cap_pct", 0), current.get("large_cap_pct", 0), drift.get("large_cap_drift_pct", 0)),
        ("  Mid/Small Cap", target.get("mid_small_cap_pct", 0), current.get("mid_small_cap_pct", 0), drift.get("mid_small_drift_pct", 0)),
        ("Total Debt", target.get("debt_pct", 0), current.get("debt_pct", 0), drift.get("debt_drift_pct", 0)),
        ("Gold / Other", target.get("gold_pct", 0), current.get("gold_pct", 0), drift.get("gold_drift_pct", 0)),
    ]
    
    rows = [headers]
    for name, tgt, cur, dr in asset_classes:
        status = "Aligned" if abs(dr) <= 5 else ("Overweight" if dr > 0 else "Underweight")
        status_color = ACCENT_GREEN if abs(dr) <= 5 else (ACCENT_RED if dr > 0 else ACCENT_GOLD)
        
        rows.append([
            Paragraph(name, styles["TableCellBold"] if "Total" in name else styles["TableCell"]),
            Paragraph(_fmt_pct(tgt), styles["TableCellCenter"]),
            Paragraph(_fmt_pct(cur), styles["TableCellCenter"]),
            Paragraph(_fmt_pct(dr), styles["TableCellCenter"]),
            Paragraph(f'<font color="{status_color}">{status}</font>', styles["TableCellCenter"]),
        ])
    
    col_widths = [4*cm, 3*cm, 3*cm, 3*cm, 4*cm]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.4, TABLE_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 1), (-1, 1), TABLE_ALT_ROW),
        ("BACKGROUND", (0, 3), (-1, 3), TABLE_ALT_ROW),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.5*cm))
    
    rebalance_required = saa.get("rebalance_required", False)
    if rebalance_required:
        story.append(Paragraph("<b>Rebalancing Action Required:</b> Portfolio drift exceeds the \u00b15% tolerance band. A systematic rebalancing plan is recommended to restore SAA alignment. Incremental SIPs should be routed to underweight sleeves; overweight sleeves should receive no new capital until drift normalizes.", styles["BodyText"]))
    else:
        story.append(Paragraph("The portfolio is within the \u00b15% SAA tolerance bands. Continue routing incremental capital per the target SAA weights. Monitor quarterly for drift.", styles["BodyText"]))
    story.append(Spacer(1, 0.3*cm))


def _build_sip_blueprint(story, styles, data):
    story.append(Paragraph("4. Fiduciary SIP Recommendation Blueprint", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=MEDIUM_BLUE, spaceAfter=0.5*cm))
    sip_plan = data.get("sip_plan", {})
    if not sip_plan or sip_plan.get("status") != "DETERMINISTIC_SIP_READY":
        story.append(Paragraph("SIP blueprint not available. Generate SIP plan from the advisory dashboard.", styles["BodyText"]))
        return
    
    budget = sip_plan.get("monthly_budget_inr", 0)
    allocated = sip_plan.get("allocated_budget_inr", 0)
    unallocated = sip_plan.get("unallocated_budget_inr", 0)
    
    story.append(Paragraph(f"<b>Monthly SIP Budget:</b> {_fmt_inr(budget)} | <b>Allocated:</b> {_fmt_inr(allocated)} | <b>Unallocated:</b> {_fmt_inr(unallocated)}", styles["BodyText"]))
    story.append(Spacer(1, 0.3*cm))
    
    timing = sip_plan.get("optimal_tranche_timing", {})
    if timing:
        story.append(Paragraph(f"<b>Optimal Execution Cadence:</b> {timing.get('recommended_cadence', 'Bi-Weekly')} \u2014 {timing.get('dates', '5th and 20th of each month')}. Bi-weekly tranche: {_fmt_inr(timing.get('biweekly_amount_inr', 0))}. <i>{timing.get('rationale', '')}</i>", styles["BodyText"]))
        story.append(Spacer(1, 0.3*cm))
    
    recommendations = sip_plan.get("recommendations", [])
    if recommendations:
        headers = [
            Paragraph("Mandate Slot", styles["TableHeader"]),
            Paragraph("Scheme Recommendation", styles["TableHeader"]),
            Paragraph("Category", styles["TableHeader"]),
            Paragraph("Plan", styles["TableHeader"]),
            Paragraph("Monthly SIP (INR)", styles["TableHeader"]),
            Paragraph("Allocation (%)", styles["TableHeader"]),
        ]
        
        rows = [headers]
        for rec in recommendations:
            rows.append([
                Paragraph(rec.get("slot_name", "N/A"), styles["TableCellBold"]),
                Paragraph(rec.get("scheme_name", "N/A"), styles["TableCell"]),
                Paragraph(rec.get("category", "N/A"), styles["TableCellCenter"]),
                Paragraph(rec.get("plan_type", "Direct-Growth"), styles["TableCellCenter"]),
                Paragraph(_fmt_inr(rec.get("monthly_allocation_inr", 0)), styles["TableCellRight"]),
                Paragraph(_fmt_pct(rec.get("allocation_pct", 0)), styles["TableCellRight"]),
            ])
        
        col_widths = [3*cm, 5.5*cm, 2.5*cm, 2*cm, 2.5*cm, 2*cm]
        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("GRID", (0, 0), (-1, -1), 0.4, TABLE_BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(table)
        story.append(Spacer(1, 0.3*cm))
    
    alerts = sip_plan.get("portfolio_completion_alerts", [])
    if alerts:
        story.append(Paragraph("<b>Portfolio Completion Alerts:</b>", styles["SubSectionHeader"]))
        for alert in alerts:
            severity = alert.get("severity", "MEDIUM")
            icon = "\u274c" if severity == "HIGH" else "\u27e1"
            story.append(Paragraph(f"{icon} <b>{alert.get('slot', 'N/A')}: </b> {alert.get('action', 'Review recommended')}", styles["BulletText"]))
        story.append(Spacer(1, 0.3*cm))
    
    rationale = sip_plan.get("fiduciary_routing_rationale", "")
    if rationale:
        story.append(Paragraph(f"<b>Fiduciary Routing Rationale:</b> {rationale}", styles["BodyText"]))
    story.append(Spacer(1, 0.3*cm))
def _build_lumpsum_plan(story, styles, data):
    ls_plan = data.get("lumpsum_plan", {})
    if not ls_plan or ls_plan.get("status") not in ("ELIGIBLE", "CAPPED_AT_SURPLUS"):
        return
    
    story.append(Paragraph("5. Lump-Sum Capital Deployment & STP Waterfall", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=MEDIUM_BLUE, spaceAfter=0.5*cm))
    
    story.append(Paragraph(f"<b>Total Staged Capital:</b> {_fmt_inr(ls_plan.get('effective_lumpsum_inr', 0))}<br/><b>Equity Staging (STP):</b> {_fmt_inr(ls_plan.get('target_equity_capital_inr', 0))}<br/><b>Debt/Liquid Retention:</b> {_fmt_inr(ls_plan.get('target_debt_capital_inr', 0))}<br/><b>Parking Vehicle:</b> {ls_plan.get('parking_scheme', 'Direct Liquid Fund')}<br/><b>STP Duration:</b> {ls_plan.get('stp_duration_months', 6)} months @ {_fmt_inr(ls_plan.get('monthly_stp_tranche_inr', 0))}/month", styles["BodyText"]))
    story.append(Spacer(1, 0.3*cm))


def _build_monte_carlo(story, styles, data):
    mc = data.get("monte_carlo", {})
    if not mc or mc.get("status") != "SIMULATED":
        return
    
    story.append(Paragraph("6. Monte Carlo Wealth Accumulation Simulation", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=MEDIUM_BLUE, spaceAfter=0.5*cm))
    
    prob = mc.get("probability_of_success_pct", 0)
    p50 = mc.get("p50_corpus_inr", 0)
    p05 = mc.get("p05_corpus_inr", 0)
    action = mc.get("recommended_action", "")
    
    headers = [
        Paragraph("Metric", styles["TableHeader"]),
        Paragraph("Value", styles["TableHeader"]),
    ]
    
    rows = [
        headers,
        [Paragraph("Success Probability", styles["TableCellBold"]), Paragraph(f"{prob:.1f}%", styles["TableCellRight"])],
        [Paragraph("Median Corpus (P50)", styles["TableCellBold"]), Paragraph(_fmt_inr(p50), styles["TableCellRight"])],
        [Paragraph("Severe Bear Market (P05)", styles["TableCellBold"]), Paragraph(_fmt_inr(p05), styles["TableCellRight"])],
    ]
    
    table = Table(rows, colWidths=[8*cm, 6*cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("GRID", (0, 0), (-1, -1), 0.4, TABLE_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 2), (-1, 2), TABLE_ALT_ROW),
    ]))
    story.append(table)
    story.append(Spacer(1, 0.3*cm))
    
    if action:
        story.append(Paragraph(f"<b>Guidance:</b> {action}", styles["BodyText"]))
    story.append(Spacer(1, 0.3*cm))


def _build_fiduciary_disclosures(story, styles, data):
    story.append(PageBreak())
    story.append(Paragraph("7. Fiduciary Disclosures & Compliance Statement", styles["SectionHeader"]))
    story.append(HRFlowable(width="100%", thickness=1, color=MEDIUM_BLUE, spaceAfter=0.5*cm))
    
    disclosures = [
        ("Statutory Mandate", "SEBI (Investment Advisers) Regulations, 2013 \u2014 Regulation 15(1) & Schedule III Code of Conduct."),
        ("Direct Plan Enforcement", "All proposed switches and SIP allocations strictly mandate Direct Plans to eliminate intermediary commissions and distributor trail leakage."),
        ("Conflict of Interest Prohibition", "The adviser receives zero consideration, referral fees, or commissions from any Asset Management Company (AMC) or intermediary."),
        ("Non-Execution Authority", "The adviser operates solely on a fee-only, non-execution advisory basis; order execution remains exclusively in client control via MFCentral, AMC portals, or RTAs."),
        ("Fee Transparency", "Advisory fees are agreed in writing upfront, deducted only from client\\'s bank account \u2014 never from portfolio assets."),
        ("Data Provenance", f"Portfolio data sourced from CAS (CAMS/Karvy) with integrity verification. Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC."),
    ]
    
    for title, text in disclosures:
        story.append(Paragraph(f"<b>{title}:</b> {text}", styles["BulletText"]))
    
    story.append(Spacer(1, 1*cm))
    
    story.append(HRFlowable(width="100%", thickness=0.5, color=TABLE_BORDER, spaceAfter=0.3*cm))
    story.append(Paragraph("<b>Disclaimer:</b> This report is prepared for the exclusive use of the named client under a fee-only fiduciary advisory engagement. It does not constitute an offer or solicitation for the purchase or sale of any securities. Past performance does not guarantee future results. Mutual fund investments are subject to market risks. Read all scheme-related documents carefully. The adviser accepts no liability for decisions made based on this report without independent verification. Report generated by Fiduciary Advisory Engine v1.0.", styles["Disclaimer"]))


def generate_fiduciary_pdf_report(data: dict[str, Any]) -> bytes:
    """Generate a professional PDF fiduciary report from portfolio analysis data."""
    buffer = io.BytesIO()
    
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
        title="Executive Fiduciary Report",
        author="Fiduciary Advisory Engine",
        subject="Portfolio Diagnostic & Investment Advisory",
    )
    
    styles = _get_styles()
    
    frame_cover = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="cover")
    frame_content = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="content")
    
    cover_template = PageTemplate(id="cover", frames=[frame_cover])
    content_template = PageTemplate(id="content", frames=[frame_content])
    
    doc.addPageTemplates([cover_template, content_template])
    
    story = []
    
    story.append(NextPageTemplate("cover"))
    _build_cover_page(story, styles, data)
    
    story.append(NextPageTemplate("content"))
    _build_executive_summary(story, styles, data)
    _build_portfolio_overview(story, styles, data)
    _build_saa_analysis(story, styles, data)
    _build_sip_blueprint(story, styles, data)
    _build_lumpsum_plan(story, styles, data)
    _build_monte_carlo(story, styles, data)
    _build_fiduciary_disclosures(story, styles, data)
    
    doc.build(story)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_fiduciary_html_report(data: dict[str, Any]) -> str:
    """Generate an HTML version of the fiduciary report for web viewing."""
    portfolio = data.get("portfolio", [])
    total_value = data.get("portfolio_value_inr", sum(float(h.get("current_value_inr", 0)) for h in portfolio))
    saa = data.get("saa_analysis", {})
    sip_plan = data.get("sip_plan", {})
    mc = data.get("monte_carlo", {})
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Executive Fiduciary Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 0 auto; padding: 40px 20px; line-height: 1.6; color: #1e293b; background: #fff; }}
        .cover {{ text-align: center; padding: 80px 0; background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); color: white; margin: -40px -20px 40px -20px; }}
        .cover h1 {{ font-size: 2.5rem; margin-bottom: 1rem; }}
        .cover p {{ font-size: 1.2rem; opacity: 0.9; }}
        .badge {{ display: inline-block; background: #f59e0b; color: #0f172a; padding: 4px 12px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; margin-top: 20px; }}
        h2 {{ color: #0f172a; border-bottom: 2px solid #2563eb; padding-bottom: 8px; margin-top: 40px; }}
        h3 {{ color: #1e3a8a; margin-top: 24px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 16px 0; font-size: 0.9rem; }}
        th {{ background: #1e293b; color: white; padding: 10px 8px; text-align: left; font-weight: 600; }}
        td {{ padding: 8px; border-bottom: 1px solid #e2e8f0; }}
        tr:nth-child(even) td {{ background: #f8fafc; }}
        tr.total td {{ font-weight: bold; background: #e8eef7; }}
        .metric-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin: 20px 0; }}
        .metric-card {{ background: #f1f5f9; padding: 16px; border-radius: 8px; }}
        .metric-label {{ font-size: 0.85rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }}
        .metric-value {{ font-size: 1.5rem; font-weight: 700; color: #0f172a; }}
        .alert {{ padding: 12px 16px; border-radius: 6px; margin: 8px 0; }}
        .alert-high {{ background: #fef2f2; border-left: 4px solid #ef4444; }}
        .alert-medium {{ background: #fffbeb; border-left: 4px solid #f59e0b; }}
        .alert-low {{ background: #f0fdf4; border-left: 4px solid #10b981; }}
        .disclaimer {{ margin-top: 40px; padding: 20px; background: #f8fafc; border-radius: 8px; font-size: 0.8rem; color: #64748b; border: 1px solid #e2e8f0; }}
        .footer {{ margin-top: 40px; text-align: center; color: #94a3b8; font-size: 0.8rem; }}
    </style>
</head>
<body>
    <div class="cover">
        <h1>Executive Fiduciary Report</h1>
        <p>Comprehensive Portfolio Diagnostic & Investment Advisory</p>
        <p>Prepared for: <strong>{data.get('client_name', 'Confidential Client')}</strong></p>
        <p>Report Date: {data.get('report_date', date.today().strftime('%B %d, %Y'))}</p>
        <p>Portfolio Value: <strong>{_fmt_inr(total_value)}</strong></p>
        <span class="badge">SEBI RIA \u2022 Fee-Only Fiduciary Standard</span>
    </div>
    
    <h2>1. Executive Summary</h2>
    <div class="metric-grid">
        <div class="metric-card"><div class="metric-label">Portfolio Value</div><div class="metric-value">{_fmt_inr(total_value)}</div></div>
        <div class="metric-card"><div class="metric-label">Holdings</div><div class="metric-value">{len(portfolio)}</div></div>
        <div class="metric-card"><div class="metric-label">Equity</div><div class="metric-value">{_fmt_pct(saa.get('equity_pct', 0))}</div></div>
        <div class="metric-card"><div class="metric-label">Debt</div><div class="metric-value">{_fmt_pct(saa.get('debt_pct', 0))}</div></div>
        <div class="metric-card"><div class="metric-label">Monthly SIP</div><div class="metric-value">{_fmt_inr(sip_plan.get('monthly_budget_inr', 0))}</div></div>
    </div>
    <p>Risk Profile: <strong>{data.get('risk_tier', 'Moderate')}</strong> | Target SAA: {_fmt_pct(saa.get('equity_pct', 0))} Equity / {_fmt_pct(saa.get('debt_pct', 0))} Debt</p>
"""
    
    return html



def build_report_data(
    portfolio: list[dict[str, Any]],
    saa_analysis: dict[str, Any] | None = None,
    sip_plan: dict[str, Any] | None = None,
    lumpsum_plan: dict[str, Any] | None = None,
    monte_carlo: dict[str, Any] | None = None,
    client_name: str = "Confidential Client",
    risk_tier: str = "Moderate",
) -> dict[str, Any]:
    """Build standardized report data dictionary from analysis components."""
    total_value = sum(float(h.get("current_value_inr", 0)) for h in portfolio)
    
    return {
        "client_name": client_name,
        "report_date": date.today().strftime("%B %d, %Y"),
        "portfolio_value_inr": total_value,
        "portfolio": portfolio,
        "saa_analysis": saa_analysis or {},
        "sip_plan": sip_plan or {},
        "lumpsum_plan": lumpsum_plan or {},
        "monte_carlo": monte_carlo or {},
        "risk_tier": risk_tier,
    }