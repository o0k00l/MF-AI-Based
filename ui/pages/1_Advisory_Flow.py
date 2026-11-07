"""Advisory Workflow & Flow Navigator — Step-by-step fiduciary roadmap."""
from __future__ import annotations

import sys
from pathlib import Path
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st

from core.settings import AI_PROVIDER_KEYS, ai_key_status, save_ai_keys

# --- Page Configuration ---
st.set_page_config(
    page_title="Advisory Flow | Fiduciary Roadmap",
    page_icon="🧭",
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

    st.markdown("<p style='font-weight: 700; font-size: 0.82rem; color: #334155; margin-bottom: 6px;'>🧭 TWO-STEP FIDUCIARY FLOW</p>", unsafe_allow_html=True)

    # Two-Step Fiduciary Flow
    st.page_link("app.py", label=f"Step 1: Portfolio Intake & Audit {'✅' if _has_cas else '⏳'}", icon="📊")
    st.page_link("pages/5_Fiduciary_Report.py", label=f"Step 2: Executive Fiduciary Report {'✅' if _has_cas else '⏳'}", icon="📄")

    st.markdown("<p style='font-weight: 700; font-size: 0.75rem; color: #64748b; margin-top: 10px; margin-bottom: 4px;'>🔬 OPTIONAL DEEP-DIVES</p>", unsafe_allow_html=True)
    st.page_link("pages/2_Risk_Profiler.py", label="Risk Profiler & SAA", icon="📋")
    st.page_link("pages/4_Debt_Allocation.py", label="True Debt Factsheet Matrix", icon="📈")
    st.page_link("pages/3_Financial_Goals.py", label="Financial Goals Wizard", icon="🎯")
    st.page_link("pages/1_Advisory_Flow.py", label="Advisory Roadmap", icon="🧭")

    st.markdown("---")
    if st.button("🔄 Reset / Clear Session", use_container_width=True, help="Clear active session portfolio and start over"):
        st.session_state.clear()
        st.rerun()

    st.caption("🛡️ **Fiduciary Standard:** SEBI (Investment Advisers) Regulations, 2013 | Non-execution authority | Zero distributor commission bias.")

# --- Custom Styling ---
st.markdown("""
<style>
    .flow-card {
        background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 16px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.04);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .flow-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0,0,0,0.08);
        border-color: #cbd5e1;
    }
    .flow-step-num {
        display: inline-block;
        background: #1e3a8a;
        color: #ffffff;
        font-weight: 700;
        border-radius: 50%;
        width: 32px;
        height: 32px;
        text-align: center;
        line-height: 32px;
        margin-right: 12px;
    }
    .flow-title {
        font-size: 1.25rem;
        font-weight: 700;
        color: #0f172a;
        display: inline-block;
        vertical-align: middle;
    }
    .status-badge-done {
        background-color: #dcfce7;
        color: #15803d;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        float: right;
    }
    .status-badge-pending {
        background-color: #f1f5f9;
        color: #64748b;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
        float: right;
    }
    .step-desc {
        color: #475569;
        font-size: 0.95rem;
        margin-top: 10px;
        line-height: 1.5;
    }
</style>
""", unsafe_allow_html=True)

# --- Header ---
st.title("🧭 End-to-End Investment Advisory Flow")
st.markdown(
    "A transparent, **SEBI-aligned fiduciary journey** for Indian Mutual Fund investors. "
    "Follow each stage to diagnose your portfolio, align asset allocation with your true risk tolerance, "
    "and construct an actionable goal plan."
)

# --- Session Progress Tracker ---
user_portfolio = st.session_state.get("user_portfolio", [])
cgs_data = st.session_state.get("cgs_data")
has_cas = len(user_portfolio) > 0
has_cgs = bool(cgs_data)
has_statements = has_cas and has_cgs
has_risk = bool(st.session_state.get("user_risk_score") or st.session_state.get("risk_tier"))
has_goals = bool(st.session_state.get("goals_allocation"))

completed_count = sum([has_statements, has_risk, has_goals])
progress_pct = int((completed_count / 3.0) * 100)

st.markdown("---")
st.subheader("📊 Your Advisory Journey Status")

col_prog1, col_prog2 = st.columns([3, 1])
with col_prog1:
    st.progress(progress_pct / 100.0)
with col_prog2:
    st.markdown(f"**{progress_pct}% Completed** ({completed_count} of 3 milestones)")

if has_statements:
    total_val = sum(f.get("current_value", 0) for f in user_portfolio)
    st.info(f"💼 **Active Session Portfolio:** {len(user_portfolio)} live funds worth **₹{total_val/100000:.2f} Lakhs** (CAS & CGS Verified ✅).")
elif has_cas:
    st.warning("⚠️ **CAS uploaded, but CGS Statement is missing.** Both statements are required to proceed.")
else:
    st.warning("⚠️ **Statements missing.** Both CAS and CGS statements are required. Begin with **Step 1** below.")

st.markdown("---")
st.subheader("📋 Step-by-Step Fiduciary Roadmap")

# --- Step 1 Card ---
badge_step1 = '<span class="status-badge-done">✅ COMPLETED</span>' if has_statements else '<span class="status-badge-pending">⏳ ACTION REQUIRED</span>'
st.markdown(f"""
<div class="flow-card">
    <span class="flow-step-num">1</span>
    <span class="flow-title">Portfolio Statement Ingestion (CAS & CGS)</span>
    {badge_step1}
    <div class="step-desc">
        Upload your Consolidated Account Statement (CAS) and Capital Gains Statement (CGS) from CAMS / KFintech / MFCentral.
        <strong>CAS</strong> unbundles folios, identifies Regular vs. Direct plans, and computes current asset allocations.
        <strong>CGS</strong> audits statutory realized LTCG/STCG, Section 112A grandfathering, and tracks your remaining ₹1.25 Lakh tax-free headroom.
    </div>
</div>
""", unsafe_allow_html=True)
c_btn1, _ = st.columns([1, 2])
with c_btn1:
    if st.button("📤 Go to Statement Intake", key="flow_btn_s1", use_container_width=True):
        st.switch_page("app.py")

# --- Step 2 Card ---
badge_step2 = '<span class="status-badge-done">✅ PROFILED</span>' if has_risk else '<span class="status-badge-pending">⏳ PENDING</span>'
st.markdown(f"""
<div class="flow-card">
    <span class="flow-step-num">2</span>
    <span class="flow-title">Fiduciary Risk Profiling & Strategic Asset Allocation (SAA)</span>
    {badge_step2}
    <div class="step-desc">
        Under SEBI Investment Adviser Regulations (Schedule III), your portfolio is governed by the <b>Weakest Link Principle</b>:
        <br><code>Governing Risk = min(Financial Capacity, Emotional Loss Tolerance)</code><br>
        If your maximum drawdown tolerance is 5% or less, equity is strictly bounded and volatile Mid/Small Cap funds are eliminated (0%).
    </div>
</div>
""", unsafe_allow_html=True)
c_btn2, _ = st.columns([1, 2])
with c_btn2:
    if st.button("📋 Open Risk Profiler", key="flow_btn_s2", type="primary" if (has_statements and not has_risk) else "secondary", use_container_width=True):
        st.switch_page("pages/2_Risk_Profiler.py")
if has_risk:
    tier = str(st.session_state.get("risk_tier", "Evaluated")).replace("_", " ").title()
    st.caption(f"🎯 *Current Governing Profile: **{tier}***")

# --- Step 3 Card ---
badge_step3 = '<span class="status-badge-done">✅ PLANNED</span>' if has_goals else '<span class="status-badge-pending">⏳ PENDING</span>'
st.markdown(f"""
<div class="flow-card">
    <span class="flow-step-num">3</span>
    <span class="flow-title">Financial Goals & Smart Step-Up SIP Allocation</span>
    {badge_step3}
    <div class="step-desc">
        Map your savings to tangible milestones (Retirement, Higher Education, House Down Payment).
        Your existing CAS investments compound towards your future corpus, and an optional <b>10% Annual Step-Up SIP</b> reduces
        your starting monthly commitment by ~35-50% to match career income increments.
    </div>
</div>
""", unsafe_allow_html=True)
c_btn3, _ = st.columns([1, 2])
with c_btn3:
    if st.button("🎯 Open Goals Wizard", key="flow_btn_s3", type="primary" if (has_risk and not has_goals) else "secondary", use_container_width=True):
        st.switch_page("pages/3_Financial_Goals.py")

# --- Step 4 Card ---
badge_step4 = '<span class="status-badge-done">✅ READY</span>' if has_cas else '<span class="status-badge-pending">⏳ WAITING FOR CAS</span>'
st.markdown(f"""
<div class="flow-card">
    <span class="flow-step-num">4</span>
    <span class="flow-title">Deep-Dive Diagnostics & True Debt Exposure</span>
    {badge_step4}
    <div class="step-desc">
        Inspect lookthrough holdings, sector concentration, and unbundled fixed-income assets.
        Identifies hidden cash/debt inside Arbitrage and Balanced Advantage Funds (BAFs), and calculates commission bleed from Regular plans.
    </div>
</div>
""", unsafe_allow_html=True)
c_btn4, _ = st.columns([1, 2])
with c_btn4:
    if st.button("📈 Inspect True Debt", key="flow_btn_s4", use_container_width=True):
        st.switch_page("pages/4_Debt_Allocation.py")

# --- Step 5 Card ---
badge_step5 = '<span class="status-badge-done">✅ AVAILABLE</span>' if (has_cas and has_risk and has_goals) else '<span class="status-badge-pending">⏳ AWAITING PREREQUISITES</span>'
st.markdown(f"""
<div class="flow-card">
    <span class="flow-step-num">5</span>
    <span class="flow-title">Executive Fiduciary Report & Rebalancing Manifest</span>
    {badge_step5}
    <div class="step-desc">
        Synthesizes your entire portfolio audit into an investor-ready document with actionable switch proposals,
        tax-aware exit load estimates, and ongoing SIP execution mandates.
    </div>
</div>
""", unsafe_allow_html=True)

# --- Advanced AI Configuration Expander ---
c_btn5, _ = st.columns([1, 2])
with c_btn5:
    if st.button("📄 View Fiduciary Report", key="flow_btn_s5", type="primary" if (has_statements and has_risk and has_goals) else "secondary", use_container_width=True):
        st.switch_page("pages/5_Fiduciary_Report.py")

st.markdown("---")
with st.expander("⚙️ Advanced Settings: AI Research & Model Keys", expanded=False):
    st.caption("Configure optional AI narrative providers for automated research summarization.")
    
    status = ai_key_status()
    for provider, configured in status.items():
        st.write(f"**{provider}** — {'Configured' if configured else 'Not configured'}")

    st.info(
        "Keys are stored locally in the Git-ignored .env file or environment secrets. "
        "Existing keys are never displayed."
    )

    with st.form("ai_provider_keys_flow"):
        st.subheader("Add or Replace API Keys")
        requesty = st.text_input(
            "Requesty API key",
            type="password",
            placeholder="Leave blank to keep existing key",
            help="REQUESTY_API_KEY",
        )
        openrouter = st.text_input(
            "OpenRouter API key",
            type="password",
            placeholder="Leave blank to keep existing key",
            help="OPENROUTER_API_KEY",
        )
        st.caption("Only non-empty fields are updated.")
        submitted = st.form_submit_button("Save API Keys", type="primary")

    if submitted:
        try:
            result = save_ai_keys({
                "REQUESTY_API_KEY": requesty,
                "OPENROUTER_API_KEY": openrouter,
            })
            st.success("API keys saved locally.")
            for provider, configured in result.items():
                st.write(f"**{provider}:** {'Configured' if configured else 'Not configured'}")
        except (OSError, TypeError, ValueError):
            st.error("Settings could not be saved. Check file permissions.")

