"""Executive Fiduciary Report & Download Page."""
from __future__ import annotations

import streamlit as st

# --- Page Configuration ---
st.set_page_config(
    page_title="Fiduciary Report | Portfolio Review",
    page_icon="📄",
    layout="wide",
)

st.title("📄 Executive Fiduciary Report & Action Plan")
st.markdown("Your formal, comprehensive portfolio diagnostic and investment advisory report.")

# Check prerequisites
portfolio = st.session_state.get("user_portfolio", [])
cgs_data = st.session_state.get("cgs_data")
goals_alloc = st.session_state.get("goals_allocation")
risk_tier = st.session_state.get("risk_tier") or st.session_state.get("risk_bucket")

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
            "## 3. Statutory Capital Gains Audit (CGS)",
            f"* **Realized LTCG (§112A):** ₹{ltcg:,.2f}",
            f"* **Realized STCG (§111A):** ₹{stcg:,.2f}",
            f"* **Remaining §112A Exemption Headroom:** ₹{rem_hd:,.2f} (out of ₹1.25 Lakhs annual tax-free limit)",
            f"* **Statement Provenance:** SHA256 `{cgs_data.get('source_sha256', 'N/A')[:16]}...`",
        ])

    report_lines.extend([
        "",
        "## 4. Financial Goal Allocation",
    ])
    for g_id, g_info in goals_alloc.get("goals", {}).items():
        g_name = g_info.get("goal_name", g_id)
        req = g_info.get("required_monthly", 0)
        alloc = g_info.get("allocated_monthly", 0)
        report_lines.append(f"* **{g_name}:** Required SIP: ₹{req:,.0f}/mo | Allocated SIP: ₹{alloc:,.0f}/mo")

    report_lines.extend([
        "",
        "## 5. Fiduciary Disclosures & Compliance Statement",
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

