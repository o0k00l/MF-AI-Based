import sys
from pathlib import Path

app_path = Path("app.py")
content = app_path.read_text(encoding="utf-8")

# 1. Update imports
old_import = "    get_available_strategies,\n)"
new_import = "    get_available_strategies,\n    compute_personal_redemption_plan,\n)"
if "compute_personal_redemption_plan" not in content:
    content = content.replace(old_import, new_import)

# 2. Update tabs line
old_tabs = '''# 4 Main Tabs
tab_switch, tab_fresh, tab_copilot, tab_upload = st.tabs([
    f"📋 Switch to Direct (Save ₹{f1.annual_bleed_inr/1000:.0f}k/yr)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💬 Ask Copilot & Reports",
    "📤 Upload Statement"
])'''

new_tabs = '''# 5 Main Tabs
tab_switch, tab_fresh, tab_redeem, tab_copilot, tab_upload = st.tabs([
    f"📋 Switch to Direct (Save ₹{f1.annual_bleed_inr/1000:.0f}k/yr)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💸 Personal Redemption Planner",
    "💬 Ask Copilot & Reports",
    "📤 Upload Statement"
])'''

content = content.replace(old_tabs, new_tabs)

# 3. Add tab_redeem content before tab_copilot
tab_redeem_code = '''
# ═══════════════════════════════════════════════════════════════════════
# TAB 3: PERSONAL REDEMPTION PLANNER
# ═══════════════════════════════════════════════════════════════════════
with tab_redeem:
    st.markdown("### 💸 Fiduciary Personal Cash Redemption Planner")
    st.caption("Need money for personal expenses? Calculate the mathematically optimal liquidation plan to minimize taxes, eliminate broker commissions, avoid exit loads, and derisk toxic bubble holdings.")

    r_col_input, r_col_mode = st.columns([2, 1])
    with r_col_input:
        redeem_input = st.number_input(
            "Cash Needed for Personal Use (₹):",
            min_value=5000,
            max_value=int(tot_val),
            value=100000,
            step=10000,
            format="%d",
            help="Enter the exact rupee amount you wish to withdraw from your mutual funds portfolio."
        )
    with r_col_mode:
        target_mode = st.radio(
            "Target Withdrawal Mode:",
            ["Gross Capital Withdrawal", "Net Cash in Bank Account (Post-Tax)"],
            index=0,
            help="Select whether you want to redeem a gross amount, or receive the exact specified amount into your bank account after all taxes and exit loads."
        )

    is_net_target = ("Net Cash" in target_mode)

    cas, metrics, config, aliases, outputs = get_default_paths()
    tx_path = cas.parent.parent / "transactions.json"
    if not tx_path.exists():
        tx_path = cas.parent / "transactions.json"

    redemption_plan = compute_personal_redemption_plan(
        requested_amount=float(redeem_input),
        holdings=facts.holdings,
        transactions_path=tx_path if tx_path.exists() else None,
        is_net_cash=is_net_target,
    )

    # 4 Key Impact KPIs
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    with kpi1:
        st.metric(
            label="Gross Amount Redeemed",
            value=f"₹{redemption_plan.total_gross_redeemed_inr:,.0f}",
            delta=f"{redemption_plan.funds_liquidated_count} Schemes ({redemption_plan.full_folio_exits_count} Full Closures)"
        )
    with kpi2:
        st.metric(
            label="Net Cash to Bank Account",
            value=f"₹{redemption_plan.total_net_cash_inr:,.0f}",
            delta="After All Taxes & Loads"
        )
    with kpi3:
        st.metric(
            label="Taxes & Loads",
            value=f"₹{redemption_plan.total_net_tax_inr:,.0f}",
            delta=f"₹{redemption_plan.total_tax_sheltered_under_112a_inr:,.0f} Sheltered (112A)",
            delta_color="inverse" if redemption_plan.total_net_tax_inr > 0 else "normal"
        )
    with kpi4:
        st.metric(
            label="Broker Commission Saved",
            value=f"₹{redemption_plan.total_annual_commission_saved_inr:,.0f} / yr",
            delta="Permanently Terminated",
            delta_color="normal"
        )

    # Fiduciary Tier & Rationale Banner
    tier_badge = "🟢" if redemption_plan.ticket_category == "SMALL_TICKET" else ("🟡" if redemption_plan.ticket_category == "MEDIUM_TICKET" else "🔵")
    st.info(f"{tier_badge} **Operational Category: {redemption_plan.ticket_category.replace('_', ' ')}** — {redemption_plan.ticket_rationale}")

    # Tranche Execution Schedule Table
    st.markdown("#### 📋 Tranche-by-Tranche Liquidation Schedule")
    tranche_records = []
    for t in redemption_plan.tranches:
        tranche_records.append({
            "Priority": t.priority_label,
            "Scheme Name": t.scheme_name,
            "Folio No.": str(t.folio),
            "Units to Redeem": f"{t.units_to_redeem:,.3f}",
            "Gross (₹)": f"₹{t.gross_amount_inr:,.2f}",
            "Net Cash (₹)": f"₹{t.net_cash_realized_inr:,.2f}",
            "Tax (₹)": f"₹{t.net_tax_liability_inr:,.2f}",
            "Bleed Saved (₹/yr)": f"₹{t.annual_commission_saved_inr:,.2f}",
            "Status": "🔴 Full Folio Exit" if t.is_full_redemption else "🟡 Partial Redemption",
            "Fiduciary Rationale": t.fiduciary_reason,
        })
    df_tranches = pd.DataFrame(tranche_records)
    st.dataframe(
        df_tranches,
        width="stretch",
        hide_index=True,
        column_config={
            "Priority": st.column_config.TextColumn("Priority Tier", width="medium"),
            "Scheme Name": st.column_config.TextColumn("Scheme Name", width="large"),
            "Folio No.": st.column_config.TextColumn("Folio", width="small"),
            "Units to Redeem": st.column_config.TextColumn("Units", width="small"),
            "Gross (₹)": st.column_config.TextColumn("Gross", width="medium"),
            "Net Cash (₹)": st.column_config.TextColumn("Net Cash", width="medium"),
            "Tax (₹)": st.column_config.TextColumn("Tax", width="small"),
            "Bleed Saved (₹/yr)": st.column_config.TextColumn("Bleed Saved", width="small"),
            "Status": st.column_config.TextColumn("Action Status", width="small"),
            "Fiduciary Rationale": st.column_config.TextColumn("Rationale", width="large"),
        }
    )

    # MFCentral Step-by-Step Instructions
    with st.expander("🛠️ View MFCentral Step-by-Step Execution Instructions", expanded=True):
        st.markdown("**Follow these steps on MFCentral or AMC Online Portal:**")
        for step in redemption_plan.execution_steps:
            st.markdown(f"- {step}")

    # Fiduciary Safeguards & Invariants
    with st.expander("🛡️ Institutional Fiduciary Safeguards Applied", expanded=False):
        for guard in redemption_plan.fiduciary_safeguards:
            st.markdown(f"- {guard}")

'''

old_copilot_header = '''# ═══════════════════════════════════════════════════════════════════════
# TAB 3: ASK COPILOT & DELIVERABLES
# ═══════════════════════════════════════════════════════════════════════
with tab_copilot:'''

new_copilot_header = '''# ═══════════════════════════════════════════════════════════════════════
# TAB 4: ASK COPILOT & DELIVERABLES
# ═══════════════════════════════════════════════════════════════════════
with tab_copilot:'''

if "tab_redeem" not in content:
    content = content.replace(old_copilot_header, tab_redeem_code + new_copilot_header)

app_path.write_text(content, encoding="utf-8")
print("app.py patched with Tab 3 Personal Redemption Planner successfully!")

