for file_path in ["app.py", "ui/app.py"]:
    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    target_block = """    c_strat1, c_strat2 = st.columns(2)
    with c_strat1:
        large_strategies = {
            "nifty50_index": "🛡️ HDFC Nifty 50 Index Direct (0.18% TER) — Fiduciary Core [Default]",
            "nippon_large": "⚡ Nippon India Large Cap Direct (0.88% TER) — Active Alpha",
            "next50_index": "📊 UTI Nifty Next 50 Index Direct (0.28% TER) — Next 50 Alpha",
        }
        selected_large = st.selectbox(
            "Large-Cap Bluechip Strategy:",
            options=list(large_strategies.keys()),
            format_func=lambda k: large_strategies[k],
            help="Compare 0.18% low-cost passive index beta vs 0.88% active manager rotation vs Next 50."
        )

    with c_strat2:
        mid_strategies = {
            "hdfc_midcap": "🛡️ HDFC Mid-Cap Opportunities Direct (80 Stocks, 0.76% TER) [Default]",
            "motilal_midcap": "⚡ Motilal Oswal Midcap Direct (31 Stocks, 0.91% TER) — Concentrated Alpha",
            "nifty_midcap_150": "📊 Nifty Midcap 150 Index Direct (150 Stocks, 0.25% TER) — Passive Index",
        }
        selected_mid = st.selectbox(
            "Mid-Cap Alpha Strategy:",
            options=list(mid_strategies.keys()),
            format_func=lambda k: mid_strategies[k],
            help="Compare diversified 80-stock institutional core vs concentrated 31-stock momentum vs passive index."
        )

    # 1. Deterministic SIP Blueprint
    sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=float(sip_input),
        risk_tier=selected_tier,
        stability_buffer_pct=stab_pct,
        holdings=facts.holdings,
        client_aum=tot_val,
        mid_choice=selected_mid,
        large_choice=selected_large
    )"""

    replacement_block = """    c_strat0, c_strat1, c_strat2 = st.columns(3)
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
        )

    # 1. Deterministic SIP Blueprint
    sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=float(sip_input),
        risk_tier=selected_tier,
        stability_buffer_pct=stab_pct,
        holdings=facts.holdings,
        client_aum=tot_val,
        mid_choice=selected_mid,
        large_choice=selected_large,
        flexi_choice=selected_flexi
    )"""

    assert target_block in text, f"target_block not found in {file_path}!"
    text = text.replace(target_block, replacement_block, 1)

    lump_call_old = """    lump_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=float(lumpsum_input),
        bank_cash_total=bank_tot,
        emergency_reserve=em_res,
        holdings=facts.holdings,
        risk_tier=selected_tier,
        stability_buffer_pct=stab_pct,
        mid_choice=selected_mid,
        large_choice=selected_large
    )"""

    lump_call_new = """    lump_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=float(lumpsum_input),
        bank_cash_total=bank_tot,
        emergency_reserve=em_res,
        holdings=facts.holdings,
        risk_tier=selected_tier,
        stability_buffer_pct=stab_pct,
        mid_choice=selected_mid,
        large_choice=selected_large,
        flexi_choice=selected_flexi
    )"""

    assert lump_call_old in text, f"lump_call_old not found in {file_path}!"
    text = text.replace(lump_call_old, lump_call_new, 1)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(text)

    print(f"SUCCESS: {file_path} updated with 3-strategy selectors!")

