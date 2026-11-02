with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Add _resolve_flexi_details helper right after _resolve_largecap_details
helper_flexi = '''def _resolve_flexi_details(
    flexi_choice: str = "ppfas_flexi",
    holdings: Optional[List[HoldingItem]] = None,
    direct_flexi_folio: Optional[str] = None
) -> Tuple[str, Optional[str], str]:
    """
    Resolves scheme name, target folio, and fiduciary rationale for Core Flexi-Cap Compounder.
    Supports:
      - 'ppfas_flexi': Parag Parikh Flexi Cap Direct (Default Fiduciary, 0.69% TER)
      - 'hdfc_flexi': HDFC Flexi Cap Direct (0.83% TER, reuses Folio #44678193)
      - 'jm_flexi': JM Flexi Cap Direct (0.45% TER, Agile ~5k Cr AUM)
    """
    hdfc_folio = None
    ppfas_folio = direct_flexi_folio
    if holdings:
        for h in holdings:
            s_lower = h.scheme.lower()
            if "hdfc" in s_lower and h.folio and "flexi" in s_lower:
                hdfc_folio = h.folio
            elif "hdfc" in s_lower and h.folio and not hdfc_folio:
                hdfc_folio = h.folio
            if ("parag parikh" in s_lower or "ppfas" in s_lower) and h.folio:
                ppfas_folio = h.folio

    choice = str(flexi_choice).lower().strip()
    if "hdfc" in choice:
        scheme = "HDFC Flexi Cap Fund - Direct Plan - Growth Option"
        folio = hdfc_folio
        rat = f"High-conviction domestic alpha flexi-cap (+5.27% 3Y alpha, 0.83% TER); {'reuses active HDFC Direct Folio #' + folio if folio else 'initiates domestic flexi core'}."
    elif "jm" in choice or "agile" in choice:
        scheme = "JM Flexi Cap Fund - Direct Plan - Growth"
        folio = None
        rat = "Agile small-AUM flexi-cap (~INR 5,000 Cr AUM, lowest 0.45% TER) with top-decile multi-cap momentum and zero size drag."
    else:  # default: ppfas_flexi
        scheme = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
        folio = ppfas_folio
        rat = f"Core compounding anchor with lowest category TER (0.69%), global tech diversification (Alphabet, Meta, Microsoft), and 15-18% defensive cash/arbitrage buffer; {'reuses Folio #' + folio if folio else 'initiates global compounder'}."
    return scheme, folio, rat
'''

marker = "def _resolve_largecap_details("
idx_m = text.find(marker)
idx_end_m = text.find("def compute_deterministic_lumpsum_blueprint(", idx_m)
text = text[:idx_end_m] + helper_flexi + "\n\n" + text[idx_end_m:]

# 2. Update compute_deterministic_lumpsum_blueprint signature
old_sig_lump = """def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    mid_choice: str = "hdfc_midcap",
    large_choice: str = "nifty50_index","""

new_sig_lump = """def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    mid_choice: str = "hdfc_midcap",
    large_choice: str = "nifty50_index",
    flexi_choice: str = "ppfas_flexi","""

text = text.replace(old_sig_lump, new_sig_lump, 1)

# 3. Update compute_deterministic_sip_blueprint signature
old_sig_sip = """def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
    mid_choice: str = "hdfc_midcap",
    large_choice: str = "nifty50_index",
) -> DeterministicSIPPlan:"""

new_sig_sip = """def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 7.54,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
    mid_choice: str = "hdfc_midcap",
    large_choice: str = "nifty50_index",
    flexi_choice: str = "ppfas_flexi",
) -> DeterministicSIPPlan:"""

text = text.replace(old_sig_sip, new_sig_sip, 1)

# 4. In compute_deterministic_sip_blueprint, resolve flexi_scheme
old_flexi_decl = 'flexi_scheme = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"'
new_flexi_decl = 'flexi_scheme, flexi_target_folio, flexi_default_rat = _resolve_flexi_details(flexi_choice, holdings, direct_flexi_folio)'
text = text.replace(old_flexi_decl, new_flexi_decl, 1)

# Update flexi items folio target
text = text.replace("folio_target=direct_flexi_folio,", "folio_target=flexi_target_folio,")

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: core/math_engine.py patched with flexi_choice selector!")

