"""Executive Fiduciary Report & Download Page."""
from __future__ import annotations

import streamlit as st
from services.fiduciary_engine import evaluate_portfolio_saa_audit, generate_fiduciary_sip_blueprint

# --- Page Configuration ---
st.set_page_config(
    page_title="Fiduciary Report | Portfolio Review",
    page_icon="📄",
    layout="wide",
)

# --- Render Advisory Flow Sidebar ---
with st.sidebar:
    st.markdown("### 🧭 Advisory Workflow")
    
    _user_portfolio = st.session_state.get("user_portfolio", [])
    _has_cas = len(_user_portfolio) > 0
    _has_cgs = bool(st.session_state.get("cgs_data"))
    _has_statements = _has_cas and _has_cgs
    _has_risk = bool(st.session_state.get("user_risk_score") or st.session_state.get("risk_tier"))
    _has_goals = bool(st.session_state.get("goals_allocation"))
    
    st.markdown(
        f"**1. 📤 Upload CAS & CGS Statements** {'✅' if _has_statements else '⏳'}<br>"
        f"<span style='color: #64748b; font-size: 0.8rem;'>Portfolio Ingestion & Tax Audit</span>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"**2. 📋 SEBI Risk Profiling** {'✅' if _has_risk else '⏳'}<br>"
        f"<span style='color: #64748b; font-size: 0.8rem;'>Binding Constraint SAA</span>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"**3. 🎯 Goals & Step-Up SIP** {'✅' if _has_goals else '⏳'}<br>"
        f"<span style='color: #64748b; font-size: 0.8rem;'>Compounding & Step-Up SIP</span>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"**4. 📈 True Debt Allocation** {'✅' if _has_cas else '⏳'}<br>"
        f"<span style='color: #64748b; font-size: 0.8rem;'>Unbundle Hybrid Internal Debt</span>",
        unsafe_allow_html=True
    )
    st.markdown(
        f"**5. 📄 Fiduciary Review Report** {'✅' if (_has_cas and _has_risk and _has_goals) else '⏳'}<br>"
        f"<span style='color: #64748b; font-size: 0.8rem;'>Actionable Client Report</span>",
        unsafe_allow_html=True
    )
    
    if _has_cas:
        _total_val = sum(f.get("current_value", 0) for f in _user_portfolio)
        st.markdown("---")
        st.markdown(f"💼 **Active Portfolio:** ₹{_total_val/100000:.2f}L ({len(_user_portfolio)} funds)")
    
    st.markdown("---")
    st.caption("🛡️ **Fiduciary Standard:** SEBI (Investment Advisers) Regulations, 2013 | Non-execution authority | Zero distributor commission bias.")


st.title("📄 Executive Fiduciary Report & Action Plan")
st.markdown("Your formal, comprehensive portfolio diagnostic and investment advisory report.")

# Check prerequisites
portfolio = st.session_state.get("user_portfolio", [])
cgs_data = st.session_state.get("cgs_data")
goals_alloc = st.session_state.get("goals_allocation")
risk_tier = st.session_state.get("risk_tier") or st.session_state.get("risk_bucket")

# Synthesize goal allocation if user generated SIP blueprint from dashboard
if not goals_alloc and st.session_state.get("deterministic_sip_plan"):
    bp = st.session_state["deterministic_sip_plan"]
    lc_val = float(next((a["amount_inr"] for a in bp.get("allocations", []) if "Large" in a.get("sleeve", "")), 0.0))
    ms_val = float(next((a["amount_inr"] for a in bp.get("allocations", []) if "Mid" in a.get("sleeve", "")), 0.0))
    db_val = float(next((a["amount_inr"] for a in bp.get("allocations", []) if "Debt" in a.get("sleeve", "")), 0.0))
    goals_alloc = {
        "goals": {
            "sip_plan": {
                "goal_name": "Long-Term Wealth Accumulation and SAA Compounding",
                "priority": 1,
                "required_monthly": float(bp["monthly_budget_inr"]),
                "allocated_monthly": float(bp["allocated_budget_inr"]),
                "gap_monthly": float(bp["unallocated_budget_inr"]),
                "target_corpus": 0.0,
                "horizon_years": 10,
            }
        },
        "total_required": float(bp["monthly_budget_inr"]),
        "total_allocated": float(bp["allocated_budget_inr"]),
        "total_gap": float(bp["unallocated_budget_inr"]),
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
    missing.append("📤 Upload CAS & CGS Statements (Portfolio Dashboard)")
if not cgs_data:
    missing.append("📑 Upload Capital Gains Statement (CGS) (Portfolio Dashboard)")
if not risk_tier:
    missing.append("📋 Complete Risk Profiler (Portfolio Dashboard)")
if not goals_alloc:
    missing.append("🎯 Calculate Goal Allocations (Financial Goals)")

if missing:
    st.warning("⚠️ **Prerequisites Missing:** Please complete the following steps to generate your full advisory report:")
    for m in missing:
        st.markdown(f"* {m}")
    st.info("👉 *Follow the step-by-step advisory flow from the sidebar to complete all milestones.*")
else:
    total_val = sum(f.get("current_value", 0) for f in portfolio)
    total_invested = sum(f.get("invested_value", 0) for f in portfolio)
    total_gain = total_val - total_invested if total_invested > 0 else 0
    gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else 0

    st.success("✅ All advisory milestones complete! Your review report is ready.")

    # High-level Summary
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Portfolio Value", f"₹{total_val:,.0f}")
    with col2:
        st.metric("Governing Risk Profile", str(risk_tier).replace("_", " ").title())
    with col3:
        sip_budget = goals_alloc.get("total_allocated", 0)
        st.metric("Monthly SIP Budget", f"₹{sip_budget:,.0f}/mo")

    # Build report preview
    report_lines = [
        "# Executive Mutual Fund Portfolio Review & Fiduciary Advisory Plan",
        "",
        f"**Valuation Date:** Current Session  |  **Governing Risk Tier:** {risk_tier}  |  **Active Funds:** {len(portfolio)}",
        "",
        "---",
        "",
        "## 1. Portfolio Diagnostic Summary",
        f"* **Total Portfolio Value:** ₹{total_val:,.0f}",
        f"* **Total Invested Cost:** ₹{total_invested:,.0f}",
        f"* **Unrealized Gain / (Loss):** ₹{total_gain:,.0f} ({gain_pct:+.1f}%)",
        "",
        "## 2. Holdings Breakdown",
        "| Scheme Name | Category | Plan | Current Value (₹) | Equity % | Debt % |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for f in portfolio:
        name = f.get("scheme", "Unknown")
        cat = f.get("category", "N/A")
        plan = f.get("plan_type", "Direct")
        val = f.get("current_value", 0)
        eq = f.get("eq", 0)
        debt = f.get("debt", 0)
        report_lines.append(f"| {name} | {cat} | {plan} | ₹{val:,.0f} | {eq:.1f}% | {debt:.1f}% |")

    # Add CGS section if available
    cgs_data = st.session_state.get("cgs_data")
    if cgs_data and cgs_data.get("summary"):
        cg_s = cgs_data.get("summary", {})
        ltcg = float(cg_s.get("ltcg_inr") or 0.0)
        stcg = float(cg_s.get("stcg_inr") or 0.0)
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
    regular_val = sum(f.get("current_value", 0) for f in regular_holdings)
    regular_pct = (regular_val / total_val * 100.0) if total_val > 0 else 0.0

    report_lines.extend([
        "",
        "## 3. Distributor Commission Bleed & Direct Plan Audit",
    ])
    if regular_val > 0:
        est_10y = regular_val * 0.1046  # 10-year compounded drag factor at ~1% p.a.
        report_lines.extend([
            f"* **Regular Plan Exposure:** ₹{regular_val:,.0f} ({regular_pct:.1f}% of total portfolio) across {len(regular_holdings)} schemes",
            f"* **Estimated 10-Year Compounded Drag:** ₹{est_10y:,.0f} in avoidable distributor commissions",
            "* **Fiduciary Switch Recommendation:** Recommend executing switches from Regular to Direct Growth plans to retain 100% of compounding returns.",
            "",
            "| Identified Regular Scheme | Current Value (₹) | Potential Annual Savings (~1% p.a.) |",
            "| :--- | :--- | :--- |",
        ])
        for rf in regular_holdings:
            r_name = rf.get("scheme", "Regular Scheme")
            r_val = rf.get("current_value", 0)
            report_lines.append(f"| {r_name} | ₹{r_val:,.0f} | ~₹{r_val * 0.01:,.0f}/yr |")
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
            f"* **Total Bank Cash:** ₹{float(ls_plan['bank_cash_inr']):,.2f}",
            f"* **6-Month Emergency Reserve:** ₹{float(ls_plan['emergency_reserve_inr']):,.2f}",
            f"* **Deployable Surplus:** ₹{float(ls_plan['deployable_surplus_inr']):,.2f}",
            f"* **Effective Staged Deployment:** ₹{float(ls_plan['effective_lumpsum_inr']):,.2f}",
            f"* **Liquid Parking Vehicle:** {ls_plan['parking_scheme']}",
            f"* **STP Duration:** {ls_plan['stp_duration_months']} months @ ₹{float(ls_plan['monthly_stp_tranche_inr']):,.2f} / month",
        ])

    report_lines.extend([
        "",
        "## 7. Fiduciary Disclosures & Compliance Statement",
        "* **Statutory Mandate:** SEBI (Investment Advisers) Regulations, 2013.",
        "* **Direct Plan Enforcement:** All proposed switches and SIP allocations strictly mandate Direct Plans to eliminate intermediary commissions.",
        "* **Non-Execution Authority:** The adviser operates solely on a fee-only, non-execution advisory basis; order execution remains exclusively in client control.",
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

