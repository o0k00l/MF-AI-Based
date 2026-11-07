"""ui/pages/3_Financial_Goals.py — Sensible Milestone Goal Planner & SIP Sizing.

Integrates with the uploaded CAS portfolio, supports smart annual step-up SIPs,
and applies realistic horizon-adjusted compounding instead of blunt shortfalls.
"""
from __future__ import annotations

import streamlit as st
from services.goal_planner import plan_goal, compute_expected_cagr

st.set_page_config(
    page_title="Financial Goal Wizard | Milestone SIP Planner",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 Financial Goal Wizard & SIP Sizing")
st.markdown(
    "Plan realistic, achievable milestones. Your existing CAS portfolio investments "
    "compound towards your future targets, and optional **10% annual step-up SIPs** "
    "drastically reduce your initial monthly commitment to match career salary raises."
)

# --- 1. Detect Uploaded CAS Portfolio ---
funds = st.session_state.get("user_portfolio", [])
total_existing_corpus = sum(f.get("current_value", 0.0) for f in funds) if funds else 0.0

if total_existing_corpus > 0:
    st.info(
        f"💼 **Linked CAS Portfolio Detected:** You have **₹{total_existing_corpus/100000:.2f} Lakhs** "
        f"across {len(funds)} active funds. You can allocate portions of this existing wealth to compound towards your goals."
    )
else:
    st.info(
        "💡 **Tip:** Upload your CAS statement on the Portfolio Dashboard to automatically link your "
        "existing investments towards your future goals."
    )

st.markdown("---")

# --- 2. Monthly Budget & Step-Up Strategy ---
st.subheader("💰 Your Monthly Investment Capacity")
col_b1, col_b2 = st.columns([2, 1])

with col_b1:
    sip_budget = st.number_input(
        "Total Monthly SIP Budget (₹/month):",
        min_value=1_000,
        max_value=5_000_000,
        value=int(st.session_state.get("sip_budget", 40_000)),
        step=2_500,
        help="Total amount you can comfortably invest each month across all your financial goals.",
    )
with col_b2:
    use_step_up = st.checkbox(
        "Enable 10% Annual Step-Up SIP",
        value=True,
        help="Models a 10% annual increase in your SIP, matching normal salary increments. Lowers starting monthly SIP by ~35% to 50%!"
    )
    step_up_pct = 10.0 if use_step_up else 0.0

st.markdown("---")

# --- 3. Goal Selection & Configuration ---
st.subheader("🎯 Configure Your Financial Goals")
st.markdown("Select only the goals you are actively targeting:")

col_g1, col_g2, col_g3, col_g4 = st.columns(4)
with col_g1:
    want_retire = st.checkbox("🌴 Retirement", value=True)
with col_g2:
    want_edu = st.checkbox("🎓 Child Higher Education", value=False)
with col_g3:
    want_house = st.checkbox("🏠 House Purchase / Down Payment", value=False)
with col_g4:
    want_custom = st.checkbox("🛡️ Wealth Creation / Custom", value=False)

configured_goals = []

# --- Goal 1: Retirement ---
if want_retire:
    with st.expander("🌴 Retirement Planning (Priority 1)", expanded=True):
        st.markdown("**Plan your retirement nest egg:**")
        ret_mode = st.radio(
            "How would you like to estimate your retirement need?",
            ["By Desired Monthly Expenses (Recommended)", "By Target Corpus in Lakhs"],
            horizontal=True,
            key="ret_mode_radio",
        )
        c1, c2, c3 = st.columns(3)
        if "Monthly Expenses" in ret_mode:
            with c1:
                monthly_exp = st.number_input(
                    "Current Monthly Living Expenses to Maintain (₹/mo):",
                    min_value=10_000,
                    max_value=2_000_000,
                    value=50_000,
                    step=5_000,
                    help="Your expected monthly expenses in retirement in today's money value.",
                )
                # 4.8% Safe Withdrawal Rate rule: Corpus = (monthly_exp * 12) / 0.048
                cost_today_retire = (monthly_exp * 12) / 0.048
                st.caption(f"📐 *Implied Today's Corpus: **₹{cost_today_retire/100000:.1f} Lakhs** (at 4.8% Safe Withdrawal Rate)*")
        else:
            with c1:
                cost_lakhs_retire = st.number_input(
                    "Desired Retirement Corpus in Today's Value (₹ Lakhs):",
                    min_value=10.0,
                    max_value=5000.0,
                    value=150.0,
                    step=10.0,
                    help="Target corpus in today's money (e.g. 150 Lakhs = ₹1.5 Crore).",
                )
                cost_today_retire = cost_lakhs_retire * 100_000.0

        with c2:
            years_retire = st.slider("Years Until Retirement:", min_value=1, max_value=35, value=20, step=1, key="ret_yrs")
            inf_retire = st.number_input("Expected Inflation (% p.a.):", min_value=3.0, max_value=12.0, value=6.0, step=0.5, key="ret_inf")

        with c3:
            max_ret_alloc = float(total_existing_corpus)
            def_ret_alloc = min(max_ret_alloc * 0.5, cost_today_retire * 0.4) if max_ret_alloc > 0 else 0.0
            alloc_retire = st.number_input(
                "Earmark Existing Portfolio (₹ Lakhs):",
                min_value=0.0,
                max_value=max_ret_alloc / 100000.0 if max_ret_alloc > 0 else 500.0,
                value=def_ret_alloc / 100000.0,
                step=1.0,
                key="ret_alloc",
                help="Amount of existing mutual fund investments allocated to compound towards retirement.",
            ) * 100_000.0

        res_ret = plan_goal(
            goal_name="Retirement Corpus",
            cost_today_inr=cost_today_retire,
            horizon_years=years_retire,
            existing_allocated_corpus_inr=alloc_retire,
            inflation_rate_pct=inf_retire,
            annual_step_up_pct=step_up_pct,
            monthly_budget_capacity_inr=float(sip_budget),
        )
        configured_goals.append({
            "id": "retirement",
            "name": "Retirement Corpus",
            "priority": 1,
            "cost_today": cost_today_retire,
            "horizon": years_retire,
            "future_target": res_ret.future_target_inr,
            "existing_fv": res_ret.existing_corpus_future_val_inr,
            "required_sip": res_ret.step_up_initial_sip_inr if use_step_up else res_ret.flat_monthly_sip_inr,
            "flat_sip": res_ret.flat_monthly_sip_inr,
            "step_up_sip": res_ret.step_up_initial_sip_inr,
            "cagr": res_ret.expected_cagr_pct,
            "result": res_ret,
        })
        st.caption(
            f"🎯 Future Target Corpus at Year {years_retire}: **₹{res_ret.future_target_inr/100000:.1f} Lakhs** | "
            f"Existing Savings Compound to: **₹{res_ret.existing_corpus_future_val_inr/100000:.1f} Lakhs** | "
            f"Starting Monthly SIP: **₹{res_ret.step_up_initial_sip_inr if use_step_up else res_ret.flat_monthly_sip_inr:,.0f}/mo**"
        )

# --- Goal 2: Child Education ---
if want_edu:
    with st.expander("🎓 Child Higher Education (Priority 2)", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            cost_lakhs_edu = st.number_input(
                "Estimated College Cost in Today's Terms (₹ Lakhs):",
                min_value=5.0,
                max_value=300.0,
                value=25.0,
                step=2.5,
                help="Estimated degree fees in today's terms (e.g. 25 Lakhs = ₹25,00,000).",
                key="edu_cost",
            )
            cost_today_edu = cost_lakhs_edu * 100_000.0

        with c2:
            years_edu = st.slider("Years Until College Admission:", min_value=1, max_value=25, value=12, step=1, key="edu_yrs")
            inf_edu = st.number_input("Higher Education Inflation (% p.a.):", min_value=4.0, max_value=15.0, value=8.0, step=0.5, key="edu_inf")

        with c3:
            alloc_edu = st.number_input(
                "Earmark Existing Portfolio (₹ Lakhs):",
                min_value=0.0,
                max_value=max(10.0, total_existing_corpus / 100000.0),
                value=0.0,
                step=1.0,
                key="edu_alloc",
            ) * 100_000.0

        res_edu = plan_goal(
            goal_name="Child Higher Education",
            cost_today_inr=cost_today_edu,
            horizon_years=years_edu,
            existing_allocated_corpus_inr=alloc_edu,
            inflation_rate_pct=inf_edu,
            annual_step_up_pct=step_up_pct,
            monthly_budget_capacity_inr=float(sip_budget),
        )
        configured_goals.append({
            "id": "education",
            "name": "Child Higher Education",
            "priority": 2,
            "cost_today": cost_today_edu,
            "horizon": years_edu,
            "future_target": res_edu.future_target_inr,
            "existing_fv": res_edu.existing_corpus_future_val_inr,
            "required_sip": res_edu.step_up_initial_sip_inr if use_step_up else res_edu.flat_monthly_sip_inr,
            "flat_sip": res_edu.flat_monthly_sip_inr,
            "step_up_sip": res_edu.step_up_initial_sip_inr,
            "cagr": res_edu.expected_cagr_pct,
            "result": res_edu,
        })
        st.caption(
            f"🎯 Future College Target at Year {years_edu}: **₹{res_edu.future_target_inr/100000:.1f} Lakhs** | "
            f"Starting Monthly SIP: **₹{res_edu.step_up_initial_sip_inr if use_step_up else res_edu.flat_monthly_sip_inr:,.0f}/mo**"
        )

# --- Goal 3: House Purchase ---
if want_house:
    with st.expander("🏠 Home Down Payment / Purchase (Priority 3)", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            cost_lakhs_house = st.number_input(
                "Target Down Payment in Today's Terms (₹ Lakhs):",
                min_value=5.0,
                max_value=500.0,
                value=30.0,
                step=2.5,
                help="Estimated down payment + registration in today's terms (e.g. 30 Lakhs = ₹30,00,000).",
                key="house_cost",
            )
            cost_today_house = cost_lakhs_house * 100_000.0

        with c2:
            years_house = st.slider("Years Until Purchase:", min_value=1, max_value=15, value=5, step=1, key="house_yrs")
            inf_house = st.number_input("Real Estate Cost Inflation (% p.a.):", min_value=3.0, max_value=12.0, value=6.0, step=0.5, key="house_inf")

        with c3:
            alloc_house = st.number_input(
                "Earmark Existing Portfolio (₹ Lakhs):",
                min_value=0.0,
                max_value=max(10.0, total_existing_corpus / 100000.0),
                value=0.0,
                step=1.0,
                key="house_alloc",
            ) * 100_000.0

        res_house = plan_goal(
            goal_name="Home Down Payment",
            cost_today_inr=cost_today_house,
            horizon_years=years_house,
            existing_allocated_corpus_inr=alloc_house,
            inflation_rate_pct=inf_house,
            annual_step_up_pct=step_up_pct,
            monthly_budget_capacity_inr=float(sip_budget),
        )
        configured_goals.append({
            "id": "house",
            "name": "Home Down Payment",
            "priority": 3,
            "cost_today": cost_today_house,
            "horizon": years_house,
            "future_target": res_house.future_target_inr,
            "existing_fv": res_house.existing_corpus_future_val_inr,
            "required_sip": res_house.step_up_initial_sip_inr if use_step_up else res_house.flat_monthly_sip_inr,
            "flat_sip": res_house.flat_monthly_sip_inr,
            "step_up_sip": res_house.step_up_initial_sip_inr,
            "cagr": res_house.expected_cagr_pct,
            "result": res_house,
        })
        st.caption(
            f"🎯 Future Target at Year {years_house}: **₹{res_house.future_target_inr/100000:.1f} Lakhs** | "
            f"Starting Monthly SIP: **₹{res_house.step_up_initial_sip_inr if use_step_up else res_house.flat_monthly_sip_inr:,.0f}/mo**"
        )

# --- Goal 4: Custom Goal ---
if want_custom:
    with st.expander("🛡️ Wealth Creation / Custom Milestone (Priority 4)", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            custom_name = st.text_input("Goal Description:", value="Financial Freedom Reserve", key="cust_name")
            cost_lakhs_cust = st.number_input(
                "Target Corpus in Today's Terms (₹ Lakhs):",
                min_value=2.0,
                max_value=1000.0,
                value=20.0,
                step=2.0,
                key="cust_cost",
            )
            cost_today_cust = cost_lakhs_cust * 100_000.0

        with c2:
            years_cust = st.slider("Time Horizon (Years):", min_value=1, max_value=30, value=7, step=1, key="cust_yrs")
            inf_cust = st.number_input("Estimated Inflation (% p.a.):", min_value=3.0, max_value=12.0, value=6.0, step=0.5, key="cust_inf")

        with c3:
            alloc_cust = st.number_input(
                "Earmark Existing Portfolio (₹ Lakhs):",
                min_value=0.0,
                max_value=max(10.0, total_existing_corpus / 100000.0),
                value=0.0,
                step=1.0,
                key="cust_alloc",
            ) * 100_000.0

        res_cust = plan_goal(
            goal_name=custom_name,
            cost_today_inr=cost_today_cust,
            horizon_years=years_cust,
            existing_allocated_corpus_inr=alloc_cust,
            inflation_rate_pct=inf_cust,
            annual_step_up_pct=step_up_pct,
            monthly_budget_capacity_inr=float(sip_budget),
        )
        configured_goals.append({
            "id": "custom",
            "name": custom_name,
            "priority": 4,
            "cost_today": cost_today_cust,
            "horizon": years_cust,
            "future_target": res_cust.future_target_inr,
            "existing_fv": res_cust.existing_corpus_future_val_inr,
            "required_sip": res_cust.step_up_initial_sip_inr if use_step_up else res_cust.flat_monthly_sip_inr,
            "flat_sip": res_cust.flat_monthly_sip_inr,
            "step_up_sip": res_cust.step_up_initial_sip_inr,
            "cagr": res_cust.expected_cagr_pct,
            "result": res_cust,
        })

if not configured_goals:
    st.warning("⚠️ Please select at least one goal checkbox above to plan your portfolio.")
    st.stop()

st.markdown("---")

# --- 4. Priority-Based Waterfall Budget Allocation ---
st.subheader("📊 SIP Allocation by Priority")
st.markdown("Your monthly budget is allocated in priority order (Retirement > Education > Home > Wealth Creation):")

# Sort by priority
configured_goals.sort(key=lambda x: x["priority"])
remaining_budget = float(sip_budget)
goals_allocation_map = {}
total_required_sip = sum(g["required_sip"] for g in configured_goals)
total_allocated_sip = 0.0

summary_rows = []
for g in configured_goals:
    req = round(g["required_sip"], 2)
    alloc = min(req, max(0.0, remaining_budget))
    remaining_budget -= alloc
    total_allocated_sip += alloc
    gap = req - alloc
    
    status_icon = "🟢 Fully Funded" if gap <= 0 else ("🟡 Partially Funded" if alloc > 0 else "🔴 Awaiting Budget")

    goals_allocation_map[g["id"]] = {
        "goal_name": g["name"],
        "priority": g["priority"],
        "required_monthly": req,
        "allocated_monthly": alloc,
        "gap_monthly": gap,
        "target_corpus": g["future_target"],
        "horizon_years": g["horizon"],
    }

    summary_rows.append({
        "Milestone": g["name"],
        "Priority": f"P{g['priority']}",
        "Horizon": f"{g['horizon']} Years",
        "Target Corpus": f"₹{g['future_target']/100000:.1f}L",
        "Required SIP": f"₹{req:,.0f} /mo",
        "Allocated SIP": f"₹{alloc:,.0f} /mo",
        "Status": status_icon,
    })

st.table(summary_rows)

# Metric Summary Cards
col_m1, col_m2, col_m3, col_m4 = st.columns(4)
with col_m1:
    st.metric("Total Required SIP", f"₹{total_required_sip:,.0f}/mo")
with col_m2:
    st.metric("Total Monthly Budget", f"₹{sip_budget:,.0f}/mo")
with col_m3:
    st.metric("Budget Allocated", f"₹{total_allocated_sip:,.0f}/mo")
with col_m4:
    surplus = max(0.0, sip_budget - total_allocated_sip)
    shortfall = max(0.0, total_required_sip - total_allocated_sip)
    if shortfall > 0:
        st.metric("Budget Shortfall", f"₹{shortfall:,.0f}/mo", delta="-Deficit", delta_color="inverse")
    else:
        st.metric("Surplus Buffer", f"₹{surplus:,.0f}/mo", delta="+Surplus")

# --- 5. Save Plan & Session State Integration ---
session_allocation_payload = {
    "goals": goals_allocation_map,
    "total_required": round(total_required_sip, 2),
    "total_allocated": round(total_allocated_sip, 2),
    "total_gap": round(max(0.0, total_required_sip - total_allocated_sip), 2),
    "surplus": round(max(0.0, sip_budget - total_allocated_sip), 2),
    "use_step_up": use_step_up,
}

st.session_state["goals_allocation"] = session_allocation_payload
st.session_state["goals_list"] = configured_goals
st.session_state["sip_budget"] = sip_budget

st.success("✅ **Goal Plan Saved to Session!** Your targets are synchronized with your Advisory Report.")

# Navigation Action
st.markdown("---")
col_act1, col_act2 = st.columns([2, 1])
with col_act1:
    st.info("💡 **Next Step:** Review your unbundled debt allocation or generate your formal Executive Review Report.")
with col_act2:
    if st.button("📄 Generate Executive Fiduciary Report", type="primary", use_container_width=True):
        st.switch_page("pages/4_Fiduciary_Report.py")
