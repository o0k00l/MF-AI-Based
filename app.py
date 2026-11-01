"""
app.py — Fiduciary Wealth Copilot (Streamlit Web Dashboard)
Executive-grade, ultra-minimal, 100% grounded fiduciary mutual funds copilot.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd
import streamlit as st
import advisor_lean as adv
from core.pdf_exporter import convert_markdown_file_to_pdf
from ui.pages.page_upload import render_upload_page

# Ground Truth Data
facts = adv.facts
client_name = facts.get("client", "Valued Client")
f1 = facts["fee_bleed"]
tot = facts["total_value"]

# Page Setup
st.set_page_config(
    page_title=f"Wealth Copilot | {client_name}",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Minimal Clean Styling
st.markdown("""
<style>
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        max-width: 1100px;
    }
    div[data-testid="stMetricValue"] {
        font-size: 1.7rem;
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)

# Sidebar (Metadata only)
with st.sidebar:
    st.markdown("### 💼 Portfolio Details")
    st.markdown(f"**Investor:** {client_name}")
    st.markdown(f"**Statement Date:** {facts['as_of']}")
    st.markdown(f"**Total Value:** ₹{facts['total_value']/100000:.2f} Lakhs")
    st.markdown(f"**Regular AUM:** ₹{f1['regular_value']/100000:.2f} Lakhs")
    st.markdown(f"**Broker Bleed:** ₹{f1['annual_bleed']:,.0f} / yr")

# Header with Client Risk Tolerance Selector
col_head1, col_head2 = st.columns([1.7, 1.3])
with col_head1:
    st.title("🛡️ Wealth Copilot")
    st.caption(f"Investor: **{facts['client']}** • Portfolio Date: **{facts['as_of']}** • 100% Fee-Only Direct Advisory")

risk_options = {
    "6_very_high": "🔴 Level 6: Aggressive Equity (95% Eq / 5% Debt)",
    "5_high": "🟠 Level 5: Growth SAA (85% Eq / 15% Debt)",
    "4_moderately_high": "🟡 Level 4: Moderately High (70% Eq / 30% Debt)",
    "3_moderate": "🟡 Level 3: Moderate Hybrid (50% Eq / 50% Debt)",
    "2_low_to_moderate": "🟢 Level 2: Low-Moderate (20% Eq / 80% Debt)",
    "1_low": "🟢 Level 1: Capital Preservation (100% Debt/Liquid)"
}

with col_head2:
    selected_sebi_key = st.selectbox(
        "Investor SAA Risk Profile:",
        options=list(risk_options.keys()),
        format_func=lambda k: risk_options[k],
        index=1,
        help="Investor Strategic Asset Allocation profile per SEBI (Investment Advisers) Regulations, 2013."
    )

with st.expander("ℹ️ Regulatory Clarity: SEBI Scheme Risk-o-meter vs Investor SAA Profile", expanded=False):
    st.markdown("""
    - **SEBI Scheme Risk-o-meter ([investor.sebi.gov.in](https://investor.sebi.gov.in/riskometer.html)):** A mandatory product-level label evaluated monthly by AMCs based on underlying holdings (market cap, volatility, impact cost, credit risk, duration). Under SEBI rules, almost **all equity schemes** (Large Cap, Mid Cap, Flexi Cap, Thematic) are individually rated **'🔴 Very High Risk'**.
    - **Investor SAA Profile (SEBI IA Regulations 2013):** The investor's target macro asset allocation (Equity vs Debt) matching risk capacity and horizon. The selector above sets your strategic equity-to-debt target.
    """)

# Dynamic SAA based on Client Risk Tolerance
saa_data = adv.compute_saa(profile_name=selected_sebi_key)
cur_eq = saa_data['current']['large'] + saa_data['current']['mid_small']
tgt_eq = saa_data['target']['large'] + saa_data['target']['mid_small']
cur_debt = saa_data['current']['debt']
tgt_debt = saa_data['target']['debt']
debt_drift = cur_debt - tgt_debt

# Top 4 High-Impact KPIs
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric(
        label="Portfolio Valuation",
        value=f"₹{facts['total_value']/100000:.2f} Lakh",
        delta=f"+₹{facts['gain']/100000:.2f} L (+16.7% Gain)"
    )
with c2:
    st.metric(
        label="Recoverable Broker Bleed",
        value=f"₹{f1['annual_bleed']:,.0f} / yr",
        delta="14 Regular Plans to Switch",
        delta_color="inverse"
    )
with c3:
    st.metric(
        label="Portfolio Return (XIRR)",
        value=f"{facts.get('xirr_pct', 0.15815)*100:.1f}%",
        delta=f"+{facts.get('alpha_pct', 3.82):.1f}% Alpha vs Benchmark"
    )
with c4:
    st.metric(
        label="Asset Mix vs Target",
        value=f"{cur_eq:.0f}% Eq / {cur_debt:.0f}% Debt",
        delta=f"Target: {tgt_eq:.0f}/{tgt_debt:.0f}% ({debt_drift:+.0f}% Debt Drift)",
        delta_color="normal" if abs(debt_drift) <= 5 else "inverse"
    )

st.write("")

# 4 Essential Tabs
tab_switch, tab_fresh, tab_copilot, tab_upload = st.tabs([
    "📋 Switch to Direct (Save ₹39k)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💬 Ask Copilot & Reports",
    "📤 Upload Statement"
])

# ═══════════════════════════════════════════════════════════════════════
# TAB 1: SWITCH TO DIRECT (SAVE ₹39K/YR)
# ═══════════════════════════════════════════════════════════════════════
with tab_switch:
    st.info(
        f"💡 Moving your 14 Regular plans to Direct saves **₹{f1['annual_bleed']:,.0f} every year** in broker commissions. "
        f"Switch **72 mature lots today** with **₹0 tax and ₹0 exit fees**."
    )

    csv_file = Path("outputs/MFCentral_Action_Checklist.csv")
    needs_regen = not csv_file.exists()
    if csv_file.exists():
        try:
            sample_df = pd.read_csv(csv_file, nrows=1)
            if "Recommended Action" not in sample_df.columns:
                needs_regen = True
        except Exception:
            needs_regen = True

    if needs_regen:
        import generate_checklist
        generate_checklist.generate_mfcentral_checklist()

    if csv_file.exists():
        df = pd.read_csv(csv_file)
        
        # Defensive column resolution
        col_name = "Current Scheme Name" if "Current Scheme Name" in df.columns else ("Current Fund" if "Current Fund" in df.columns else df.columns[1])
        col_val = "Current Value (INR)" if "Current Value (INR)" in df.columns else ("Current Value" if "Current Value" in df.columns else df.columns[3])
        col_saved = "Annual Commission Saved (INR)" if "Annual Commission Saved (INR)" in df.columns else ("Annual Savings (INR/yr)" if "Annual Savings (INR/yr)" in df.columns else df.columns[4])
        col_action = "Recommended Action" if "Recommended Action" in df.columns else ("Action" if "Action" in df.columns else df.columns[2])
        col_target = "Target Direct Scheme" if "Target Direct Scheme" in df.columns else ("Target Direct Fund" if "Target Direct Fund" in df.columns else df.columns[-1])

        # Filter toggle
        view_choice = st.radio(
            "Show Holdings:",
            ["14 Regular Funds to Switch (Save ₹39k/yr)", f"All {len(df)} Holdings"],
            horizontal=True,
            label_visibility="collapsed"
        )

        if "14" in view_choice:
            display_df = df[~df[col_action].astype(str).str.contains("RETAIN", case=False, na=False)].copy()
        else:
            display_df = df.copy()

        # Clean 5-column action table
        st.dataframe(
            display_df[[col_name, col_val, col_saved, col_action, col_target]],
            use_container_width=True,
            hide_index=True,
            column_config={
                col_name: st.column_config.TextColumn("Scheme Name", width="large"),
                col_val: st.column_config.TextColumn("Current Value (₹)", width="medium"),
                col_saved: st.column_config.TextColumn("Saved (₹/yr)", width="medium"),
                col_action: st.column_config.TextColumn("Action", width="medium"),
                col_target: st.column_config.TextColumn("Switch To (Direct Plan)", width="large"),
            }
        )

        dcol1, dcol2 = st.columns([1, 2])
        with dcol1:
            st.download_button(
                label="📥 Download Switch Checklist (CSV)",
                data=csv_file.read_bytes(),
                file_name=f"MFCentral_Switch_Checklist_{client_name.lower().replace(' ', '_')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with dcol2:
            st.caption("Execute on **MFCentral** (Official Zero-Fee AMFI Platform): Service Requests → Switch Funds.")


# ═══════════════════════════════════════════════════════════════════════
# TAB 2: FRESH MONEY (SIP & LUMPSUM) — DYNAMIC BY RISK TOLERANCE
# ═══════════════════════════════════════════════════════════════════════
with tab_fresh:
    b1, b2 = st.columns(2)
    with b1:
        sip_input = st.number_input("Monthly SIP Budget (₹):", value=100000, step=5000)
    with b2:
        lumpsum_input = st.number_input("Fresh Lumpsum Capital (₹):", value=200000, step=25000)

    # Dynamic Blueprint according to selected Client Risk Tolerance
    sip_plan = adv.compute_sip_blueprint(
        monthly_budget=sip_input,
        profile_name=selected_sebi_key,
        mid_choice="hdfc_midcap"
    )
    lumpsum_data = adv.compute_lumpsum_blueprint(
        lumpsum_amount=lumpsum_input,
        profile_name=selected_sebi_key,
        deployment_mode="staggered_stp",
        stp_months=6,
        mid_choice="hdfc_midcap"
    )

    lump_map = {l["scheme"]: l for l in lumpsum_data.get("allocations", [])}
    fresh_rows = []
    debt_lump_sum = 0.0

    for s in sip_plan:
        scheme = s["scheme"]
        l = lump_map.get(scheme, {})
        lump_amt = l.get("lumpsum_amount", 0.0)
        is_debt = "Debt" in s["category"] or "Fixed Income" in s["category"]

        if is_debt:
            debt_lump_sum += lump_amt
            lump_display = f"₹{lump_amt:,.0f} (Deploy Day 1 Upfront)"
        else:
            lump_display = f"₹{lump_amt:,.0f} (6-Mo Liquid STP @ ~6.8%)"

        fresh_rows.append({
            "Asset Sleeve": s["category"],
            "Recommended Direct Scheme": scheme,
            "Target": s["target_pct"],
            "Monthly SIP": f"₹{s['monthly_amount']:,.0f} / mo",
            "Lumpsum Plan": lump_display,
            "Key Reason": s["rationale"]
        })

    st.dataframe(
        pd.DataFrame(fresh_rows),
        use_container_width=True,
        hide_index=True,
        column_config={
            "Asset Sleeve": st.column_config.TextColumn("Asset Sleeve", width="medium"),
            "Recommended Direct Scheme": st.column_config.TextColumn("Recommended Direct Scheme", width="large"),
            "Target": st.column_config.TextColumn("Target", width="small"),
            "Monthly SIP": st.column_config.TextColumn(f"Monthly SIP (₹{sip_input:,.0f})", width="medium"),
            "Lumpsum Plan": st.column_config.TextColumn(f"Lumpsum (₹{lumpsum_input:,.0f})", width="large"),
            "Key Reason": st.column_config.TextColumn("Strategic Fiduciary Rationale", width="large"),
        }
    )

    equity_lump = max(0.0, lumpsum_input - debt_lump_sum)
    profile_label = risk_options[selected_sebi_key].split('(')[0].strip()
    st.info(
        f"💡 **Execution Rule ({profile_label}):** Set up monthly auto-debit SIP on MFCentral (5th/10th of each month). "
        f"For lumpsum (₹{lumpsum_input:,.0f}), deploy ₹{debt_lump_sum:,.0f} into Debt on Day 1, "
        f"and park ₹{equity_lump:,.0f} in Liquid Direct (~6.8% yield) to STP into equity over 6 months."
    )


# ═══════════════════════════════════════════════════════════════════════
# TAB 3: ASK COPILOT & REPORTS
# ═══════════════════════════════════════════════════════════════════════
with tab_copilot:
    # 1-Row Report Downloader
    r_col1, r_col2 = st.columns([2.5, 1.0])
    with r_col1:
        rep_choice = st.selectbox(
            "Select Fiduciary Report (PDF):",
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
                use_container_width=True
            )

    st.divider()

    # Prompt Buttons
    st.write("**Quick Questions:**")
    qcols = st.columns(4)
    quick_query = None
    if qcols[0].button("💡 My SIP Plan", use_container_width=True):
        quick_query = f"Explain my monthly SIP breakdown of Rs {sip_input:,.0f} under {risk_options[selected_sebi_key]} in simple terms."
    if qcols[1].button("💼 Lumpsum Rule", use_container_width=True):
        quick_query = f"How should I invest my Rs {lumpsum_input:,.0f} lumpsum under {risk_options[selected_sebi_key]} without buying at market highs?"
    if qcols[2].button("⚡ Asset Mix Drift", use_container_width=True):
        quick_query = f"Why is my current {cur_eq:.1f}% equity different from the target {tgt_eq:.0f}% equity under {risk_options[selected_sebi_key]}?"
    if qcols[3].button("🛡️ Crash Protection", use_container_width=True):
        quick_query = "What happens to my portfolio if the equity markets crash 30%?"

    # Chat State
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = [
            {
                "role": "assistant",
                "content": f"Hello {facts['client']}! I am your fee-only fiduciary advisor. Your portfolio of **₹{facts['total_value']/100000:.2f} Lakhs** has **₹{f1['annual_bleed']:,.0f}/year** in recoverable commissions. Risk tolerance is currently set to **{risk_options[selected_sebi_key]}**. How can I help you today?"
            }
        ]

    for msg in st.session_state["chat_history"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("Ask a question about your portfolio...") or quick_query

    if user_input:
        st.session_state["chat_history"].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        holdings_ledger = "\n".join(
            f"- {h['scheme']} | {'Direct' if 'direct' in h['scheme'].lower() else 'Regular'} | Val: Rs{h['value']:,.0f} | Gain: Rs{h['value']-h['invested']:+,.0f} ({(h['value']-h['invested'])/h['invested']*100:+.1f}%)"
            for h in sorted(adv.holdings, key=lambda x: -x["value"])
        )

        sip_str = "\n".join(f"  * {i['category']}: {i['scheme']} | Alloc: {i['target_pct']} | Amount: Rs{i['monthly_amount']:,.0f}/mo" for i in sip_plan)
        lump_str = "\n".join(f"  * {i['category']}: {i['scheme']} | Amount: Rs{i['lumpsum_amount']:,.0f} | Execution: {i['execution_mode']}" for i in lumpsum_data.get("allocations", []))

        ctx = (
            f"Client: {facts['client']} | As of: {facts['as_of']}\n"
            f"Total Value: Rs{facts['total_value']:,.2f} | Gain: Rs{facts['gain']:,.2f}\n"
            f"Portfolio XIRR: {facts['xirr_pct']*100:.2f}% | Benchmark: {facts['benchmark_xirr_pct']*100:.2f}% | Alpha: {facts['alpha_pct']:+.2f}%\n"
            f"Active Funds: {facts['n_funds']} | Regular Plans: {f1['n_funds']} worth Rs{f1['regular_value']:,.2f}\n"
            f"Annual Commission Drag: Rs{f1['annual_bleed']:,.2f}/yr\n"
            f"Selected Client Risk Tolerance: {risk_options[selected_sebi_key]}\n"
            f"Current Asset Mix: {cur_eq:.1f}% Equity / {cur_debt:.1f}% Debt (Target: {tgt_eq:.0f}% Eq / {tgt_debt:.0f}% Debt)\n"
            f"SIP Plan (Rs{sip_input:,.0f}/mo):\n{sip_str}\n\n"
            f"LUMPSUM Plan (Rs{lumpsum_input:,.0f}):\n{lump_str}\n\n"
            f"ALL ACTIVE HOLDINGS:\n{holdings_ledger}\n"
        )

        hist_str = "\n".join(f"{h['role'].upper()}: {h['content']}" for h in st.session_state["chat_history"][-4:])
        prompt = f"{adv.SYS}\n\nPORTFOLIO CONTEXT:\n{ctx}\n\nCONVERSATION HISTORY:\n{hist_str}\n\nUSER QUESTION: {user_input}\n\nProvide a direct, grounded answer with exact numbers and clear bullet points."

        with st.chat_message("assistant"):
            with st.spinner("Drafting answer from saved portfolio data..."):
                try:
                    response_text = adv.call_llm(prompt)
                except Exception as e:
                    response_text = f"⚠️ Advisory Engine Error: {e}"
                st.markdown(response_text)

        st.session_state["chat_history"].append({"role": "assistant", "content": response_text})


# ═══════════════════════════════════════════════════════════════════════
# TAB 4: UPLOAD STATEMENT
# ═══════════════════════════════════════════════════════════════════════
with tab_upload:
    render_upload_page()

# Minimal Footer
st.write("")
st.caption("🛡️ **Fiduciary Wealth Copilot** • 100% Fee-Only Direct Mutual Funds • SEBI & AMFI Regulatory Standards")
