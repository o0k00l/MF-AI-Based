import sys
from pathlib import Path

# 1. Update core/math_engine.py
me_path = Path("core/math_engine.py")
me_content = me_path.read_text(encoding="utf-8")

# Set defaults to authentic fiduciary choices
me_content = me_content.replace(
    'def _resolve_midcap_details(\n    mid_choice: str = "hdfc_midcap",',
    'def _resolve_midcap_details(\n    mid_choice: str = "motilal_midcap",'
)
me_content = me_content.replace(
    'def _resolve_largecap_details(\n    large_choice: str = "nifty50_index",',
    'def _resolve_largecap_details(\n    large_choice: str = "nippon_large",'
)
me_content = me_content.replace(
    '    mid_choice: str = "hdfc_midcap",\n    large_choice: str = "nifty50_index",\n    flexi_choice: str = "ppfas_flexi",\n) -> DeterministicLumpsumPlan:',
    '    mid_choice: str = "motilal_midcap",\n    large_choice: str = "nippon_large",\n    flexi_choice: str = "ppfas_flexi",\n) -> DeterministicLumpsumPlan:'
)
me_content = me_content.replace(
    '    mid_choice: str = "hdfc_midcap",\n    large_choice: str = "nifty50_index",\n    flexi_choice: str = "ppfas_flexi",\n) -> DeterministicSIPPlan:',
    '    mid_choice: str = "motilal_midcap",\n    large_choice: str = "nippon_large",\n    flexi_choice: str = "ppfas_flexi",\n) -> DeterministicSIPPlan:'
)

me_path.write_text(me_content, encoding="utf-8")
print("core/math_engine.py defaults updated successfully!")

# 2. Update app.py - Remove strategy dropdown selectboxes
app_path = Path("app.py")
app_content = app_path.read_text(encoding="utf-8")

# Remove get_available_strategies import if present
app_content = app_content.replace("    get_available_strategies,\n", "")

old_strategy_block = '''    c_strat0, c_strat1, c_strat2 = st.columns(3)
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
    )'''

new_strategy_block = '''    # 1. Deterministic SIP Blueprint (Pure Quantitative Execution)
    sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=float(sip_input),
        risk_tier=selected_tier,
        stability_buffer_pct=stab_pct,
        holdings=facts.holdings,
        client_aum=tot_val
    )'''

app_content = app_content.replace(old_strategy_block, new_strategy_block)

old_lump_call = '''    lump_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=float(lumpsum_input),
        bank_cash_total=bank_tot,
        emergency_reserve=em_res,
        holdings=facts.holdings,
        risk_tier=selected_tier,
        stability_buffer_pct=stab_pct,
        mid_choice=selected_mid,
        large_choice=selected_large,
        flexi_choice=selected_flexi
    )'''

new_lump_call = '''    lump_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=float(lumpsum_input),
        bank_cash_total=bank_tot,
        emergency_reserve=em_res,
        holdings=facts.holdings,
        risk_tier=selected_tier,
        stability_buffer_pct=stab_pct
    )'''

app_content = app_content.replace(old_lump_call, new_lump_call)

app_path.write_text(app_content, encoding="utf-8")
print("app.py updated - strategy dropdowns completely removed!")

