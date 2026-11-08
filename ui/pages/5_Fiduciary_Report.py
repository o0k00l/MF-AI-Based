"""Executive Fiduciary Report & Download Page."""
from __future__ import annotations

import sys
from pathlib import Path
_this_file = Path(__file__).resolve() if "__file__" in globals() else Path.cwd()
_REPO_ROOT = None
for _cand in [_this_file.parent, _this_file.parent.parent, _this_file.parent.parent.parent, Path.cwd()]:
    if (_cand / "services").is_dir() and (_cand / "data").is_dir():
        _REPO_ROOT = str(_cand)
        break
if not _REPO_ROOT:
    _REPO_ROOT = str(Path.cwd())
if _REPO_ROOT in sys.path:
    sys.path.remove(_REPO_ROOT)
sys.path.insert(0, _REPO_ROOT)

import streamlit as st
from services.sidebar import render_fiduciary_sidebar
from services.fiduciary_engine import evaluate_portfolio_saa_audit, generate_fiduciary_sip_blueprint
from services.ai_fund_classifier import enrich_funds_with_ai, generate_fiduciary_ai_narrative
from services.report_generator import generate_fiduciary_pdf_report, build_report_data

# --- Page Configuration ---
st.set_page_config(
    page_title="Fiduciary Report | Portfolio Review",
    page_icon="📄",
    layout="wide",
)

# --- Render Advisory Flow Sidebar ---
# --- Render Unified Advisory Flow Sidebar (Single Source of Truth) ---
render_fiduciary_sidebar(current_page="pages/5_Fiduciary_Report.py")


st.title("📄 Executive Fiduciary Report & Action Plan")
st.markdown("Your formal, comprehensive portfolio diagnostic and investment advisory report.")

# Check prerequisites
portfolio = st.session_state.get("user_portfolio", [])
if portfolio:
    portfolio = enrich_funds_with_ai(portfolio)

cgs_data = st.session_state.get("cgs_data")
goals_alloc = st.session_state.get("goals_allocation")
risk_tier = st.session_state.get("risk_tier") or st.session_state.get("risk_bucket") or "Moderate (Evaluated SAA)"

# Synthesize goal allocation / SIP blueprint seamlessly from evaluated portfolio SAA
if not goals_alloc:
    bp = st.session_state.get("deterministic_sip_plan")
    if not bp and portfolio:
        try:
            budget = float(st.session_state.get("sip_budget", 25000.0) or 25000.0)
        except (ValueError, TypeError):
            budget = 25000.0
        bp = generate_fiduciary_sip_blueprint(
            monthly_budget_inr=budget,
            funds=portfolio,
            target_saa=st.session_state.get("saa_target"),
        )
        st.session_state["deterministic_sip_plan"] = bp
    if bp:
        # Helper function for safe float conversion
        def parse_amount(val):
            if val is None:
                return 0.0
            try:
                if isinstance(val, str):
                    val = val.replace('₹', '').replace(',', '').strip()
                return float(val) if val != '' else 0.0
            except (ValueError, TypeError):
                return 0.0
        
        lc_val = parse_amount(next((a["amount_inr"] for a in bp.get("allocations", []) if "Large" in a.get("sleeve", "")), 0.0))
        ms_val = parse_amount(next((a["amount_inr"] for a in bp.get("allocations", []) if "Mid" in a.get("sleeve", "")), 0.0))
        db_val = parse_amount(next((a["amount_inr"] for a in bp.get("allocations", []) if "Debt" in a.get("sleeve", "")), 0.0))
        sip_confidence = bp.get("sip_selection_confidence_pct", 100.0)
        goals_alloc = {
            "goals": {
                "sip_plan": {
                    "goal_name": "Long-Term Wealth Accumulation & SAA Compounding",
                    "priority": 1,
                    "required_monthly": parse_amount(bp["monthly_budget_inr"]),
                    "allocated_monthly": parse_amount(bp["allocated_budget_inr"]),
                    "gap_monthly": parse_amount(bp["unallocated_budget_inr"]),
                    "target_corpus": 0.0,
                    "horizon_years": 10,
                }
            },
            "total_required": parse_amount(bp["monthly_budget_inr"]),
            "total_allocated": parse_amount(bp["allocated_budget_inr"]),
            "total_gap": parse_amount(bp["unallocated_budget_inr"]),
            "sip_selection_confidence_pct": sip_confidence,
            "surplus": 0.0,
            "use_step_up": False,
            "asset_sleeves": {
                "large_cap_inr": lc_val,
                "mid_small_cap_inr": ms_val,
                "debt_inr": db_val,
            },
        }
        st.session_state["goals_allocation"] = goals_alloc

missing = []
if not portfolio:
    missing.append("📤 Upload CAS Statement (Portfolio Dashboard)")

if missing:
    st.warning("⚠️ **Prerequisites Missing:** Please upload your CAS portfolio statement to generate your report:")
    for m in missing:
        st.markdown(f"* {m}")
    st.info("👉 *Return to Step 1 (Portfolio Intake & Audit) to upload your statement.*")
else:
    # Handle current_value which might be numeric or formatted string
    def safe_float(val):
        """Convert value to float, handling strings with commas/currency symbols."""
        if val is None:
            return 0.0
        try:
            if isinstance(val, str):
                val = val.replace('₹', '').replace(',', '').strip()
            return float(val) if val != '' else 0.0
        except (ValueError, TypeError):
            return 0.0
    
    total_val = sum(safe_float(f.get("current_value", 0)) for f in portfolio)
    total_invested = sum(safe_float(f.get("invested_value", 0)) for f in portfolio)
    total_gain = total_val - total_invested if total_invested > 0 else 0
    gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else 0

    st.success("✅ All advisory milestones complete! Your review report is ready.")

    # High-level Summary
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Portfolio Value", f"₹{total_val:,.0f}")
    with col2:
        st.metric("Governing Risk Profile", str(risk_tier).replace("_", " ").title())
    with col3:
        sip_budget = goals_alloc.get("total_allocated", 0)
        st.metric("Monthly SIP Budget", f"₹{sip_budget:,.0f}/mo")
    with col4:
        sip_confidence = goals_alloc.get("sip_selection_confidence_pct", 100.0)
        confidence_color = "green" if sip_confidence >= 80 else ("orange" if sip_confidence >= 60 else "red")
        st.metric("SIP Confidence", f"{sip_confidence:.0f}%", delta=None, help="Confidence score based on portfolio completeness and fund alignment")

    # Group by canonical underlying strategy
    canonical_portfolio = {}
    for f in portfolio:
        c_name = f.get("canonical_scheme") or f.get("scheme", "")
        canonical_portfolio.setdefault(c_name, []).append(f)

    unique_strat_count = len(canonical_portfolio)
    dual_schemes = {c_name: flist for c_name, flist in canonical_portfolio.items() if len(flist) > 1}

    # AI Executive Diagnostic Synthesis Integration
    ai_narrative = st.session_state.get("ai_portfolio_narrative")
    if not ai_narrative and portfolio:
        portfolio_metrics_for_report = {
            "total_value": total_val,
            "total_invested": total_invested,
            "eq_pct": (sum(f.get("current_value", 0) * f.get("eq", 0) / 100 for f in portfolio) / total_val * 100) if total_val else 0,
            "debt_pct": (sum(f.get("current_value", 0) * f.get("debt", 0) / 100 for f in portfolio) / total_val * 100) if total_val else 0,
            "regular_value": sum(f.get("current_value", 0) for f in portfolio if str(f.get("plan_type", "Direct")).upper() == "REGULAR"),
            "regular_pct": (sum(f.get("current_value", 0) for f in portfolio if str(f.get("plan_type", "Direct")).upper() == "REGULAR") / total_val * 100) if total_val else 0,
            "annual_bleed": sum(f.get("annual_commission_bleed", 0) for f in portfolio),
            "compounded_10y_drag": sum(f.get("ten_year_compounded_drag", 0) for f in portfolio),
            "unique_strategies_count": unique_strat_count,
            "dual_count": len(dual_schemes),
        }
        ai_narrative = generate_fiduciary_ai_narrative(
            portfolio_metrics=portfolio_metrics_for_report,
            funds=portfolio,
            target_saa=st.session_state.get("saa_target"),
            use_live_ai=False,
        )
        st.session_state["ai_portfolio_narrative"] = ai_narrative

    # Build report preview
    report_lines = [
        "# Executive Mutual Fund Portfolio Review & Fiduciary Advisory Plan",
        "",
        f"**Valuation Date:** Current Session  |  **Governing Risk Tier:** {risk_tier}  |  **Active Strategies:** {unique_strat_count} ({len(portfolio)} Plan Folios)",
        "",
        "---",
        "",
        "## 1. Portfolio Diagnostic Summary",
        f"* **Total Portfolio Value:** ₹{total_val:,.0f}",
        f"* **Total Invested Cost:** ₹{total_invested:,.0f}",
        f"* **Unrealized Gain / (Loss):** ₹{total_gain:,.0f} ({gain_pct:+.1f}%)",
        "",
        "### 1.1 Fiduciary Executive Analysis & Diagnostic Synthesis",
        ai_narrative.get("content", "") if ai_narrative else "",
        "",
        "### 1.2 Concentration Risk & Fiduciary Vulnerability Alerts",
    ]

    from services.ai_fund_classifier import evaluate_portfolio_concentration_risks, evaluate_portfolio_peer_attribution
    conc_res = evaluate_portfolio_concentration_risks(portfolio)
    peer_res = evaluate_portfolio_peer_attribution(portfolio)

    report_lines.extend([
        f"* **Concentration Risk Status:** {conc_res.get('concentration_score', 'BALANCED').replace('_', ' ').title()}",
        f"* **Top Scheme Concentration:** {conc_res.get('max_scheme_pct', 0.0):.1f}% (Recommended <= 25.0%)",
        f"* **Top 3 Holdings Weight:** {conc_res.get('top_3_pct', 0.0):.1f}% (Recommended <= 60.0%)",
        f"* **Thematic/Sector Exposure:** {conc_res.get('thematic_pct', 0.0):.1f}% (Recommended <= 15.0%)",
        f"* **Primary AMC Concentration:** {conc_res.get('max_amc_name', 'N/A')} ({conc_res.get('max_amc_pct', 0.0):.1f}% of wealth)",
    ])
    if conc_res.get("alerts"):
        for a in conc_res["alerts"]:
            sev_badge = "🚨 [HIGH RISK]" if a.get("severity") == "HIGH" else "⚠️ [MODERATE RISK]"
            report_lines.append(f"* {sev_badge} {a.get('message', '')}")
    else:
        report_lines.append("* ✅ **Balanced Allocation:** No individual scheme, thematic bet, or AMC exceeds SEBI fiduciary concentration limits.")

    from services.ai_fund_classifier import evaluate_factor_attribution
    from services.cas_parser import audit_cas_document_integrity
    factor_res = evaluate_factor_attribution(portfolio)
    cas_audit = audit_cas_document_integrity(portfolio)

    styles = peer_res.get("style_breakdown", {})
    tilts = factor_res.get("factor_tilts", {})
    report_lines.extend([
        "",
        "### 1.3 Portfolio Style Box & Academic Factor Attribution",
        f"* **Core Index Foundation:** {styles.get('core_index_pct', 0.0):.1f}% | **Active Alpha Engine:** {styles.get('active_alpha_pct', 0.0):.1f}% | **Defensive Buffer:** {styles.get('stability_buffer_pct', 0.0):.1f}%",
        f"* **Style Factor Tilts:** Quality Core: {tilts.get('quality_large_core_pct', 0.0):.1f}% | Momentum Alpha: {tilts.get('momentum_alpha_pct', 0.0):.1f}% | Value/Yield: {tilts.get('value_contra_pct', 0.0):.1f}% | Stability: {tilts.get('low_vol_stability_pct', 0.0):.1f}%",
        f"* **Concentration Index (HHI):** {factor_res.get('hhi_score', 0.0):,.0f} ({factor_res.get('diversification_rating', 'BALANCED').replace('_', ' ').title()})",
        f"* **Weighted Portfolio TER:** Direct: {peer_res.get('weighted_direct_ter', 0.0):.2f}% vs. Regular: {peer_res.get('weighted_regular_ter', 0.0):.2f}%",
        f"* **Direct Alpha Advantage:** +{peer_res.get('peer_alpha_spread', 0.0):.2f}% per annum compounded return advantage over regular distributor plans.",
        "",
        "## 2. Holdings Breakdown",
        "| Scheme Name | Category | Plan | Current Value (₹) | Equity % | Debt % |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for f in portfolio:
        name = f.get("scheme", "Unknown")
        cat = f.get("category", "N/A")
        plan = f.get("plan_type", "Direct")
        val = safe_float(f.get("current_value", 0))
        eq = safe_float(f.get("eq", 0))
        debt = safe_float(f.get("debt", 0))
        report_lines.append(f"| {name} | {cat} | {plan} | ₹{val:,.0f} | {eq:.1f}% | {debt:.1f}% |")

    # Add CGS section if available
    cgs_data = st.session_state.get("cgs_data")
    if cgs_data and cgs_data.get("summary"):
        cg_s = cgs_data.get("summary", {})
        ltcg = safe_float(cg_s.get("ltcg_inr") or 0.0)
        stcg = safe_float(cg_s.get("stcg_inr") or 0.0)
        rem_hd = max(0.0, 125_000.0 - ltcg)
        report_lines.extend([
            "",
            "## 6. Statutory Capital Gains Audit (CGS)",
            f"* **Realized LTCG (§112A):** ₹{ltcg:,.2f}",
            f"* **Realized STCG (§111A):** ₹{stcg:,.2f}",
            f"* **Remaining §112A Exemption Headroom:** ₹{rem_hd:,.2f} (out of ₹1.25 Lakhs annual tax-free limit)",
            f"* **Statement Provenance:** SHA256 `{cgs_data.get('source_sha256', 'N/A')[:16]}...`",
        ])

    # Commission Bleed & Direct Conversion Audit
    regular_holdings = [f for f in portfolio if str(f.get("plan_type", "Direct")).upper() == "REGULAR"]
    regular_val = sum(safe_float(f.get("current_value", 0)) for f in regular_holdings)
    regular_pct = (regular_val / total_val * 100.0) if total_val > 0 else 0.0
    total_annual_bleed = sum(safe_float(f.get("annual_commission_bleed", 0.0)) for f in regular_holdings)
    total_10y_linear = sum(safe_float(f.get("ten_year_linear_commission", 0.0)) for f in regular_holdings)
    total_10y_compounded = sum(safe_float(f.get("ten_year_compounded_drag", 0.0)) for f in regular_holdings)
    avg_trail = (total_annual_bleed / regular_val * 100.0) if regular_val > 0 else 0.0

    report_lines.extend([
        "",
        "## 3. Distributor Commission Bleed & Direct Plan Audit",
    ])
    if regular_val > 0:
        report_lines.extend([
            f"* **Regular Plan Exposure:** ₹{regular_val:,.0f} ({regular_pct:.1f}% of total portfolio) across {len(regular_holdings)} schemes",
            f"* **Annual Distributor Trail Bleed:** ₹{total_annual_bleed:,.0f} / year (weighted avg trail ~{avg_trail:.2f}% p.a.)",
            f"* **Estimated 10-Year Compounded Drag:** ₹{total_10y_compounded:,.0f} (Linear Cumulative: ₹{total_10y_linear:,.0f})",
            "* **Fiduciary Switch Recommendation:** Execute non-taxable/disciplined switches from Regular to Direct Growth plans to halt distributor commission leakage.",
            "",
            "| Identified Regular Scheme | Current Value (₹) | Direct TER | Regular TER | Trail Comm. % | Annual Bleed (₹/yr) | 10Y Compounded Drag (₹) |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])

        if dual_schemes:
            report_lines.extend([
                "",
                "### Dual-Plan Duplication & Folio Consolidation Priority",
                f"The audit identified **{len(dual_schemes)} mutual fund strategies** held simultaneously in both Direct and Regular plans:",
                "",
                "| Underlying Strategy | Direct Value (₹) | Regular Value (₹) | Total Strategy Value (₹) | Annual Commission Bleed |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for c_name, flist in dual_schemes.items():
                d_val = sum(safe_float(f.get("current_value", 0)) for f in flist if f.get("plan_type") == "Direct")
                r_val = sum(safe_float(f.get("current_value", 0)) for f in flist if f.get("plan_type") == "Regular")
                r_fund = next((f for f in flist if f.get("plan_type") == "Regular"), None)
                bleed = safe_float(r_fund.get("annual_commission_bleed", 0)) if r_fund else 0.0
                trail = safe_float(r_fund.get("trail_commission_pct", 1.0)) if r_fund else 1.0
                report_lines.append(f"| **{c_name}** | ₹{d_val:,.0f} | ₹{r_val:,.0f} | ₹{d_val+r_val:,.0f} | ₹{bleed:,.0f}/yr ({trail:.2f}%) |")
            report_lines.extend([
                "",
                "* **Immediate Fiduciary Action:** Consolidate the Regular plan units of these schemes directly into your existing Direct folios of the same scheme to eliminate trail leakage without altering asset allocation.",
            ])
        for rf in sorted(regular_holdings, key=lambda x: safe_float(x.get("annual_commission_bleed", 0)), reverse=True):
            r_name = rf.get("scheme", "Regular Scheme")
            r_val = safe_float(rf.get("current_value", 0))
            r_td = safe_float(rf.get("ter_direct", 0.75))
            r_tr = safe_float(rf.get("ter_regular", 1.75))
            r_trail = safe_float(rf.get("trail_commission_pct", 1.0))
            r_yr = safe_float(rf.get("annual_commission_bleed", 0))
            r_10y = safe_float(rf.get("ten_year_compounded_drag", 0))
            report_lines.append(f"| {r_name} | ₹{r_val:,.0f} | {r_td:.2f}% | {r_tr:.2f}% | {r_trail:.2f}% | ₹{r_yr:,.0f}/yr | ₹{r_10y:,.0f} |")
    else:
        report_lines.extend([
            "* **Direct Plan Compliance:** ✅ 100% Direct Plan Mandate Verified",
            "* **Commission Leakage:** Zero distributor trail commission bleed detected across all active folios.",
        ])

    # SAA Drift & Fiduciary Audit
    target_saa = st.session_state.get("saa_target")
    audit_res = evaluate_portfolio_saa_audit(portfolio, target_saa=target_saa) if target_saa else None

    if audit_res and audit_res.get("status") == "ANALYZED":
        tgt_eq = audit_res["target_equity_pct"]
        tgt_db = audit_res["target_debt_pct"]
        cur_eq = audit_res["current_equity_pct"]
        cur_db = audit_res["current_debt_pct"]
        db_gap = audit_res["debt_gap_inr"]
        is_def = audit_res["is_debt_deficit"]

        report_lines.extend([
            "",
            "## 4. Strategic Asset Allocation (SAA) & Drift Diagnostic",
            f"* **Target SAA:** {tgt_eq:.1f}% Equity / {tgt_db:.1f}% Debt",
            f"* **Current Portfolio Mix:** {cur_eq:.1f}% Equity / {cur_db:.1f}% Debt",
            f"* **Debt Stability Buffer:** {'Deficit of ₹' + str(round(float(db_gap)/100000.0, 2)) + ' Lakhs' if is_def else 'Adequate Surplus'}",
            f"* **Fiduciary Rebalancing Flag:** {'Action Required (Drift exceeds tolerance band)' if audit_res.get('rebalance_required') else 'Compliant within +/-5% Band'}",
        ])

    report_lines.extend([
        "",
        "## 5. Financial Goal Allocation & SIP Deployment",
    ])
    for g_id, g_info in goals_alloc.get("goals", {}).items():
        g_name = g_info.get("goal_name", g_id)
        req = g_info.get("required_monthly", 0)
        alloc = g_info.get("allocated_monthly", 0)
        report_lines.append(f"* **{g_name}:** Required SIP: ₹{req:,.0f}/mo | Allocated SIP: ₹{alloc:,.0f}/mo")

    # Add Asset Sleeve SIP Blueprint if available
    sleeves = goals_alloc.get("asset_sleeves")
    if sleeves:
        report_lines.extend([
            "",
            "### Monthly SIP Asset-Sleeve Deployment Breakdown",
            f"* **Large-Cap Core Index:** ₹{sleeves.get('large_cap_inr', 0):,.2f} / month",
            f"* **Mid/Small-Cap Alpha:** ₹{sleeves.get('mid_small_cap_inr', 0):,.2f} / month",
            f"* **Debt & Liquidity Cushion:** ₹{sleeves.get('debt_inr', 0):,.2f} / month",
        ])

    # Add Lump-Sum Deployment Plan if available
    ls_plan = st.session_state.get("deterministic_lumpsum_plan")
    if ls_plan and ls_plan.get("status") in ("ELIGIBLE", "CAPPED_AT_SURPLUS"):
        report_lines.extend([
            "",
            "### Lump-Sum Capital Staging & STP Plan",
            f"* **Total Staged Lump-Sum Capital:** ₹{float(ls_plan['effective_lumpsum_inr']):,.2f}",
            f"* **Equity Staging (STP):** ₹{float(ls_plan['target_equity_capital_inr']):,.2f}",
            f"* **Debt / Liquid Retention:** ₹{float(ls_plan['target_debt_capital_inr']):,.2f}",
            f"* **Liquid Parking Vehicle:** {ls_plan['parking_scheme']}",
            f"* **STP Duration:** {ls_plan['stp_duration_months']} months @ ₹{float(ls_plan['monthly_stp_tranche_inr']):,.2f} / month",
        ])

    report_lines.extend([
        "",
        "## 7. Fiduciary Disclosures & Compliance Statement",
        f"* **CAS Document Provenance:** {cas_audit.get('total_folios', len(portfolio))} plan folios verified | Integrity Score: {cas_audit.get('integrity_score_pct', 100.0):.1f}% | RFC-8785 Decision Hash: `{cas_audit.get('audit_hash', 'N/A')[:24]}...`",
        "* **Statutory Mandate:** SEBI (Investment Advisers) Regulations, 2013 (Regulation 15(1) & Schedule III Code of Conduct).",
        "* **Direct Plan Enforcement:** All proposed switches and SIP allocations strictly mandate Direct Plans to eliminate intermediary commissions and distributor trail leakage.",
        "* **Conflict of Interest Prohibition:** The adviser receives zero consideration, referral fees, or commissions from any Asset Management Company (AMC) or intermediary.",
        "* **Non-Execution Authority:** The adviser operates solely on a fee-only, non-execution advisory basis; order execution remains exclusively in client control via MFCentral, AMC portals, or RTAs.",
    ])

    report_md = "\n".join(report_lines)

    tab1, tab2 = st.tabs(["📄 Report Preview", "💾 Download"])
    with tab1:
        st.markdown(report_md)
    with tab2:
        st.download_button(
            "📥 Download Report (Markdown)",
            data=report_md,
            file_name="Executive_Fiduciary_Report.md",
            mime="text/markdown",
            use_container_width=True,
        )
        st.download_button(
            "📥 Download Report (HTML)",
            data=f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Executive Fiduciary Report</title>
<style>body{{font-family:Arial, sans-serif; max-width:850px; margin:2rem auto; padding:1.5rem; line-height: 1.6;}}</style>
</head>
<body>{report_md}</body>
</html>""",
            file_name="Executive_Fiduciary_Report.html",
            mime="text/html",
            use_container_width=True,
        )
        
        # PDF Download Button
        if st.button("📥 Generate & Download Fiduciary Report (PDF)", type="primary", use_container_width=True):
            with st.spinner("Generating professional PDF report..."):
                # Build report data from session state
                sip_plan = st.session_state.get("deterministic_sip_plan", {})
                saa_analysis = st.session_state.get("saa_audit", {})
                lumpsum_plan = st.session_state.get("deterministic_lumpsum_plan", {})
                monte_carlo = st.session_state.get("monte_carlo_results", {})
                
                # Convert SIP plan to expected format
                if sip_plan and "allocations" in sip_plan:
                    recommendations = []
                    for alloc in sip_plan.get("allocations", []):
                        amt = alloc.get("amount_inr", 0)
                        if isinstance(amt, str):
                            amt = float(amt) if amt else 0.0
                        recommendations.append({
                            "slot_name": alloc.get("sleeve", ""),
                            "scheme_name": alloc.get("scheme_name", ""),
                            "category": alloc.get("category", ""),
                            "plan_type": "Direct-Growth",
                            "monthly_allocation_inr": amt,
                            "allocation_pct": (amt / sip_plan.get("monthly_budget_inr", 1)) * 100 if sip_plan.get("monthly_budget_inr", 0) > 0 else 0,
                        })
                    sip_plan = {
                        "status": "DETERMINISTIC_SIP_READY",
                        "monthly_budget_inr": sip_plan.get("monthly_budget_inr", 0),
                        "allocated_budget_inr": sip_plan.get("allocated_budget_inr", 0),
                        "unallocated_budget_inr": sip_plan.get("unallocated_budget_inr", 0),
                        "recommendations": recommendations,
                        "optimal_tranche_timing": sip_plan.get("optimal_tranche_timing", {}),
                        "portfolio_completion_alerts": sip_plan.get("portfolio_completion_alerts", []),
                        "fiduciary_routing_rationale": sip_plan.get("fiduciary_routing_rationale", ""),
                    }
                
                report_data = build_report_data(
                    portfolio=portfolio,
                    saa_analysis=saa_analysis,
                    sip_plan=sip_plan,
                    lumpsum_plan=lumpsum_plan,
                    monte_carlo=monte_carlo,
                    client_name=st.session_state.get("client_name", "Confidential Client"),
                    risk_tier=risk_tier,
                )
                
                pdf_bytes = generate_fiduciary_pdf_report(report_data)
                
                st.download_button(
                    "⬇️ Download PDF Report",
                    data=pdf_bytes,
                    file_name="Executive_Fiduciary_Report.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
                st.success("PDF report generated successfully!")

