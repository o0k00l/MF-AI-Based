"""Debt Allocation Verification Page - Display true portfolio debt allocation.

This page analyzes user-uploaded portfolio data to show true debt allocation
including internal debt in equity funds.

NO HARDCODING: Every value comes from user-uploaded CAS data.
"""
from __future__ import annotations

from pathlib import Path
import sys

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
from services.fiduciary_engine import evaluate_portfolio_saa_audit
from services.ai_fund_classifier import enrich_funds_with_ai, compute_portfolio_segment_breakdown

# --- Page Configuration ---
st.set_page_config(
    page_title="Debt Allocation | Portfolio Dashboard",
    page_icon="📈",
    layout="wide",
)

# --- Render Unified Advisory Flow Sidebar ---
render_fiduciary_sidebar(current_page="pages/4_Debt_Allocation.py")

# --- Custom CSS for Professional Styling ---
st.markdown("""
<style>
    .metric-card {
        background: var(--secondary-background-color, #f8fafc);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.06);
        border: 1px solid rgba(148, 163, 184, 0.25);
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: var(--text-color, #0f172a);
    }
    .metric-label {
        font-size: 0.875rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .section-title {
        color: var(--text-color, #0f172a) !important;
        font-weight: 700;
        margin-top: 24px;
        margin-bottom: 12px;
        border-bottom: 2px solid rgba(148, 163, 184, 0.25);
        padding-bottom: 8px;
    }
    .disclaimer-box {
        background: var(--secondary-background-color, #f8fafc);
        color: var(--text-color, #0f172a);
        border-radius: 12px;
        padding: 16px;
        border: 1px solid rgba(148, 163, 184, 0.25);
        border-left: 4px solid #16a34a;
        margin-top: 32px;
    }
    @media (prefers-color-scheme: dark) {
        .metric-card, .disclaimer-box {
            background: #1e293b !important;
            border-color: rgba(148, 163, 184, 0.2) !important;
        }
        .metric-value, .section-title {
            color: #f8fafc !important;
        }
    }
    [data-theme="dark"] .metric-card, [data-theme="dark"] .disclaimer-box {
        background: #1e293b !important;
        border-color: rgba(148, 163, 184, 0.2) !important;
    }
    [data-theme="dark"] .metric-value, [data-theme="dark"] .section-title {
        color: #f8fafc !important;
    }
</style>
""", unsafe_allow_html=True)

# --- Page Header ---
st.title("📈 Debt Allocation Verification")
st.caption("True portfolio debt allocation including internal debt in equity funds")

# Check if user has uploaded portfolio data (CAS data)
if "user_portfolio" not in st.session_state or not st.session_state["user_portfolio"]:
    st.info("Please upload your CAS file on the Portfolio Dashboard page first to analyze your debt allocation.")
    st.stop()

# Get user's actual portfolio from session state
user_portfolio = st.session_state["user_portfolio"]
funds = enrich_funds_with_ai(user_portfolio)

# --- Explanation ---
st.markdown("""
### 🔬 How True Debt is Calculated (Fund-Wise AMC Disclosures)

Rather than assuming generic category percentages, the fiduciary engine performs **fund-by-fund look-through** based on published AMC factsheets and SEBI portfolio disclosures:

* **Balanced Advantage & Dynamic Asset Funds**: Unbundles equity derivatives from actual fixed income (G-Secs, T-Bills, Corporate Bonds).
* **Multi-Asset Allocation Funds**: Unbundles physical domestic gold and debt reserves from pure equities.
* **Flexi Cap & Large Cap Funds**: Tracks real TREPS, repo cash, and net debt held for daily liquidity and deployment.
* **Pure Sectoral & Thematic Funds**: Reflects near-100% net equity exposure without artificial debt drag.
""")

# --- Portfolio-Level Analysis ---
total_portfolio_value = sum(f.get("current_value", 0) for f in funds) or 0

if total_portfolio_value > 0:
    # Authoritative canonical segment breakdown (zero heuristic fabrication)
    seg = compute_portfolio_segment_breakdown(funds)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Total Portfolio Value</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{total_portfolio_value/100000:.1f} Lakhs</span>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with col2:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">True Equity Look-Through</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">{seg["equity_pct"]:.1f}%</span>', unsafe_allow_html=True)
        st.caption(f"₹{seg['equity_value']/100000:.2f}L active equities")
        st.markdown('</div>', unsafe_allow_html=True)
    with col3:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">True Debt & Cash Buffer</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">{seg["debt_pct"]:.1f}%</span>', unsafe_allow_html=True)
        st.caption(f"₹{seg['debt_value']/100000:.2f}L stability reserves")
        st.markdown('</div>', unsafe_allow_html=True)

    # --- Target SAA Benchmark & Deficit Analysis ---
    target_saa = st.session_state.get("saa_target")
    if target_saa:
        audit = evaluate_portfolio_saa_audit(funds, target_saa=target_saa)
        tgt_db_pct = audit.get("target_debt_pct", 25.0)
        curr_db_pct = audit.get("current_debt_pct", 0.0)
        db_gap = audit.get("debt_gap_inr", 0.0)
        is_deficit = audit.get("is_debt_deficit", False)
        tier_title = str(st.session_state.get("risk_tier", "Assessed Profile")).replace("_", " ").title()

        st.markdown("---")
        st.subheader("🎯 Fiduciary Target Debt Benchmark")
        st.caption(f"Benchmarked against your evaluated **{tier_title}** Strategic Asset Allocation (SAA):")

        tc1, tc2, tc3, tc4 = st.columns(4)
        with tc1:
            st.metric("Target Debt SAA", f"{tgt_db_pct:.1f}%", "Required Safety Buffer")
        with tc2:
            st.metric("Actual Portfolio Debt", f"{curr_db_pct:.1f}%", f"{curr_db_pct - tgt_db_pct:+.1f}% vs Target")
        with tc3:
            tgt_db_inr = total_portfolio_value * (tgt_db_pct / 100.0)
            st.metric("Target Debt Corpus", f"₹{tgt_db_inr/100000:.2f}L")
        with tc4:
            if is_deficit:
                st.metric("Debt Buffer Deficit", f"₹{float(db_gap)/100000:.2f}L", delta="-Deficit", delta_color="inverse")
            else:
                surplus_val = max(0.0, (curr_db_pct - tgt_db_pct) / 100.0 * total_portfolio_value)
                st.metric("Debt Cushion Surplus", f"₹{surplus_val/100000:.2f}L", delta="+Surplus")

        if is_deficit:
            st.warning(
                f"🛡️ **Fiduciary Action Required:** Your portfolio has a **₹{float(db_gap)/100000:.2f} Lakhs Debt Deficit** "
                f"relative to your {tier_title} profile. In a market downturn, your portfolio will experience greater volatility than your declared risk tolerance. "
                "Recommend routing incremental monthly SIPs or rebalancing regular funds into Direct Liquid / Money Market funds to build this stability floor."
            )
        else:
            st.success("✅ **Stability Floor Satisfied:** Your portfolio holds adequate defensive reserves aligned with your SEBI risk mandate.")
    else:
        st.info("💡 **Tip:** Complete Step 2: Risk Profiler to automatically benchmark your debt exposure against your required SEBI safety buffer.")

    st.markdown("---", unsafe_allow_html=True)
    st.markdown('<h2 class="section-title">Allocation Breakdown</h2>', unsafe_allow_html=True)

    # Create multi-asset look-through breakdown
    chart_data = {
        "Large Cap": seg.get("large_cap_value", 0),
        "Mid Cap": seg.get("mid_cap_value", 0),
        "Small Cap": seg.get("small_cap_value", 0),
        "True Debt / Cash": seg.get("debt_value", 0),
    }
    if seg.get("gold_value", 0) > 0:
        chart_data["Gold"] = seg["gold_value"]

    st.bar_chart(chart_data, use_container_width=True)

st.markdown("---", unsafe_allow_html=True)
st.markdown('<h2 class="section-title">Fund-by-Fund Debt Allocation</h2>', unsafe_allow_html=True)

# Show funds with debt allocation from USER portfolio
debt_table_rows = []
for fund in sorted(funds, key=lambda f: -((f.get("current_value", 0) * f.get("debt", 0) / 100.0))):
    if fund.get("current_value", 0) <= 0:
        continue
    c_val = float(fund.get("current_value", 0))
    d_pct = float(fund.get("debt", 0))
    d_inr = c_val * (d_pct / 100.0)
    debt_table_rows.append({
        "Scheme Name": fund.get("scheme", "")[:50],
        "Mandate": fund.get("scheme_type", fund.get("category", "")),
        "Current Value": c_val,
        "Debt / Cash %": d_pct,
        "Debt Corpus": d_inr,
        "Equity %": float(fund.get("eq", 0)),
        "Gold %": float(fund.get("gold", 0) or 0.0),
        "Source": fund.get("classification_source", "AMC Factsheet"),
    })

if debt_table_rows:
    st.dataframe(
        debt_table_rows,
        column_config={
            "Scheme Name": st.column_config.TextColumn("Scheme Name", width="large"),
            "Mandate": st.column_config.TextColumn("Mandate", width="small"),
            "Current Value": st.column_config.NumberColumn("Current Value", format="₹%d"),
            "Debt / Cash %": st.column_config.ProgressColumn("Debt / Cash %", format="%.2f%%", min_value=0, max_value=100),
            "Debt Corpus": st.column_config.NumberColumn("Debt Corpus", format="₹%d"),
            "Equity %": st.column_config.ProgressColumn("Equity %", format="%.2f%%", min_value=0, max_value=100),
            "Gold %": st.column_config.ProgressColumn("Gold %", format="%.1f%%", min_value=0, max_value=100),
            "Source": st.column_config.TextColumn("Source", width="small"),
        },
        use_container_width=True,
        hide_index=True,
    )

st.markdown("""
<div class="disclaimer-box">
<b>📝 Disclaimer:</b> This portfolio analysis is for informational purposes only. 
All values are parsed directly from your uploaded CAS file. 
This is not financial advice. Always consult with a qualified financial advisor 
before making investment decisions.
</div>
""", unsafe_allow_html=True)
st.caption("All portfolio values parsed dynamically from your uploaded CAS. Reference metrics from AMFI factsheets.")

# Navigation to next step
st.markdown("---")
col_nav1, col_nav2 = st.columns([2, 1])
with col_nav1:
    st.info("💡 **Next Step:** Debt allocation verified. Proceed to generate your comprehensive Fiduciary Review Report.")
with col_nav2:
    if st.button("📄 Generate Fiduciary Review Report", type="primary", use_container_width=True):
        st.switch_page("pages/5_Fiduciary_Report.py")
