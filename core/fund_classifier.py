"""
core/fund_classifier.py - Standardized SEBI Mutual Fund Classifier & Passive Alternatives.
"""

from __future__ import annotations

import json
import hashlib
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
            # Do not discard the sample envelope status and upgrade test
            # fixture rows into authoritative runtime scheme identity evidence.
            if data.get("status") != "VERIFIED":
                return None
            envelope = data.get("scheme_master")
            if not isinstance(envelope, dict) or envelope.get("status") != "VERIFIED":
                return None
            schemes = envelope.get("schemes_by_isin")
            return schemes if isinstance(schemes, dict) and schemes else None
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def is_verified_passive_scheme(
    fund_data: Optional[Dict[str, Any]] = None,
    fund_name: str = "",
    category: str = "",
    scheme_master: Optional[Dict[str, Any]] = None,
    require_scheme_master: bool = True,
    scheme_master_source_bytes: Optional[bytes] = None,
    trust_registry: Optional[Dict[str, Any]] = None,
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
    
    # The checked-in map is a sample fixture, not a trust root. A strict
    # Gate 4 caller must supply an independently reviewed source envelope.
    if scheme_master is None:
        scheme_master = _load_scheme_master()

    isin = fund_data.get("isin", "") or fund_data.get("ISIN", "")

    if require_scheme_master:
        if not isinstance(scheme_master, dict) or scheme_master.get("status") != "VERIFIED":
            raise InsufficientDataError(
                "A source-verified passive scheme-master envelope is required; sample/raw mappings are rejected.",
                missing_data="verified passive scheme-master envelope",
                required_source="independently reviewed SEBI/AMFI scheme master and detached reviewer approval",
            )
        required_fields = (
            "source_url", "source_document_sha256", "effective_date",
            "reviewer_approval_envelope", "schemes_by_isin",
        )
        if any(not scheme_master.get(field) for field in required_fields):
            raise InsufficientDataError(
                "Passive scheme-master provenance, source bytes, or reviewer approval is incomplete.",
                missing_data="scheme-master provenance and detached approval",
                required_source="independently administered reviewer trust registry",
            )
        if (not isinstance(scheme_master_source_bytes, bytes) or not scheme_master_source_bytes
                or hashlib.sha256(scheme_master_source_bytes).hexdigest().lower()
                != str(scheme_master["source_document_sha256"]).lower()):
            raise InsufficientDataError(
                "Passive scheme-master original source bytes do not match the declared digest.",
                missing_data="matching original scheme-master source bytes",
                required_source="official SEBI/AMFI scheme-master source document",
            )
        if not isinstance(scheme_master["source_url"], str) or not scheme_master["source_url"].startswith("https://"):
            raise InsufficientDataError("Passive scheme-master source URL must be HTTPS.")
        try:
            from datetime import date, datetime, timezone
            from services.sip_reviewer_approval import load_sip_reviewer_trust_registry, verify_sip_reviewer_approval
            effective_date = date.fromisoformat(scheme_master["effective_date"])
            registry = trust_registry if trust_registry is not None else load_sip_reviewer_trust_registry()
            records = scheme_master["schemes_by_isin"]
            if not isinstance(records, dict) or not records:
                raise ValueError("schemes_by_isin must be a non-empty mapping")
            normalized_records = [records[key] for key in sorted(records)]
            approval = verify_sip_reviewer_approval(
                scheme_master["reviewer_approval_envelope"], registry,
                expected_scope="SIP_SCHEME_MASTER",
                expected_source_sha256=scheme_master["source_document_sha256"],
                structured_records=normalized_records,
                now=datetime.combine(effective_date, datetime.min.time(), tzinfo=timezone.utc),
            )
            if not approval.ok:
                raise ValueError("; ".join(approval.errors))
        except (OSError, TypeError, ValueError, KeyError) as exc:
            raise InsufficientDataError(
                f"Passive scheme-master reviewer verification failed ({type(exc).__name__}).",
                missing_data="valid detached reviewer approval",
                required_source="independently administered reviewer trust registry",
            ) from None
        if not isin:
            raise InsufficientDataError("An exact ISIN is required for passive scheme verification.")
        scheme_info = records.get(isin)
        if not isinstance(scheme_info, dict) or scheme_info.get("isin") != isin:
            raise InsufficientDataError(
                f"ISIN {isin!r} is not present in the verified passive scheme master.",
                missing_data=f"verified scheme-master entry for {isin}",
                required_source="SEBI/AMFI scheme master",
            )
        if not isinstance(scheme_info.get("is_passive"), bool):
            raise InsufficientDataError("Verified scheme-master passive mandate must be an explicit boolean.")
        if not isinstance(scheme_info.get("benchmark_index"), str) or not scheme_info["benchmark_index"].strip():
            raise InsufficientDataError("Verified passive scheme record requires an exact benchmark identity.")
        if not isinstance(scheme_info.get("mandate"), str) or not scheme_info["mandate"].strip():
            raise InsufficientDataError("Verified passive scheme record requires an exact mandate.")
        return scheme_info["is_passive"]

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


def classify_fund_category(
    fund_name: str,
    fund_category: str = "",
    fund_data: Optional[Dict[str, Any]] = None,
) -> str:
    """Classify only from an exact canonical category supplied by verified data.

    Scheme marketing names and free-form descriptions are not category evidence.
    Unknown and distinct SEBI categories remain distinct rather than falling
    through to a neighboring sleeve.
    """
    raw_category = str(fund_category or "").strip()
    if not raw_category:
        return "Unknown"

    normalized = " ".join(
        raw_category.casefold().replace("&", " and ").replace("-", " ").split()
    )
    exact_categories = {
        "large cap": "Large Cap Equity",
        "large cap equity": "Large Cap Equity",
        "large and mid cap": "Large & Mid Cap Equity",
        "large and mid cap equity": "Large & Mid Cap Equity",
        "mid cap": "Mid Cap Equity",
        "mid cap equity": "Mid Cap Equity",
        "mid and small cap": "Mid & Small Cap Equity",
        "mid and small cap equity": "Mid & Small Cap Equity",
        "small cap": "Small Cap Equity",
        "small cap equity": "Small Cap Equity",
        "flexi cap": "Flexi Cap Equity",
        "flexi cap equity": "Flexi Cap Equity",
        "focused": "Focused Equity",
        "focused fund": "Focused Equity",
        "focused equity": "Focused Equity",
        "multi cap": "Multi Cap Equity",
        "multi cap equity": "Multi Cap Equity",
        "index fund": "Index Funds",
        "index funds": "Index Funds",
        "etf": "Index Funds",
        "sectoral/thematic": "Thematic Equity",
        "thematic": "Thematic Equity",
        "thematic equity": "Thematic Equity",
        "healthcare": "Healthcare Thematic",
        "healthcare thematic": "Healthcare Thematic",
        "debt": "Debt Funds",
        "debt fund": "Debt Funds",
        "debt funds": "Debt Funds",
        "liquid": "Debt Funds",
        "liquid fund": "Debt Funds",
        "money market": "Debt Funds",
        "hybrid": "Hybrid Equity",
        "hybrid equity": "Hybrid Equity",
        "balanced advantage": "Hybrid Equity",
        "dynamic asset allocation": "Hybrid Equity",
    }
    return exact_categories.get(normalized, "Unknown")


def get_fund_passive_alternatives(category: str) -> List[str]:
    """No alternatives are returned until exact scheme and operational evidence is verified.

    The legacy universe contains search terms and product-like labels, not
    exact source-backed scheme IDs/ISINs and Direct/Growth identities.
    """
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
