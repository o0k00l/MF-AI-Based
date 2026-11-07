"""Portfolio Dashboard — CAS-upload-only.

NO HARDCODING ALLOWED. Every user uploads their own CAS file.
No demo data. No sample portfolios. No hardcoded fund names or values.
If no CAS is uploaded, the app shows a prompt to upload one.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from services.cas_parser import parse_cas_file
from services.sip_api_client import get_api_health, request_sip_recommendations
from services.risk_profiler import evaluate_fiduciary_profile
from services.cgs_parser import parse_cgs_file

# --- Page Configuration ---
st.set_page_config(
    page_title="Portfolio Dashboard | Fiduciary Analysis",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Initialize Session State ---
if "user_portfolio" not in st.session_state:
    st.session_state["user_portfolio"] = []
if "portfolio_metadata" not in st.session_state:
    st.session_state["portfolio_metadata"] = {
        "upload_time": None,
        "upload_source": None,
        "fund_count": 0,
        "total_value": 0,
        "validation_status": "pending",
    }
if "api_recommendation_result" not in st.session_state:
    st.session_state["api_recommendation_result"] = None
if "cgs_data" not in st.session_state:
    st.session_state["cgs_data"] = None

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

# --- Helper Functions ---
def export_portfolio_csv(funds: list[dict], metadata: dict) -> bytes:
    """Generate CSV export of the portfolio."""
    if not funds:
        return b""

    fieldnames = [
        "scheme", "category", "plan_type", "option_type", "folio_no",
        "current_value", "invested_value", "unrealized_gain", "gain_pct",
        "units", "nav", "eq", "debt", "lc", "mc", "sc",
    ]
    lines = [",".join(fieldnames)]
    for fund in funds:
        row = []
        for field in fieldnames:
            val = str(fund.get(field, "") if fund.get(field) is not None else "")
            if "," in val or '"' in val or "\n" in val:
                val = '"' + val.replace('"', '""') + '"'
            row.append(val)
        lines.append(",".join(row))
    return "\n".join(lines).encode("utf-8")


def export_portfolio_json(funds: list[dict], metadata: dict) -> str:
    """Generate JSON export of the portfolio with metadata."""
    export_data = {
        "export_metadata": {
            "exported_at": str(metadata.get("upload_time", "unknown")),
            "upload_source": metadata.get("upload_source", "unknown"),
            "fund_count": len(funds),
            "total_value": sum(f.get("current_value", 0) for f in funds),
            "total_invested": sum(f.get("invested_value", 0) for f in funds),
        },
        "portfolio": funds,
    }
    return json.dumps(export_data, indent=2, ensure_ascii=False)


# --- Custom CSS for Professional Styling ---
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #1e3a8a 0%, #16a34a 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
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
st.markdown('<h1 class="main-header">📊 Portfolio Dashboard</h1>', unsafe_allow_html=True)
st.markdown(
    "<p style='color: #64748b; font-size: 1.1rem;'>Upload your CAS (Consolidated Account Statement) and CGS (Capital Gains Statement) to analyze your portfolio.</p>",
    unsafe_allow_html=True,
)

# --- Dual Mandatory Statement Ingestion (CAS & CGS) ---
st.markdown(
    "<p style='color: #64748b; font-size: 1.05rem;'>"
    "A SEBI-compliant review strictly mandates uploading <strong>both statements</strong>:<br>"
    "• <strong>1. CAS (Consolidated Account Statement):</strong> Current holdings, units, folios, and market valuations. <em>(Mandatory)</em><br>"
    "• <strong>2. CGS (Capital Gains Statement):</strong> Realized LTCG/STCG, Section 112A grandfathered values, and exemption headroom. <em>(Mandatory)</em>"
    "</p>",
    unsafe_allow_html=True,
)

col_up1, col_up2 = st.columns(2)
with col_up1:
    uploaded_file = st.file_uploader(
        "1. CAS Statement (.xlsx) *Mandatory*",
        type=["xlsx"],
        help="Upload your CAMS/Karvy/NSDL/MFCentral Consolidated Account Statement Excel file.",
        key="main_cas_uploader",
    )
with col_up2:
    cgs_file = st.file_uploader(
        "2. Capital Gains Statement (CGS .xlsx) *Mandatory*",
        type=["xlsx"],
        help="Upload your CAMS or KFintech Capital Gains Statement for realized LTCG/STCG and tax audit.",
        key="main_cgs_uploader",
    )

if uploaded_file is None or cgs_file is None:
    if uploaded_file is None and cgs_file is None:
        st.info("⬆️ **Both CAS and CGS Statements Required:** Please upload both your CAS statement on the left and your Capital Gains Statement (CGS) on the right to begin.")
    elif uploaded_file is None:
        st.warning("⚠️ **CAS Statement Missing:** Please upload your Consolidated Account Statement (CAS) on the left to proceed.")
    else:
        st.warning("⚠️ **CGS Statement Missing:** Please upload your Capital Gains Statement (CGS) on the right to complete intake.")
    st.stop()

# --- Parse uploaded statements ---
with st.spinner("Parsing your CAS file..."):
    funds = parse_cas_file(uploaded_file)

if not funds:
    st.error("Could not parse any funds from the uploaded CAS file. Please check the file format.")
    st.stop()

# Parse mandatory CGS file
with st.spinner("Auditing Capital Gains Statement (CGS)..."):
    try:
        cgs_res = parse_cgs_file(cgs_file)
        if not cgs_res or not cgs_res.get("summary"):
            st.error("Could not parse valid capital gains summary from the uploaded CGS file. Please upload an official CAMS/KFintech CGS statement.")
            st.stop()
        st.session_state["cgs_data"] = cgs_res
    except Exception as exc:
        st.error(f"❌ Failed to parse CGS: {exc}")
        st.stop()

st.success(f"✅ **Both Statements Verified:** Parsed **{len(funds)}** active funds from your CAS and verified statutory CGS tax evidence.")

# Store portfolio in session state for other pages
st.session_state["user_portfolio"] = funds
st.session_state["portfolio_metadata"] = {
    "upload_time": "uploaded_session",
    "upload_source": getattr(uploaded_file, "name", "uploaded_cas.xlsx"),
    "fund_count": len(funds),
    "total_value": sum(f.get("current_value", 0) for f in funds),
    "validation_status": "parsed",
}

# --- Portfolio Metrics (computed dynamically) ---
total_value = sum(f.get("current_value", 0) for f in funds)
total_invested = sum(f.get("invested_value", 0) for f in funds)
total_gain = (total_value - total_invested) if total_invested > 0 else 0.0
gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else 0.0

total_eq = sum(f.get("current_value", 0) * f.get("eq", 0) / 100 for f in funds)
total_debt = sum(f.get("current_value", 0) * f.get("debt", 0) / 100 for f in funds)
total_lc = sum(f.get("current_value", 0) * f.get("lc", 0) / 100 for f in funds)
total_mc = sum(f.get("current_value", 0) * f.get("mc", 0) / 100 for f in funds)
total_sc = sum(f.get("current_value", 0) * f.get("sc", 0) / 100 for f in funds)

eq_pct = (total_eq / total_value * 100) if total_value else 0
debt_pct = (total_debt / total_value * 100) if total_value else 0

# --- Key Metrics Row ---
st.markdown('<h2 class="section-title">📊 Portfolio Overview</h2>', unsafe_allow_html=True)
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<span class="metric-label">Total Active Funds</span>', unsafe_allow_html=True)
    st.markdown(f'<span class="metric-value">{len(funds)}</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
with col2:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<span class="metric-label">Current Value</span>', unsafe_allow_html=True)
    st.markdown(f'<span class="metric-value">₹{total_value/100000:.1f} Lakhs</span>', unsafe_allow_html=True)
    if total_invested > 0:
        st.caption(f"Cost: ₹{total_invested/100000:.1f}L | Gain: {gain_pct:+.1f}%")
    st.markdown('</div>', unsafe_allow_html=True)
with col3:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<span class="metric-label">Equity Allocation</span>', unsafe_allow_html=True)
    st.markdown(f'<span class="metric-value">{eq_pct:.1f}%</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
with col4:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<span class="metric-label">True Debt</span>', unsafe_allow_html=True)
    st.markdown(f'<span class="metric-value">{debt_pct:.1f}%</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --- Segment Allocation ---
st.markdown('<h2 class="section-title">📈 Segment Allocation</h2>', unsafe_allow_html=True)
seg1, seg2, seg3, seg4 = st.columns(4)
with seg1:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<span class="metric-label">Large Cap</span>', unsafe_allow_html=True)
    st.markdown(f'<span class="metric-value">₹{total_lc/100000:.2f} Lakhs</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
with seg2:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<span class="metric-label">Mid Cap</span>', unsafe_allow_html=True)
    st.markdown(f'<span class="metric-value">₹{total_mc/100000:.2f} Lakhs</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
with seg3:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<span class="metric-label">Small Cap</span>', unsafe_allow_html=True)
    st.markdown(f'<span class="metric-value">₹{total_sc/100000:.2f} Lakhs</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
with seg4:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown('<span class="metric-label">Debt Funds</span>', unsafe_allow_html=True)
    debt_val = sum(f.get("current_value", 0) * f.get("debt", 0) / 100 for f in funds if f.get("category") == "Debt")
    st.markdown(f'<span class="metric-value">₹{debt_val/100000:.2f} Lakhs</span>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# --- Direct vs Regular Plan Analysis ---
st.markdown('<h2 class="section-title">🛡️ Direct vs Regular Plan Audit</h2>', unsafe_allow_html=True)
regular_funds = [f for f in funds if f.get("plan_type") == "Regular"]
direct_funds = [f for f in funds if f.get("plan_type") == "Direct"]
regular_total = sum(f.get("current_value", 0) for f in regular_funds)
direct_total = sum(f.get("current_value", 0) for f in direct_funds)
regular_pct = (regular_total / total_value * 100) if total_value else 0

pcol1, pcol2, pcol3 = st.columns(3)
with pcol1:
    st.metric("Direct Plan Holdings", f"₹{direct_total/100000:.2f} Lakhs", f"{100 - regular_pct:.1f}%")
with pcol2:
    st.metric("Regular Plan Holdings", f"₹{regular_total/100000:.2f} Lakhs", f"{regular_pct:.1f}%", delta_color="inverse")
with pcol3:
    est_10y_commission = regular_total * 0.1046
    st.metric("Est. 10Y Commission Drag", f"₹{est_10y_commission/100000:.2f} Lakhs")

if regular_total > 0:
    st.warning(
        f"⚠️ **Distributor Commission Notice**: You hold **₹{regular_total/100000:.2f} Lakhs** ({regular_pct:.1f}%) "
        f"in Regular mutual fund plans across {len(regular_funds)} schemes. Switching to Direct plans can save ~0.75% to 1.25% p.a. "
        f"in perpetual distributor trail commissions without altering underlying stock/bond holdings."
    )
else:
    st.success("✅ **Fiduciary Best Practice**: 100% of your holdings are in Direct plans. Zero intermediary commission bleed detected.")

# --- Statutory Capital Gains & Tax Audit (CGS) ---
cgs_info = st.session_state.get("cgs_data")
if cgs_info and cgs_info.get("summary"):
    st.markdown('<h2 class="section-title">📑 Capital Gains & Tax Audit (CGS)</h2>', unsafe_allow_html=True)
    s_data = cgs_info.get("summary", {})
    ltcg_val = float(s_data.get("ltcg_inr") or 0.0)
    stcg_val = float(s_data.get("stcg_inr") or 0.0)
    outflows_val = float(s_data.get("total_outflows") or 0.0)
    cost_val = float(s_data.get("total_cost") or 0.0)
    rem_exempt = max(0.0, 125_000.0 - ltcg_val)
    
    cg_c1, cg_c2, cg_c3, cg_c4 = st.columns(4)
    with cg_c1:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Realized LTCG (§112A)</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{ltcg_val:,.0f}</span>', unsafe_allow_html=True)
        st.caption("Long-term equity gains")
        st.markdown('</div>', unsafe_allow_html=True)
    with cg_c2:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Realized STCG (§111A)</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{stcg_val:,.0f}</span>', unsafe_allow_html=True)
        st.caption("Short-term gains @ 20%")
        st.markdown('</div>', unsafe_allow_html=True)
    with cg_c3:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Remaining §112A Headroom</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{rem_exempt:,.0f}</span>', unsafe_allow_html=True)
        st.caption("of ₹1.25 Lakh annual tax-free limit")
        st.markdown('</div>', unsafe_allow_html=True)
    with cg_c4:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">CGS Audit Status</span>', unsafe_allow_html=True)
        st.markdown('<span class="metric-value" style="color:#16a34a;">Verified</span>', unsafe_allow_html=True)
        st.caption(f"Digest: {cgs_info.get('source_sha256', '')[:10]}...")
        st.markdown('</div>', unsafe_allow_html=True)

# --- SAA Target Alignment ---
st.markdown('<h2 class="section-title">🎯 Strategic Asset Allocation (SAA) Drift</h2>', unsafe_allow_html=True)

with st.expander("🔍 Take SEBI Fiduciary Risk Profiler Questionnaire (Market Standard)", expanded=False):
    st.caption("Evaluates Financial Capacity vs. Psychological Loss Tolerance under SEBI IA Regulations.")
    q_c1, q_c2 = st.columns(2)
    with q_c1:
        q_horizon = st.selectbox(
            "1. Primary Investment Time Horizon",
            options=[
                ("Under 3 years (Capital Preservation Priority)", 2.0),
                ("3 to 5 years (Medium Term)", 4.0),
                ("5 to 7 years (Balanced Growth)", 6.0),
                ("7 to 10+ years (Long Term Compounding)", 10.0),
            ],
            format_func=lambda x: x[0],
            index=1,
        )[1]
        q_drop = st.selectbox(
            "2. Maximum Portfolio Drop Tolerated Without Selling",
            options=[
                ("5% or less (Strict Drawdown Ceiling)", 5.0),
                ("6% to 10% (Moderate Fluctuations)", 10.0),
                ("11% to 20% (Substantial Corrections)", 18.0),
                ("20%+ (Deep Bear Market Tolerant)", 30.0),
            ],
            format_func=lambda x: x[0],
            index=0,
        )[1]
        q_emergency = st.selectbox(
            "3. Liquid Savings / Emergency Reserve",
            options=[
                ("Under 3 months of expenses", 2.0),
                ("3 to 6 months of expenses", 4.5),
                ("6 to 12 months of expenses", 9.0),
                ("12+ months of expenses", 12.0),
            ],
            format_func=lambda x: x[0],
            index=3,
        )[1]
    with q_c2:
        q_income = st.selectbox(
            "4. Primary Income Stability",
            options=["Stable (Corporate / Govt / Salaried)", "Variable (Business / Freelance)", "Retired / Fixed Pension"],
            index=0,
        )
        q_emi = st.selectbox(
            "5. Total Debt / EMI Burden (% of monthly income)",
            options=[
                ("Under 20% (Low Debt)", 15.0),
                ("20% to 40% (Moderate Debt)", 30.0),
                ("Over 40% (High Debt)", 50.0),
            ],
            format_func=lambda x: x[0],
            index=0,
        )[1]
        q_exp = st.selectbox(
            "6. Mutual Fund Investment Experience",
            options=["Beginner (< 2 years)", "Moderate (2-5 years)", "Experienced (5+ years through bear markets)"],
            index=2,
        )

    if st.button("📊 Calculate Fiduciary SAA Target", use_container_width=True):
        inc_key = "stable" if "stable" in q_income.lower() else ("variable" if "variable" in q_income.lower() else "retired")
        exp_key = "experienced" if "experienced" in q_exp.lower() else ("moderate" if "moderate" in q_exp.lower() else "beginner")
        st.session_state["fiduciary_profile_result"] = evaluate_fiduciary_profile(
            horizon_years=float(q_horizon),
            max_drawdown_tolerance_pct=float(q_drop),
            emergency_fund_months=float(q_emergency),
            income_stability=inc_key,
            emi_burden_pct=float(q_emi),
            experience_level=exp_key,
        )

if st.session_state.get("fiduciary_profile_result"):
    p_res = st.session_state["fiduciary_profile_result"]
    st.markdown(f"#### 🎯 Fiduciary Assessment: **{p_res.tier_label}**")
    st.caption(f"**Expected Drawdown Range:** {p_res.expected_drawdown_range}")
    rc1, rc2, rc3 = st.columns(3)
    with rc1:
        st.metric("Large-Cap Core", f"{p_res.target_saa.large_cap_pct:.1f}%")
    with rc2:
        st.metric("Mid & Small-Cap Alpha", f"{p_res.target_saa.mid_small_cap_pct:.1f}%")
    with rc3:
        st.metric("Debt & Stability Cushion", f"{p_res.target_saa.debt_pct:.1f}%")
    if p_res.binding_constraints:
        for c in p_res.binding_constraints:
            st.warning(f"🔒 **Binding Limiter:** {c}")
    target_eq = p_res.target_saa.total_equity_pct
    target_debt = p_res.target_saa.debt_pct
    st.caption(f"Applying customized fiduciary SAA target: {target_eq:.1f}% Equity / {target_debt:.1f}% Debt.")
else:
    saa_options = {
        "Conservative (Tier 1 & 2: 30% Equity / 70% Debt)": (30.0, 70.0),
        "Moderate (Tier 3: 60% Equity / 40% Debt)": (60.0, 40.0),
        "Aggressive (Tier 4 & 5: 85% Equity / 15% Debt)": (85.0, 15.0),
        "Very High / Pure Growth (Tier 6: 95% Equity / 5% Debt)": (95.0, 5.0),
    }
    chosen_saa = st.selectbox("Select Target Risk Profile", list(saa_options.keys()), index=2)
    target_eq, target_debt = saa_options[chosen_saa]

eq_drift = eq_pct - target_eq
debt_drift = debt_pct - target_debt

scol1, scol2, scol3 = st.columns(3)
with scol1:
    st.metric("Current Equity", f"{eq_pct:.1f}%", f"{eq_drift:+.1f}% vs Target")
with scol2:
    st.metric("Current True Debt", f"{debt_pct:.1f}%", f"{debt_drift:+.1f}% vs Target")
with scol3:
    if abs(eq_drift) <= 5.0:
        st.info("✅ Portfolio allocation is within ±5% of your SAA target.")
    elif eq_drift > 5.0:
        st.warning(f"⚠️ Overweight Equity by {eq_drift:+.1f}%. Consider rebalancing towards debt/arbitrage.")
    else:
        st.warning(f"⚠️ Underweight Equity by {eq_drift:+.1f}%. Consider deploying incremental SIPs into core equity.")

# --- Fiduciary SIP Decision Support (API Powered) ---
st.markdown('<h2 class="section-title">🎯 Fiduciary SIP Decision Support (API Powered)</h2>', unsafe_allow_html=True)
st.caption("Connected to Mutual Fund SIP Decision Support API. Enforces SEBI fail-closed fiduciary safety boundaries.")

api_col1, api_col2 = st.columns(2)
with api_col1:
    sip_budget = st.number_input(
        "Monthly SIP Budget (₹)",
        min_value=1000.0,
        max_value=10000000.0,
        value=25000.0,
        step=1000.0,
        help="Target monthly capital deployment across direct mutual fund schemes."
    )
with api_col2:
    risk_choice = st.selectbox(
        "Deployment Risk Profile",
        options=["Aggressive", "Moderate", "Conservative"],
        index=0,
        help="Aligned with SEBI SAA asset allocation matrix."
    )

if st.button("🚀 Run Fiduciary SIP Analysis via API", type="primary", use_container_width=True):
    with st.spinner("Executing decision support analysis via API..."):
        uploaded_file.seek(0)
        cas_raw_bytes = uploaded_file.read()
        api_result = request_sip_recommendations(
            cas_bytes=cas_raw_bytes,
            monthly_budget_inr=float(sip_budget),
            risk_profile=risk_choice,
            filename=getattr(uploaded_file, "name", "portfolio.xlsx"),
        )
        st.session_state["api_recommendation_result"] = api_result

if st.session_state.get("api_recommendation_result"):
    res = st.session_state["api_recommendation_result"]
    res_status = res.get("status", "HOLD")
    res_decision = res.get("decision", "NO_ACTION")
    unallocated = res.get("unallocated_budget_inr", sip_budget)
    reasons = res.get("reasons", [])

    st.markdown("### 📋 API Recommendation Result")
    rc1, rc2, rc3 = st.columns(3)
    with rc1:
        st.metric("Fiduciary Status", res_status)
    with rc2:
        st.metric("Decision Branch", res_decision)
    with rc3:
        st.metric("Unallocated Capital", f"₹{unallocated:,.2f}" if unallocated is not None else "₹0.00")

    if reasons:
        st.markdown("**Fiduciary Safeguards & Invariants:**")
        for r in reasons:
            st.info(f"🔒 {r}")

    with st.expander("🔍 View Raw API JSON Contract"):
        st.code(json.dumps(res, indent=2), language="json")

# --- Equity vs Internal Debt Chart ---
st.markdown('<h2 class="section-title">⚖️ Equity vs Internal Debt</h2>', unsafe_allow_html=True)
st.info("💡 Equity funds legally hold internal debt (cash equivalents) for liquidity management. Large Cap funds typically hold ~5% debt, while Flexi/Multi Cap funds hold ~2% debt.")
chart_data = {"Equity": total_eq, "Internal Debt": total_debt}
st.bar_chart(chart_data, use_container_width=True)

# --- Fund-by-Fund Details ---
st.markdown('<h2 class="section-title">📋 Fund Details</h2>', unsafe_allow_html=True)
st.caption("All data parsed dynamically from your uploaded CAS. No hardcoded values.")

tab1, tab2, tab3 = st.tabs(["Equity Funds", "Hybrid Funds", "Debt Funds"])

with tab1:
    equity_funds = [f for f in funds if f.get("category") in ["Equity", "Contra"]]
    if equity_funds:
        for fund in sorted(equity_funds, key=lambda f: f.get("scheme", "")):
            if fund.get("current_value", 0) <= 0:
                continue
            with st.expander(f"{fund['scheme'][:70]} — ₹{fund['current_value']:,.0f}"):
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.markdown(f"**Category:** {fund.get('category', 'Equity')}")
                    st.caption(f"**EQ:** {fund.get('eq', 0):.0f}% | **Debt:** {fund.get('debt', 0):.0f}%")
                    if fund.get("folio_no"):
                        st.caption(f"**Folio:** {fund['folio_no']}")
                with c2:
                    st.markdown(f"**Plan:** {fund.get('plan_type', 'Direct')}")
                    st.caption(f"**Option:** {fund.get('option_type', 'Growth')}")
                    if fund.get("invested_value", 0) > 0:
                        st.caption(f"**Cost:** ₹{fund['invested_value']:,.0f} | **Gain:** {fund.get('gain_pct', 0):+.1f}%")
                with c3:
                    nav_val = fund.get("nav") or 0.0
                    units_val = fund.get("units") or 0.0
                    nav_str = f"₹{nav_val:.4f}" if nav_val > 0 else "N/A"
                    units_str = f"{units_val:.3f}" if units_val > 0 else "N/A"
                    st.markdown(f"**NAV:** {nav_str}")
                    st.caption(f"**Units:** {units_str}")
    else:
        st.info("No equity funds in portfolio.")

with tab2:
    hybrid_funds = [f for f in funds if f.get("category") == "Hybrid"]
    if hybrid_funds:
        for fund in sorted(hybrid_funds, key=lambda f: f.get("scheme", "")):
            if fund.get("current_value", 0) <= 0:
                continue
            with st.expander(f"{fund['scheme'][:70]} — ₹{fund['current_value']:,.0f}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**Debt Allocation:** {fund.get('debt', 0):.0f}%")
                    st.write(f"**Equity Allocation:** {fund.get('eq', 0):.0f}%")
                    if fund.get("folio_no"):
                        st.caption(f"**Folio:** {fund['folio_no']}")
                with c2:
                    nav_val = fund.get("nav") or 0.0
                    units_val = fund.get("units") or 0.0
                    nav_str = f"₹{nav_val:.4f}" if nav_val > 0 else "N/A"
                    units_str = f"{units_val:.3f}" if units_val > 0 else "N/A"
                    st.markdown(f"**NAV:** {nav_str}")
                    st.caption(f"**Units:** {units_str}")
    else:
        st.info("No hybrid funds in portfolio.")

with tab3:
    debt_funds = [f for f in funds if f.get("category") == "Debt"]
    if debt_funds:
        for fund in sorted(debt_funds, key=lambda f: f.get("scheme", "")):
            if fund.get("current_value", 0) <= 0:
                continue
            with st.expander(f"{fund['scheme'][:70]} — ₹{fund['current_value']:,.0f}"):
                c1, c2 = st.columns(2)
                with c1:
                    st.write(f"**Plan:** {fund.get('plan_type', 'Direct')} | **Option:** {fund.get('option_type', 'Growth')}")
                    if fund.get("folio_no"):
                        st.caption(f"**Folio:** {fund['folio_no']}")
                with c2:
                    nav_val = fund.get("nav") or 0.0
                    units_val = fund.get("units") or 0.0
                    nav_str = f"₹{nav_val:.4f}" if nav_val > 0 else "N/A"
                    units_str = f"{units_val:.3f}" if units_val > 0 else "N/A"
                    st.markdown(f"**NAV:** {nav_str}")
                    st.caption(f"**Units:** {units_str}")
    else:
        st.info("No debt funds in portfolio.")

# --- Export Clean Portfolio ---
st.markdown('<h2 class="section-title">📥 Export Clean Portfolio</h2>', unsafe_allow_html=True)
ecol1, ecol2 = st.columns(2)
with ecol1:
    st.download_button(
        label="📄 Download Clean CSV",
        data=export_portfolio_csv(funds, st.session_state["portfolio_metadata"]),
        file_name="cas_portfolio_clean.csv",
        mime="text/csv",
        use_container_width=True,
    )
with ecol2:
    st.download_button(
        label="📦 Download Clean JSON",
        data=export_portfolio_json(funds, st.session_state["portfolio_metadata"]),
        file_name="cas_portfolio_clean.json",
        mime="application/json",
        use_container_width=True,
    )

# --- Disclaimer ---
st.markdown("---", unsafe_allow_html=True)
st.markdown("""
<div class="disclaimer-box">
<b>📝 Disclaimer:</b> This portfolio analysis is for informational purposes only. 
All values are parsed directly from your uploaded CAS file. 
This is not financial advice. Always consult with a qualified financial advisor 
before making investment decisions.
</div>
""", unsafe_allow_html=True)
st.caption("Data source: Dynamically parsed from your uploaded CAS file. Reference metrics from AMFI factsheets.")
