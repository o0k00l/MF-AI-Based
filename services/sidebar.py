"""services/sidebar.py — Unified Fiduciary Advisory Flow Sidebar.

Single source of truth for the Two-Step Fiduciary Advisory navigation and
active portfolio telemetry across all Streamlit pages. Eliminates double coding.
"""
from __future__ import annotations

import streamlit as st


def render_fiduciary_sidebar(current_page: str = "app.py") -> None:
    """Render the standard SEBI IA Two-Step Fiduciary sidebar."""
    with st.sidebar:
        # Sidebar Brand Header & Universal Theme Styles
        st.markdown("""
        <style>
            [data-testid="stSidebarNav"] { display: none !important; }
            .sidebar-brand-title {
                font-size: 1.15rem;
                font-weight: 700;
                color: var(--text-color, #0f172a);
                margin-bottom: 4px;
            }
            .sidebar-brand-sub {
                font-size: 0.72rem;
                color: #94a3b8;
                text-transform: uppercase;
                letter-spacing: 0.05em;
                margin-bottom: 12px;
            }
            .portfolio-card {
                background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
                color: #ffffff;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-left: 4px solid #38bdf8;
                border-radius: 8px;
                padding: 10px 14px;
                margin-bottom: 12px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.15);
            }
            .sidebar-risk-card {
                background: var(--secondary-background-color, #f8fafc);
                border: 1px solid rgba(148, 163, 184, 0.25);
                border-left: 4px solid #38bdf8;
                border-radius: 8px;
                padding: 8px 12px;
                margin-bottom: 12px;
            }
            .sidebar-section-header {
                font-weight: 700;
                font-size: 0.8rem;
                color: var(--text-color, #334155);
                opacity: 0.88;
                margin-bottom: 6px;
                letter-spacing: 0.03em;
            }
            @media (prefers-color-scheme: dark) {
                .sidebar-brand-title { color: #f8fafc !important; }
                .sidebar-section-header { color: #cbd5e1 !important; opacity: 1 !important; }
                .sidebar-risk-card { background: #1e293b !important; border-color: rgba(148, 163, 184, 0.2) !important; }
            }
            [data-theme="dark"] .sidebar-brand-title { color: #f8fafc !important; }
            [data-theme="dark"] .sidebar-section-header { color: #cbd5e1 !important; opacity: 1 !important; }
            [data-theme="dark"] .sidebar-risk-card { background: #1e293b !important; border-color: rgba(148, 163, 184, 0.2) !important; }
        </style>
        """, unsafe_allow_html=True)
        st.markdown("""
        <div class="sidebar-brand-title">🛡️ Fiduciary Engine</div>
        <div class="sidebar-brand-sub">SEBI IA Advisory Decision Support</div>
        """, unsafe_allow_html=True)

        user_portfolio = st.session_state.get("user_portfolio", [])
        has_cas = len(user_portfolio) > 0
        has_cgs = bool(st.session_state.get("cgs_data"))
        has_risk = bool(st.session_state.get("user_risk_score") or st.session_state.get("risk_tier"))

        # Active Portfolio Telemetry Card
        if has_cas:
            tot_val = sum(f.get("current_value", 0) for f in user_portfolio)
            tot_inv = sum(f.get("invested_value", 0) for f in user_portfolio)
            gain = tot_val - tot_inv if tot_inv > 0 else 0
            gain_pct = (gain / tot_inv * 100) if tot_inv > 0 else 0
            dir_val = sum(f.get("current_value", 0) for f in user_portfolio if str(f.get("plan_type", "Direct")).upper() == "DIRECT")
            dir_pct = (dir_val / tot_val * 100) if tot_val > 0 else 100.0

            st.markdown(f"""
            <div class="portfolio-card">
                <div style="font-size: 0.72rem; text-transform: uppercase; color: #94a3b8; letter-spacing: 0.05em;">Active Portfolio</div>
                <div style="font-size: 1.45rem; font-weight: 700; color: #38bdf8; margin: 2px 0;">₹{tot_val/100000:.2f}L</div>
                <div style="font-size: 0.78rem; color: #cbd5e1; display: flex; justify-content: space-between;">
                    <span>{len(user_portfolio)} Schemes</span>
                    <span style="color: {'#4ade80' if gain >= 0 else '#f87171'}; font-weight: 600;">{gain_pct:+.1f}%</span>
                </div>
                <div style="font-size: 0.72rem; color: #94a3b8; margin-top: 6px; border-top: 1px solid rgba(255,255,255,0.15); padding-top: 5px;">
                    Direct Plans: <b style="color: {'#4ade80' if dir_pct == 100 else '#facc15'}">{dir_pct:.0f}%</b>
                </div>
            </div>
            """, unsafe_allow_html=True)

        # Active Governing Risk Tier Badge
        if has_risk:
            tier_name = str(st.session_state.get("risk_tier", "Assessed")).replace("_", " ").title()
            target = st.session_state.get("saa_target", {})
            eq_t = target.get("total_equity_pct", target.get("equity_pct", 75.0))
            db_t = target.get("debt_pct", 25.0)
            st.markdown(f"""
            <div class="sidebar-risk-card">
                <div style="color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; font-weight: 600;">Governing Risk Profile</div>
                <div style="color: var(--text-color, #0f172a); font-size: 0.85rem; font-weight: 700; margin: 2px 0;">🎯 {tier_name}</div>
                <div style="color: var(--text-color, #475569); opacity: 0.85; font-size: 0.75rem;">Target SAA: <b>{eq_t:.0f}% Eq / {db_t:.0f}% Debt</b></div>
            </div>
            """, unsafe_allow_html=True)

        # Primary Two-Step Fiduciary Flow
        st.markdown("<p class='sidebar-section-header'>🧭 TWO-STEP FIDUCIARY FLOW</p>", unsafe_allow_html=True)
        st.page_link("app.py", label=f"Step 1: Intake & Audit {'✅' if has_cas else '⏳'}", icon="📊")
        st.page_link("pages/5_Fiduciary_Report.py", label=f"Step 2: Executive Report {'✅' if has_cas else '⏳'}", icon="📄")

        # Optional Deep-Dive Tools
        st.markdown("<p class='sidebar-section-header' style='margin-top: 14px;'>🔬 OPTIONAL DEEP-DIVES</p>", unsafe_allow_html=True)
        st.page_link("pages/2_Risk_Profiler.py", label="Risk Profiler & SAA", icon="📋")
        st.page_link("pages/4_Debt_Allocation.py", label="True Debt Factsheet Matrix", icon="📈")
        st.page_link("pages/3_Financial_Goals.py", label="Financial Goals Wizard", icon="🎯")
        st.page_link("pages/1_Advisory_Flow.py", label="Advisory Roadmap", icon="🧭")

        # Reset Session Action
        if has_cas:
            st.markdown("---")
            if st.button("🔄 Reset Active Session", use_container_width=True, type="secondary", help="Clear current session data to upload a new statement"):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
