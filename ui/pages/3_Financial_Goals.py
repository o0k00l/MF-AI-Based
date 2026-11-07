"""ui/pages/3_Financial_Goals.py — Sensible Milestone Goal Planner & SIP Sizing.

Integrates with the uploaded CAS portfolio, supports smart annual step-up SIPs,
and applies realistic horizon-adjusted compounding instead of blunt shortfalls.
"""
from __future__ import annotations

import sys
from pathlib import Path
_this_file = Path(__file__).resolve() if "__file__" in globals() else Path.cwd()
_REPO_ROOT = None
for _cand in [_this_file.parent, _this_file.parent.parent, _this_file.parent.parent.parent, Path.cwd()]:
    if (_cand / "services").is_dir() and (_cand / "data").is_dir():
        _REPO_ROOT = str(_cand)
        break
if not _REPO_ROOT:
    _REPO_ROOT = str(Path.cwd())
if _REPO_ROOT in sys.path:
    sys.path.remove(_REPO_ROOT)
sys.path.insert(0, _REPO_ROOT)

import streamlit as st
from services.goal_planner import plan_goal, compute_expected_cagr, decompose_sip_to_asset_sleeves

st.set_page_config(
    page_title="Financial Goal Wizard | Milestone SIP Planner",
    page_icon="🎯",
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

    st.markdown("<p style='font-weight: 700; font-size: 0.82rem; color: #334155; margin-bottom: 6px;'>🧭 TWO-STEP FIDUCIARY FLOW</p>", unsafe_allow_html=True)

    # Two-Step Fiduciary Flow
    st.page_link("app.py", label=f"Step 1: Portfolio Intake & Audit {'✅' if _has_cas else '⏳'}", icon="📊")
    st.page_link("pages/5_Fiduciary_Report.py", label=f"Step 2: Executive Fiduciary Report {'✅' if _has_cas else '⏳'}", icon="📄")

    st.markdown("<p style='font-weight: 700; font-size: 0.75rem; color: #64748b; margin-top: 10px; margin-bottom: 4px;'>🔬 OPTIONAL DEEP-DIVES</p>", unsafe_allow_html=True)
    st.page_link("pages/2_Risk_Profiler.py", label="Risk Profiler & SAA", icon="📋")
    st.page_link("pages/4_Debt_Allocation.py", label="True Debt Factsheet Matrix", icon="📈")
    st.page_link("pages/3_Financial_Goals.py", label="Financial Goals Wizard", icon="🎯")
    st.page_link("pages/1_Advisory_Flow.py", label="Advisory Roadmap", icon="🧭")

    st.markdown("---")
    if st.button("🔄 Reset / Clear Session", use_container_width=True, help="Clear active session portfolio and start over"):
        st.session_state.clear()
        st.rerun()

    st.caption("🛡️ **Fiduciary Standard:** SEBI (Investment Advisers) Regulations, 2013 | Non-execution authority | Zero distributor commission bias.")

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

target_saa = st.session_state.get("saa_target")
if target_saa:
    eq_p = target_saa.get("total_equity_pct", 75.0)
    db_p = target_saa.get("debt_pct", 25.0)
    blended_cagr = compute_expected_cagr(10, target_saa=target_saa)
    tier_name = str(st.session_state.get("risk_tier", "Evaluated Profile")).replace("_", " ").title()
    st.success(f"🎯 **Linked Fiduciary SAA ({tier_name}):** Target is **{eq_p:.0f}% Equity / {db_p:.0f}% Debt**. Milestones compound dynamically at **{blended_cagr:.2f}% p.a.** based on your verified risk profile.")
else:
    st.caption("ℹ️ *Default compounding applied. Complete Step 2: Risk Profiler to align goal returns with your exact SEBI asset allocation.*")

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
            target_saa=target_saa,
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
            target_saa=target_saa,
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
            target_saa=target_saa,
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
            target_saa=target_saa,
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

# --- Asset Allocation Decomposition of Monthly SIP ---
st.markdown("### 🏛️ Asset Sleeve Decomposition of Monthly SIP")
st.caption("Your monthly SIP budget is automatically mapped into direct asset class sleeves per your Strategic Asset Allocation (SAA):")
sleeves = decompose_sip_to_asset_sleeves(total_allocated_sip, target_saa=target_saa)
sc1, sc2, sc3 = st.columns(3)
with sc1:
    lc_pct_disp = target_saa.get('large_cap_pct', 50.0) if target_saa else 50.0
    st.metric("Large-Cap Core Index", f"₹{sleeves['large_cap_inr']:,.0f}/mo", f"{lc_pct_disp:.0f}% SAA Target")
with sc2:
    ms_pct_disp = target_saa.get('mid_small_cap_pct', 25.0) if target_saa else 25.0
    st.metric("Mid/Small-Cap Alpha", f"₹{sleeves['mid_small_cap_inr']:,.0f}/mo", f"{ms_pct_disp:.0f}% SAA Target")
with sc3:
    db_pct_disp = target_saa.get('debt_pct', 25.0) if target_saa else 25.0
    st.metric("Debt & Liquidity Cushion", f"₹{sleeves['debt_inr']:,.0f}/mo", f"{db_pct_disp:.0f}% SAA Target")

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

# --- AI Scenario Forecaster & Gap Mitigation Advisor ---
from services.goal_planner import evaluate_goal_scenarios_with_ai
goal_ai_diag = evaluate_goal_scenarios_with_ai(
    goals=configured_goals,
    total_budget_inr=float(sip_budget),
    portfolio=funds,
    target_saa=target_saa,
    use_live_ai=False,
)

with st.expander("🤖 AI Scenario Forecaster & Gap Mitigation Advisor", expanded=True):
    st.markdown(goal_ai_diag.get("ai_scenario_narrative", ""))
    
    st.markdown("#### 🔮 Stress-Testing & Life-Stage Scenarios")
    sc_cols = st.columns(3)
    for idx, sc in enumerate(goal_ai_diag.get("scenarios", [])):
        with sc_cols[idx % 3]:
            st.markdown(f"**{sc['scenario_name']}**")
            st.caption(sc["description"])
            st.metric("Future Target", f"₹{sc['target_corpus_inr']/100000:.1f}L", f"₹{sc['monthly_sip_inr']:,.0f}/mo SIP")
            st.caption(f"Status: {sc['budget_status']}")

    if goal_ai_diag.get("mitigation_paths"):
        st.markdown("#### ⚖️ Fiduciary Trade-Off & Gap Mitigation Options")
        for p in goal_ai_diag["mitigation_paths"]:
            st.markdown(p)

# --- 5. Save Plan & Session State Integration ---
session_allocation_payload = {
    "goals": goals_allocation_map,
    "total_required": round(total_required_sip, 2),
    "total_allocated": round(total_allocated_sip, 2),
    "total_gap": round(max(0.0, total_required_sip - total_allocated_sip), 2),
    "surplus": round(max(0.0, sip_budget - total_allocated_sip), 2),
    "use_step_up": use_step_up,
    "asset_sleeves": sleeves,
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
        st.switch_page("pages/5_Fiduciary_Report.py")
