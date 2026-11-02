with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Add STRATEGY_CATALOG and get_available_strategies
catalog_code = '''
# ============================================================
# UNIVERSAL FIDUCIARY STRATEGY CATALOG
# Data-driven strategy registry eliminating UI & engine hardcoding
# ============================================================

STRATEGY_CATALOG: Dict[str, Dict[str, Dict[str, Any]]] = {
    "flexi_cap": {
        "blend_50_50": {
            "label": "⚖️ 50:50 Core Blend (PPFAS + HDFC Flexi) [Recommended]",
            "schemes": [
                "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                "HDFC Flexi Cap Fund - Direct Plan - Growth Option"
            ],
            "description": "50:50 blend balancing PPFAS global value & cash defense with HDFC domestic cyclical momentum."
        },
        "ppfas_flexi": {
            "label": "🛡️ Parag Parikh Flexi Cap Direct (0.69% TER) — Global Value",
            "scheme": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            "description": "Lowest category TER (0.69%), global tech diversification (Alphabet, Meta, Microsoft), and 15-18% cash buffer."
        },
        "hdfc_flexi": {
            "label": "⚡ HDFC Flexi Cap Direct (0.83% TER) — Domestic Momentum",
            "scheme": "HDFC Flexi Cap Fund - Direct Plan - Growth Option",
            "description": "High-conviction domestic alpha flexi-cap (+5.27% 3Y alpha, Roshi Jain) with zero foreign remittance bottlenecks."
        },
        "jm_flexi": {
            "label": "🚀 JM Flexi Cap Direct (0.45% TER) — Agile Small AUM (~₹5k Cr)",
            "scheme": "JM Flexi Cap Fund - Direct Plan - Growth",
            "description": "Agile small-AUM flexi-cap with top-decile momentum and zero size drag."
        }
    },
    "large_cap": {
        "nifty50_index": {
            "label": "🛡️ HDFC Nifty 50 Index Direct (0.18% TER) [Default]",
            "scheme": "HDFC Nifty 50 Index Fund - Direct Plan - Growth",
            "description": "Pure institutional large-cap beta with rock-bottom 0.18% TER (saves 70 bps/yr vs active large caps); SPIVA-compliant."
        },
        "nippon_large": {
            "label": "⚡ Nippon India Large Cap Direct (0.88% TER) — Active",
            "scheme": "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION",
            "description": "Top-quartile active large cap (+1.99% 3Y alpha) with tactical manager rotation."
        },
        "next50_index": {
            "label": "📊 UTI Nifty Next 50 Index Direct (0.28% TER) — Next 50",
            "scheme": "UTI Nifty Next 50 Index Fund - Direct Plan - Growth",
            "description": "Low-cost passive exposure to 51-100 high-growth bluechips."
        }
    },
    "mid_cap": {
        "hdfc_midcap": {
            "label": "🛡️ HDFC Mid-Cap Opp Direct (80 Stocks, 0.76% TER) [Default]",
            "scheme": "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth",
            "description": "Rank #1 institutional fiduciary mid-cap: lower 0.76% TER (saves 15 bps/yr vs Motilal), robust 80-stock diversification."
        },
        "motilal_midcap": {
            "label": "⚡ Motilal Oswal Midcap Direct (31 Stocks, 0.91% TER) — Alpha",
            "scheme": "Motilal Oswal Midcap Fund - Direct Plan Growth",
            "description": "High-conviction mid-cap momentum driver (+4.11% 3Y alpha, 31 stocks, 54.6% top-10 concentration)."
        },
        "nifty_midcap_150": {
            "label": "📊 Nifty Midcap 150 Index Direct (150 Stocks, 0.25% TER)",
            "scheme": "Nifty Midcap 150 Index Fund - Direct Plan - Growth",
            "description": "Pure passive mid-cap beta (150 stocks, 0.25% TER) eliminating active manager risk."
        }
    }
}


def get_available_strategies(slot: str) -> Dict[str, str]:
    """
    Returns {strategy_key: formatted_label} dynamically from the strategy catalog.
    Prevents UI view hardcoding.
    """
    slot_clean = slot.lower().replace("-", "_").replace(" ", "_")
    cat_data = STRATEGY_CATALOG.get(slot_clean, {})
    return {k: v["label"] for k, v in cat_data.items()}


def _resolve_thematic_details(
    holdings: Optional[List[HoldingItem]] = None,
    direct_pharma_folio: Optional[str] = None
) -> Tuple[str, Optional[str], str]:
    """Dynamically resolves thematic satellite scheme, reusing client folios if available."""
    folio = direct_pharma_folio
    if holdings and not folio:
        for h in holdings:
            s_lower = h.scheme.lower()
            if ("pharma" in s_lower or "health" in s_lower) and h.folio:
                folio = h.folio
                break
    scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
    rat = f"Forward-looking tactical satellite capturing attractive (~28x P/E) valuations and non-cyclical structural tailwinds; {'reuses active Folio #' + folio if folio else 'initiates tactical thematic satellite'}."
    return scheme, folio, rat


def _resolve_debt_details(
    holdings: Optional[List[HoldingItem]] = None,
    direct_debt_folio: Optional[str] = None
) -> Tuple[str, Optional[str], str]:
    """Dynamically resolves high-grade debt anchor, reusing client debt folios if available."""
    folio = direct_debt_folio
    if holdings and not folio:
        for h in holdings:
            s_lower = h.scheme.lower()
            if any(k in s_lower for k in ("debt", "short term", "liquid", "bond", "banking & psu", "balanced advantage")) and h.folio:
                folio = h.folio
                break
    scheme = "ICICI Prudential Short Term Fund - Direct Plan - Growth"
    rat = f"High-grade AAA short-term debt preserving capital stability and fulfilling SAA fixed income target; {'reuses active Folio #' + folio if folio else 'initiates high-grade debt anchor'}."
    return scheme, folio, rat
'''

# Find insertion spot right before _resolve_midcap_details
insert_target = "def _resolve_midcap_details("
assert insert_target in text, "insert_target not found!"
text = text.replace(insert_target, catalog_code + "\n\n" + insert_target, 1)

# 2. Change stability_buffer_pct default parameter from 7.54 to 0.0 in both blueprints
text = text.replace(
    "    stability_buffer_pct: float = 7.54,",
    "    stability_buffer_pct: float = 0.0,"
)

# 3. Use _resolve_thematic_details and _resolve_debt_details in compute_deterministic_sip_blueprint
old_pharma_debt = '''    large_scheme, large_target_folio, large_default_rat = _resolve_largecap_details(large_choice, holdings, direct_large_folio)
    pharma_scheme = "Nippon India Pharma / Healthcare Fund - Direct Plan - Growth"
    debt_scheme = "ICICI Prudential Short Term Fund - Direct Plan - Growth"
    mid_scheme, mid_target_folio, mid_default_rat = _resolve_midcap_details(mid_choice, holdings, direct_mid_folio)'''

new_pharma_debt = '''    large_scheme, large_target_folio, large_default_rat = _resolve_largecap_details(large_choice, holdings, direct_large_folio)
    mid_scheme, mid_target_folio, mid_default_rat = _resolve_midcap_details(mid_choice, holdings, direct_mid_folio)
    pharma_scheme, direct_pharma_folio, pharma_rat = _resolve_thematic_details(holdings, direct_pharma_folio)
    debt_scheme, direct_debt_folio, debt_rat = _resolve_debt_details(holdings, direct_debt_folio)'''

assert old_pharma_debt in text, "old_pharma_debt not found!"
text = text.replace(old_pharma_debt, new_pharma_debt, 1)

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: core/math_engine.py patched cleanly with STRATEGY_CATALOG, get_available_strategies, dynamic resolution, and 0.0 default buffer!")

