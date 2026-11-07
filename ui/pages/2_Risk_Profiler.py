"""SEBI-Compliant Fiduciary Risk Profiler Page.

Evaluates Financial Risk Capacity and Emotional Loss Tolerance separately
under SEBI (Investment Advisers) Regulations, 2013 (Schedule III).
Enforces the Binding Constraint Principle:
    Governing Risk Tier = min(Capacity Tier, Tolerance Tier)
"""
from __future__ import annotations

import streamlit as st
from services.risk_profiler import evaluate_fiduciary_profile, SebiRiskTier

st.set_page_config(
    page_title="SEBI Risk Profiler | Binding Constraint SAA",
    page_icon="📋",
    layout="wide",
)

st.title("📋 SEBI Risk Profiler & Strategic Asset Allocation (SAA)")
st.markdown(
    "A fiduciary risk assessment evaluates **Financial Capacity** (ability to absorb losses) "
    "and **Emotional Risk Tolerance** (willingness to withstand bear markets) separately. "
    "Per SEBI regulations and CFA standards, your **Governing Risk Tier** is strictly constrained "
    "by the lower of the two (*The Weakest Link Principle*)."
)

# Detect portfolio context
funds = st.session_state.get("user_portfolio", [])
total_corpus = sum(f.get("current_value", 0.0) for f in funds) if funds else 0.0

if total_corpus > 0:
    st.info(f"💼 **Linked Portfolio:** Analyzing risk for portfolio of **₹{total_corpus/100000:.2f} Lakhs** ({len(funds)} active schemes).")
else:
    st.caption("💡 *Tip: Upload your CAS & CGS statements on the Portfolio Dashboard to compare your current portfolio against your target SAA.*")

st.markdown("---")

with st.form("sebi_fiduciary_profiler_form"):
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🔹 1. Financial Risk Capacity")
        st.caption("Objective financial ability to endure portfolio declines without financial distress.")

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
            help="Variable income necessitates a higher debt cushion to absorb earnings volatility.",
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
            help="High debt commitments restrict capacity to hold volatile equity allocations.",
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
            help="Investors with demonstrated cycle experience have proven behavioral endurance.",
        )

        q_goal_criticality = st.selectbox(
            "Criticality of Underlying Financial Goals",
            options=[
                "Non-Negotiable (Essential capital: child college, home down payment)",
                "Somewhat Flexible (Target year can shift by 1-2 years if needed)",
                "Fully Discretionary (Wealth creation / aspirational milestones)",
            ],
            index=1,
            help="Essential non-negotiable milestones enforce lower equity exposure as target date approaches.",
        )

        q_lockin = st.selectbox(
            "Willingness to Commit Capital Without Premature Withdrawal",
            options=[
                "High (Comfortable committing funds for 5+ years)",
                "Moderate (May need access within 3-5 years)",
                "Low (May require immediate liquidity on short notice)",
            ],
            index=0,
        )

    submit_profiler = st.form_submit_button("📊 Evaluate SEBI Fiduciary SAA Target", type="primary", use_container_width=True)

if submit_profiler:
    inc_key = "stable" if "stable" in q_income.lower() else ("variable" if "variable" in q_income.lower() else "retired")
    exp_key = "experienced" if "experienced" in q_exp.lower() else ("moderate" if "moderate" in q_exp.lower() else "beginner")

    profile_result = evaluate_fiduciary_profile(
        horizon_years=float(q_horizon),
        max_drawdown_tolerance_pct=float(q_drop),
        emergency_fund_months=float(q_emergency),
        income_stability=inc_key,
        emi_burden_pct=float(q_emi),
        experience_level=exp_key,
    )

    # Persist in session state
    st.session_state["fiduciary_profile_result"] = profile_result
    st.session_state["risk_tier"] = profile_result.governing_tier.name
    st.session_state["risk_bucket"] = profile_result.governing_tier.name
    st.session_state["user_risk_score"] = int(profile_result.governing_tier)
    st.session_state["saa_target"] = profile_result.target_saa.as_dict()

    st.success("✅ **Risk Profile Computed and Synchronized with Session State!**")

# Display Result
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
        st.markdown("#### 🔒 Active Fiduciary Binding Limiters")
        for c in p_res.binding_constraints:
            st.warning(f"🛡️ **Binding Constraint Applied:** {c}")

    with st.expander("📝 Fiduciary Governance Rationale & Compliance Notes", expanded=True):
        st.markdown(p_res.fiduciary_rationale)
        st.markdown(
            "- **Capacity Tier:** " + str(p_res.capacity_tier.name).replace("_", " ").title() + "<br>"
            "- **Tolerance Tier:** " + str(p_res.tolerance_tier.name).replace("_", " ").title() + "<br>"
            "- **Binding Rule:** $\\text{Governing Tier} = \\min(\\text{Capacity}, \\text{Tolerance})$",
            unsafe_allow_html=True,
        )

    # Navigation to next step
    st.markdown("---")
    col_nav1, col_nav2 = st.columns([2, 1])
    with col_nav1:
        st.info("💡 **Next Step:** SAA targets are locked. Proceed to define your milestone financial goals.")
    with col_nav2:
        if st.button("➡️ Proceed to Step 3: Financial Goals", type="primary", use_container_width=True):
            st.switch_page("pages/3_Financial_Goals.py")
