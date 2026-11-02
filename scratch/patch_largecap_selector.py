with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Add _resolve_largecap_details helper right after _resolve_midcap_details
helper_large = '''def _resolve_largecap_details(
    large_choice: str = "nifty50_index",
    holdings: Optional[List[HoldingItem]] = None,
    direct_large_folio: Optional[str] = None
) -> Tuple[str, Optional[str], str]:
    """
    Resolves scheme name, target folio, and fiduciary rationale for Large-Cap Bluechip Anchor.
    Supports:
      - 'nifty50_index': HDFC Nifty 50 Index Direct / UTI Nifty 50 Index Direct (Default Fiduciary, 0.18% TER)
      - 'nippon_large': Nippon India Large Cap Direct (Active Alpha, 0.88% TER)
      - 'next50_index': UTI Nifty Next 50 Index Direct (0.28% TER)
    """
    hdfc_folio = None
    if holdings:
        for h in holdings:
            s_lower = h.scheme.lower()
            if "hdfc" in s_lower and h.folio:
                hdfc_folio = h.folio

    choice = str(large_choice).lower().strip()
    if "nippon" in choice or "active" in choice:
        scheme = "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"
        folio = direct_large_folio
        rat = f"Top-quartile active large cap (+1.99% 3Y alpha, 0.88 beta); {'consolidates active Direct Folio #' + folio if folio else 'initiates bluechip stability anchor'}."
    elif "next" in choice:
        scheme = "UTI Nifty Next 50 Index Fund - Direct Plan - Growth"
        folio = None
        rat = "Captures high-growth potential of 51st-100th large-cap leaders (0.28% TER) without paying active manager fee drag."
    else:  # default: nifty50_index
        scheme = "HDFC Nifty 50 Index Fund - Direct Plan - Growth"
        folio = hdfc_folio
        rat = f"Pure institutional large-cap beta with rock-bottom 0.18% TER (saves 70 bps/yr vs active large caps); SPIVA-compliant elimination of large-cap manager underperformance risk and eliminates single-AMC concentration in Nippon; {'reuses verified Folio #' + folio if folio else 'initiates index core'}."
    return scheme, folio, rat
'''

marker = "def _resolve_midcap_details("
idx_m = text.find(marker)
idx_end_m = text.find("def compute_deterministic_lumpsum_blueprint(", idx_m)
text = text[:idx_end_m] + helper_large + "\n\n" + text[idx_end_m:]

# 2. Update compute_deterministic_lumpsum_blueprint signature
old_sig_lump = """def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    mid_choice: str = "hdfc_midcap","""

new_sig_lump = """def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    mid_choice: str = "hdfc_midcap",
    large_choice: str = "nifty50_index","""

text = text.replace(old_sig_lump, new_sig_lump, 1)

# 3. Update Day 1 Large-Cap Anchor in lumpsum
old_lump_imm = """        # Day 1 Large-Cap Anchor
        imm_pct = round((immediate_eq / L) * 100.0, 1)
        tranches.append(
            LumpsumTrancheItem(
                role="Day-1 Large-Cap Anchor",
                scheme_name="Nippon India Large Cap Fund - Direct Plan - Growth",
                folio_target=direct_large_folio,
                amount_inr=immediate_eq,
                allocation_pct=imm_pct,
                timing="Immediate (Day 1)",
                source_vehicle="Bank Deployable Surplus",
                fiduciary_rationale="Anchors baseline portfolio stability with liquid bluechips (+1.99% 3Y alpha, 0.88 beta)."
            )
        )"""

new_lump_imm = """        # Day 1 Large-Cap Anchor
        imm_pct = round((immediate_eq / L) * 100.0, 1)
        large_s, large_f, large_r = _resolve_largecap_details(large_choice, holdings, direct_large_folio)
        tranches.append(
            LumpsumTrancheItem(
                role="Day-1 Large-Cap Anchor",
                scheme_name=large_s,
                folio_target=large_f,
                amount_inr=immediate_eq,
                allocation_pct=imm_pct,
                timing="Immediate (Day 1)",
                source_vehicle="Bank Deployable Surplus",
                fiduciary_rationale=large_r
            )
        )"""

text = text.replace(old_lump_imm, new_lump_imm, 1)

# 4. Update STP Leg 3 Large-Cap Anchor in lumpsum
old_lump_stp_large = """            tranches.append(
                LumpsumTrancheItem(
                    role="Large-Cap Bluechip Anchor (STP Leg 3)",
                    scheme_name="Nippon India Large Cap Fund - Direct Plan - Growth",
                    folio_target=direct_large_folio,
                    amount_inr=large_stp,
                    monthly_inr=round(large_stp / stp_months, 2),
                    allocation_pct=round((large_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(large_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale="Reinforces bluechip ballast across corporate earnings cycles."
                )
            )"""

new_lump_stp_large = """            tranches.append(
                LumpsumTrancheItem(
                    role="Large-Cap Bluechip Anchor (STP Leg 3)",
                    scheme_name=large_s,
                    folio_target=large_f,
                    amount_inr=large_stp,
                    monthly_inr=round(large_stp / stp_months, 2),
                    allocation_pct=round((large_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(large_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale=large_r
                )
            )"""

text = text.replace(old_lump_stp_large, new_lump_stp_large, 1)

# 5. Update compute_deterministic_sip_blueprint signature
old_sig_sip = """def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
    mid_choice: str = "hdfc_midcap",
) -> DeterministicSIPPlan:"""

new_sig_sip = """def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
    mid_choice: str = "hdfc_midcap",
    large_choice: str = "nifty50_index",
) -> DeterministicSIPPlan:"""

text = text.replace(old_sig_sip, new_sig_sip, 1)

# 6. Update large_scheme resolution in compute_deterministic_sip_blueprint
old_large_decl = 'large_scheme = "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"'
new_large_decl = 'large_scheme, large_target_folio, large_default_rat = _resolve_largecap_details(large_choice, holdings, direct_large_folio)'

text = text.replace(old_large_decl, new_large_decl, 1)

# Update large items in sip:
text = text.replace("folio_target=direct_large_folio,", "folio_target=large_target_folio,")
text = text.replace("fiduciary_rationale=large_rat", "fiduciary_rationale=large_default_rat")

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: core/math_engine.py patched with largecap selector (default: nifty50_index)!")

