"""
core/fund_classifier.py - Standardized SEBI Mutual Fund Classifier & Passive Alternatives.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Any, Optional


def _load_passive_universe() -> Dict[str, List[str]]:
    """Load passive fund universe from policy configuration."""
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "passive_universe.json"
    if policy_path.exists():
        try:
            with open(policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("passive_universe", {})
        except (json.JSONDecodeError, KeyError):
            pass
    return {}


def _load_scheme_master() -> Optional[Dict[str, Any]]:
    """
    Load Scheme Master (ISIN → benchmark index → mandate) from policy configuration.
    
    This is the authoritative source for Gate 4 passive scheme verification.
    Returns None if not available (triggers InsufficientDataError in verification).
    """
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "scheme_master.json"
    if policy_path.exists():
        try:
            with open(policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # The checked-in policy file is explicitly SAMPLE. Never
            # discard its envelope status and upgrade its fixture map to
            # authoritative runtime scheme evidence.
            if data.get("status") != "VERIFIED":
                return None
            envelope = data.get("scheme_master")
            if not isinstance(envelope, dict) or envelope.get("status") != "VERIFIED":
                return None
            return envelope.get("schemes_by_isin")
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def is_verified_passive_scheme(
    fund_data: Optional[Dict[str, Any]] = None,
    fund_name: str = "",
    category: str = "",
    scheme_master: Optional[Dict[str, Any]] = None,
    require_scheme_master: bool = True
) -> bool:
    """
    Strict, non-sloppy verification of passive index fund or ETF product structure.
    Rejects active thematic, flexi, or debt funds that happen to mention 'index' in their prose.
    
    GATE 4 REQUIREMENT: Scheme master (ISIN -> benchmark index -> mandate) required for release gate.
    If require_scheme_master=True (default) and scheme_master not available/ISIN not found, raises InsufficientDataError.
    
    Verification hierarchy:
    1. Scheme Master lookup by ISIN (authoritative, if available)
    2. If require_scheme_master=False: Explicit metadata 'is_passive' is True, OR
    3. If require_scheme_master=False: SEBI category is strictly an index/ETF category, OR
    4. If require_scheme_master=False: Scheme name explicitly ends with / contains designated passive product structures
       AND does NOT contain active descriptors like 'Index Opportunities', 'Enhanced Index', 'Index Advantage', 'Active'.
    """
    from core.models import InsufficientDataError
    
    if fund_data is None:
        fund_data = {}
    
    # Try to load scheme master if not provided
    if scheme_master is None:
        scheme_master = _load_scheme_master()
    
    isin = fund_data.get("isin", "") or fund_data.get("ISIN", "")
    
    # GATE 4: Scheme master is REQUIRED for passive scheme verification
    # If require_scheme_master=True (default for Gate 4), fail safe -- do NOT fall back to heuristics
    if isin and scheme_master:
        # Authoritative lookup by ISIN
        scheme_info = scheme_master.get(isin)
        if scheme_info:
            is_passive = scheme_info.get("is_passive", False)
            benchmark_index = scheme_info.get("benchmark_index", "")
            mandate = scheme_info.get("mandate", "")
            if is_passive:
                return True
            # If ISIN found but not passive, explicitly return False (not heuristic)
            return False
    
    # If ISIN provided but not found in scheme master, or no scheme master available
    if isin:
        raise InsufficientDataError(
            f"Scheme Master required for Gate 4 passive verification of ISIN '{isin}'. "
            "ISIN not found in scheme_master.json or scheme master unavailable. "
            "Cannot verify passive status via heuristics for Gate 4 release gate.",
            missing_data=f"scheme_master entry for ISIN {isin}",
            required_source="SEBI/AMFI Scheme Master (ISIN -> benchmark index -> mandate mapping)"
        )
    
    # If no ISIN provided and require_scheme_master=True, fail
    if require_scheme_master:
        raise InsufficientDataError(
            "Scheme Master required for Gate 4 passive verification. "
            "No ISIN provided for scheme lookup. Cannot verify passive status via heuristics for Gate 4 release gate.",
            missing_data="ISIN for scheme master lookup",
            required_source="SEBI/AMFI Scheme Master (ISIN -> benchmark index -> mandate mapping)"
        )
    
    # DEVELOPMENT-ONLY FALLBACK: Heuristic checks below are NOT sufficient for Gate 4 release gate.
    # They return True only for clearly passive products; production MUST use scheme_master path above.
    # These heuristics are logged and should trigger a warning in production deployments.
    
    name = (fund_name or fund_data.get("fund_name", "") or fund_data.get("name", "")).strip()
    cat = (category or fund_data.get("category", "") or "").strip()
    name_lower = name.lower()
    cat_lower = cat.lower()
    
    # Active disguise keywords that disqualify pure passive exemption
    disqualifying_active_keywords = ["opportunities", "enhanced", "advantage", "active alpha", "active"]
    if any(k in name_lower for k in disqualifying_active_keywords):
        return False
    
    # Check 1: Explicit boolean flag (must be strictly True, not truthy string or int)
    if fund_data.get("is_passive") is True:
        import warnings
        warnings.warn("Passive verification via metadata flag - scheme master not used. Gate 4 release gate requires scheme_master.")
        return True
    
    # Check 2: Exact SEBI Category designation
    sebi_passive_categories = [
        "index funds", "exchange traded funds (etfs)", "etf", "etfs",
        "equity index fund", "index: large cap", "index: mid cap",
        "index: small cap", "index: flexi cap", "index: broad"
    ]
    if any(cat_lower == sc or cat_lower.startswith("index: ") or cat_lower.startswith("etf: ") for sc in sebi_passive_categories):
        import warnings
        warnings.warn("Passive verification via SEBI category heuristic - scheme master not used. Gate 4 release gate requires scheme_master.")
        return True
    
    # Check 3: Verified Scheme Name Structure
    passive_name_tokens = ["index fund", " etf", "-etf", "(etf)", "index direct", "nifty 50 index", "nifty midcap 150 index"]
    if any(token in name_lower for token in passive_name_tokens):
        import warnings
        warnings.warn("Passive verification via name heuristic - scheme master not used. Gate 4 release gate requires scheme_master.")
        return True
    
    return False

FUND_CATEGORY_TAXONOMY = {
    "Large Cap Equity": [
        "large cap", "large & mid cap", "large and mid cap", "large cap bluechip",
        "bluechip", "top 100", "nifty 50", "nifty 100", "sensex"
    ],
    "Mid & Small Cap Equity": [
        "mid & small cap", "mid and small cap", "mid-small cap"
    ],
    "Mid Cap Equity": [
        "mid cap", "mid-cap", "midcap", "nifty midcap 150", "emerging equity"
    ],
    "Small Cap Equity": [
        "small cap", "small-cap", "smallcap", "nifty smallcap"
    ],
    "Flexi Cap Equity": [
        "flexi cap", "flexi-cap", "flexicap", "focused"
    ],
    "Multi Cap Equity": [
        "multi cap", "multi-cap", "multicap"
    ],
    "Hybrid Equity": [
        "hybrid", "balanced advantage", "hybrid: daa", "dynamic asset allocation", "equity savings", "multi asset"
    ],
    "Healthcare Thematic": [
        "healthcare", "pharma", "pharmaceutical", "health fund", "pharma fund"
    ],
    "Defensive Thematic": [
        "defence", "defense", "energy", "power", "infrastructure", "psu", "commodities", "natural resources"
    ],
    "Debt Funds": [
        "debt", "short duration", "short term", "banking & psu debt", "liquid", "overnight", "money market", "arbitrage"
    ],
    "Index Funds": [
        "index", "etf", "nifty 50 index", "nifty midcap index"
    ]
}


def classify_fund_category(fund_name: str, fund_category: str = "", fund_data: Optional[Dict[str, Any]] = None) -> str:
    """
    Classify fund into standardized SEBI categories based on scheme name and category attributes.
    Checks both category string and scheme name with strict priority.
    """
    if not fund_name and not fund_category:
        return "Unknown"

    name_lower = (fund_name or "").lower()
    cat_lower = (fund_category or "").lower()
    combined = f"{name_lower} {cat_lower}"

    # 1. Dedicated Sector / Thematic Check
    for kw in FUND_CATEGORY_TAXONOMY["Healthcare Thematic"]:
        if kw in combined:
            return "Healthcare Thematic"

    for kw in FUND_CATEGORY_TAXONOMY["Defensive Thematic"]:
        if kw in combined:
            return "Defensive Thematic"

    # 2. Hybrid / Balanced Advantage Check
    for kw in FUND_CATEGORY_TAXONOMY["Hybrid Equity"]:
        if kw in combined:
            return "Hybrid Equity"

    # 3. Debt / Arbitrage Check
    for kw in FUND_CATEGORY_TAXONOMY["Debt Funds"]:
        if kw in combined:
            return "Debt Funds"

    # 4. Large Cap Check
    for kw in FUND_CATEGORY_TAXONOMY["Large Cap Equity"]:
        if kw in combined:
            return "Large Cap Equity"

    # 5. Distinguish combined Mid & Small mandates before pure-cap categories.
    for kw in FUND_CATEGORY_TAXONOMY["Mid & Small Cap Equity"]:
        if kw in combined:
            return "Mid & Small Cap Equity"

    # 6. Small Cap Check (before Mid/Flexi/Multi)
    for kw in FUND_CATEGORY_TAXONOMY["Small Cap Equity"]:
        if kw in combined:
            return "Small Cap Equity"

    # 7. Mid Cap Check (before Flexi/Multi)
    for kw in FUND_CATEGORY_TAXONOMY["Mid Cap Equity"]:
        if kw in combined:
            return "Mid Cap Equity"

    # 8. Flexi Cap Check
    for kw in FUND_CATEGORY_TAXONOMY["Flexi Cap Equity"]:
        if kw in combined:
            return "Flexi Cap Equity"

    # 9. Multi Cap Check
    for kw in FUND_CATEGORY_TAXONOMY["Multi Cap Equity"]:
        if kw in combined:
            return "Multi Cap Equity"

    # 10. Index Funds Check
    for kw in FUND_CATEGORY_TAXONOMY["Index Funds"]:
        if kw in combined:
            return "Index Funds"

    return "Other"


def get_fund_passive_alternatives(category: str) -> List[str]:
    """Retrieve verified institutional passive index alternatives for a category."""
    universe = _load_passive_universe()
    if category in universe:
        return universe[category]

    # Search-term and display-name fallbacks are not exact scheme identities
    # and cannot be presented as verified passive alternatives.
    return []


def detect_fund_theme(fund_name: str, category: str = "") -> Optional[str]:
    """Detect macro theme label if applicable."""
    combined = f"{fund_name} {category}".lower()
    if any(k in combined for k in ("pharma", "healthcare", "health")):
        return "Healthcare"
    if any(k in combined for k in ("defence", "defense")):
        return "Defence"
    if any(k in combined for k in ("energy", "power", "infra")):
        return "Power/Energy"
    if any(k in combined for k in ("psu", "cpse")):
        return "PSU"
    if any(k in combined for k in ("commodity", "commodities", "metal", "mining")):
        return "Commodities"
    return None
