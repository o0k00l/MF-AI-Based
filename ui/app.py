"""Portfolio Dashboard — CAS-upload-only Intake & Audit.

NO HARDCODING ALLOWED. Every user uploads their own CAS file.
No demo data. No sample portfolios. No hardcoded fund names or values.
If no CAS is uploaded, the app shows a prompt to upload one.
"""
from __future__ import annotations

import json
from pathlib import Path

_sys = __import__("sys")
_this_file = Path(__file__).resolve() if "__file__" in globals() else Path.cwd()
_REPO_ROOT = None
for _cand in [_this_file.parent, _this_file.parent.parent, _this_file.parent.parent.parent, Path.cwd()]:
    if (_cand / "services").is_dir() and (_cand / "data").is_dir():
        _REPO_ROOT = str(_cand)
        break
if not _REPO_ROOT:
    _REPO_ROOT = str(Path.cwd())
if _REPO_ROOT in _sys.path:
    _sys.path.remove(_REPO_ROOT)
_sys.path.insert(0, _REPO_ROOT)

# Invalidate stale in-memory cached modules from previous hot reloads
for _k in list(_sys.modules.keys()):
    if _k == "services" or _k.startswith("services."):
        del _sys.modules[_k]

import streamlit as st

try:
    from services.cas_parser import parse_cas_file
    from services.ai_fund_classifier import enrich_funds_with_ai, classify_fund_with_ai, generate_fiduciary_ai_narrative
    from services.sip_api_client import get_api_health, request_sip_recommendations
    from services.risk_profiler import evaluate_fiduciary_profile
    from services.cgs_parser import parse_cgs_file
    from services.fiduciary_engine import generate_fiduciary_sip_blueprint, evaluate_portfolio_saa_audit, evaluate_fiduciary_lumpsum_blueprint
    from services.sidebar import render_fiduciary_sidebar
except BaseException as _startup_exc:
    st.error(f"⚠️ Service Engine Startup Notice: {type(_startup_exc).__name__}: {_startup_exc}")
    st.info(f"Target Repository Path: {_REPO_ROOT}")
    st.stop()

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
if "api_health" not in st.session_state:
    st.session_state["api_health"] = None
if "cgs_data" not in st.session_state:
    st.session_state["cgs_data"] = None
# Initialize fiduciary/SAA related session state keys
if "saa_target" not in st.session_state:
    st.session_state["saa_target"] = None
if "risk_tier" not in st.session_state:
    st.session_state["risk_tier"] = None
if "user_risk_score" not in st.session_state:
    st.session_state["user_risk_score"] = None
if "deterministic_sip_plan" not in st.session_state:
    st.session_state["deterministic_sip_plan"] = None
if "lumpsum_plan_result" not in st.session_state:
    st.session_state["lumpsum_plan_result"] = None
if "goals_allocation" not in st.session_state:
    st.session_state["goals_allocation"] = None
if "sip_blueprint_result" not in st.session_state:
    st.session_state["sip_blueprint_result"] = None
if "sip_budget" not in st.session_state:
    st.session_state["sip_budget"] = 25000.0
if "risk_bucket" not in st.session_state:
    st.session_state["risk_bucket"] = None

# Ensure downstream contracts: read risk keys
_active_user_risk_score = st.session_state.get("user_risk_score")
_active_risk_tier = st.session_state.get("risk_tier")

# --- Render Unified Advisory Flow Sidebar (Zero Double Coding) ---
render_fiduciary_sidebar(current_page="app.py")

# --- Helper Functions ---
def format_inr(val: float | int) -> str:
    """Format a number in Indian currency style."""
    if val >= 10000000:
        return f"₹{val / 10000000:.2f} Cr"
    elif val >= 100000:
        return f"₹{val / 100000:.2f} L"
    return f"₹{val:,.0f}"

def format_crores(val: float | int) -> str:
    """Format a number in Crores."""
    return f"₹{val / 10000000:.2f} Cr"

# --- Custom CSS for Clean, Professional Styling ---
st.markdown("""
<style>
    .metric-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 10px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    .metric-label {
        font-size: 0.78rem;
        color: #64748b;
        text-transform: uppercase;
        font-weight: 600;
        letter-spacing: 0.04em;
    }
    .metric-value {
        font-size: 1.55rem;
        font-weight: 700;
        color: #0f172a;
        margin-top: 4px;
        display: block;
    }
    .section-title {
        font-size: 1.15rem;
        font-weight: 700;
        color: #0f172a;
        margin-top: 18px;
        margin-bottom: 10px;
        border-bottom: 2px solid #e2e8f0;
        padding-bottom: 6px;
    }
    .banner-intake {
        background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%);
        color: white;
        padding: 18px 22px;
        border-radius: 10px;
        margin-bottom: 18px;
    }
</style>
""", unsafe_allow_html=True)

# --- Page Title Banner ---
st.markdown("""
<div class="banner-intake">
    <div style="font-size: 0.8rem; text-transform: uppercase; color: #38bdf8; letter-spacing: 0.08em; font-weight: 600;">Step 1: Portfolio Intake & Institutional Audit</div>
    <h1 style="margin: 4px 0 6px 0; color: white; font-size: 1.85rem; font-weight: 800;">Fiduciary Portfolio Diagnostic Dashboard</h1>
    <p style="margin: 0; color: #cbd5e1; font-size: 0.92rem;">Audit true underlying equity/debt exposure, eliminate distributor commission leakage, and establish your mathematical strategic asset allocation.</p>
</div>
""", unsafe_allow_html=True)

# --- Dual Mandatory Statement Ingestion (CAS & CGS) ---
st.markdown('<h2 class="section-title">📂 Upload Statements (CAS & CGS Required)</h2>', unsafe_allow_html=True)

upload_c1, upload_c2 = st.columns(2)
with upload_c1:
    st.markdown("##### 1. Consolidated Account Statement (CAS)")
    uploaded_file = st.file_uploader(
        "Upload CAS PDF or Excel Statement",
        type=["pdf", "xlsx", "xls"],
        help="Upload your CAMS / KFintech monthly CAS statement",
        key="cas_uploader_input",
    )
    pdf_password = st.text_input(
        "CAS PDF Password (if encrypted)",
        type="password",
        help="Usually your PAN (uppercase) or date of birth per CAMS/KFintech instructions",
        key="cas_pdf_password_input",
    )

with upload_c2:
    st.markdown("##### 2. Capital Gains Statement (CGS)")
    cgs_file = st.file_uploader(
        "Upload CGS Excel Statement (Optional for Gains Audit)",
        type=["xlsx", "xls"],
        help="Upload your CAMS / KFintech Capital Gains Statement for statutory tax audit",
        key="cgs_uploader_input",
    )
    st.caption("🔒 100% Client-Side Privacy: Statement data remains strictly local in session memory. No data is stored or logged.")

# --- Parse Uploaded Statements ---
funds = []
has_session_data = len(st.session_state["user_portfolio"]) > 0

if uploaded_file is not None:
    try:
        content = uploaded_file.read()
        # parse_cas_file expects a BinaryIO-compatible object (bytes or file-like)
        parsed_funds = parse_cas_file(content)

        if not parsed_funds:
            st.warning("⚠️ No mutual fund folios detected in this statement. Please ensure it is a valid CAS statement.")
            st.stop()

        enriched_funds = enrich_funds_with_ai(parsed_funds)
        st.session_state["user_portfolio"] = enriched_funds
        st.session_state["portfolio_metadata"] = {
            "upload_time": str(__import__("datetime").datetime.now()),
            "upload_source": uploaded_file.name,
            "fund_count": len(enriched_funds),
            "total_value": sum(f.get("current_value", 0) for f in enriched_funds),
            "validation_status": "parsed_successfully",
        }
        funds = enriched_funds
        st.session_state["ai_portfolio_narrative"] = None

    except Exception as exc:
        st.error(f"❌ Error processing statement '{uploaded_file.name}': {exc}")
        st.stop()

    if cgs_file is not None:
        try:
            cgs_content = cgs_file.read()
            cgs_result = parse_cgs_file(cgs_content)
            st.session_state["cgs_data"] = cgs_result
        except Exception as cgs_exc:
            st.warning(f"⚠️ CGS Statement could not be fully parsed: {cgs_exc}")

elif has_session_data:
    funds = enrich_funds_with_ai(st.session_state["user_portfolio"])
    src_name = st.session_state.get("portfolio_metadata", {}).get("upload_source", "uploaded CAS")
    st.info(f"📂 **Active Statements Loaded:** Retaining **{len(funds)}** active funds from `{src_name}`.")
else:
    st.info("⬆️ **Please upload your Consolidated Account Statement (CAS)** above to generate your fiduciary audit.")
    st.stop()

# --- Compute Portfolio Metrics Dynamically (Zero Hardcoding) ---
total_value = sum(f.get("current_value", 0) for f in funds)
total_invested = sum(f.get("invested_value", 0) for f in funds)
total_gain = (total_value - total_invested) if total_invested > 0 else 0.0
gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else 0.0

total_eq = sum(f.get("current_value", 0) * f.get("eq", 0) / 100 for f in funds)
total_debt = sum(f.get("current_value", 0) * f.get("debt", 0) / 100 for f in funds)
total_lc = sum(f.get("current_value", 0) * f.get("lc", 0) / 100 for f in funds)
total_mc = sum(f.get("current_value", 0) * f.get("mc", 0) / 100 for f in funds)
total_sc = sum(f.get("current_value", 0) * f.get("sc", 0) / 100 for f in funds)
total_gold = sum(f.get("current_value", 0) * f.get("gold", 0) / 100 for f in funds)
total_intl = sum(f.get("current_value", 0) * f.get("intl", 0) / 100 for f in funds)

eq_pct = (total_eq / total_value * 100) if total_value else 0.0
debt_pct = (total_debt / total_value * 100) if total_value else 0.0

# Group by canonical underlying strategy to distinguish unique schemes from duplicate plan variants
canonical_schemes = {}
for f in funds:
    c_name = f.get("canonical_scheme") or f.get("scheme", "")
    canonical_schemes.setdefault(c_name, []).append(f)

unique_strategies_count = len(canonical_schemes)
total_plan_holdings = len(funds)
dual_holding_schemes = {c_name: flist for c_name, flist in canonical_schemes.items() if len(flist) > 1}
dual_count = len(dual_holding_schemes)

# Regular plan leakage metrics
regular_holdings = [f for f in funds if str(f.get("plan_type", "Direct")).upper() == "REGULAR"]
regular_total = sum(f.get("current_value", 0) for f in regular_holdings)
regular_pct = (regular_total / total_value * 100) if total_value else 0.0
total_annual_bleed = sum(f.get("annual_commission_bleed", 0.0) for f in regular_holdings)
total_10y_linear = sum(f.get("ten_year_linear_commission", 0.0) for f in regular_holdings)
total_10y_compounded = sum(f.get("ten_year_compounded_drag", 0.0) for f in regular_holdings)

# --- Intuitive 3-Tab Structure (Eliminates Visual Clutter & Complexity) ---
tab_audit, tab_ai_tax, tab_blueprint = st.tabs([
    "📊 Portfolio Audit & Holdings",
    "🤖 AI Fiduciary Health & Tax",
    "🎯 SAA Drift & Capital Blueprint",
])

with tab_audit:
    # 1. Overview KPI Cards
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Active Schemes</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">{unique_strategies_count} Funds</span>', unsafe_allow_html=True)
        if dual_count > 0:
            st.caption(f"{total_plan_holdings} Plan Folios ({dual_count} dual Regular+Direct)")
        else:
            st.caption(f"{total_plan_holdings} Plan Folios (0 duplicate overlaps)")
        st.markdown('</div>', unsafe_allow_html=True)

    with col2:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Current Value</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{total_value/100000:.2f} Lakhs</span>', unsafe_allow_html=True)
        if total_invested > 0:
            st.caption(f"Cost: ₹{total_invested/100000:.2f}L | Gain: {gain_pct:+.1f}% (+₹{total_gain/100000:.2f}L)")
        st.markdown('</div>', unsafe_allow_html=True)

    with col3:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Net Equity Allocation</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">{eq_pct:.1f}%</span>', unsafe_allow_html=True)
        st.caption(f"₹{total_eq/100000:.2f}L authentic look-through")
        st.markdown('</div>', unsafe_allow_html=True)

    with col4:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">True Debt & Cash Buffer</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">{debt_pct:.1f}%</span>', unsafe_allow_html=True)
        debt_sources = [f for f in funds if f.get("debt", 0) > 0]
        st.caption(f"₹{total_debt/100000:.2f}L unbundled liquidity ({len(debt_sources)} schemes)")
        st.markdown('</div>', unsafe_allow_html=True)

    # 2. Market Cap & Segment Allocation
    st.markdown("##### 📈 Market Cap & Asset Class Look-Through")
    seg1, seg2, seg3, seg4 = st.columns(4)
    with seg1:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Large Cap</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{total_lc/100000:.2f}L</span>', unsafe_allow_html=True)
        st.caption(f"{(total_lc/total_value*100):.1f}% of portfolio")
        st.markdown('</div>', unsafe_allow_html=True)
    with seg2:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Mid Cap</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{total_mc/100000:.2f}L</span>', unsafe_allow_html=True)
        st.caption(f"{(total_mc/total_value*100):.1f}% of portfolio")
        st.markdown('</div>', unsafe_allow_html=True)
    with seg3:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">Small Cap</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{total_sc/100000:.2f}L</span>', unsafe_allow_html=True)
        st.caption(f"{(total_sc/total_value*100):.1f}% of portfolio")
        st.markdown('</div>', unsafe_allow_html=True)
    with seg4:
        st.markdown('<div class="metric-card">', unsafe_allow_html=True)
        st.markdown('<span class="metric-label">True Debt & Liquid Cash</span>', unsafe_allow_html=True)
        st.markdown(f'<span class="metric-value">₹{total_debt/100000:.2f}L</span>', unsafe_allow_html=True)
        st.caption(f"{(total_debt/total_value*100):.1f}% (Bonds, T-Bills, TREPS)")
        st.markdown('</div>', unsafe_allow_html=True)

    with st.expander("🔍 Scheme-by-Scheme Segment Allocation (Actual Factsheet Look-Through)", expanded=False):
        st.caption("Actual underlying market capitalization and stability asset look-through audited scheme-by-scheme per AMC disclosures and regulatory filings.")
        seg_rows = []
        for sf in sorted(funds, key=lambda x: -x.get("current_value", 0)):
            c_val = sf.get("current_value", 0)
            if c_val <= 0:
                continue
            seg_rows.append({
                "Scheme": sf.get("scheme", "")[:45],
                "Mandate": sf.get("scheme_type", sf.get("category", "")),
                "Large Cap": f"{sf.get('lc', 0):.1f}% (₹{c_val * sf.get('lc', 0) / 10000000:.2f}L)",
                "Mid Cap": f"{sf.get('mc', 0):.1f}% (₹{c_val * sf.get('mc', 0) / 10000000:.2f}L)",
                "Small Cap": f"{sf.get('sc', 0):.1f}% (₹{c_val * sf.get('sc', 0) / 10000000:.2f}L)",
                "Debt / Cash": f"{sf.get('debt', 0):.1f}% (₹{c_val * sf.get('debt', 0) / 10000000:.2f}L)",
                "Provenance": sf.get("classification_source", "AMC Factsheet Look-Through"),
            })
        if seg_rows:
            st.dataframe(seg_rows, use_container_width=True, hide_index=True)

    # 2.1 Factor-Aware Attribution & Concentration Index
    from services.ai_fund_classifier import evaluate_factor_attribution
    factor_res = evaluate_factor_attribution(funds)
    if factor_res.get("status") == "ANALYZED":
        st.markdown("##### 🔬 Factor-Aware Style Attribution & Concentration Index")
        fac1, fac2, fac3, fac4 = st.columns(4)
        tilts = factor_res.get("factor_tilts", {})
        with fac1:
            st.metric("Quality Core", f"{tilts.get('quality_large_core_pct', 0.0):.1f}%", "Large-cap index & bluechips")
        with fac2:
            st.metric("Momentum Alpha", f"{tilts.get('momentum_alpha_pct', 0.0):.1f}%", "Mid/Small & thematic engines")
        with fac3:
            st.metric("Value & Contra", f"{tilts.get('value_contra_pct', 0.0):.1f}%", "Deep-value & high-yield")
        with fac4:
            hhi = factor_res.get("hhi_score", 0.0)
            rating = factor_res.get("diversification_rating", "N/A").replace("_", " ").title()
            st.metric("Concentration (HHI)", f"{hhi:,.0f}", rating)

        if factor_res.get("exit_signals"):
            with st.expander(f"🚨 Fiduciary Exit & Pruning Signals ({len(factor_res['exit_signals'])} Actionable Alerts)", expanded=False):
                for sig in factor_res["exit_signals"]:
                    badge = "🛑 [CRITICAL ACTION]" if sig.get("severity") == "HIGH" else "⚠️ [REBALANCE]"
                    saving_note = f" (Saves ₹{sig.get('annual_saving_inr', 0):,.0f}/yr)" if sig.get("annual_saving_inr") else ""
                    st.markdown(f"**{badge} {sig.get('scheme')}** — `{sig.get('action')}`{saving_note}")
                    st.caption(sig.get("rationale", ""))

    # 3. Direct vs Regular Plan Audit
    st.markdown("##### 🛡️ Distributor Commission Drag & Direct Plan Audit")
    if regular_total > 0:
        reg_c1, reg_c2, reg_c3 = st.columns(3)
        with reg_c1:
            st.metric("Regular Plan Exposure", f"₹{regular_total/100000:.2f}L", f"{regular_pct:.1f}% of wealth")
        with reg_c2:
            st.metric("Annual Distributor Bleed", f"₹{total_annual_bleed:,.0f} / yr", "Trailing fee drag", delta_color="inverse")
        with reg_c3:
            st.metric("10-Year Compounded Drag", f"₹{total_10y_compounded:,.0f}", "@ 12% CAGR wealth drag", delta_color="inverse")

        if dual_count > 0:
            st.warning(f"🚨 **Scheme Duplication Alert:** You hold **{dual_count} mutual fund strategies** in BOTH Regular and Direct plans simultaneously. Consolidate these units to stop immediate commission bleed.")

        with st.expander("🔍 View Identified Regular Plan Schemes & TER Breakdown", expanded=False):
            st.markdown("| Scheme Name | Current Value | Direct TER | Regular TER | Trail Commission | Annual Bleed |")
            st.markdown("| :--- | :--- | :--- | :--- | :--- | :--- |")
            for rf in regular_holdings:
                st.markdown(f"| {rf.get('scheme')} | ₹{rf.get('current_value', 0):,.0f} | {rf.get('ter_direct', 0):.2f}% | {rf.get('ter_regular', 0):.2f}% | {rf.get('trail_commission_pct', 0):.2f}% | ₹{rf.get('annual_commission_bleed', 0):,.0f}/yr |")
    else:
        st.success("✅ **100% Direct Plan Compliance:** Entire portfolio is invested in Direct plans. Zero intermediary commission leakage detected.")

    # 4. Scheme-by-Scheme Holdings Table
    st.markdown("##### 📋 Fund Holdings Look-Through")
    filter_search = st.text_input("Filter funds by name or AMC", "", key="holdings_search_query")
    filtered_funds = [f for f in funds if filter_search.lower() in str(f.get("scheme", "")).lower()] if filter_search else funds

    table_data = []
    for f in filtered_funds:
        table_data.append({
            "Scheme Name": f.get("scheme", ""),
            "Category": f.get("category", ""),
            "Plan": f.get("plan_type", "Direct"),
            "Current Value (₹)": f"₹{f.get('current_value', 0):,.0f}",
            "Equity %": f"{f.get('eq', 0):.1f}%",
            "Debt %": f"{f.get('debt', 0):.1f}%",
            "Direct TER": f"{f.get('ter_direct', 0):.2f}%",
            "Benchmark": f.get("benchmark", ""),
        })
    st.dataframe(table_data, use_container_width=True)

with tab_ai_tax:
    # 1. AI Executive Fiduciary Portfolio Diagnosis
    st.markdown("##### 🤖 Institutional AI Fiduciary Diagnosis")
    st.caption("Deep institutional synthesis across asset allocation drift, distributor commission bleed, and folio consolidation.")

    ai_c1, ai_c2 = st.columns([3, 1])
    with ai_c1:
        st.markdown("Generate a personalized fiduciary assessment combining live AI analysis with official SEBI & AMFI statutory benchmarks.")
    with ai_c2:
        gen_ai_btn = st.button("🧠 Synthesize Diagnosis", use_container_width=True)

    portfolio_metrics_summary = {
        "total_value": total_value,
        "total_invested": total_invested,
        "eq_pct": eq_pct,
        "debt_pct": debt_pct,
        "gold_pct": (total_gold / total_value * 100.0) if total_value else 0.0,
        "intl_pct": (total_intl / total_value * 100.0) if total_value else 0.0,
        "regular_value": regular_total,
        "regular_pct": regular_pct,
        "annual_bleed": total_annual_bleed,
        "compounded_10y_drag": total_10y_compounded,
        "unique_strategies_count": unique_strategies_count,
        "dual_count": dual_count,
    }

    if gen_ai_btn or st.session_state.get("ai_portfolio_narrative"):
        if gen_ai_btn:
            with st.spinner("Synthesizing institutional fiduciary diagnostic..."):
                st.session_state["ai_portfolio_narrative"] = generate_fiduciary_ai_narrative(
                    portfolio_metrics=portfolio_metrics_summary,
                    funds=funds,
                    target_saa=st.session_state.get("saa_target"),
                    use_live_ai=True,
                )

        diag = st.session_state.get("ai_portfolio_narrative")
        if diag:
            st.markdown(f'''
            <div style="background: #f8fafc; border: 1px solid #cbd5e1; border-left: 5px solid #2563eb; border-radius: 8px; padding: 16px 20px; margin: 12px 0;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-size: 0.82rem; font-weight: 700; color: #1e40af; text-transform: uppercase;">Fiduciary Provenance</span>
                    <span style="background: #dbeafe; color: #1e40af; font-size: 0.75rem; font-weight: 600; padding: 3px 10px; border-radius: 12px;">{diag.get("source", "SEBI Statutory Rule")}</span>
                </div>
            ''', unsafe_allow_html=True)
            st.markdown(diag.get("content", ""))
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    # 2. Capital Gains & Tax Optimization (CGS)
    st.markdown("##### 📑 Capital Gains & Tax Harvesting Optimization")
    cgs_info = st.session_state.get("cgs_data")
    if cgs_info and cgs_info.get("summary"):
        cg_s = cgs_info["summary"]
        ltcg = float(cg_s.get("ltcg_inr") or 0.0)
        stcg = float(cg_s.get("stcg_inr") or 0.0)
        rem_headroom = max(0.0, 125000.0 - ltcg)

        tax_c1, tax_c2, tax_c3 = st.columns(3)
        with tax_c1:
            st.metric("Realized LTCG (§112A)", f"₹{ltcg:,.2f}")
        with tax_c2:
            st.metric("Realized STCG (§111A)", f"₹{stcg:,.2f}")
        with tax_c3:
            st.metric("§112A Annual Headroom", f"₹{rem_headroom:,.2f}", f"of ₹1.25L Tax-Free Limit")

        from services.cgs_parser import evaluate_tax_harvesting_strategy
        tax_adv = evaluate_tax_harvesting_strategy(cgs_info, funds, use_live_ai=False)
        if tax_adv.get("status") == "ANALYZED":
            st.markdown(f"💡 **Section 112A Tax Harvesting:** You have **₹{tax_adv.get('harvestable_amount_inr', 0):,.0f}** in harvestable unrealized equity gains saving up to **₹{tax_adv.get('potential_tax_saving_inr', 0):,.0f}** tax.")
            for rec in tax_adv.get("rebalancing_recommendations", []):
                st.info(f"👉 {rec}")
    else:
        st.info("ℹ️ Upload your Capital Gains Statement (CGS) above to unlock Section 112A tax harvesting, capital loss utilization, and zero-tax Regular-to-Direct switching strategies.")

    st.markdown("---")
    # 3. Interactive AI Fiduciary Assistant
    st.markdown("##### 💬 Interactive AI Fiduciary Assistant")
    st.caption("Ask natural language queries about your portfolio, fee leakage, tax harvesting, or rebalancing priorities.")

    quick_cols = st.columns(5)
    preset_q = None
    with quick_cols[0]:
        if st.button("💸 Fee Bleed?", use_container_width=True):
            preset_q = "What is my total annual distributor fee bleed and 10-year compounded drag?"
    with quick_cols[1]:
        if st.button("📊 Segments?", use_container_width=True):
            preset_q = "What is my authentic Large Cap, Mid Cap, and Small Cap segment allocation across funds?"
    with quick_cols[2]:
        if st.button("⚖️ SAA Drift?", use_container_width=True):
            preset_q = "What is my current net equity vs debt drift against my target SAA?"
    with quick_cols[3]:
        if st.button("📑 Tax Harvesting?", use_container_width=True):
            preset_q = "How can I harvest capital gains tax-free under Section 112A this year?"
    with quick_cols[4]:
        if st.button("🚨 Pruning Signals?", use_container_width=True):
            preset_q = "Which funds should I exit or consolidate first to stop commission leakage?"

    from services.ai_fund_classifier import answer_fiduciary_query
    user_query = st.text_input("Ask anything about your mutual fund portfolio:", value=preset_q if preset_q else "", placeholder="e.g. How much trail commission am I losing in regular funds every year?", key="fiduciary_nl_query_box")

    if user_query:
        with st.spinner("Analyzing portfolio facts per SEBI statutory rules..."):
            qa_res = answer_fiduciary_query(
                query=user_query,
                portfolio_metrics=portfolio_metrics_summary,
                funds=funds,
                target_saa=st.session_state.get("saa_target"),
                use_live_ai=True,
            )
            st.markdown(f"""
            <div style="background: #f0fdf4; border: 1px solid #86efac; border-left: 5px solid #16a34a; border-radius: 8px; padding: 14px 18px; margin: 10px 0;">
                <div style="font-size: 0.78rem; font-weight: 700; color: #15803d; text-transform: uppercase; margin-bottom: 6px;">
                    🤖 {qa_res.get('source', 'Statutory Fiduciary Intelligence')}
                </div>
                <div style="color: #14532d; font-size: 0.95rem; line-height: 1.6;">
            """, unsafe_allow_html=True)
            st.markdown(qa_res.get("response", ""))
            st.markdown("</div></div>", unsafe_allow_html=True)

with tab_blueprint:
    # 1. SAA Target Alignment & Drift
    st.markdown("##### 🎯 Strategic Asset Allocation (SAA) Alignment")
    saa_options = {
        "Conservative (Tier 1 & 2: 30% Equity / 70% Debt)": (30.0, 70.0),
        "Moderate (Tier 3: 60% Equity / 40% Debt)": (60.0, 40.0),
        "Aggressive (Tier 4 & 5: 85% Equity / 15% Debt)": (85.0, 15.0),
        "Very High / Pure Growth (Tier 6: 95% Equity / 5% Debt)": (95.0, 5.0),
    }

    # Preset selection from session state if available
    preset_idx = 2
    if st.session_state.get("risk_tier"):
        rt = str(st.session_state.get("risk_tier", ""))
        if "TIER_1" in rt or "TIER_2" in rt:
            preset_idx = 0
        elif "TIER_3" in rt:
            preset_idx = 1
        elif "TIER_6" in rt:
            preset_idx = 3

    chosen_saa = st.selectbox("Select Target Risk Profile", list(saa_options.keys()), index=preset_idx)
    target_eq, target_debt = saa_options[chosen_saa]

    if "Conservative" in chosen_saa:
        st.session_state["saa_target"] = {"total_equity_pct": 30.0, "large_cap_pct": 20.0, "mid_small_cap_pct": 10.0, "debt_pct": 70.0}
        st.session_state["risk_tier"] = "TIER_2_LOW"
    elif "Moderate" in chosen_saa:
        st.session_state["saa_target"] = {"total_equity_pct": 60.0, "large_cap_pct": 40.0, "mid_small_cap_pct": 20.0, "debt_pct": 40.0}
        st.session_state["risk_tier"] = "TIER_3_MODERATE"
    elif "Very High" in chosen_saa:
        st.session_state["saa_target"] = {"total_equity_pct": 95.0, "large_cap_pct": 55.0, "mid_small_cap_pct": 40.0, "debt_pct": 5.0}
        st.session_state["risk_tier"] = "TIER_6_VERY_HIGH"
    else:
        st.session_state["saa_target"] = {"total_equity_pct": 85.0, "large_cap_pct": 50.0, "mid_small_cap_pct": 35.0, "debt_pct": 15.0}
        st.session_state["risk_tier"] = "TIER_4_MODERATE_HIGH"

    # Get target SAA from session state for drift calculation
    saa_tgt = st.session_state.get("saa_target", {})
    if saa_tgt:
        target_eq = saa_tgt.get("total_equity_pct", 0.0)
        target_debt = saa_tgt.get("debt_pct", 0.0)
    else:
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
            st.info("✅ Portfolio is within ±5% of your SAA target.")
        elif eq_drift > 5.0:
            st.warning(f"⚠️ Overweight Equity by {eq_drift:+.1f}%. Direct incremental capital to stability buffers.")
        else:
            st.warning(f"⚠️ Underweight Equity by {abs(eq_drift):.1f}%. Deploy incremental SIPs into core equity.")

    st.caption("Need a formal suitability assessment? Visit the dedicated [Risk Profiler & SAA Page](pages/2_Risk_Profiler.py) for the complete 6-question SEBI test.")

    st.markdown("---")
    # 2. Fiduciary SIP Recommendation Blueprint
    st.markdown("##### 🚀 Fiduciary SIP Recommendation Blueprint")
    st.caption("100% Direct Plan compliance with bi-weekly optimal tranche timing and portfolio completion alerts.")

    sip_budget_val = st.number_input("Monthly SIP Investment Budget (₹)", min_value=1000.0, max_value=10000000.0, value=25000.0, step=1000.0)

    if st.button("Generate Fiduciary SIP Blueprint", type="primary", use_container_width=True):
        with st.spinner("Generating deterministic SIP blueprint..."):
            bp = generate_fiduciary_sip_blueprint(monthly_budget_inr=sip_budget_val, target_saa=st.session_state.get("saa_target"), funds=funds)
            st.session_state["sip_blueprint_result"] = bp

    sip_res = st.session_state.get("sip_blueprint_result")
    if sip_res:
        if sip_res.get("optimal_tranche_timing"):
            tt = sip_res["optimal_tranche_timing"]
            st.markdown(f"📅 **Optimal Cadence:** {tt.get('recommended_cadence')} (₹{float(tt.get('biweekly_amount_inr', 0)):,.0f} per tranche on the {', '.join(str(d) for d in tt.get('suggested_execution_dates_of_month', []))}th).")

        if sip_res.get("portfolio_completion_alerts"):
            for al in sip_res["portfolio_completion_alerts"]:
                st.warning(f"⚠️ **Gap Detected:** {al.get('slot')} is under-represented. {al.get('action')}")

        st.markdown("| Mandate Slot | Scheme Recommendation | Category | Plan | Monthly SIP | Allocation |")
        st.markdown("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for rec in sip_res.get("recommendations", []):
            st.markdown(f"| {rec.get('slot_name')} | **{rec.get('scheme_name')}** | {rec.get('category')} | {rec.get('plan_type')} | ₹{float(rec.get('monthly_allocation_inr', 0)):,.0f} | {float(rec.get('allocation_pct', 0)):.1f}% |")

    st.markdown("---")
    # 3. Lump-Sum Capital Deployment & Systematic Transfer Plan (STP)
    st.markdown("##### 💰 Lump-Sum Capital Deployment & STP Waterfall")
    st.caption("Systematically mitigates entry timing risk via automated staging from high-grade parking vehicles.")

    lump_c1, lump_c2 = st.columns(2)
    with lump_c1:
        lump_in = st.number_input("Lump-Sum Capital Available (₹)", min_value=10000.0, max_value=100000000.0, value=500000.0, step=25000.0)
    with lump_c2:
        stp_months = st.slider("STP Staging Horizon (Months)", min_value=3, max_value=12, value=6, step=1)

    if st.button("Generate Lump-Sum STP Plan", use_container_width=True):
        with st.spinner("Computing staging waterfall..."):
            l_plan = evaluate_fiduciary_lumpsum_blueprint(
                lumpsum_amount_inr=float(lump_in),
                stp_duration_months=int(stp_months),
                target_saa=st.session_state.get("saa_target"),
                funds=funds,
            )
            st.session_state["lumpsum_plan_result"] = l_plan

    lp = st.session_state.get("lumpsum_plan_result")
    if lp:
        st.markdown(f"🛡️ **Staging Strategy:** Park capital in a zero-exit-load Direct liquid/arbitrage vehicle and stage ₹{float(lp.get('monthly_stp_amount_inr', 0)):,.0f}/month across equity sleeves over {stp_months} months.")

    st.markdown("---")
    # 4. Monte Carlo Wealth Accumulation Stochastic Simulation
    st.markdown("##### 🎲 Monte Carlo Wealth Accumulation Stochastic Simulation")
    st.caption("Simulates 1,000 randomized market trajectories to calculate your statistical probability of goal achievement.")
    from services.goal_planner import run_monte_carlo_goal_simulation
    mc_c1, mc_c2 = st.columns(2)
    with mc_c1:
        target_corpus_goal = st.number_input("Target Corpus Goal (₹)", min_value=100000.0, max_value=500000000.0, value=10000000.0, step=500000.0)
    with mc_c2:
        goal_horizon = st.slider("Goal Horizon (Years)", min_value=1, max_value=30, value=15, step=1)

    mc_sim = run_monte_carlo_goal_simulation(
        monthly_sip_inr=float(sip_budget_val),
        target_corpus_inr=float(target_corpus_goal),
        horizon_years=int(goal_horizon),
        existing_corpus_inr=float(total_value),
        equity_pct=float(target_eq),
        num_trials=1000,
    )
    if mc_sim.get("status") == "SIMULATED":
        prob = mc_sim.get("probability_of_success_pct", 0.0)
        mc_m1, mc_m2, mc_m3 = st.columns(3)
        with mc_m1:
            st.metric("Success Probability", f"{prob:.1f}%", "Historical market paths")
        with mc_m2:
            st.metric("Median Corpus (P50)", f"₹{mc_sim.get('p50_corpus_inr', 0)/100000:.2f}L", "Expected compounding")
        with mc_m3:
            st.metric("Severe Bear Market (P05)", f"₹{mc_sim.get('p05_corpus_inr', 0)/100000:.2f}L", "Left-tail stress test")
        st.info(f"💡 **Fiduciary Monte Carlo Guidance:** {mc_sim.get('recommended_action', '')}")

# --- Step 2 Transition Banner ---
st.markdown("---")
st.markdown('''
<div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); color: white; padding: 20px 24px; border-radius: 12px; margin-top: 15px; margin-bottom: 20px;">
    <div style="font-size: 0.8rem; text-transform: uppercase; color: #38bdf8; letter-spacing: 0.08em; font-weight: 600;">Ready for Step 2?</div>
    <h3 style="margin: 4px 0 6px 0; color: white; font-size: 1.3rem;">📄 Generate Executive Fiduciary Report & Statutory Deliverable</h3>
    <p style="margin: 0 0 12px 0; color: #cbd5e1; font-size: 0.92rem;">Your intake audit is complete. Proceed to Step 2 to generate, inspect, and export your official fee-only fiduciary report per SEBI (Investment Advisers) Regulations, 2013.</p>
</div>
''', unsafe_allow_html=True)
st.page_link("pages/5_Fiduciary_Report.py", label="👉 Open Step 2: Executive Fiduciary Report & Download", icon="📄")

# --- Disclaimer ---
st.caption("SEBI Registered Investment Adviser (RIA) / Research Analyst (RA) Compliance Notice: This dashboard operates on a strict fee-only, non-execution fiduciary basis under SEBI (Investment Advisers) Regulations, 2013. Past performance does not guarantee future results.")
