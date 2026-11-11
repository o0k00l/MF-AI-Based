"""UI utilities for Streamlit dashboard components."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st


# Path constants
ROOT_DIR = Path(__file__).resolve().parents[1]
METRICS_PATH = ROOT_DIR / "data" / "policy" / "fund_metrics.json"
SCHEMA_PATH = ROOT_DIR / "data" / "policy" / "scheme_master.json"
# CAS_PATH is never hardcoded. Every user uploads their own CAS file at runtime.
# NO HARDCODING RULE: Any hardcoded CAS path is a P0 defect.


@st.cache_data(ttl=3600, show_spinner=False)
def load_fund_metrics() -> dict | None:
    """Load fund metrics from the policy file."""
    if METRICS_PATH.exists():
        with open(METRICS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def load_scheme_master() -> dict | None:
    """Load scheme master from the policy file."""
    if SCHEMA_PATH.exists():
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            return json.load(f)
    return None


def calculate_allocations(funds: list) -> dict:
    """Calculate portfolio-level allocation metrics via canonical fiduciary engine.

    Returns true debt allocation including internal debt in equity funds.
    """
    from services.ai_fund_classifier import compute_portfolio_segment_breakdown
    seg = compute_portfolio_segment_breakdown(funds)
    return {
        "total_value": seg["total_value"],
        "equity_value": seg["equity_value"],
        "debt_value": seg["debt_value"],
        "large_cap_value": seg["large_cap_value"],
        "mid_cap_value": seg["mid_cap_value"],
        "small_cap_value": seg["small_cap_value"],
        "unmeasured_value": seg.get("unmeasured_value", 0.0),
        "unmeasured_pct": seg.get("unmeasured_pct", 0.0),
        "is_fully_measured": seg.get("is_fully_measured", True),
    }


def get_category_counts(funds: list) -> dict:
    """Get counts of funds by category."""
    return {
        "total": len(funds),
        "equity": len([f for f in funds if f.get("category") in ("Equity", "Flexi Cap", "Multi Cap")]),
        "hybrid": len([f for f in funds if f.get("category") == "Hybrid"]),
        "debt": len([f for f in funds if f.get("category") == "Debt"]),
    }


def render_sidebar():
    """Render the professional sidebar navigation."""
    st.sidebar.markdown(
        """
<h1>📊 Portfolio Analysis</h1>
<p style='color: #64748b; font-size: 0.9rem;'>
Upload your CAS file to begin analysis.
</p>
""",
        unsafe_allow_html=True
    )
    
    # Navigation
    st.sidebar.markdown("**Navigation**", help="Go to different analysis pages")
    if st.sidebar.button("🏠 Portfolio Dashboard", use_container_width=True, type="secondary"):
        st.session_state["nav_page"] = "dashboard"
    if st.sidebar.button("📈 Debt Allocation", use_container_width=True, type="secondary"):
        st.session_state["nav_page"] = "debt"
    
    st.sidebar.markdown("---")
    
    # Status indicator
    if "user_portfolio" in st.session_state and st.session_state["user_portfolio"]:
        st.sidebar.success(f"✅ **Portfolio Loaded**\n{len(st.session_state['user_portfolio'])} funds")
    else:
        st.sidebar.info("⚠️ Upload CAS & CGS to proceed")
    
    st.sidebar.markdown("---")
    
    # Disclaimer
    st.sidebar.markdown("""
<div style='font-size: 0.75rem; color: #64748b;'>
<b>Disclaimer</b><br>
This is not financial advice. Consult a qualified advisor for investment decisions.<br>
Data parsed dynamically from your uploaded CAS & CGS statements.
</div>
""", unsafe_allow_html=True)


def apply_styling():
    """Apply custom CSS styling for professional look."""
    st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #1e3a8a 0%, #16a34a 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .metric-card {
        background: var(--secondary-background-color, #f8fafc);
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
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
        border-left: 4px solid #16a34a;
        margin-top: 32px;
    }
    .stButton>button {
        border-radius: 8px;
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