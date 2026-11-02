import re

with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Enhance _resolve_flexi_details to prioritize direct folio for HDFC
old_resolve = """def _resolve_flexi_details(
    flexi_choice: str = "ppfas_flexi",
    holdings: Optional[List[HoldingItem]] = None,
    direct_flexi_folio: Optional[str] = None
) -> Tuple[str, Optional[str], str]:
    \"\"\"
    Resolves scheme name, target folio, and fiduciary rationale for Core Flexi-Cap Compounder.
    Supports:
      - 'ppfas_flexi': Parag Parikh Flexi Cap Direct (Default Fiduciary, 0.69% TER)
      - 'hdfc_flexi': HDFC Flexi Cap Direct (0.83% TER, reuses Folio #44678193)
      - 'jm_flexi': JM Flexi Cap Direct (0.45% TER, Agile ~5k Cr AUM)
    \"\"\"
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
    return scheme, folio, rat"""

new_resolve = """def _resolve_flexi_details(
    flexi_choice: str = "ppfas_flexi",
    holdings: Optional[List[HoldingItem]] = None,
    direct_flexi_folio: Optional[str] = None
) -> Tuple[str, Optional[str], str]:
    \"\"\"
    Resolves scheme name, target folio, and fiduciary rationale for Core Flexi-Cap Compounder.
    Supports:
      - 'ppfas_flexi': Parag Parikh Flexi Cap Direct (Default Fiduciary, 0.69% TER)
      - 'hdfc_flexi': HDFC Flexi Cap Direct (0.83% TER, reuses Folio #44678193)
      - 'jm_flexi': JM Flexi Cap Direct (0.45% TER, Agile ~5k Cr AUM)
    \"\"\"
    hdfc_direct_folio = None
    hdfc_any_folio = None
    ppfas_folio = direct_flexi_folio
    if holdings:
        for h in holdings:
            s_lower = h.scheme.lower()
            if "hdfc" in s_lower and h.folio:
                if "flexi" in s_lower:
                    if h.is_direct and not hdfc_direct_folio:
                        hdfc_direct_folio = h.folio
                    elif not hdfc_any_folio:
                        hdfc_any_folio = h.folio
                elif not hdfc_any_folio:
                    hdfc_any_folio = h.folio
            if ("parag parikh" in s_lower or "ppfas" in s_lower) and h.folio:
                ppfas_folio = h.folio

    choice = str(flexi_choice).lower().strip()
    if "hdfc" in choice:
        scheme = "HDFC Flexi Cap Fund - Direct Plan - Growth Option"
        folio = hdfc_direct_folio or hdfc_any_folio
        rat = f"High-conviction domestic alpha flexi-cap (+5.27% 3Y alpha, 0.83% TER, Roshi Jain); overcomes PPFAS foreign remit cap and size drag; {'reuses active Direct Folio #' + folio if folio else 'initiates domestic flexi core'}."
    elif "jm" in choice or "agile" in choice:
        scheme = "JM Flexi Cap Fund - Direct Plan - Growth"
        folio = None
        rat = "Agile small-AUM flexi-cap (~INR 5,000 Cr AUM, lowest 0.45% TER) with top-decile multi-cap momentum and zero size drag."
    else:  # default: ppfas_flexi
        scheme = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
        folio = ppfas_folio
        rat = f"Core compounding anchor with lowest category TER (0.69%), global tech diversification (Alphabet, Meta, Microsoft), and 15-18% defensive cash/arbitrage buffer; {'reuses Folio #' + folio if folio else 'initiates global compounder'}."
    return scheme, folio, rat"""

assert old_resolve in text, "old_resolve not found in math_engine.py!"
text = text.replace(old_resolve, new_resolve, 1)

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: _resolve_flexi_details updated!")

