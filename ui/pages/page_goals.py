"""
ui/pages/page_goals.py — Financial Goal Waterfall & Milestone Planning.
Calculates future inflation-adjusted corpus requirements and monthly SIP sizing.
"""
from __future__ import annotations

import streamlit as st
import pandas as pd
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def render_goals_page() -> None:
    st.header("🎯 Financial Goal Waterfall & SIP Sizing")
    st.caption("Plan your milestone goals with compounding mathematics, inflation adjustment, and SIP budget distribution.")

    col_b1, col_b2 = st.columns([1.5, 1.0])
    with col_b1:
        monthly_budget = st.number_input(
            "Total Monthly Investment Capacity (₹):",
            value=100000,
            step=5000,
            min_value=5000,
            max_value=2000000
        )
    with col_b2:
        st.metric("Monthly Flow", f"₹{monthly_budget:,.0f}/mo")

    st.divider()

    st.subheader("🏁 Core Milestones")

    goals = [
        {"name": "Retirement Corpus", "today_cost": 50000000.0, "years": 15, "inflation": 6.0, "priority": 1},
        {"name": "Child Higher Education", "today_cost": 10000000.0, "years": 10, "inflation": 8.0, "priority": 2},
        {"name": "Home Purchase / Upgrade", "today_cost": 8000000.0, "years": 5, "inflation": 6.0, "priority": 3},
    ]

    goal_results = []
    tot_req_sip = 0.0

    for idx, g in enumerate(goals):
        with st.expander(f"📌 Goal {idx+1}: {g['name']} (Priority #{g['priority']})", expanded=True):
            gc1, gc2, gc3 = st.columns(3)
            with gc1:
                cost = st.number_input(f"Today's Estimated Cost (₹) - {g['name']}:", value=int(g["today_cost"]), step=500000, key=f"cost_{idx}")
            with gc2:
                years = st.number_input(f"Time Horizon (Years) - {g['name']}:", value=int(g["years"]), min_value=1, max_value=35, key=f"yr_{idx}")
            with gc3:
                inf = st.number_input(f"Estimated Inflation (% p.a.) - {g['name']}:", value=float(g["inflation"]), step=0.5, key=f"inf_{idx}")

            # Future Value with inflation
            fv = cost * ((1 + inf / 100.0) ** years)

            # Required monthly SIP assuming 12% annual equity/debt CAGR
            r_mo = 0.12 / 12.0
            n_mo = years * 12
            fv_factor = (((1 + r_mo) ** n_mo) - 1) / r_mo
            req_sip = fv / fv_factor

            tot_req_sip += req_sip

            st.markdown(
                f"🎯 **Target Future Corpus:** <span style='color:#63b3ed; font-weight:bold;'>₹{fv:,.0f}</span> &nbsp;&nbsp;|&nbsp;&nbsp; "
                f"💸 **Required Monthly SIP:** <span style='color:#68d391; font-weight:bold;'>₹{req_sip:,.0f}/mo</span>",
                unsafe_allow_html=True
            )

            goal_results.append({
                "Goal": g["name"],
                "Horizon (Years)": f"{years} yrs",
                "Today's Cost": f"₹{cost:,.0f}",
                "Future Corpus Needed": f"₹{fv:,.0f}",
                "Required Monthly SIP": f"₹{req_sip:,.0f}",
                "Priority": g["priority"]
            })

    st.divider()

    st.subheader("📊 Goal Waterfall Summary vs. Monthly Capacity")
    summary_df = pd.DataFrame(goal_results)
    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    scol1, scol2 = st.columns(2)
    with scol1:
        st.metric("Total Monthly SIP Required", f"₹{tot_req_sip:,.0f}")
    with scol2:
        diff = monthly_budget - tot_req_sip
        st.metric("Budget Surplus / (Deficit)", f"₹{diff:,.0f}", delta=f"{diff:+,.0f}", delta_color="normal")


if __name__ == "__main__":
    render_goals_page()

