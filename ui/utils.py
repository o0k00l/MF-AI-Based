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
    """Calculate portfolio-level allocation metrics.

    Returns true debt allocation including internal debt in equity funds.
    """
    total_value = sum(f.get("current_value", 0) for f in funds) or 0

    allocations = {
        "total_value": total_value,
        "equity_value": 0.0,
        "debt_value": 0.0,
        "large_cap_value": 0.0,
        "mid_cap_value": 0.0,
        "small_cap_value": 0.0,
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
        category = fund.get("category", "")

        # Equity allocation
        allocations["equity_value"] += current * eq / 100

        # Internal debt in equity/hybrid funds
        if category in ("Equity", "Hybrid", "Flexi Cap", "Multi Cap"):
            allocations["debt_value"] += current * debt / 100

        # Segment allocations
        allocations["large_cap_value"] += current * lc / 100
        allocations["mid_cap_value"] += current * mc / 100
        allocations["small_cap_value"] += current * sc / 100

    return allocations


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
        st.sidebar.info("⚠️ Upload CAS to proceed")
    
    st.sidebar.markdown("---")
    
    # Disclaimer
    st.sidebar.markdown("""
<div style='font-size: 0.75rem; color: #64748b;'>
<b>Disclaimer</b><br>
This is not financial advice. Consult a qualified advisor for investment decisions.<br>
Data parsed dynamically from your uploaded CAS.
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
    .stButton>button {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)