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

