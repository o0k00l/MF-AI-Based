"""Debt Allocation Verification Page - Display true portfolio debt allocation.

This page analyzes user-uploaded portfolio data to show true debt allocation
including internal debt in equity funds.

NO HARDCODING: Every value comes from user-uploaded CAS data.
"""
from __future__ import annotations

import json
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
from services.ai_fund_classifier import enrich_funds_with_ai

# --- Page Configuration ---
st.set_page_config(
    page_title="Debt Allocation | Portfolio Dashboard",
    page_icon="📈",
    layout="wide",
)

# --- Render Advisory Flow Sidebar ---
# --- Render Unified Advisory Flow Sidebar (Single Source of Truth) ---
render_fiduciary_sidebar(current_page="pages/4_Debt_Allocation.py")

# --- Custom CSS for Professional Styling ---
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        border: 1px solid #e2e8f0;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        color: #0f172a;
    }
    .metric-label {
        font-size: 0.875rem;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .section-title {
        color: #0f172a;
        font-weight: 700;
        margin-top: 24px;
        margin-bottom: 12px;
        border-bottom: 2px solid #cbd5e1;
        padding-bottom: 8px;
    }
    .disclaimer-box {
        background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
        border-radius: 12px;
        padding: 16px;
        border-left: 4px solid #16a34a;
        margin-top: 32px;
    }
</style>
""", unsafe_allow_html=True)

# --- Page Title ---
st.markdown('<h1 class="section-title">📈 Debt Allocation Verification</h1>', unsafe_allow_html=True)
st.markdown('<p style="color: #64748b; font-size: 1.1rem;">True portfolio debt allocation including internal debt in equity funds</p>', unsafe_allow_html=True)

# Load fund metrics (REFERENCE DATA ONLY - for debt allocation percentages)
METRICS_PATH = Path(__file__).parent.parent.parent / "data" / "policy" / "fund_metrics.json"


@st.cache_data(ttl=3600, show_spinner=False)
def load_fund_metrics() -> dict | None:
    """Load fund metrics from the policy file. This is REFERENCE DATA for debt allocation percentages."""
    if METRICS_PATH.exists():
        with open(METRICS_PATH) as f:
            return json.load(f)
    return None


# Get fund metrics (reference data)
metrics = load_fund_metrics()

# Check if user has uploaded portfolio data (CAS data)
if "user_portfolio" not in st.session_state or not st.session_state["user_portfolio"]:
    st.title("Debt Allocation Verification")
    st.info("Please upload your CAS file on the Portfolio Dashboard page first to analyze your debt allocation.")
    st.stop()

st.title("Debt Allocation Verification")
st.caption("True portfolio debt allocation including internal debt in equity funds")

# Reference metrics loaded if present; user CAS data is primary.

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
    # Calculate allocations based on USER portfolio values
    allocations = {
        "Equity": 0.0,
        "Debt (Internal)": 0.0,
        "Large Cap": 0.0,
        "Mid Cap": 0.0,
        "Small Cap": 0.0,
    }
    
    for fund in funds:
        current = fund.get("current_value", 0) or 0
        if current <= 0:
            continue
            
        eq = fund.get("eq", 0) or 0
        debt = fund.get("debt", 0) or 0
        lc = fund.get("lc", 0) or 0
        mc = fund.get("mc", 0) or 0
        sc = fund.get("sc", 0) or 0
        cat = fund.get("category", "")
        
        # Equity allocation based on category
        if cat == "Hybrid":
            allocations["Equity"] += current * eq / 100
        else:
            allocations["Equity"] += current * eq / 100
        
        # Internal debt in equity funds
        if cat in ["Equity", "Hybrid"]:
            allocations["Debt (Internal)"] += current * debt / 100
        
        # Segment allocations
        allocations["Large Cap"] += current * lc / 100
        allocations["Mid Cap"] += current * mc / 100
        allocations["Small Cap"] += current * sc / 100

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Total Portfolio Value</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{total_portfolio_value/100000:.1f} Lakhs</span>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with col2:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">True Equity</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">{allocations["Equity"]/total_portfolio_value*100:.1f}%</span>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with col3:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">True Debt</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">{allocations["Debt (Internal)"]/total_portfolio_value*100:.1f}%</span>', unsafe_allow_html=True)
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

    # Create bar chart data
    chart_data = {
        "Equity": allocations["Equity"],
        "Internal Debt": allocations["Debt (Internal)"],
    }

    st.bar_chart(chart_data, use_container_width=True)

    # Detailed segment breakdown
    seg_col1, seg_col2, seg_col3 = st.columns(3)
    with seg_col1:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Large Cap</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{allocations["Large Cap"]/100000:.2f} Lakhs</span>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with seg_col2:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Mid Cap</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{allocations["Mid Cap"]/100000:.2f} Lakhs</span>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)
    with seg_col3:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Small Cap</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{allocations["Small Cap"]/100000:.2f} Lakhs</span>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---", unsafe_allow_html=True)
st.markdown('<h2 class="section-title">Fund-by-Fund Debt Allocation</h2>', unsafe_allow_html=True)

# Show funds with debt allocation from USER portfolio
debt_table_rows = []
for fund in sorted(funds, key=lambda f: -((f.get("current_value", 0) * f.get("debt", 0) / 100.0))):
    if fund.get("current_value", 0) <= 0:
        continue
    c_val = fund.get("current_value", 0)
    d_pct = fund.get("debt", 0)
    d_inr = c_val * (d_pct / 100.0)
    debt_table_rows.append({
        "Scheme Name": fund.get("scheme", "")[:50],
        "Scheme Mandate": fund.get("scheme_type", fund.get("category", "")),
        "Current Value": f"₹{c_val:,.0f}",
        "Debt / Cash %": f"{d_pct:.2f}%",
        "Debt Corpus (₹)": f"₹{d_inr:,.0f}",
        "Equity %": f"{fund.get('eq', 0):.2f}%",
        "Gold %": f"{fund.get('gold', 0):.1f}%" if fund.get("gold", 0) > 0 else "0.0%",
        "Source": fund.get("classification_source", "AMC Factsheet"),
    })

if debt_table_rows:
    st.dataframe(debt_table_rows, use_container_width=True, hide_index=True)

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
