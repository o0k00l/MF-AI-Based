"""
app.py — Fiduciary Wealth Copilot (Streamlit Web Dashboard)
Executive-grade, 100% grounded fiduciary mutual funds copilot.
Powered by deterministic financial mathematics and SEBI fee-only advisory standards.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from advisor import get_default_paths
from core.math_engine import (
    aggregate_fiduciary_facts,
    compute_deterministic_sip_blueprint,
    compute_deterministic_lumpsum_blueprint,
    _parse_sebi_risk_tier,
    compute_personal_redemption_plan,
)
from core.prompt_advisor import answer_interactive_query
from core.pdf_exporter import convert_markdown_file_to_pdf
from ui.pages.page_upload import render_upload_page
from ui.pages.page_profile import render_profile_page

# Page Configuration must be first Streamlit command
st.set_page_config(
    page_title="Wealth Copilot | Fiduciary Portfolio Engine",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

from advisor import discover_client_portfolios

# Discover Available Portfolios
available_ports = discover_client_portfolios(ROOT)
if not available_ports:
    available_ports = {"lalit_portfolio": ROOT / "data" / "lalit_portfolio"}

with st.sidebar:
    st.markdown("### 💼 Portfolio Selection")
    client_list = list(available_ports.keys())
    default_idx = client_list.index("lalit_portfolio") if "lalit_portfolio" in client_list else 0
    selected_client_key = st.selectbox(
        "Select Client Account:",
        options=client_list,
        index=default_idx
    )

# Load Verified Ground Truth Facts
@st.cache_data(ttl=300)
def load_portfolio_facts(client_target: str = "lalit_portfolio"):
    cas, metrics, config, aliases, outputs = get_default_paths(client_target)
    facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)
    return facts

try:
    facts = load_portfolio_facts(selected_client_key)
except Exception as e:
    st.error(f"Error loading portfolio data for '{selected_client_key}': {e}")
    st.stop()

client_name = facts.client_name
f1 = facts.fee_bleed
tot_val = facts.total_portfolio_value_inr
tot_inv = facts.total_invested_value_inr
tot_gain = facts.total_unrealized_gain_inr

# Minimal Styling
st.markdown("""
<style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1120px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.65rem;
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar (Metadata)
with st.sidebar:
    st.markdown("### 💼 Portfolio Summary")
    st.markdown(f"**Investor:** {client_name}")
    st.markdown(f"**Age:** {facts.client_age or 35} | **Horizon:** {facts.horizon_years or 10} Years")
    st.markdown(f"**Total AUM:** ₹{tot_val/100000:.2f} Lakhs")
    st.markdown(f"**Regular AUM:** ₹{f1.regular_portfolio_value_inr/100000:.2f} Lakhs")
    st.markdown(f"**Annual Fee Bleed:** ₹{f1.annual_bleed_inr:,.0f} / yr")
    if facts.stability_buffer:
        st.markdown(f"**Stability Buffer:** {facts.stability_buffer.total_stability_buffer_pct:.2f}%")

# Header & Profile
col_head1, col_head2 = st.columns([1.7, 1.3])
with col_head1:
    st.title("🛡️ Wealth Copilot")
    st.caption(f"Investor: **{client_name}** • Risk Mandate: **{facts.risk_tier_name}** • 100% Fee-Only Direct Advisory")

risk_options = {
    "Tier 6 (Very High)": "🔴 Tier 6: Aggressive Equity (100% Eq / 0% Debt)",
    "Tier 5 (High)": "🟠 Tier 5: Growth SAA (85% Eq / 15% Debt)",
    "Tier 4 (Moderate High)": "🟡 Tier 4: Moderately High (70% Eq / 30% Debt)",
    "Tier 3 (Moderate)": "🟡 Tier 3: Moderate Hybrid (50% Eq / 50% Debt)",
    "Tier 2 (Low)": "🟢 Tier 2: Conservative (20% Eq / 80% Debt)",
    "Tier 1 (Capital Preservation)": "🛡️ Tier 1: Capital Preservation (0% Eq / 100% Debt)",
}

with col_head2:
    selected_tier = st.selectbox(
        "Investor SAA Risk Profile:",
        options=list(risk_options.keys()),
        format_func=lambda k: risk_options[k],
        index=0,
        help="Strategic Asset Allocation profile per SEBI (Investment Advisers) Regulations."
    )

# Top 4 High-Impact KPIs
c1, c2, c3, c4 = st.columns(4)
with c1:
    gain_pct = (tot_gain / tot_inv * 100) if tot_inv > 0 else 0.0
    st.metric(
        label="Portfolio Valuation",
        value=f"₹{tot_val/100000:.2f} Lakh",
        delta=f"+₹{tot_gain/100000:.2f} L (+{gain_pct:.1f}% Gain)"
    )
with c2:
    st.metric(
        label="Recoverable Broker Bleed",
        value=f"₹{f1.annual_bleed_inr:,.0f} / yr",
        delta=f"{f1.regular_funds_count} Regular Plans to Switch",
        delta_color="inverse"
    )
with c3:
    xirr_val = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "N/A"
    alpha_val = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "N/A"
    st.metric(
        label="Portfolio Return (XIRR)",
        value=xirr_val,
        delta=f"{alpha_val} Alpha vs Benchmark" if alpha_val != "N/A" else None
    )
with c4:
    stab_pct = facts.stability_buffer.total_stability_buffer_pct if facts.stability_buffer else 0.0
    t_num = _parse_sebi_risk_tier(selected_tier)
    if t_num == 6:
        delta_c4 = f"Tier 6 Target Satisfied ({stab_pct:.2f}% buffer)"
        delta_col_c4 = "normal"
    else:
        d_target = 15 if t_num == 5 else (30 if t_num == 4 else (50 if t_num == 3 else (80 if t_num == 2 else 100)))
        delta_c4 = f"Tier {t_num} SAA Mandate ({d_target}% Fixed Income)"
        delta_col_c4 = "off"
    st.metric(
        label="Stability Cushion",
        value=f"{stab_pct:.2f}% Buffer",
        delta=delta_c4,
        delta_color=delta_col_c4
    )

st.write("")

# 6 Main Tabs
tab_switch, tab_fresh, tab_redeem, tab_copilot, tab_upload, tab_profile = st.tabs([
    f"📋 Switch to Direct (Save ₹{f1.annual_bleed_inr/1000:.0f}k/yr)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💸 Personal Redemption Planner",
    "💬 Ask Copilot & Reports",
    "📤 Upload Statement",
    "⚖️ Risk Profiler & Tolerances"
])

# ═══════════════════════════════════════════════════════════════════════
# TAB 1: SWITCH TO DIRECT (SAVE ₹41K/YR)
# ═══════════════════════════════════════════════════════════════════════
with tab_switch:
    st.info(
        f"💡 Switching your {f1.regular_funds_count} Regular plans to Direct saves **₹{f1.annual_bleed_inr:,.0f} every year** in distributor commissions. "
        f"Over 10 years at 12% CAGR, this preserves **₹{f1.ten_year_compounded_loss_inr:,.0f}** in wealth. "
        f"Under our 3-Phase Fiduciary Roadmap, mature lots are switched under the **₹1.25 Lakh Section 112A tax exemption with ₹0 exit loads**."
    )

    csv_file = Path("outputs/MFCentral_Action_Checklist.csv")
    if not csv_file.exists():
        import generate_checklist
        generate_checklist.generate_mfcentral_checklist(
            regular_funds=getattr(f1, 'regular_funds', None),
            annual_bleed_inr=getattr(f1, 'annual_bleed_inr', 0.0)
        )

    if csv_file.exists():
        df = pd.read_csv(csv_file)
        col_name = "Current Scheme Name" if "Current Scheme Name" in df.columns else df.columns[1]
        col_val = "Current Value (INR)" if "Current Value (INR)" in df.columns else df.columns[3]
        col_saved = "Annual Commission Saved (INR)" if "Annual Commission Saved (INR)" in df.columns else df.columns[4]
        col_action = "Recommended Action" if "Recommended Action" in df.columns else df.columns[2]
        col_target = "Target Direct Scheme" if "Target Direct Scheme" in df.columns else df.columns[-1]

        view_choice = st.radio(
            "Show Holdings:",
            [f"{f1.regular_funds_count} Regular Funds to Switch", f"All {len(df)} Holdings"],
            horizontal=True,
            label_visibility="collapsed"
        )

        if "Regular" in view_choice:
            display_df = df[~df[col_action].astype(str).str.contains("RETAIN", case=False, na=False)].copy()
        else:
            display_df = df.copy()

        st.dataframe(
            display_df[[col_name, col_val, col_saved, col_action, col_target]],
            width="stretch",
            hide_index=True,
            column_config={
                col_name: st.column_config.TextColumn("Scheme Name", width="large"),
                col_val: st.column_config.TextColumn("Current Value (₹)", width="medium"),
                col_saved: st.column_config.TextColumn("Saved (₹/yr)", width="medium"),
                col_action: st.column_config.TextColumn("Fiduciary Action", width="medium"),
                col_target: st.column_config.TextColumn("Switch Target (Direct Plan)", width="large"),
            }
        )

        dcol1, dcol2 = st.columns([1, 2])
        with dcol1:
            st.download_button(
                label="📥 Download Switch Checklist (CSV)",
                data=csv_file.read_bytes(),
                file_name=f"MFCentral_Switch_Checklist_{client_name.lower().replace(' ', '_')}.csv",
                mime="text/csv",
                width="stretch"
            )
        with dcol2:
            st.caption("Execute on **MFCentral** (Official Zero-Fee AMFI Platform): Service Requests → Switch Funds.")


# ═══════════════════════════════════════════════════════════════════════
# TAB 2: FRESH MONEY (SIP & LUMPSUM) — UNIVERSAL 4-SLOT ENGINE
# ═══════════════════════════════════════════════════════════════════════
with tab_fresh:
    b1, b2 = st.columns(2)
    with b1:
        sip_input = st.number_input(
            "Monthly SIP Budget (₹):",
            value=int(facts.monthly_sip_budget_inr),
            step=5000
        )
    with b2:
        lumpsum_input = st.number_input(
            "Fresh Lumpsum Capital (₹):",
            value=int(getattr(facts, "lumpsum_budget_inr", 0.0) or 0.0),
            step=25000
        )

    # 1. Deterministic SIP Blueprint (Pure Quantitative Execution)
    sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=float(sip_input),
        risk_tier=selected_tier,
        stability_buffer_pct=stab_pct,
        holdings=facts.holdings,
        client_aum=tot_val
    )

    st.markdown("### 1. Deterministic Direct SIP Blueprint")
    if sip_plan.debt_sip_pct > 0:
        st.caption(f"🎯 **{selected_tier} SAA Mandate:** {sip_plan.equity_sip_pct:.0f}% Equity Compounding / {sip_plan.debt_sip_pct:.0f}% High-Grade Fixed Income Cushion across {len(sip_plan.items)} Direct Schemes.")
    else:
        st.caption(f"🎯 **100% Equity Compounding Mandate:** Zero standalone debt drag ({stab_pct:.2f}% look-through stability buffer satisfies Tier 6 debt target).")

    # SIP KPI Summary Cards
    sip_c1, sip_c2, sip_c3, sip_c4 = st.columns(4)
    with sip_c1:
        st.metric("Total Monthly SIP", f"₹{sip_plan.total_monthly_budget_inr:,.0f} / mo")
    with sip_c2:
        eq_sip_amt = sum(x.monthly_inr for x in sip_plan.items if "debt" not in x.category_role.lower() and "preservation" not in x.category_role.lower())
        st.metric("Equity SIP Sleeve", f"₹{eq_sip_amt:,.0f} / mo", f"{sip_plan.equity_sip_pct:.0f}% Allocation")
    with sip_c3:
        debt_sip_amt = sum(x.monthly_inr for x in sip_plan.items if "debt" in x.category_role.lower() or "preservation" in x.category_role.lower())
        st.metric("Debt Anchor Sleeve", f"₹{debt_sip_amt:,.0f} / mo", f"{sip_plan.debt_sip_pct:.0f}% Fixed Income")
    with sip_c4:
        st.metric("Direct Funds Count", f"{len(sip_plan.items)} Funds", "100% Direct Plans")

    sip_rows = []
    for item in sip_plan.items:
        f_str = item.folio_target if item.folio_target else "New Direct Folio"
        sip_rows.append({
            "Category Role": item.category_role,
            "Recommended Direct Scheme": item.scheme_name,
            "Target Folio": f_str,
            "Allocation": f"{item.allocation_pct:.1f}%",
            "Monthly SIP": f"₹{item.monthly_inr:,.0f} / mo",
            "Fiduciary Rationale": item.fiduciary_rationale
        })

    st.dataframe(
        pd.DataFrame(sip_rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Category Role": st.column_config.TextColumn("Category Role", width="medium"),
            "Recommended Direct Scheme": st.column_config.TextColumn("Recommended Direct Scheme", width="large"),
            "Target Folio": st.column_config.TextColumn("Target Folio", width="small"),
            "Allocation": st.column_config.TextColumn("Alloc %", width="small"),
            "Monthly SIP": st.column_config.TextColumn("Monthly SIP (₹)", width="medium"),
            "Fiduciary Rationale": st.column_config.TextColumn("Fiduciary Rationale", width="large"),
        }
    )

    # 2. Deterministic Lumpsum Blueprint
    if facts.stability_buffer:
        bank_tot = facts.stability_buffer.bank_deployable_cash_inr + facts.stability_buffer.emergency_reserve_inr
        em_res = facts.stability_buffer.emergency_reserve_inr
    elif facts.cash_plan:
        bank_tot = facts.cash_plan.bank_cash_inr
        em_res = facts.cash_plan.emergency_buffer_inr
    else:
        bank_tot = 0.0
        em_res = 0.0
    lump_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=float(lumpsum_input),
        bank_cash_total=bank_tot,
        emergency_reserve=em_res,
        holdings=facts.holdings,
        risk_tier=selected_tier,
        stability_buffer_pct=stab_pct
    )

    st.markdown("### 2. Institutional Lumpsum Deployment Strategy")
    st.caption(f"Execution Horizon: **{lump_plan.stp_duration_months} Months STP** • Parking Vehicle: **{lump_plan.parking_vehicle}**")

    # Lumpsum KPI Summary Cards
    lump_c1, lump_c2, lump_c3, lump_c4 = st.columns(4)
    with lump_c1:
        st.metric("Total Lumpsum", f"₹{lump_plan.total_lumpsum_inr:,.0f}", f"{len(lump_plan.tranches)} Deployment Legs")
    with lump_c2:
        st.metric("Day-1 Immediate", f"₹{lump_plan.immediate_amount_inr:,.0f}", "Anchor Execution")
    with lump_c3:
        if lump_plan.stp_duration_months > 0:
            st.metric("STP Staggered", f"₹{lump_plan.stp_total_amount_inr:,.0f}", f"₹{lump_plan.monthly_stp_total_inr:,.0f}/mo × {lump_plan.stp_duration_months}M")
        else:
            st.metric("STP Staggered", "₹0", "Zero Equity Drag")
    with lump_c4:
        if lump_plan.tax_savings_vs_debt_fund_inr > 0:
            st.metric("Arbitrage Tax Saved", f"₹{lump_plan.tax_savings_vs_debt_fund_inr:,.0f}", "Sec 50AA Shield")
        else:
            st.metric("Parking Vehicle", "Direct Plan", "Zero Exit Load")

    lump_rows = []
    for tr in lump_plan.tranches:
        f_str = tr.folio_target if tr.folio_target else "New Direct Folio"
        lump_rows.append({
            "Deployment Leg": tr.role,
            "Destination Scheme": tr.scheme_name,
            "Target Folio": f_str,
            "Amount (₹)": f"₹{tr.amount_inr:,.0f}",
            "Alloc %": f"{tr.allocation_pct:.1f}%",
            "Timing & Horizon": tr.timing,
            "Source Vehicle": tr.source_vehicle,
            "Fiduciary Rationale": tr.fiduciary_rationale
        })

    st.dataframe(
        pd.DataFrame(lump_rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Deployment Leg": st.column_config.TextColumn("Deployment Leg", width="medium"),
            "Destination Scheme": st.column_config.TextColumn("Destination Scheme", width="large"),
            "Target Folio": st.column_config.TextColumn("Target Folio", width="small"),
            "Amount (₹)": st.column_config.TextColumn("Amount", width="medium"),
            "Alloc %": st.column_config.TextColumn("Alloc %", width="small"),
            "Timing & Horizon": st.column_config.TextColumn("Timing & Horizon", width="medium"),
            "Source Vehicle": st.column_config.TextColumn("Source Vehicle", width="medium"),
            "Fiduciary Rationale": st.column_config.TextColumn("Fiduciary Rationale", width="large"),
        }
    )

    if lump_plan.tax_savings_vs_debt_fund_inr > 0:
        st.success(f"💰 **Tax Arbitrage Shield:** Parking in Equity Arbitrage rather than Debt Liquid saves an estimated **₹{lump_plan.tax_savings_vs_debt_fund_inr:,.2f}** in slab tax (Section 50AA vs 112A/111A).")

    if lump_plan.cash_validation_passed:
        st.info(f"🛡️ **Cash Reality Check:** {lump_plan.cash_validation_message}")
    else:
        st.warning(f"⚠️ **Cash Reality Check:** {lump_plan.cash_validation_message}")


# ═══════════════════════════════════════════════════════════════════════
# TAB 3: ASK COPILOT & DELIVERABLES
# ═══════════════════════════════════════════════════════════════════════
with tab_copilot:
    st.markdown("### 📄 Institutional Fiduciary Reports")
    r_col1, r_col2 = st.columns([2.5, 1.0])
    with r_col1:
        rep_choice = st.selectbox(
            "Select Fiduciary Deliverable (PDF):",
            [
                "1. Portfolio Health & Commission Audit",
                "2. Fund-by-Fund Switch & Consolidation Plan",
                "3. Fresh Money Deployment Plan (SIP & Lumpsum)"
            ]
        )
    file_map = {
        "1. Portfolio Health & Commission Audit": "outputs/Portfolio_Health_Audit.md",
        "2. Fund-by-Fund Switch & Consolidation Plan": "outputs/Switch_and_Consolidation_Plan.md",
        "3. Fresh Money Deployment Plan (SIP & Lumpsum)": "outputs/Fresh_Money_Deployment_Plan.md"
    }
    t_path = Path(file_map[rep_choice])
    if t_path.exists():
        p_path = t_path.with_suffix(".pdf")
        if not p_path.exists():
            p_path = convert_markdown_file_to_pdf(t_path)
        with r_col2:
            st.write("")
            st.download_button(
                label=f"📥 Download {p_path.name}",
                data=p_path.read_bytes(),
                file_name=p_path.name,
                mime="application/pdf",
                width="stretch"
            )

    st.divider()

    st.markdown("### 💬 Conversational Portfolio Copilot")
    st.write("**Quick Prompts:**")
    qcols = st.columns(4)
    quick_query = None
    if qcols[0].button("💡 SIP Blueprint", width="stretch"):
        quick_query = f"Explain my monthly SIP breakdown of Rs {sip_input:,.0f} across the 4 slots and why Pharma was chosen over Defence."
    if qcols[1].button("💼 Lumpsum Strategy", width="stretch"):
        quick_query = f"How should I deploy Rs {lumpsum_input:,.0f} lumpsum without buying at market highs, and why use Arbitrage funds?"
    if qcols[2].button("⚡ Thematic Exposures", width="stretch"):
        quick_query = "What % of my portfolio currently holds Defence, Commodities, PSU, Pharma, and Infra?"
    if qcols[3].button("🛡️ Stability Cushion", width="stretch"):
        quick_query = f"Explain how my {stab_pct:.2f}% look-through stability buffer satisfies the {selected_tier} debt ceiling without standalone debt drag."

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = [
            {
                "role": "assistant",
                "content": f"Hello {client_name}! I am your fee-only fiduciary wealth copilot. Your portfolio of **₹{tot_val/100000:.2f} Lakhs** has **₹{f1.annual_bleed_inr:,.0f}/year** in recoverable commissions and a **{stab_pct:.2f}% look-through stability buffer**. How can I assist you today?"
            }
        ]

    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Ask a question about your mutual funds, switch plan, taxes, or idle cash...") or quick_query

    if user_input:
        st.session_state["chat_history"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Analyzing portfolio facts..."):
                response_text = answer_interactive_query(facts, user_input, st.session_state["chat_history"])
                st.markdown(response_text)
                st.session_state["chat_history"].append({"role": "assistant", "content": response_text})


# ═══════════════════════════════════════════════════════════════════════
# TAB 4: UPLOAD STATEMENTS
# ═══════════════════════════════════════════════════════════════════════
with tab_upload:
    render_upload_page()

# ═══════════════════════════════════════════════════════════════════════
# TAB 6: RISK PROFILER & TOLERANCES
# ═══════════════════════════════════════════════════════════════════════
with tab_profile:
    client_path = ROOT / "data" / selected_client_key
    render_profile_page(client_path)

st.divider()
st.caption("🛡️ **Fiduciary Wealth Copilot** • 100% Fee-Only Direct Mutual Funds • SEBI (Investment Advisers) Regulations, 2013 • Zero Commission Leakage")
