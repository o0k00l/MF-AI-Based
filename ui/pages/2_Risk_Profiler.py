"""SEBI-Compliant Fiduciary Risk Profiler Page.

Offers 3 distinct investor assessment paths:
1. 🌱 Guided SEBI Questionnaire (Beginners / Retail Investors): Evaluates Financial Capacity
   and Emotional Loss Tolerance separately with the Weakest Link Principle (Governing Tier = min(Cap, Tol)).
2. ⚡ Direct Regulatory Risk Tier (Informed / DIY Investors): Direct selection of the 6 SEBI regulatory tiers.
3. 🎯 Custom Asset Allocation Target (Experts / HNIs / RIAs): Direct percentage inputs (Large Cap, Mid/Small, Debt)
   validated to 100% with bespoke IPS mandate tracking.
"""
from __future__ import annotations

import sys
from pathlib import Path
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import streamlit as st
from services.risk_profiler import (
    evaluate_fiduciary_profile,
    evaluate_direct_tier,
    evaluate_custom_saa,
    predict_risk_tier_from_portfolio,
    SebiRiskTier,
)

st.set_page_config(
    page_title="SEBI Risk Profiler | Binding Constraint SAA",
    page_icon="📋",
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

st.title("📋 SEBI Risk Profiler & Strategic Asset Allocation (SAA)")
st.markdown(
    "A fiduciary risk assessment aligns your mutual fund portfolio with statutory SEBI standards. "
    "Select your preferred profiling pathway below based on your investment experience."
)

# Detect portfolio context
funds = st.session_state.get("user_portfolio", [])
total_corpus = sum(f.get("current_value", 0.0) for f in funds) if funds else 0.0

if total_corpus > 0:
    pred_risk = predict_risk_tier_from_portfolio(funds, use_live_ai=False)
    st.info(f"💼 **Linked Portfolio:** Analyzing risk for portfolio of **₹{total_corpus/100000:.2f} Lakhs** ({len(funds)} active schemes).")
    with st.expander("🤖 AI Behavioral Risk Diagnosis & Pre-Flight Prediction", expanded=True):
        st.markdown(pred_risk.get("ai_behavioral_rationale", ""))
        pr_c1, pr_c2, pr_c3, pr_c4 = st.columns(4)
        with pr_c1:
            tier_sub = pred_risk["predicted_tier_name"].split(":")[1].strip() if ":" in pred_risk["predicted_tier_name"] else ""
            st.metric("Revealed Risk Profile", f"Tier {pred_risk['predicted_tier_num']}", tier_sub)
        with pr_c2:
            st.metric("Revealed Equity Mix", f"{pred_risk['portfolio_equity_pct']:.1f}%", f"{pred_risk['portfolio_debt_pct']:.1f}% Debt")
        with pr_c3:
            st.metric("Mid/Small Exposure", f"{pred_risk['portfolio_mid_small_pct']:.1f}%", "Growth Engine")
        with pr_c4:
            st.metric("AI Confidence", f"{pred_risk['confidence_score_pct']:.0f}%", "Revealed Preference")

        if st.button("⚡ Apply AI-Predicted Profile & Target SAA (One-Click)", type="primary", use_container_width=True, key="apply_ai_pred_risk"):
            p_res = pred_risk["profile_result"]
            st.session_state["fiduciary_profile_result"] = p_res
            st.session_state["risk_tier"] = p_res.governing_tier.name
            st.session_state["risk_bucket"] = p_res.governing_tier.name
            st.session_state["user_risk_score"] = int(p_res.governing_tier)
            st.session_state["saa_target"] = p_res.target_saa.as_dict()
            st.success(f"✅ Applied {pred_risk['predicted_tier_name']} Target SAA ({p_res.target_saa.total_equity_pct:.0f}% Eq / {p_res.target_saa.debt_pct:.0f}% Debt) to all advisory engines!")
            st.rerun()
else:
    st.caption("💡 *Tip: Upload your CAS & CGS statements on the Portfolio Dashboard to compare your current portfolio against your target SAA.*")

st.markdown("---")

tab1, tab2, tab3 = st.tabs([
    "🌱 Mode 1: Guided SEBI Questionnaire (Beginners)",
    "⚡ Mode 2: Direct Regulatory Risk Tier (Informed)",
    "🎯 Mode 3: Custom SAA Target (Experts & HNIs)",
])

# -----------------------------------------------------------------------------
# MODE 1: GUIDED QUESTIONNAIRE
# -----------------------------------------------------------------------------
with tab1:
    st.markdown("#### Comprehensive Capacity vs. Tolerance Assessment")
    st.caption("Evaluates objective financial ability and psychological loss tolerance separately. Binding Rule: Governing Tier = min(Capacity, Tolerance).")

    with st.form("mode1_guided_form"):
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🔹 1. Financial Risk Capacity")
            st.caption("Objective financial ability to endure portfolio declines.")

            q_horizon = st.selectbox(
                "Primary Investment Time Horizon",
                options=[
                    ("Under 3 years (Capital Preservation Priority)", 2.0),
                    ("3 to 5 years (Medium Term)", 4.0),
                    ("5 to 7 years (Balanced Growth)", 6.0),
                    ("7 to 10+ years (Long-Term Compounding)", 10.0),
                ],
                format_func=lambda x: x[0],
                index=1,
                help="Shorter horizons strictly limit equity exposure to prevent sequence-of-returns risk.",
            )[1]

            q_emergency = st.selectbox(
                "Liquid Savings & Emergency Reserve",
                options=[
                    ("Under 3 months of living expenses (High Liquidity Strain)", 2.0),
                    ("3 to 6 months of expenses (Adequate Safety Net)", 4.5),
                    ("6 to 12 months of expenses (Comfortable Buffer)", 9.0),
                    ("12+ months of expenses (Strong Capital Cushion)", 12.0),
                ],
                format_func=lambda x: x[0],
                index=2,
                help="Emergency reserves prevent premature forced liquidations of mutual fund investments.",
            )[1]

            q_income = st.selectbox(
                "Primary Income Stability",
                options=[
                    "Stable (Corporate Salaried / Government / Established Professional)",
                    "Variable (Business / Freelance / Commission-Based)",
                    "Retired / Dependent on Fixed Capital Returns",
                ],
                index=0,
            )

            q_emi = st.selectbox(
                "Total Monthly Debt & EMI Obligations (% of income)",
                options=[
                    ("Under 20% (Low Fixed Debt)", 15.0),
                    ("20% to 40% (Moderate Fixed Obligations)", 30.0),
                    ("Over 40% (High Debt Burden)", 50.0),
                ],
                format_func=lambda x: x[0],
                index=0,
            )[1]

        with col2:
            st.subheader("🔸 2. Emotional Loss Tolerance")
            st.caption("Psychological willingness and behavioral discipline during market corrections.")

            q_drop = st.selectbox(
                "Maximum Portfolio Drawdown Tolerated Without Selling",
                options=[
                    ("5% or less (Strict Drawdown Ceiling — Zero Capital Risk)", 5.0),
                    ("6% to 10% (Moderate Fluctuations Tolerated)", 10.0),
                    ("11% to 20% (Substantial Bear Market Corrections Acceptable)", 18.0),
                    ("20%+ (Deep Bear Market Tolerant — Growth Priority)", 30.0),
                ],
                format_func=lambda x: x[0],
                index=1,
                help="If you cannot tolerate more than a 5% drop, equity is hard-capped at 25-30% with 0% Mid/Small Cap.",
            )[1]

            q_exp = st.selectbox(
                "Mutual Fund Investment Experience",
                options=[
                    "Beginner (< 2 years, first-time investor)",
                    "Moderate (2 to 5 years, witnessed mild volatility)",
                    "Experienced (5+ years, held investments through major market crashes)",
                ],
                index=1,
            )

            q_goal_crit = st.selectbox(
                "Criticality of Underlying Goals",
                options=[
                    "Non-Negotiable (Essential capital: child college, home down payment)",
                    "Somewhat Flexible (Target year can shift by 1-2 years if needed)",
                    "Fully Discretionary (Wealth creation / aspirational milestones)",
                ],
                index=1,
            )

        submit_mode1 = st.form_submit_button("📊 Evaluate Guided Fiduciary Profile", type="primary", use_container_width=True)

    if submit_mode1:
        inc_key = "stable" if "stable" in q_income.lower() else ("variable" if "variable" in q_income.lower() else "retired")
        exp_key = "experienced" if "experienced" in q_exp.lower() else ("moderate" if "moderate" in q_exp.lower() else "beginner")

        h_years = float(q_horizon)
        dd_tol = float(q_drop)
        em_mos = float(q_emergency)
        emi_pct = float(q_emi)

        p_result = evaluate_fiduciary_profile(
            horizon_years=h_years,
            max_drawdown_tolerance_pct=dd_tol,
            emergency_fund_months=em_mos,
            income_stability=inc_key,
            emi_burden_pct=emi_pct,
            experience_level=exp_key,
        )
        st.session_state["fiduciary_profile_result"] = p_result
        st.session_state["risk_tier"] = p_result.governing_tier.name
        st.session_state["risk_bucket"] = p_result.governing_tier.name
        st.session_state["user_risk_score"] = int(p_result.governing_tier)
        st.session_state["saa_target"] = p_result.target_saa.as_dict()
        st.success("✅ **Guided Fiduciary Profile Evaluated and Synchronized!**")

# -----------------------------------------------------------------------------
# MODE 2: DIRECT REGULATORY RISK TIER
# -----------------------------------------------------------------------------
with tab2:
    st.markdown("#### Direct SEBI 6-Tier Regulatory Selection")
    st.caption("For informed investors who already know their regulatory risk appetite and target asset mix.")

    with st.form("mode2_direct_form"):
        tier_choice = st.radio(
            "Select Your Regulatory Risk Tier:",
            options=[
                (1, "Tier 1: Capital Preservation (0% Equity / 100% Debt & Liquid) — Ultra Low Risk"),
                (2, "Tier 2: Low to Moderate Risk (30% Equity / 70% Debt) — Conservative"),
                (3, "Tier 3: Moderate Risk (60% Equity / 40% Debt) — Balanced Growth"),
                (4, "Tier 4: Moderately High Risk (75% Equity / 25% Debt) — Wealth Accumulation"),
                (5, "Tier 5: High Risk (85% Equity / 15% Debt) — High Growth"),
                (6, "Tier 6: Very High Risk (95% Equity / 5% Debt) — Maximum Long-Term Compounding"),
            ],
            format_func=lambda x: x[1],
            index=3,
        )[0]

        submit_mode2 = st.form_submit_button("⚡ Lock Selected Regulatory Tier", type="primary", use_container_width=True)

    if submit_mode2:
        p_result = evaluate_direct_tier(tier_choice)
        st.session_state["fiduciary_profile_result"] = p_result
        st.session_state["risk_tier"] = p_result.governing_tier.name
        st.session_state["risk_bucket"] = p_result.governing_tier.name
        st.session_state["user_risk_score"] = int(p_result.governing_tier)
        st.session_state["saa_target"] = p_result.target_saa.as_dict()
        st.success(f"✅ **Tier {tier_choice} SAA Target Successfully Locked!**")

# -----------------------------------------------------------------------------
# MODE 3: CUSTOM ASSET ALLOCATION TARGET
# -----------------------------------------------------------------------------
with tab3:
    st.markdown("#### Custom SAA Target Allocator (Experts / RIAs / HNIs)")
    st.caption("Specify your bespoke target asset allocation. Percentages must sum to exactly 100.0%.")

    with st.form("mode3_custom_form"):
        col_c1, col_c2, col_c3 = st.columns(3)
        with col_c1:
            c_lc = st.number_input("Large-Cap Core Target (%):", min_value=0.0, max_value=100.0, value=50.0, step=5.0)
        with col_c2:
            c_ms = st.number_input("Mid/Small-Cap Alpha Target (%):", min_value=0.0, max_value=100.0, value=25.0, step=5.0)
        with col_c3:
            c_db = st.number_input("Debt & Liquidity Cushion Target (%):", min_value=0.0, max_value=100.0, value=25.0, step=5.0)

        custom_notes = st.text_input("Investment Policy Statement (IPS) Mandate Reference / Notes:", value="Client-Directed Asset Allocation")
        submit_mode3 = st.form_submit_button("🎯 Save Custom Asset Allocation Target", type="primary", use_container_width=True)

    if submit_mode3:
        total_p = c_lc + c_ms + c_db
        if abs(total_p - 100.0) > 0.01:
            st.error(f"❌ Allocations must sum to exactly 100.0% (Current sum: {total_p:.1f}%). Please adjust values.")
        else:
            p_result = evaluate_custom_saa(
                large_cap_pct=c_lc,
                mid_small_cap_pct=c_ms,
                debt_pct=c_db,
                rationale=custom_notes,
            )
            st.session_state["fiduciary_profile_result"] = p_result
            st.session_state["risk_tier"] = p_result.governing_tier.name
            st.session_state["risk_bucket"] = p_result.governing_tier.name
            st.session_state["user_risk_score"] = int(p_result.governing_tier)
            st.session_state["saa_target"] = p_result.target_saa.as_dict()
            st.success("✅ **Custom Asset Allocation Target Locked and Synchronized!**")

# -----------------------------------------------------------------------------
# COMMON RESULT DISPLAY & NAVIGATION
# -----------------------------------------------------------------------------
p_res = st.session_state.get("fiduciary_profile_result")
if p_res:
    st.markdown("---")
    st.subheader(f"🎯 Fiduciary Strategic Asset Allocation: {p_res.tier_label}")
    st.caption(f"**Expected Bear Market Drawdown:** {p_res.expected_drawdown_range} | **Governing Tier:** Tier {int(p_res.governing_tier)}")

    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric("Large-Cap Core", f"{p_res.target_saa.large_cap_pct:.1f}%", "Index / Bluechip Anchor")
    with col_m2:
        st.metric("Mid/Small-Cap Alpha", f"{p_res.target_saa.mid_small_cap_pct:.1f}%", "Growth Engine")
    with col_m3:
        st.metric("Total Equity SAA", f"{p_res.target_saa.total_equity_pct:.1f}%", "Max Equity Target")
    with col_m4:
        st.metric("Debt & Stability Cushion", f"{p_res.target_saa.debt_pct:.1f}%", "Capital Preservation")

    if p_res.binding_constraints:
        st.markdown("#### 🔒 Active Fiduciary Constraints & Disclosures")
        for c in p_res.binding_constraints:
            st.warning(f"🛡️ {c}")

    with st.expander("📝 Fiduciary Governance Rationale & Compliance Notes", expanded=True):
        st.markdown(p_res.fiduciary_rationale)

    # Navigation to next step
    st.markdown("---")
    col_nav1, col_nav2 = st.columns([2, 1])
    with col_nav1:
        st.info("💡 **Next Step:** SAA targets are locked and synchronized across all engines. Proceed to define your milestone financial goals.")
    with col_nav2:
        if st.button("➡️ Proceed to Step 3: Financial Goals", type="primary", use_container_width=True):
            st.switch_page("pages/3_Financial_Goals.py")
