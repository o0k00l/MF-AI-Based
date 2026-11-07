"""Debt Allocation Verification Page - Display true portfolio debt allocation.

This page analyzes user-uploaded portfolio data to show true debt allocation
including internal debt in equity funds.

NO HARDCODING: Every value comes from user-uploaded CAS data.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st
from services.fiduciary_engine import evaluate_portfolio_saa_audit

# --- Page Configuration ---
st.set_page_config(
    page_title="Debt Allocation | Portfolio Dashboard",
    page_icon="📈",
    layout="wide",
)

# --- Render Advisory Flow Sidebar ---
with st.sidebar:
    st.markdown("""
    <style>
        [data-testid="stSidebarNav"] { display: none !important; }
        .sidebar-brand {
            font-size: 1.15rem;
            font-weight: 700;
            color: #0f172a;
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 2px;
        }
        .sidebar-subbrand {
            font-size: 0.72rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 12px;
        }
        .portfolio-card {
            background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
            color: white;
            border-radius: 10px;
            padding: 12px 14px;
            margin-top: 6px;
            margin-bottom: 14px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
        }
    </style>
    <div class="sidebar-brand">🛡️ Fiduciary Engine</div>
    <div class="sidebar-subbrand">SEBI IA Advisory Decision Support</div>
    """, unsafe_allow_html=True)

    _user_portfolio = st.session_state.get("user_portfolio", [])
    _has_cas = len(_user_portfolio) > 0
    _has_cgs = bool(st.session_state.get("cgs_data"))
    _has_statements = _has_cas and _has_cgs
    _has_risk = bool(st.session_state.get("user_risk_score") or st.session_state.get("risk_tier"))
    _has_goals = bool(st.session_state.get("goals_allocation"))

    # Active Portfolio Card (if uploaded)
    if _has_cas:
        _tot_val = sum(f.get("current_value", 0) for f in _user_portfolio)
        _tot_inv = sum(f.get("invested_value", 0) for f in _user_portfolio)
        _gain = _tot_val - _tot_inv if _tot_inv > 0 else 0
        _gain_pct = (_gain / _tot_inv * 100) if _tot_inv > 0 else 0
        _dir_val = sum(f.get("current_value", 0) for f in _user_portfolio if str(f.get("plan_type", "Direct")).upper() == "DIRECT")
        _dir_pct = (_dir_val / _tot_val * 100) if _tot_val > 0 else 100.0

        st.markdown(f"""
        <div class="portfolio-card">
            <div style="font-size: 0.72rem; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.05em;">Active Portfolio</div>
            <div style="font-size: 1.45rem; font-weight: 700; color: #38bdf8; margin: 2px 0;">₹{_tot_val/100000:.2f}L</div>
            <div style="font-size: 0.78rem; color: #cbd5e1; display: flex; justify-content: space-between;">
                <span>{len(_user_portfolio)} Schemes</span>
                <span style="color: {'#4ade80' if _gain >= 0 else '#f87171'}; font-weight: 600;">{_gain_pct:+.1f}%</span>
            </div>
            <div style="font-size: 0.72rem; color: #94a3b8; margin-top: 6px; border-top: 1px solid rgba(255,255,255,0.15); padding-top: 5px;">
                Direct Plans: <b style="color: {'#4ade80' if _dir_pct == 100 else '#facc15'}">{_dir_pct:.0f}%</b>
            </div>
        </div>
        """, unsafe_allow_html=True)

    # Active Governing Risk Tier (if evaluated)
    if _has_risk:
        _tier_name = str(st.session_state.get("risk_tier", "Assessed")).replace("_", " ").title()
        _target = st.session_state.get("saa_target", {})
        _eq_t = _target.get("total_equity_pct", _target.get("equity_pct", 75.0))
        _db_t = _target.get("debt_pct", 25.0)
        st.markdown(f"""
        <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px; margin-bottom: 12px;">
            <div style="color: #64748b; font-size: 0.7rem; text-transform: uppercase;">Governing Risk Profile</div>
            <div style="color: #0f172a; font-size: 0.85rem; font-weight: 600;">🎯 {_tier_name}</div>
            <div style="color: #475569; font-size: 0.75rem;">Target SAA: <b>{_eq_t:.0f}% Eq / {_db_t:.0f}% Debt</b></div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<p style='font-weight: 700; font-size: 0.82rem; color: #334155; margin-bottom: 6px;'>🧭 ADVISORY WORKFLOW</p>", unsafe_allow_html=True)

    # Interactive Navigation Links
    st.page_link("app.py", label=f"1. Statement Intake {'✅' if _has_statements else '⏳'}", icon="📤", help="Upload CAS & CGS statements")
    st.page_link("pages/2_Risk_Profiler.py", label=f"2. SEBI Risk Profiler {'✅' if _has_risk else '⏳'}", icon="📋", help="Binding constraint SAA evaluation")
    st.page_link("pages/3_Financial_Goals.py", label=f"3. Milestone Goals {'✅' if _has_goals else '⏳'}", icon="🎯", help="Goal compounding & Step-Up SIP")
    st.page_link("pages/4_Debt_Allocation.py", label=f"4. True Debt Analysis {'✅' if _has_cas else '⏳'}", icon="📈", help="Unbundle internal debt & hybrid buffers")
    st.page_link("pages/5_Fiduciary_Report.py", label=f"5. Executive Report {'✅' if (_has_cas and _has_risk and _has_goals) else '⏳'}", icon="📄", help="Actionable client review document")

    st.markdown("---")
    st.page_link("pages/1_Advisory_Flow.py", label="🗺️ Advisory Roadmap & Guide", icon="🧭", help="View end-to-end fiduciary journey")

    st.markdown("---")
    if st.button("🔄 Reset / Clear Session", use_container_width=True, help="Clear active session portfolio and start over"):
        st.session_state.clear()
        st.rerun()

    st.caption("🛡️ **Fiduciary Standard:** SEBI (Investment Advisers) Regulations, 2013 | Non-execution authority | Zero distributor commission bias.")

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
funds = user_portfolio

# --- Explanation ---
st.markdown("""
### Why Debt Allocation Matters

Equity funds legally hold internal debt (cash equivalents) for liquidity management:

- Large Cap funds: approximately 5% debt
- Flexi/Multi Cap funds: approximately 2% debt
- Mid/Small Cap funds: approximately 2% debt
- Tax Saver (ELSS) funds: 0% debt
- Contra funds: 0% debt
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
for fund in sorted(funds, key=lambda f: f.get("scheme", "")):
    if fund.get("current_value", 0) <= 0:
        continue
        
    current = fund["current_value"]
    eq = fund.get("eq", 0)
    debt = fund.get("debt", 0)
    scheme = fund.get("scheme", "")[:60]
    cat = fund.get("category", "")
    
    col1, col2, col3 = st.columns([4, 1, 1])
    with col1:
        st.markdown(f"**{scheme}** ({cat}) - ₹{current:,.0f}")
    with col2:
        st.caption(f"EQ: {eq:.0f}%")
    with col3:
        st.caption(f"Debt: {debt:.0f}%")

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
