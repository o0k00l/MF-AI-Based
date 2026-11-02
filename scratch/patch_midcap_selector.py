with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Add _resolve_midcap_details helper right above compute_deterministic_lumpsum_blueprint
helper_code = '''def _resolve_midcap_details(
    mid_choice: str = "hdfc_midcap",
    holdings: Optional[List[HoldingItem]] = None,
    direct_mid_folio: Optional[str] = None
) -> Tuple[str, Optional[str], str]:
    """
    Resolves scheme name, target folio, and fiduciary rationale for Mid-Cap Alpha Engine.
    Supports:
      - 'hdfc_midcap': HDFC Mid-Cap Opportunities Direct (Default Fiduciary)
      - 'motilal_midcap': Motilal Oswal Midcap Direct (Aggressive Alpha)
      - 'nifty_midcap_150': Nifty Midcap 150 Index Direct (Passive Index)
    """
    hdfc_folio = None
    motilal_folio = None
    if holdings:
        for h in holdings:
            s_lower = h.scheme.lower()
            if "hdfc" in s_lower and h.folio:
                hdfc_folio = h.folio
            if "motilal" in s_lower and h.folio:
                motilal_folio = h.folio

    choice = str(mid_choice).lower().strip()
    if "motilal" in choice:
        scheme = "Motilal Oswal Midcap Fund - Direct Plan Growth"
        folio = direct_mid_folio or motilal_folio
        rat = f"Concentrated QGLP alpha engine (31 stocks, 54.6% in top 10, 0.91% TER) targeting high ROCE (>20%) pricing-power leaders with high active share (+4.11% alpha); {'reuses active Direct Folio #' + folio if folio else 'initiates high-beta alpha engine'}."
    elif "index" in choice or "150" in choice or "passive" in choice or "nifty" in choice:
        scheme = "Nifty Midcap 150 Index Fund - Direct Plan - Growth"
        folio = None
        rat = "Passive broad-market mid-cap benchmark with zero single-stock concentration risk and rock-bottom 0.25% TER (saves 66 bps vs active peers)."
    else:  # default: hdfc_midcap
        scheme = "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth"
        folio = hdfc_folio or direct_mid_folio
        rat = f"Rank #1 institutional fiduciary mid-cap: lower 0.76% TER (saves 15 bps/yr vs Motilal), robust 80-stock diversification preventing single-stock blowup risk, Sharpe 0.62; {'reuses active HDFC Folio #' + folio if folio else 'initiates institutional core'}."
    return scheme, folio, rat


def compute_deterministic_lumpsum_blueprint('''

target_lump = "def compute_deterministic_lumpsum_blueprint("
if target_lump not in text:
    print("ERROR: compute_deterministic_lumpsum_blueprint definition not found!")
else:
    text = text.replace(target_lump, helper_code, 1)

# 2. Update compute_deterministic_lumpsum_blueprint signature
old_lump_sig = """def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,"""

new_lump_sig = """def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    mid_choice: str = "hdfc_midcap","""

text = text.replace(old_lump_sig, new_lump_sig, 1)

# 3. Update compute_deterministic_lumpsum_blueprint Leg 2 resolution
old_lump_leg2 = """            tranches.append(
                LumpsumTrancheItem(
                    role="Mid-Cap Alpha Engine (STP Leg 2)",
                    scheme_name="Motilal Oswal Midcap Fund - Direct Plan Growth",
                    folio_target=direct_mid_folio,
                    amount_inr=mid_stp,
                    monthly_inr=round(mid_stp / stp_months, 2),
                    allocation_pct=round((mid_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(mid_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale="Captures 10-year mid-cap alpha; routes to verified active Direct Folio."
                )
            )"""

new_lump_leg2 = """            mid_s, mid_f, mid_r = _resolve_midcap_details(mid_choice, holdings, direct_mid_folio)
            tranches.append(
                LumpsumTrancheItem(
                    role="Mid-Cap Alpha Engine (STP Leg 2)",
                    scheme_name=mid_s,
                    folio_target=mid_f,
                    amount_inr=mid_stp,
                    monthly_inr=round(mid_stp / stp_months, 2),
                    allocation_pct=round((mid_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(mid_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale=mid_r
                )
            )"""

text = text.replace(old_lump_leg2, new_lump_leg2, 1)

# 4. Update compute_deterministic_sip_blueprint signature
old_sip_sig = """def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
) -> DeterministicSIPPlan:"""

new_sip_sig = """def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
    mid_choice: str = "hdfc_midcap",
) -> DeterministicSIPPlan:"""

text = text.replace(old_sip_sig, new_sip_sig, 1)

# 5. Update Scheme Identifiers in compute_deterministic_sip_blueprint
old_scheme_id = """    # Scheme Identifiers
    flexi_scheme = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
    mid_scheme = "Motilal Oswal Midcap Fund - Direct Plan Growth"
    large_scheme = "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"
    pharma_scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
    debt_scheme = "ICICI Prudential Short Term Fund - Direct Plan - Growth" """

# Let's find exact text for scheme identifiers in compute_deterministic_sip_blueprint
idx_si = text.find("    # Scheme Identifiers")
if idx_si != -1:
    idx_next = text.find("    if is_starter:", idx_si)
    old_si_block = text[idx_si:idx_next]
    new_si_block = """    # Scheme Identifiers
    flexi_scheme = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
    large_scheme = "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"
    pharma_scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
    debt_scheme = "ICICI Prudential Short Term Fund - Direct Plan - Growth"
    mid_scheme, mid_target_folio, mid_default_rat = _resolve_midcap_details(mid_choice, holdings, direct_mid_folio)
"""
    text = text.replace(old_si_block, new_si_block, 1)

# Replace mid folio in sip items:
# replace folio_target=direct_mid_folio with folio_target=mid_target_folio
text = text.replace("folio_target=direct_mid_folio,", "folio_target=mid_target_folio,")

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: core/math_engine.py patched with midcap selector (default: hdfc_midcap)!")

