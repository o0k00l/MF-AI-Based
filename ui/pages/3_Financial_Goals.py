"""ui/pages/3_Financial_Goals.py — Sensible Milestone Goal Planner & SIP Sizing.

Integrates with the uploaded CAS portfolio, supports smart annual step-up SIPs,
and applies realistic horizon-adjusted compounding instead of blunt shortfalls.
"""
from __future__ import annotations

import streamlit as st
from services.goal_planner import plan_goal, compute_expected_cagr

st.set_page_config(
    page_title="Financial Goal Planner | Fiduciary Milestones",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 Sensible Financial Goal Planner & SIP Sizing")
st.caption(
    "Plan milestone goals with compounding math, existing CAS portfolio integration, "
    "and realistic 10% annual step-up SIP projections."
)

# --- Check Existing CAS Portfolio ---
funds = st.session_state.get("user_portfolio", [])
total_existing_corpus = sum(f.get("current_value", 0.0) for f in funds) if funds else 0.0

if total_existing_corpus > 0:
    st.success(
        f"💼 **Linked CAS Portfolio Detected:** You have **₹{total_existing_corpus/100000:.2f} Lakhs** "
        f"across {len(funds)} schemes. You can allocate a portion of this existing corpus to fund your goals."
    )
else:
    st.info(
        "💡 **Tip:** Upload your CAS statement on the main Portfolio Dashboard to automatically compound your "
        "existing investments towards your goals."
    )

st.divider()

# --- Sensible Preset Configurations ---
PRESETS = {
    "🏖️ Retirement Corpus": {"cost": 30000000.0, "years": 15, "inf": 6.0},
    "🎓 Child Higher Education": {"cost": 2500000.0, "years": 10, "inf": 8.0},
    "🏠 Home Down Payment / Purchase": {"cost": 4000000.0, "years": 5, "inf": 6.0},
    "🛡️ Financial Independence (FIRE)": {"cost": 25000000.0, "years": 12, "inf": 6.0},
    "🎯 Custom Goal": {"cost": 2000000.0, "years": 5, "inf": 6.0},
}

selected_preset = st.selectbox("Select Goal Category to Plan:", list(PRESETS.keys()), index=0)
cfg = PRESETS[selected_preset]

# --- Sensible Goal Inputs ---
col1, col2 = st.columns(2)

with col1:
    goal_name = st.text_input("Goal Name / Milestone:", value=selected_preset.split(" ", 1)[-1])
    cost_today = st.number_input(
        "Estimated Cost in Today's Terms (₹):",
        min_value=100000.0,
        max_value=500000000.0,
        value=float(cfg["cost"]),
        step=500000.0,
        help="How much this goal would cost if you paid for it today.",
    )
    horizon_yrs = st.slider(
        "Time Horizon (Years until Goal):",
        min_value=1,
        max_value=35,
        value=int(cfg["years"]),
        help="Number of years before you need this capital.",
    )
    inf_rate = st.number_input(
        "Estimated Annual Inflation (% p.a.):",
        min_value=2.0,
        max_value=15.0,
        value=float(cfg["inf"]),
        step=0.5,
        help="Higher education typically experiences 7-8% inflation; general lifestyle averages 6%.",
    )

with col2:
    max_allocable = float(total_existing_corpus)
    default_alloc = min(max_allocable * 0.4, cost_today * 0.5) if max_allocable > 0 else 0.0
    allocated_existing = st.number_input(
        "Allocate From Existing Portfolio (₹):",
        min_value=0.0,
        max_value=max_allocable if max_allocable > 0 else 100000000.0,
        value=float(default_alloc),
        step=100000.0,
        help="Amount of existing invested mutual funds earmarked to compound for this goal.",
    )
    step_up_pct = st.slider(
        "Annual SIP Step-Up (% p.a.):",
        min_value=0,
        max_value=25,
        value=10,
        step=1,
        help="Market standard is 8-10% annual increment as your career income grows.",
    )
    monthly_budget = st.number_input(
        "Your Monthly Investment Capacity for this Goal (₹/month):",
        min_value=0.0,
        max_value=2000000.0,
        value=25000.0,
        step=2500.0,
        help="Current monthly budget you can commit to start investing for this goal.",
    )

st.divider()

# --- Run Sensible Fiduciary Calculation ---
result = plan_goal(
    goal_name=goal_name,
    cost_today_inr=cost_today,
    horizon_years=horizon_yrs,
    existing_allocated_corpus_inr=allocated_existing,
    inflation_rate_pct=inf_rate,
    annual_step_up_pct=float(step_up_pct),
    monthly_budget_capacity_inr=monthly_budget,
)

# --- Display Clear Results & Metrics ---
st.subheader(f"📊 Projection Breakdown: {goal_name}")

m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Future Value Needed", f"₹{result.future_target_inr/100000:.2f} Lakhs", f"Inflation: {inf_rate:.1f}%")
with m2:
    st.metric("Existing Corpus Future Value", f"₹{result.existing_corpus_future_val_inr/100000:.2f} Lakhs", f"{result.existing_corpus_coverage_pct:.1f}% covered")
with m3:
    st.metric("Smart Step-Up Starting SIP", f"₹{result.step_up_initial_sip_inr:,.0f}/mo", f"{step_up_pct}% annual hike")
with m4:
    st.metric("Flat Fixed SIP (No Step-Up)", f"₹{result.flat_monthly_sip_inr:,.0f}/mo", f"CAGR: {result.expected_cagr_pct:.1f}%")

st.divider()

# --- Actionable Fiduciary Guidance ---
st.subheader("💡 Actionable Feasibility Analysis")
st.markdown(result.actionable_advice)

# Comparison Table
st.markdown("#### 📈 Compounding Comparison: Step-Up vs. Fixed Flat SIP")
st.table({
    "Plan Option": ["🚀 Smart Step-Up SIP (10% Annual Growth)", "⚓ Traditional Flat Fixed SIP"],
    "Starting Monthly Outlay (Year 1)": [f"₹{result.step_up_initial_sip_inr:,.0f} / month", f"₹{result.flat_monthly_sip_inr:,.0f} / month"],
    "Cashflow Relief in Year 1": [f"Saves ₹{max(0.0, result.flat_monthly_sip_inr - result.step_up_initial_sip_inr):,.0f} / month", "Baseline (Higher initial strain)"],
    "Existing Portfolio Earmarked": [f"₹{allocated_existing:,.0f} compounding at {result.expected_cagr_pct:.1f}%", f"₹{allocated_existing:,.0f} compounding at {result.expected_cagr_pct:.1f}%"],
    "Net Milestone Status": [result.feasibility_status, result.feasibility_status],
})

