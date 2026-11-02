for file_path in ["app.py", "ui/app.py"]:
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    # 1. Update import
    old_imp = """from core.math_engine import (
    aggregate_fiduciary_facts,
    compute_deterministic_sip_blueprint,
    compute_deterministic_lumpsum_blueprint,
    _parse_sebi_risk_tier,
)"""
    new_imp = """from core.math_engine import (
    aggregate_fiduciary_facts,
    compute_deterministic_sip_blueprint,
    compute_deterministic_lumpsum_blueprint,
    _parse_sebi_risk_tier,
    get_available_strategies,
)"""
    assert old_imp in text, f"old_imp not found in {file_path}"
    text = text.replace(old_imp, new_imp, 1)

    # 2. Update KPI fallbacks
    old_kpis = """    xirr_val = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "15.82%"
    alpha_val = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "+3.82%"
    st.metric(
        label="Portfolio Return (XIRR)",
        value=xirr_val,
        delta=f"{alpha_val} Alpha vs Benchmark"
    )
with c4:
    stab_pct = facts.stability_buffer.total_stability_buffer_pct if facts.stability_buffer else 7.54"""

    new_kpis = """    xirr_val = f"{facts.xirr_pct * 100:.2f}%" if facts.xirr_pct is not None else "N/A"
    alpha_val = f"{facts.alpha_pct:+.2f}%" if facts.alpha_pct is not None else "N/A"
    st.metric(
        label="Portfolio Return (XIRR)",
        value=xirr_val,
        delta=f"{alpha_val} Alpha vs Benchmark" if alpha_val != "N/A" else None
    )
with c4:
    stab_pct = facts.stability_buffer.total_stability_buffer_pct if facts.stability_buffer else 0.0"""

    assert old_kpis in text, f"old_kpis not found in {file_path}"
    text = text.replace(old_kpis, new_kpis, 1)

    # 3. Tab 1 title dynamic
    old_tabs = """tab_switch, tab_fresh, tab_copilot, tab_upload = st.tabs([
    "📋 Switch to Direct (Save ₹41k/yr)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💬 Ask Copilot & Reports",
    "📤 Upload Statement"
])"""

    new_tabs = """tab_switch, tab_fresh, tab_copilot, tab_upload = st.tabs([
    f"📋 Switch to Direct (Save ₹{f1.annual_bleed_inr/1000:.0f}k/yr)",
    "🎯 Fresh Money (SIP & Lumpsum)",
    "💬 Ask Copilot & Reports",
    "📤 Upload Statement"
])"""

    assert old_tabs in text, f"old_tabs not found in {file_path}"
    text = text.replace(old_tabs, new_tabs, 1)

    # 4. Tab 2 lumpsum fallback
    old_lump_input = """        lumpsum_input = st.number_input(
            "Fresh Lumpsum Capital (₹):",
            value=int(getattr(facts, "lumpsum_budget_inr", 200000.0)),
            step=25000
        )"""

    new_lump_input = """        lumpsum_input = st.number_input(
            "Fresh Lumpsum Capital (₹):",
            value=int(getattr(facts, "lumpsum_budget_inr", 0.0) or 0.0),
            step=25000
        )"""

    assert old_lump_input in text, f"old_lump_input not found in {file_path}"
    text = text.replace(old_lump_input, new_lump_input, 1)

    # 5. Dynamic strategy selectors using get_available_strategies
    old_selectors = """    c_strat0, c_strat1, c_strat2 = st.columns(3)
    with c_strat0:
        flexi_strategies = {
            "blend_50_50": "⚖️ 50:50 Core Blend (PPFAS + HDFC Flexi) [Recommended]",
            "ppfas_flexi": "🛡️ Parag Parikh Flexi Cap Direct (0.69% TER) — Global Value",
            "hdfc_flexi": "⚡ HDFC Flexi Cap Direct (0.83% TER) — Domestic Momentum",
            "jm_flexi": "🚀 JM Flexi Cap Direct (0.45% TER) — Agile Small AUM (~₹5k Cr)",
        }
        selected_flexi = st.selectbox(
            "Core Flexi-Cap Strategy:",
            options=list(flexi_strategies.keys()),
            format_func=lambda k: flexi_strategies[k],
            help="Avoid single-fund AUM bloat (>₹90k Cr) and RBI foreign remit freeze by blending PPFAS with HDFC Flexi Cap."
        )

    with c_strat1:
        large_strategies = {
            "nifty50_index": "🛡️ HDFC Nifty 50 Index Direct (0.18% TER) [Default]",
            "nippon_large": "⚡ Nippon India Large Cap Direct (0.88% TER) — Active",
            "next50_index": "📊 UTI Nifty Next 50 Index Direct (0.28% TER) — Next 50",
        }
        selected_large = st.selectbox(
            "Large-Cap Bluechip Strategy:",
            options=list(large_strategies.keys()),
            format_func=lambda k: large_strategies[k],
            help="Compare 0.18% low-cost passive index beta vs 0.88% active manager rotation vs Next 50."
        )

    with c_strat2:
        mid_strategies = {
            "hdfc_midcap": "🛡️ HDFC Mid-Cap Opp Direct (80 Stocks, 0.76% TER) [Default]",
            "motilal_midcap": "⚡ Motilal Oswal Midcap Direct (31 Stocks, 0.91% TER) — Alpha",
            "nifty_midcap_150": "📊 Nifty Midcap 150 Index Direct (150 Stocks, 0.25% TER)",
        }
        selected_mid = st.selectbox(
            "Mid-Cap Alpha Strategy:",
            options=list(mid_strategies.keys()),
            format_func=lambda k: mid_strategies[k],
            help="Compare diversified 80-stock institutional core vs concentrated 31-stock momentum vs passive index."
        )"""

    new_selectors = """    c_strat0, c_strat1, c_strat2 = st.columns(3)
    with c_strat0:
        flexi_strategies = get_available_strategies("flexi_cap")
        selected_flexi = st.selectbox(
            "Core Flexi-Cap Strategy:",
            options=list(flexi_strategies.keys()),
            format_func=lambda k: flexi_strategies[k],
            help="Avoid single-fund AUM bloat (>₹90k Cr) and RBI foreign remit freeze by blending PPFAS with HDFC Flexi Cap."
        )

    with c_strat1:
        large_strategies = get_available_strategies("large_cap")
        selected_large = st.selectbox(
            "Large-Cap Bluechip Strategy:",
            options=list(large_strategies.keys()),
            format_func=lambda k: large_strategies[k],
            help="Compare 0.18% low-cost passive index beta vs 0.88% active manager rotation vs Next 50."
        )

    with c_strat2:
        mid_strategies = get_available_strategies("mid_cap")
        selected_mid = st.selectbox(
            "Mid-Cap Alpha Strategy:",
            options=list(mid_strategies.keys()),
            format_func=lambda k: mid_strategies[k],
            help="Compare diversified 80-stock institutional core vs concentrated 31-stock momentum vs passive index."
        )"""

    assert old_selectors in text, f"old_selectors not found in {file_path}"
    text = text.replace(old_selectors, new_selectors, 1)

    # 6. Tab 2 cash calculation fallback
    old_cash = """    bank_tot = facts.stability_buffer.bank_deployable_cash_inr + facts.stability_buffer.emergency_reserve_inr if facts.stability_buffer else 435000.0
    em_res = facts.stability_buffer.emergency_reserve_inr if facts.stability_buffer else 115000.0"""

    new_cash = """    if facts.stability_buffer:
        bank_tot = facts.stability_buffer.bank_deployable_cash_inr + facts.stability_buffer.emergency_reserve_inr
        em_res = facts.stability_buffer.emergency_reserve_inr
    elif facts.cash_plan:
        bank_tot = facts.cash_plan.bank_cash_inr
        em_res = facts.cash_plan.emergency_buffer_inr
    else:
        bank_tot = 0.0
        em_res = 0.0"""

    assert old_cash in text, f"old_cash not found in {file_path}"
    text = text.replace(old_cash, new_cash, 1)

    # 7. Tab 3 quick prompt & greeting
    old_chat = """    if qcols[3].button("🛡️ Stability Cushion", width="stretch"):
        quick_query = "Explain how my 7.54% look-through stability buffer satisfies the Tier 6 debt ceiling without standalone debt drag."

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = [
            {
                "role": "assistant",
                "content": f"Hello {client_name}! I am your fee-only fiduciary wealth copilot. Your portfolio of **₹{tot_val/100000:.2f} Lakhs** has **₹{f1.annual_bleed_inr:,.0f}/year** in recoverable commissions and a **7.54% look-through stability buffer**. How can I assist you today?"
            }
        ]"""

    new_chat = """    if qcols[3].button("🛡️ Stability Cushion", width="stretch"):
        quick_query = f"Explain how my {stab_pct:.2f}% look-through stability buffer satisfies the {selected_tier} debt ceiling without standalone debt drag."

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = [
            {
                "role": "assistant",
                "content": f"Hello {client_name}! I am your fee-only fiduciary wealth copilot. Your portfolio of **₹{tot_val/100000:.2f} Lakhs** has **₹{f1.annual_bleed_inr:,.0f}/year** in recoverable commissions and a **{stab_pct:.2f}% look-through stability buffer**. How can I assist you today?"
            }
        ]"""

    assert old_chat in text, f"old_chat not found in {file_path}"
    text = text.replace(old_chat, new_chat, 1)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"SUCCESS: {file_path} cleaned of all hardcoding!")

