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

import streamlit as st

try:
    from services.cas_parser import parse_cas_file
    from services.ai_fund_classifier import enrich_funds_with_ai, classify_fund_with_ai, generate_fiduciary_ai_narrative, compute_portfolio_segment_breakdown, evaluate_portfolio_concentration_risks
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
    .portfolio-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-left: 4px solid #38bdf8;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
</style>
""", unsafe_allow_html=True)

# --- Page Title Banner ---
st.markdown("""
<div class="banner-intake">
    <div style="font-size: 0.8rem; text-transform: uppercase; color: #38bdf8; letter-spacing: 0.08em; font-weight: 600;">⚡ Step 1: Portfolio Intake & Audit</div>
    <h1 style="margin: 4px 0 6px 0; color: white; font-size: 1.85rem; font-weight: 800;">Fiduciary Portfolio Diagnostic</h1>
    <p style="margin: 0; color: #cbd5e1; font-size: 0.92rem;">Uncover hidden commission bleed, eliminate duplicate overlaps, and reveal your true strategic asset allocation.</p>
</div>
""", unsafe_allow_html=True)

# --- Dual Mandatory Statement Ingestion (CAS Detailed & CGS) ---
st.markdown('<h2 class="section-title">📂 Upload Statements (CAS Detailed & CGS Required)</h2>', unsafe_allow_html=True)

upload_c1, upload_c2 = st.columns(2)
with upload_c1:
    st.markdown("##### 1. Consolidated Account Statement (CAS) (Detailed)")
    uploaded_file = st.file_uploader(
        "Upload CAS (Detailed) PDF or Excel Statement",
        type=["pdf", "xlsx", "xls"],
        help="Download the 'Detailed' (not Summary) CAS from CAMS, KFintech, or MFCentral to include complete transaction histories and acquisition costs.",
        key="cas_uploader_input",
    )
    pdf_password = st.text_input(
        "CAS PDF Password (if encrypted)",
        type="password",
        help="Usually your PAN (uppercase) or date of birth per CAMS/KFintech instructions",
        key="cas_pdf_password_input",
    )
    st.caption("📌 **Detailed Statement Required:** Please ensure you select **'Detailed'** when requesting your CAS from CAMS, KFintech, or MFCentral so complete transaction lots, purchase dates, and acquisition NAVs are included.")

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
        has_detailed_txns = any(f.get("unrealized_ltcg") is not None for f in enriched_funds)
        st.session_state["portfolio_metadata"] = {
            "upload_time": str(__import__("datetime").datetime.now().isoformat()),
            "upload_source": uploaded_file.name,
            "fund_count": len(enriched_funds),
            "total_value": sum(f.get("current_value", 0) for f in enriched_funds),
            "is_detailed_statement": has_detailed_txns,
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
    src_name = st.session_state.get("portfolio_metadata", {}).get("upload_source", "uploaded CAS (Detailed)")
    is_detailed = st.session_state.get("portfolio_metadata", {}).get("is_detailed_statement", False)
    detail_note = " — *Detailed Transaction History & Lots Verified*" if is_detailed else ""
    st.info(f"📂 **Active Statements Loaded:** Retaining **{len(funds)}** active funds from `{src_name}`{detail_note}.")
else:
    st.info("⬆️ **Please upload your Consolidated Account Statement (CAS) (Detailed)** above to generate your fiduciary audit.")
    st.stop()

# --- Compute Portfolio Metrics Dynamically (Zero Hardcoding) ---
total_value = sum(f.get("current_value", 0) for f in funds)
total_invested = sum(f.get("invested_value", 0) for f in funds)
total_gain = (total_value - total_invested) if total_invested > 0 else 0.0
gain_pct = (total_gain / total_invested * 100) if total_invested > 0 else 0.0

seg_breakdown = compute_portfolio_segment_breakdown(funds)
total_eq = seg_breakdown["equity_value"]
total_debt = seg_breakdown["debt_value"]
total_lc = seg_breakdown["large_cap_value"]
total_mc = seg_breakdown["mid_cap_value"]
total_sc = seg_breakdown["small_cap_value"]
total_gold = seg_breakdown["gold_value"]
total_intl = seg_breakdown["intl_value"]
eq_pct = seg_breakdown["equity_pct"]
debt_pct = seg_breakdown["debt_pct"]
# Compute thematic/sectoral concentration percentage
conc_res = evaluate_portfolio_concentration_risks(funds)
thematic_pct = conc_res.get("thematic_pct", 0.0)

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
    "📊 **PORTFOLIO AUDIT** – Fees, Drift & Truth",
    "🤖 **AI TAX INSIGHTS** – Gains, Harvesting & Savings",
    "🎯 **CAPITAL BLUEPRINT** – SIPs, Lumpsums & Simulations",
])

with tab_audit:
    # 1. Overview KPI Cards
    st.markdown("##### 🔍 **Portfolio Truth Engine** – Your Money, Unfiltered")
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
    st.markdown("##### 📈 **Equity DNA Mapping** – Large, Mid, Small Cap DNA Breakdown")
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

    with st.expander("🔍 True Debt & Liquid Cash Holdings", expanded=False):
        st.caption("Bonds, T-Bills, TREPS, and stable cash equivalents.")
        if total_debt > 0:
            debt_data = [
                {"Name": "Debt/Cash Reserve", "Value": f"₹{total_debt:,.0f}", "% of Portfolio": f"{(total_debt/total_value*100):.1f}%"},
                {"Name": "Large Cap Equity", "Value": f"₹{total_lc:,.0f}", "% of Portfolio": f"{(total_lc/total_value*100):.1f}%"},
                {"Name": "Mid Cap Equity", "Value": f"₹{total_mc:,.0f}", "% of Portfolio": f"{(total_mc/total_value*100):.1f}%"},
                {"Name": "Small Cap Equity", "Value": f"₹{total_sc:,.0f}", "% of Portfolio": f"{(total_sc/total_value*100):.1f}%"},
                {"Name": "Gold Holdings", "Value": f"₹{total_gold:,.0f}", "% of Portfolio": f"{(total_gold/total_value*100):.1f}%" if total_value else "0.0%"},
            ]
            st.table(debt_data)

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

    # 3. Scheme-by-Scheme Holdings Table with Exit Signals & Segment Allocation
    st.markdown("##### 📋 **Holdings Radar** – Scheme-Level Factsheet Audit with Exit Signals")
    st.caption("Scheme-level factsheet allocation audit with exit signals and actionable recommendations.")
    filter_search = st.text_input("Filter funds by name or AMC", "", key="holdings_search_query")
    filtered_funds = [f for f in funds if filter_search.lower() in str(f.get("scheme", "")).lower()] if filter_search else funds

    # Build exit signals lookup by scheme name
    exit_signals_by_scheme = {}
    for sig in factor_res.get("exit_signals", []):
        scheme_name = sig.get("scheme", "").lower()
        exit_signals_by_scheme[scheme_name] = sig
    
    # Build segment breakdown lookup by scheme name
    segment_breakdown_by_scheme = {}
    for seg in seg_breakdown.get("scheme_rows", []):
        scheme = seg.get("scheme", "").lower()
        segment_breakdown_by_scheme[scheme] = seg

    table_data = []
    for f in filtered_funds:
        scheme_name_lower = f.get("scheme", "").lower()
        sig = exit_signals_by_scheme.get(scheme_name_lower, {})
        seg_info = segment_breakdown_by_scheme.get(scheme_name_lower, {})
        
        badge = "🛑" if sig.get("severity") == "HIGH" else ("⚠️" if sig.get("severity") == "MODERATE" else "")
        action_text = sig.get("action", "—").replace("_", " ").title()
        saving_text = f"+₹{sig.get('annual_saving_inr', 0):,.0f}/yr" if sig.get("annual_saving_inr") else "—"
        
        # Format segment allocations
        lc = seg_info.get("large_cap_pct", 0)
        mc = seg_info.get("mid_cap_pct", 0)
        sc = seg_info.get("small_cap_pct", 0)
        debt = seg_info.get("debt_pct", 0)
        prov = seg_info.get("provenance", "AMC Factsheet")
        
        # Get numeric current value for sorting
        # Handle both numeric values and formatted strings (e.g., "1,23,456.78" or "₹1,23,456")
        current_val_raw = f.get('current_value', 0) or 0
        try:
            if isinstance(current_val_raw, str):
                # Remove currency symbols, commas, and whitespace
                current_val_clean = current_val_raw.replace('₹', '').replace(',', '').strip()
                current_val_num = float(current_val_clean) if current_val_clean else 0.0
            else:
                current_val_num = float(current_val_raw)
        except (ValueError, TypeError, AttributeError):
            current_val_num = 0.0

        table_data.append({
            "Scheme Name": f.get("scheme", ""),
            "Current Value (₹)": f"₹{current_val_num:,.0f}",
            "_sort_key": current_val_num,
            "Category": f.get("category", ""),
            "Plan": f.get("plan_type", "Direct"),
            "Large Cap": f"{lc:.1f}%",
            "Mid Cap": f"{mc:.1f}%",
            "Small Cap": f"{sc:.1f}%",
            "Debt/Cash": f"{debt:.1f}%",
            "Provenance": prov,
            "Direct TER": f"{f.get('ter_direct', 0):.2f}%",
            "Benchmark": f.get("benchmark", ""),
            "Action": f"{badge} {action_text}",
            "Savings": saving_text,
        })
    
    # Sort by Current Value (₹) descending using numeric sort key
    table_data.sort(key=lambda x: x.get("_sort_key", 0), reverse=True)
    
    # Remove the hidden sort key before displaying
    for row in table_data:
        row.pop("_sort_key", None)
    
    st.dataframe(table_data, use_container_width=True, hide_index=False)
    
    with st.expander("🔍 Scheme-by-Scheme Segment Allocation (AMC Factsheet Look-Through)", expanded=False):
        st.caption("Detailed segment allocation for each fund from AMC factsheets.")
        if seg_breakdown.get("scheme_rows"):
            scheme_rows = seg_breakdown.get("scheme_rows", [])
            scheme_segment_data = []
            for row in scheme_rows:
                scheme_name = row.get("scheme", "")
                large_cap = row.get("large_cap_pct", 0)
                mid_cap = row.get("mid_cap_pct", 0)
                small_cap = row.get("small_cap_pct", 0)
                debt = row.get("debt_pct", 0)
                total_seg = large_cap + mid_cap + small_cap + debt
                if total_seg > 0:
                    scheme_segment_data.append({
                        "Scheme": scheme_name,
                        "Large Cap": f"{large_cap:.1f}%",
                        "Mid Cap": f"{mid_cap:.1f}%",
                        "Small Cap": f"{small_cap:.1f}%",
                        "Debt/Cash": f"{debt:.1f}%",
                        "Total": f"{total_seg:.1f}%"
                    })
            if scheme_segment_data:
                st.dataframe(scheme_segment_data, use_container_width=True, hide_index=False)
        else:
            st.info("Segment allocation data not yet available.")

with tab_ai_tax:
    # 1. AI Executive Fiduciary Portfolio Diagnosis
    st.markdown("##### 🤖 **Fiduciary AI Advisor** – Live Analysis with SEBI Statutory Lens")
    st.caption("Institutional-grade synthesis of allocation drift, commission bleed, and folio consolidation opportunities.")

    ai_c1, ai_c2 = st.columns([3, 1])
    with ai_c1:
        st.markdown("Unlock your portfolio's untapped potential with AI-powered fiduciary insights, backed by SEBI & AMFI statutory benchmarks.")
    with ai_c2:
        gen_ai_btn = st.button("🧠 **Synthesize Diagnosis**", use_container_width=True)

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
        "thematic_pct": thematic_pct,
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
        # Handle potential string values with commas/currency symbols
        ltcg_raw = cg_s.get("ltcg_inr") or 0.0
        stcg_raw = cg_s.get("stcg_inr") or 0.0
        try:
            if isinstance(ltcg_raw, str):
                ltcg_raw = ltcg_raw.replace('₹', '').replace(',', '').strip()
            if isinstance(stcg_raw, str):
                stcg_raw = stcg_raw.replace('₹', '').replace(',', '').strip()
            ltcg = float(ltcg_raw) if ltcg_raw else 0.0
            stcg = float(stcg_raw) if stcg_raw else 0.0
        except (ValueError, TypeError):
            ltcg = 0.0
            stcg = 0.0
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
    st.markdown("##### 💬 **AI Ask-Me-Anything** – Your Portfolio Questions, Instantly Answered")
    st.caption("Query your investments in plain English – from commission bleed to optimal rebalancing strategies.")

    quick_cols = st.columns(5)
    preset_q = None
    with quick_cols[0]:
        if st.button("💸 **Fee Bleed Detector**", use_container_width=True):
            preset_q = "What is my total annual distributor fee bleed and 10-year compounded drag, and how much could I save?"
    with quick_cols[1]:
        if st.button("📊 **Segment Truth**", use_container_width=True):
            preset_q = "Show me my authentic Large Cap, Mid Cap, and Small Cap exposure across all funds – warts and all?"
    with quick_cols[2]:
        if st.button("⚖️ **SAA Radar**", use_container_width=True):
            preset_q = "How far am I from my target strategic asset allocation, and what's the drift cost me?"
    with quick_cols[3]:
        if st.button("📑 **Tax Harvest Pro**", use_container_width=True):
            preset_q = "How can I harvest capital gains tax-free under Section 112A this financial year?"
    with quick_cols[4]:
        if st.button("🚨 **Prune & Save**", use_container_width=True):
            preset_q = "Which funds should I exit or consolidate first to stop commission leakage and save taxes?"

    from services.ai_fund_classifier import answer_fiduciary_query
    user_query = st.text_input("🗣️ Ask your portfolio question:", value=preset_q if preset_q else "", placeholder="e.g. How much trail commission am I losing in regular funds every year?", key="fiduciary_nl_query_box")

    if user_query:
        with st.spinner("🔍 Analyzing portfolio facts through the SEBI fiduciary lens..."):
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
    st.markdown("##### 🎯 **SAA Drift Radar** – Where You Stand vs. Target")
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

    chosen_saa = st.selectbox("🎯 Choose Your Target Risk DNA", list(saa_options.keys()), index=preset_idx)
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

    st.caption("📝 Need a formal SEBI suitability test? Visit [Risk Profiler Page](pages/2_Risk_Profiler.py) for the 6-question benchmark.")

    st.markdown("---")
    # 2. Fiduciary SIP Recommendation Blueprint
    st.markdown("##### 🚀 **SIP Blueprint Engine** – Direct-Plan Optimized with Timing Secrets")
    st.caption("Bi-weekly tranche timing, 100% Direct compliance, and automated completion alerts.")

    sip_budget_val = st.number_input("💰 Monthly SIP Budget (₹)", min_value=1000.0, max_value=10000000.0, value=25000.0, step=1000.0)

    if st.button("🎯 **Generate SIP Blueprint**", type="primary", use_container_width=True):
        with st.spinner("⚙️ Crafting your optimal SIP timing blueprint..."):
            bp = generate_fiduciary_sip_blueprint(monthly_budget_inr=sip_budget_val, target_saa=st.session_state.get("saa_target"), funds=funds)
            st.session_state["sip_blueprint_result"] = bp

    sip_res = st.session_state.get("sip_blueprint_result")
    if sip_res:
        if sip_res.get("optimal_tranche_timing"):
            tt = sip_res["optimal_tranche_timing"]
            if tt and isinstance(tt, dict):
                cadence = tt.get('recommended_cadence', 'Bi-weekly')
                biweekly = float(tt.get('biweekly_amount_inr', 0))
                dates = tt.get('suggested_execution_dates_of_month', [])
                date_str = ', '.join(str(d) for d in dates)
                st.markdown(f"📅 **Optimal Cadence:** {cadence} (₹{biweekly:,.0f} per tranche on the {date_str}th).")

        if sip_res.get("portfolio_completion_alerts"):
            for al in sip_res["portfolio_completion_alerts"]:
                if al and isinstance(al, dict):
                    try:
                        slot = al.get('slot', 'Unknown Slot') or 'Unknown Slot'
                        action = al.get('action', 'Review recommended') or 'Review recommended'
                        severity = al.get('severity', 'MEDIUM') or 'MEDIUM'
                        emoji = "🔴" if severity == "HIGH" else ("🟡" if severity == "MEDIUM" else "⚪")
                        st.warning(f"{emoji} **{slot}** - {action}")
                    except (AttributeError, TypeError) as e:
                        st.warning(f"⚠️ Alert processing error: {str(e)}")
                        st.caption(f"Raw alert data: {al}")

        st.markdown("| Mandate Slot | Scheme Recommendation | Category | Plan | Monthly SIP | Allocation |")
        st.markdown("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for rec in sip_res.get("recommendations", []):
            if rec and isinstance(rec, dict):
                slot_name = rec.get('slot_name', 'N/A')
                scheme_name = rec.get('scheme_name', 'N/A')
                category = rec.get('category', 'N/A')
                plan_type = rec.get('plan_type', 'N/A')
                # Handle potential string values with commas
                try:
                    monthly_alloc_raw = rec.get('monthly_allocation_inr', 0)
                    if isinstance(monthly_alloc_raw, str):
                        monthly_alloc = float(monthly_alloc_raw.replace(',', '').replace('₹', '').strip())
                    else:
                        monthly_alloc = float(monthly_alloc_raw or 0)
                except (ValueError, TypeError):
                    monthly_alloc = 0.0
                try:
                    alloc_pct_raw = rec.get('allocation_pct', 0)
                    if isinstance(alloc_pct_raw, str):
                        alloc_pct = float(alloc_pct_raw.replace(',', '').strip())
                    else:
                        alloc_pct = float(alloc_pct_raw or 0)
                except (ValueError, TypeError):
                    alloc_pct = 0.0
                st.markdown(f"| {slot_name} | **{scheme_name}** | {category} | {plan_type} | ₹{monthly_alloc:,.0f} | {alloc_pct:.1f}% |")

    st.markdown("---")
    # 3. Lump-Sum Capital Deployment & Systematic Transfer Plan (STP)
    st.markdown("##### 💰 Lump-Sum Capital Deployment & STP Waterfall")
    st.caption("Systematically mitigates entry timing risk via automated staging from high-grade parking vehicles.")

    lump_c1, lump_c2 = st.columns(2)
    with lump_c1:
        lump_in = st.number_input("💸 Lump-Sum Capital Available (₹)", min_value=10000.0, max_value=100000000.0, value=500000.0, step=25000.0)
    with lump_c2:
        stp_months = st.slider("⏳ STP Staging Horizon (Months)", min_value=3, max_value=12, value=6, step=1)

    if st.button("🚀 **Deploy Lump-Sum via STP**", use_container_width=True):
        with st.spinner("🔄 Computing optimal staging waterfall..."):
            l_plan = evaluate_fiduciary_lumpsum_blueprint(
                lumpsum_amount_inr=float(lump_in),
                stp_duration_months=int(stp_months),
                target_saa=st.session_state.get("saa_target"),
                funds=funds,
            )
            st.session_state["lumpsum_plan_result"] = l_plan

    lp = st.session_state.get("lumpsum_plan_result")
    if lp:
        # Handle potential string values with commas/currency symbols
        stp_amt_raw = lp.get('monthly_stp_amount_inr', 0)
        try:
            if isinstance(stp_amt_raw, str):
                stp_amt_raw = stp_amt_raw.replace('₹', '').replace(',', '').strip()
            stp_amount = float(stp_amt_raw) if stp_amt_raw else 0.0
        except (ValueError, TypeError):
            stp_amount = 0.0
        st.markdown(f"🛡️ **Staging Strategy:** Park capital in a zero-exit-load Direct liquid/arbitrage vehicle and stage ₹{stp_amount:,.0f}/month across equity sleeves over {stp_months} months.")

    st.markdown("---")
    # 4. Monte Carlo Wealth Accumulation Stochastic Simulation
    st.markdown("##### 🎲 **Monte Carlo Goal Simulator** – What-if Scenarios with 1,000 Market Paths")
    st.caption("Stress-test your strategy against historical market volatility and find your success probability.")
    from services.goal_planner import run_monte_carlo_goal_simulation
    mc_c1, mc_c2 = st.columns(2)
    with mc_c1:
        target_corpus_goal = st.number_input("🎯 Target Corpus Goal (₹)", min_value=100000.0, max_value=500000000.0, value=10000000.0, step=500000.0)
    with mc_c2:
        goal_horizon = st.slider("📅 Goal Horizon (Years)", min_value=1, max_value=30, value=15, step=1)

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
            st.metric("🏆 Success Probability", f"{prob:.1f}%", "Historical market paths")
        with mc_m2:
            st.metric("📈 Median Corpus (P50)", f"₹{mc_sim.get('p50_corpus_inr', 0)/100000:.2f}L", "Expected compounding")
        with mc_m3:
            st.metric("🔥 Worst-Case (P05)", f"₹{mc_sim.get('p05_corpus_inr', 0)/100000:.2f}L", "Left-tail stress test")
        st.success(f"💡 **Monte Carlo Verdict:** {mc_sim.get('recommended_action', '')}")

# --- Step 2 Transition Banner ---
st.markdown("---")
st.markdown('''
<div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); color: white; padding: 20px 24px; border-radius: 12px; margin-top: 15px; margin-bottom: 20px;">
    <div style="font-size: 0.8rem; text-transform: uppercase; color: #38bdf8; letter-spacing: 0.08em; font-weight: 600;">🚀 Step 2 – Client-Ready Report</div>
    <h3 style="margin: 4px 0 6px 0; color: white; font-size: 1.3rem;">📄 Executive Fiduciary Report & Statutory Deliverable</h3>
    <p style="margin: 0 0 12px 0; color: #cbd5e1; font-size: 0.92rem;">Your intake audit is done. Generate your official SEBI-compliant fiduciary report with actionable recommendations, tax optimization strategies, and fee-recovery playbook.</p>
</div>
''', unsafe_allow_html=True)
st.page_link("pages/5_Fiduciary_Report.py", label="📄 **Open Step 2: Executive Fiduciary Report & Download**", icon="📄")

# --- Disclaimer ---
st.caption("📝 **SEBI RIAs & RAs: Fee-only, non-execution fiduciary basis under SEBI (Investment Advisers) Regulations, 2013. Past performance ≠ future returns.**")
