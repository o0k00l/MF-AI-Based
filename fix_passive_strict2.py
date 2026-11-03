import pathlib

p = pathlib.Path('core/fund_classifier.py')
t = p.read_text()

# Find the function boundaries
start = t.find('def is_verified_passive_scheme(')
end = t.find('\n\nFUND_CATEGORY_TAXONOMY')

new_func = '''def is_verified_passive_scheme(
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
    
    return False'''

if start >= 0 and end >= 0:
    t = t[:start] + new_func + t[end:]
    p.write_text(t)
    print("Done - passive verification made strict")
else:
    print("Function not found")
    print("start:", start, "end:", end)