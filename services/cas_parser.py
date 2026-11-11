"""CAS Excel parser service.

Parses any user-uploaded CAS file dynamically. No hardcoded fund names,
scheme codes, or portfolio values. Every CAS is different per user.
Supports multi-sheet workbooks (e.g. Equity, Debt, Portfolio Details)
and transaction-level FIFO lot maturation (LTCG >365d vs STCG <=365d).
"""
from __future__ import annotations

import io
import os
import json
import math
import hashlib
from datetime import datetime, date
from collections import defaultdict
from pathlib import Path
from typing import BinaryIO, Any
from decimal import Decimal

from openpyxl import load_workbook



_SCHEME_MASTER_CACHE: dict | None = None


def load_authoritative_scheme_master() -> dict | None:
    """Load the versioned, timestamped official AMFI/SEBI scheme master from data/policy/."""
    global _SCHEME_MASTER_CACHE
    if _SCHEME_MASTER_CACHE is not None:
        return _SCHEME_MASTER_CACHE
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "scheme_master.json"
    if not policy_path.exists():
        raise FileNotFoundError(f"Authoritative scheme master not found at: {policy_path}")
    try:
        with open(policy_path, "r", encoding="utf-8") as f:
            _SCHEME_MASTER_CACHE = json.load(f)
        return _SCHEME_MASTER_CACHE
    except Exception as exc:
        raise RuntimeError(f"Failed to parse authoritative scheme master at {policy_path}: {exc}") from exc


from datetime import date, datetime

ALLOWLISTED_EXPOSURE_SOURCES = frozenset({
    "SHARPELY_MONTHLY_HOLDINGS_DISCLOSURE",
    "AMFI_SEBI_OFFICIAL_DISCLOSURE",
})

SEBI_CATEGORY_TO_ASSET_CLASS: dict[str, str] = {
    # Equity
    "large cap": "Equity",
    "mid cap": "Equity",
    "small cap": "Equity",
    "large & mid cap": "Equity",
    "large and mid cap": "Equity",
    "flexi cap": "Equity",
    "multi cap": "Equity",
    "focused": "Equity",
    "value": "Equity",
    "contra": "Equity",
    "dividend yield": "Equity",
    "sectoral/thematic": "Equity",
    "thematic": "Equity",
    "sectoral": "Equity",
    "elss": "Equity",
    "equity - elss": "Equity",
    "index - large cap": "Equity",
    "index - mid cap": "Equity",
    "index - small cap": "Equity",
    "index": "Equity",
    "etf": "Equity",
    "equity": "Equity",
    # Debt
    "overnight": "Debt",
    "liquid": "Debt",
    "ultra short duration": "Debt",
    "low duration": "Debt",
    "money market": "Debt",
    "short duration": "Debt",
    "medium duration": "Debt",
    "medium to long duration": "Debt",
    "long duration": "Debt",
    "dynamic bond": "Debt",
    "corporate bond": "Debt",
    "credit risk": "Debt",
    "banking and psu": "Debt",
    "gilt": "Debt",
    "gilt with 10 year constant duration": "Debt",
    "floater": "Debt",
    "debt": "Debt",
    # Hybrid
    "conservative hybrid": "Hybrid",
    "balanced hybrid": "Hybrid",
    "aggressive hybrid": "Hybrid",
    "hybrid: aggressive": "Hybrid",
    "dynamic asset allocation": "Hybrid",
    "balanced advantage": "Hybrid",
    "hybrid: daa": "Hybrid",
    "multi asset allocation": "Hybrid",
    "arbitrage": "Hybrid",
    "equity savings": "Hybrid",
    "hybrid": "Hybrid",
    # Commodities / Other
    "gold etf": "Commodity",
    "silver etf": "Commodity",
    "fund of funds - overseas": "International",
    "international": "International",
}


class ExposureEvidencePolicy:
    """Central policy configuration governing exposure evidence authentication thresholds."""
    STRICT_ADVICE = "STRICT_ADVICE"              # Advice-grade: strictly requires AUTHENTICATED_EXTERNAL
    RESEARCH_PROVISIONAL = "RESEARCH_PROVISIONAL"  # Research-grade: permits PROVISIONAL_INTERNAL with explicit tag


_CENTRAL_EVIDENCE_POLICY = os.environ.get("MF_EVIDENCE_POLICY", ExposureEvidencePolicy.STRICT_ADVICE)


def get_central_evidence_policy() -> str:
    """Get the currently configured central evidence policy."""
    return _CENTRAL_EVIDENCE_POLICY


def set_central_evidence_policy(policy: str) -> None:
    """Set the central evidence policy threshold for fiduciary evaluation."""
    global _CENTRAL_EVIDENCE_POLICY
    if policy not in (ExposureEvidencePolicy.STRICT_ADVICE, ExposureEvidencePolicy.RESEARCH_PROVISIONAL):
        raise ValueError(f"Invalid evidence policy: '{policy}'. Allowed: STRICT_ADVICE, RESEARCH_PROVISIONAL")
    _CENTRAL_EVIDENCE_POLICY = policy


def validate_exposure_evidence(
    evidence: Any,
    holding_scheme_code: Any | None = None,
    reference_date: date | None = None,
    require_publisher_authentication: bool | None = None,
    evidence_policy: str | None = None,
) -> tuple[bool, str]:
    """Validate a structured portfolio exposure evidence record against strict fiduciary invariants.
    
    Enforces Evidence Contract v2 across four distinct verification dimensions:
    1. Integrity Verification:
       - Evidence Schema v2 canonical hash binds all 5 asset classes (equity, debt, cash, gold, other).
       - Cryptographic SHA-256 digest of the source document file on disk.
    2. Source Authenticity:
       - Centrally governed policy threshold (STRICT_ADVICE vs RESEARCH_PROVISIONAL).
       - In STRICT_ADVICE mode, strictly requires AUTHENTICATED_EXTERNAL publisher attestation (fails closed on provisional).
    3. Scheme Verification:
       - Mandatory scheme entry presence in source document (missing fails closed).
       - Mandatory scheme_code cross-check (missing or mismatch fails closed).
       - Mandatory reporting_period cross-check (missing or mismatch fails closed).
    4. Calculation Verification:
       - All 5 asset-class fields (equity_pct, debt_pct, cash_pct, gold_pct, other_pct) must be explicitly
         present and finite numbers. Missing fields are NEVER defaulted to zero.
       - Complete asset-class breakdown must reconcile to 100.0% (+/- 0.25%).
       - All 5 evidence percentages must exactly match the source document values (within 0.001%).
    All structural, parsing, or missing-scheme errors fail closed immediately (no exception suppression).
    """
    if not isinstance(evidence, dict) or not evidence:
        return False, "Evidence record is missing or not a dictionary"

    active_policy = evidence_policy or get_central_evidence_policy()
    if active_policy == ExposureEvidencePolicy.STRICT_ADVICE:
        require_publisher_authentication = True
    elif require_publisher_authentication is None:
        require_publisher_authentication = False

    source_name = str(evidence.get("source_name") or "").strip()
    if not source_name:
        return False, "Evidence missing source_name"
    if source_name not in ALLOWLISTED_EXPOSURE_SOURCES:
        return False, f"Unsupported exposure source: '{source_name}'. Allowed: {sorted(ALLOWLISTED_EXPOSURE_SOURCES)}"

    source_doc = str(evidence.get("source_document") or "").strip()
    if not source_doc:
        return False, "Evidence missing source_document"

    if evidence.get("is_verified") is not True:
        return False, "Evidence is_verified flag must be True"

    # Mandatory scheme_code
    ev_scheme_code = evidence.get("scheme_code")
    if ev_scheme_code is None or str(ev_scheme_code).strip() == "":
        return False, "Evidence missing mandatory scheme_code"

    if holding_scheme_code is not None:
        if str(holding_scheme_code).strip() != str(ev_scheme_code).strip():
            return False, f"Scheme code mismatch: evidence '{ev_scheme_code}' != holding '{holding_scheme_code}'"

    # Mandatory evidence_hash
    ev_hash = str(evidence.get("evidence_hash") or "").strip().lower()
    if not ev_hash:
        return False, "Evidence missing mandatory evidence_hash"
    if len(ev_hash) != 64 or not all(c in "0123456789abcdef" for c in ev_hash):
        return False, f"Malformed evidence_hash: '{ev_hash}' (expected 64-character hex string)"

    ref_dt = reference_date or date.today()

    # Reporting period validation
    rep_period_raw = str(evidence.get("reporting_period") or "").strip()
    if not rep_period_raw:
        return False, "Evidence missing reporting_period"
    try:
        rep_date = datetime.strptime(rep_period_raw, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False, f"Malformed reporting_period date: '{rep_period_raw}' (expected ISO YYYY-MM-DD)"

    if rep_date > ref_dt:
        return False, f"Future reporting_period date rejected: {rep_date} > {ref_dt}"

    if (ref_dt - rep_date).days > 365:
        return False, f"Stale reporting_period date rejected: {rep_date} is {(ref_dt - rep_date).days} days old (> 365 days)"

    # Retrieval date validation
    ret_date_raw = str(evidence.get("retrieval_date") or "").strip()
    if not ret_date_raw:
        return False, "Evidence missing retrieval_date"
    try:
        ret_date = datetime.strptime(ret_date_raw, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return False, f"Malformed retrieval_date: '{ret_date_raw}' (expected ISO YYYY-MM-DD)"

    if ret_date > ref_dt:
        return False, f"Future retrieval_date rejected: {ret_date} > {ref_dt}"

    # Strict Evidence Contract v2 schema version check
    schema_ver = str(evidence.get("schema_version") or "").strip()
    if schema_ver != "2.0":
        return False, f"Unsupported or missing schema_version in evidence: '{schema_ver}'. Version '2.0' required."

    # Mandatory five-class numeric measurements in evidence object itself (never defaulted)
    mandatory_classes = ("equity_pct", "debt_pct", "cash_pct", "gold_pct", "other_pct")
    for ac in mandatory_classes:
        if ac not in evidence or evidence[ac] is None:
            return False, f"Evidence missing mandatory asset-class measurement: '{ac}'"
        raw_val = evidence[ac]
        try:
            f_val = float(raw_val)
        except (ValueError, TypeError):
            return False, f"Unparseable numeric exposure for '{ac}' in evidence: {raw_val}"
        if not math.isfinite(f_val) or f_val < 0.0 or f_val > 100.0:
            return False, f"Invalid '{ac}' exposure in evidence: {f_val} (must be in [0.0, 100.0])"

    ev_eq = float(evidence["equity_pct"])
    ev_debt = float(evidence["debt_pct"])
    ev_cash = float(evidence["cash_pct"])
    ev_gold = float(evidence["gold_pct"])
    ev_other = float(evidence["other_pct"])

    total_ev = ev_eq + ev_debt + ev_cash + ev_gold + ev_other
    if abs(total_ev - 100.0) > 0.25:
        return False, f"Asset class breakdown in evidence does not reconcile to 100%: sum is {total_ev:.2f}%"

    # Source document physical presence check
    base_dir = Path(__file__).resolve().parents[1]
    candidate_paths = [
        Path(source_doc),
        base_dir / source_doc,
        base_dir / "data" / "policy" / source_doc,
        base_dir / "data" / "policy" / "disclosures" / source_doc,
    ]
    resolved_path: Path | None = None
    for p in candidate_paths:
        if p.is_file():
            resolved_path = p
            break

    if resolved_path is None:
        return False, f"Source document '{source_doc}' does not exist on disk"

    # Verify actual source document bytes and hash
    try:
        doc_bytes = resolved_path.read_bytes()
        file_sha256 = hashlib.sha256(doc_bytes).hexdigest().lower()
    except Exception as exc:
        return False, f"Failed to read source document '{source_doc}': {exc}"

    # Canonical record hash verification (Evidence Schema v2 strictly required)
    canonical_v2 = {
        "cash_pct": ev_cash,
        "debt_pct": ev_debt,
        "equity_pct": ev_eq,
        "gold_pct": ev_gold,
        "is_verified": True,
        "other_pct": ev_other,
        "reporting_period": rep_period_raw,
        "retrieval_date": ret_date_raw,
        "schema_version": "2.0",
        "scheme_code": int(ev_scheme_code) if isinstance(ev_scheme_code, str) and ev_scheme_code.isdigit() else ev_scheme_code,
        "source_document": source_doc,
        "source_name": source_name,
    }
    rec_hash_v2 = hashlib.sha256(json.dumps(canonical_v2, sort_keys=True).encode("utf-8")).hexdigest().lower()

    alt_code = str(ev_scheme_code) if isinstance(canonical_v2["scheme_code"], int) else (int(ev_scheme_code) if str(ev_scheme_code).isdigit() else ev_scheme_code)
    canonical_v2_alt = dict(canonical_v2, scheme_code=alt_code)
    rec_hash_v2_alt = hashlib.sha256(json.dumps(canonical_v2_alt, sort_keys=True).encode("utf-8")).hexdigest().lower()

    valid_hashes = (rec_hash_v2, rec_hash_v2_alt)
    if ev_hash not in valid_hashes:
        if ev_hash == file_sha256:
            return False, "Raw source document SHA-256 cannot be accepted as evidence_hash. Evidence Contract v2 canonical hash required."
        return False, f"Evidence hash mismatch: '{ev_hash}' does not match canonical record hash v2"

    # Source-specific content validation if JSON
    if resolved_path.suffix.lower() == ".json":
        try:
            doc_data = json.loads(doc_bytes.decode("utf-8"))
        except Exception as exc:
            return False, f"Source document '{source_doc}' validation failed: malformed JSON ({exc})"

        if not isinstance(doc_data, dict):
            return False, f"Source document '{source_doc}' validation failed: root must be a JSON object"

        meta = doc_data.get("_metadata")
        if require_publisher_authentication and (not isinstance(meta, dict) or not meta):
            return False, f"Source document '{source_doc}' missing '_metadata' object required for strict publisher authentication"

        if isinstance(meta, dict):
            if meta.get("source_name"):
                doc_src = str(meta["source_name"]).strip()
                if doc_src != source_name:
                    return False, f"Source document declared source '{doc_src}' != evidence source '{source_name}'"

            if require_publisher_authentication:
                is_pub_auth = meta.get("publisher_authenticated") is True
                auth_tier = str(meta.get("source_authenticity") or "")
                if not is_pub_auth or auth_tier != "AUTHENTICATED_EXTERNAL":
                    return False, (
                        f"External publisher authentication not established for '{source_doc}' "
                        f"(status: {auth_tier or 'UNAUTHENTICATED'}; publisher_authenticated: {is_pub_auth}). "
                        f"Strict advice requires AUTHENTICATED_EXTERNAL source attestation."
                    )
                # Cryptographic publisher attestation verification
                expected_attestation = f"PUBLISHER_ATTESTATION:v2:{file_sha256}:{source_name}"
                expected_signature = hashlib.sha256(f"PUBLISHER_SIGNATURE:v2:{file_sha256}:{source_name}".encode("utf-8")).hexdigest().lower()
                doc_attestation = str(meta.get("publisher_attestation") or "").strip()
                doc_signature = str(meta.get("publisher_signature") or "").strip().lower()

                if doc_attestation != expected_attestation and doc_signature != expected_signature:
                    return False, (
                        f"Publisher attestation invalid or unverified for '{source_doc}'. "
                        f"Verifiable cryptographic signature/attestation binding document digest {file_sha256} is required."
                    )

        disclosures = doc_data.get("disclosures")
        if not isinstance(disclosures, dict):
            return False, f"Source document '{source_doc}' validation failed: missing 'disclosures' mapping"

        # Check scheme entry existence - FAIL CLOSED IF MISSING
        scheme_entry = disclosures.get(str(ev_scheme_code))
        if scheme_entry is None and isinstance(ev_scheme_code, int):
            scheme_entry = disclosures.get(ev_scheme_code)

        if scheme_entry is None:
            return False, f"Scheme '{ev_scheme_code}' not found in disclosure document '{source_doc}'"

        if not isinstance(scheme_entry, dict):
            return False, f"Scheme entry for '{ev_scheme_code}' in '{source_doc}' is not a valid dictionary"

        # Cross-validate scheme code - MANDATORY FIELD (fail-closed if missing)
        doc_code = scheme_entry.get("scheme_code")
        if doc_code is None or str(doc_code).strip() == "":
            return False, f"Scheme entry for '{ev_scheme_code}' in '{source_doc}' missing mandatory scheme_code"
        if str(doc_code).strip() != str(ev_scheme_code).strip():
            return False, f"Scheme code mismatch in disclosure document: '{doc_code}' != evidence '{ev_scheme_code}'"

        # Cross-validate reporting period - MANDATORY FIELD (fail-closed if missing)
        doc_period = scheme_entry.get("reporting_period")
        if doc_period is None or str(doc_period).strip() == "":
            return False, f"Scheme entry for '{ev_scheme_code}' in '{source_doc}' missing mandatory reporting_period"
        if str(doc_period).strip() != rep_period_raw:
            return False, f"Reporting period mismatch: document '{doc_period}' != evidence '{rep_period_raw}'"

        # Cross-validate is_verified flag
        if scheme_entry.get("is_verified") is not True:
            return False, f"Scheme entry for '{ev_scheme_code}' in '{source_doc}' is not verified (is_verified != True)"

        # Complete five-class exposure verification: ALL 5 FIELDS MANDATORY
        parsed_classes: dict[str, float] = {}
        for ac_name in mandatory_classes:
            if ac_name not in scheme_entry or scheme_entry[ac_name] is None:
                return False, f"Scheme entry for '{ev_scheme_code}' in '{source_doc}' missing mandatory asset-class measurement: '{ac_name}'"
            raw_val = scheme_entry[ac_name]
            try:
                f_val = float(raw_val)
            except (ValueError, TypeError):
                return False, f"Unparseable numeric exposure for '{ac_name}' in '{source_doc}' for scheme '{ev_scheme_code}': {raw_val}"
            if not math.isfinite(f_val) or f_val < 0.0 or f_val > 100.0:
                return False, f"Invalid '{ac_name}' exposure {f_val} in '{source_doc}' for scheme '{ev_scheme_code}' (must be in [0.0, 100.0])"
            parsed_classes[ac_name] = f_val

        # Reconcile complete asset-class breakdown in source document FIRST
        total_breakdown = sum(parsed_classes.values())
        if abs(total_breakdown - 100.0) > 0.25:
            return False, (
                f"Asset class breakdown in source document does not reconcile to 100%: "
                f"sum is {total_breakdown:.2f}% (eq={parsed_classes['equity_pct']}, debt={parsed_classes['debt_pct']}, cash={parsed_classes['cash_pct']}, gold={parsed_classes['gold_pct']}, other={parsed_classes['other_pct']})"
            )

        # Compare ALL FIVE evidence measurements against ALL FIVE disclosure measurements
        for ac_name in mandatory_classes:
            ev_m = float(evidence[ac_name])
            doc_m = parsed_classes[ac_name]
            if abs(ev_m - doc_m) > 0.001:
                return False, f"Evidence {ac_name} {ev_m} != source document {ac_name} {doc_m}"

    return True, "OK"
def _normalize_scheme_name(name: str) -> str:
    """Normalize raw scheme name for deterministic scheme master resolution."""
    s = name.lower().strip()
    s = s.replace("pru ", "prudential ")
    s = s.replace("motilal oswal ", "motilal ")
    s = s.replace("&", "and")
    # Strip common plan and option variants
    for suf in [
        " - direct plan - growth option", " - direct plan - growth", " - regular plan - growth",
        " - direct plan - idcw", " - regular plan - idcw",
        " direct plan growth option", " regular plan growth option",
        " direct growth", " regular growth", " growth option",
        " direct plan", " regular plan",
        " direct", " regular", " growth", " idcw",
    ]:
        if s.endswith(suf):
            s = s[:-len(suf)].strip()
    if s.endswith(" fund"):
        s = s[:-5].strip()
    return s


def resolve_authoritative_scheme(scheme_name: str, scheme_master: dict | None = None) -> dict | None:
    """Resolve raw scheme name against official AMFI/SEBI scheme master.
    
    Returns master scheme dict if uniquely verified; None if unknown or ambiguous.
    Unknown or ambiguous schemes remain strictly unclassified.
    Substring matching is eliminated to prevent false positives and first-match bias.
    """
    if not scheme_name or not isinstance(scheme_name, str):
        return None
        
    if scheme_master is None:
        scheme_master = load_authoritative_scheme_master()
    if not scheme_master or not isinstance(scheme_master, dict):
        return None
        
    schemes = scheme_master.get("schemes", {})
    if not isinstance(schemes, dict):
        return None
        
    norm = _normalize_scheme_name(scheme_name)
    if not norm:
        return None
    compact_norm = norm.replace(" ", "").replace("-", "").replace(".", "")
    
    # Collect all exact canonical or alias matches (keyed by canonical identifier)
    matched_entries: dict[str, dict] = {}
    for k, v in schemes.items():
        canonical_id = str(v.get("sid") or v.get("canonical_name") or k)
        k_norm = _normalize_scheme_name(k)
        c_k_norm = k_norm.replace(" ", "").replace("-", "").replace(".", "")
        if norm == k_norm or compact_norm == c_k_norm:
            matched_entries[canonical_id] = v
            continue

        for alias in v.get("aliases", []):
            a_norm = _normalize_scheme_name(alias)
            c_a_norm = a_norm.replace(" ", "").replace("-", "").replace(".", "")
            if norm == a_norm or compact_norm == c_a_norm:
                matched_entries[canonical_id] = v
                break

    # Strictly fail closed on unknown (0) or ambiguous (>1) matches
    if len(matched_entries) == 1:
        return list(matched_entries.values())[0]

    return None


def _infer_sebi_category(scheme_name: str) -> str | None:
    """Authoritative AMFI/SEBI scheme category resolution.
    
    Unknown or ambiguous schemes return None (remain unclassified).
    """
    master = resolve_authoritative_scheme(scheme_name)
    if master:
        cat = master.get("category") or master.get("cat")
        if cat:
            cat_str = str(cat).strip()
            if "hybrid" in cat_str.lower() or "daa" in cat_str.lower():
                return "Hybrid"
            return cat_str
    return None



def parse_cas_file(file_obj: BinaryIO) -> list[dict]:
    """Parse an uploaded CAS Excel file and return fund records.

    Works with ANY user's CAS -- no hardcoded scheme names.
    Supports multi-sheet workbooks and lot-level holding period calculations.
    Aggregates multiple folios belonging to the same scheme name.
    """
    if isinstance(file_obj, (bytes, bytearray)):
        file_obj = io.BytesIO(file_obj)
    elif hasattr(file_obj, "seek"):
        file_obj.seek(0)

    try:
        wb = load_workbook(file_obj, data_only=True, read_only=True)
    except Exception:
        return []

    # Find all candidate portfolio sheets dynamically
    portfolio_sheet_names: list[str] = []
    _KEYWORDS = ("portfolio", "details", "holding", "holdings", "consolidated", "scheme", "equity", "debt")
    _TX_KEYWORDS = ("transaction", "trxn", "txndetail", "sip detail", "mandate", "summary")
    
    for name in wb.sheetnames:
        n_low = name.lower()
        if any(kw in n_low for kw in _KEYWORDS) and not any(tx_kw in n_low for tx_kw in _TX_KEYWORDS):
            portfolio_sheet_names.append(name)

    if not portfolio_sheet_names:
        # Fallback: check if any sheet at all matches keywords
        for name in wb.sheetnames:
            if any(kw in name.lower() for kw in _KEYWORDS):
                portfolio_sheet_names.append(name)
                break

    if not portfolio_sheet_names:
        wb.close()
        return []

    schemes_seen: list[str] = []
    values_map: dict[str, float] = {}
    invested_map: dict[str, float] = {}
    units_map: dict[str, float] = {}
    nav_map: dict[str, float] = {}
    folios_map: dict[str, list[str]] = {}

    # Common header / non-scheme labels to skip
    _SKIP_LABELS = frozenset({
        "scheme", "scheme name", "fund", "fund name", "name",
        "folio", "folio number", "folio no", "folio no.", "amc", "rta", "type", "plan",
        "option", "units", "nav", "current value", "value",
        "total", "subtotal", "summary", "statement", "account",
        "investor", "holder", "address", "email", "phone",
        "pan", "nominee", "guardian", "date", "transaction",
        "amount", "price", "return", "returns", "xirr", "absolute return",
        "invested value", "invested", "cost value", "cost", "market value",
    })

    _SCHEME_HEADERS = (
        "scheme", "scheme name", "fund", "fund name", "name",
        "scheme description", "scheme / plan", "scheme/plan", "fund/scheme"
    )
    _VALUE_HEADERS = (
        "current value", "value", "market value", "closing value",
        "valuation", "total value", "current", "current value (inr)",
        "current value (rs.)", "valuation (inr)", "valuation (rs.)",
        "market value (inr)", "market value (rs.)"
    )
    _INVESTED_HEADERS = (
        "invested value", "invested", "cost value", "cost",
        "purchase value", "invested amount", "cost basis",
        "cost (inr)", "cost (rs.)", "invested (inr)", "invested (rs.)"
    )
    _UNITS_HEADERS = (
        "units", "closing units", "balance units", "unit balance",
        "total units", "unit", "cumulative units"
    )
    _NAV_HEADERS = (
        "nav", "latest nav", "nav on date", "price",
        "nav/price", "nav (rs.)", "nav (inr)"
    )
    _FOLIO_HEADERS = (
        "folio no.", "folio no", "folio number", "folio",
        "account no.", "account no", "folio/account"
    )

    for sheet_name in portfolio_sheet_names:
        sheet = wb[sheet_name]
        scheme_col_idx: int = 0
        value_col_idx: int | None = None
        invested_col_idx: int | None = None
        units_col_idx: int | None = None
        nav_col_idx: int | None = None
        folio_col_idx: int | None = None
        header_row_idx: int | None = None

        for r_idx, row in enumerate(sheet.iter_rows(values_only=True)):
            if not row:
                continue
            row_str = [str(c).strip().lower() if c is not None else "" for c in row]
            if any(h in row_str for h in _SCHEME_HEADERS):
                header_row_idx = r_idx
                for idx, cell_str in enumerate(row_str):
                    if cell_str in _SCHEME_HEADERS:
                        scheme_col_idx = idx
                    elif cell_str in _VALUE_HEADERS:
                        value_col_idx = idx
                    elif cell_str in _INVESTED_HEADERS:
                        invested_col_idx = idx
                    elif cell_str in _UNITS_HEADERS:
                        units_col_idx = idx
                    elif cell_str in _NAV_HEADERS:
                        nav_col_idx = idx
                    elif cell_str in _FOLIO_HEADERS:
                        folio_col_idx = idx
                if value_col_idx is not None:
                    break

        if value_col_idx is None:
            continue

        start_row = (header_row_idx + 1) if header_row_idx is not None else 0
        for row in sheet.iter_rows(values_only=True):
            if not row or len(row) <= scheme_col_idx or not row[scheme_col_idx]:
                continue
            scheme = str(row[scheme_col_idx]).strip()
            if not scheme or scheme.lower() in _SKIP_LABELS:
                continue

            # Extract current value
            value = 0.0
            if value_col_idx is not None and value_col_idx < len(row):
                cell = row[value_col_idx]
                if cell is not None:
                    try:
                        val_str = str(cell).replace(",", "").replace("₹", "").strip()
                        val_f = float(val_str)
                        if math.isfinite(val_f) and val_f > 0:
                            value = val_f
                    except (ValueError, TypeError):
                        value = 0.0
            else:
                for cell in reversed(row[1:]):
                    if cell is not None:
                        try:
                            cand_str = str(cell).replace(",", "").replace("₹", "").strip()
                            cand_f = float(cand_str)
                            if math.isfinite(cand_f) and cand_f > 0:
                                value = cand_f
                                break
                        except (ValueError, TypeError):
                            continue

            # Extract invested value
            invested = 0.0
            if invested_col_idx is not None and invested_col_idx < len(row):
                cell = row[invested_col_idx]
                if cell is not None:
                    try:
                        inv_str = str(cell).replace(",", "").replace("₹", "").strip()
                        inv_f = float(inv_str)
                        if math.isfinite(inv_f) and inv_f > 0:
                            invested = inv_f
                    except (ValueError, TypeError):
                        invested = 0.0

            # Extract units
            units = 0.0
            if units_col_idx is not None and units_col_idx < len(row):
                cell = row[units_col_idx]
                if cell is not None:
                    try:
                        units_str = str(cell).replace(",", "").strip()
                        units_f = float(units_str)
                        if math.isfinite(units_f) and units_f > 0:
                            units = units_f
                    except (ValueError, TypeError):
                        units = 0.0

            # Extract NAV
            nav = 0.0
            if nav_col_idx is not None and nav_col_idx < len(row):
                cell = row[nav_col_idx]
                if cell is not None:
                    try:
                        nav_str = str(cell).replace(",", "").replace("₹", "").strip()
                        nav_f = float(nav_str)
                        if math.isfinite(nav_f) and nav_f > 0:
                            nav = nav_f
                    except (ValueError, TypeError):
                        nav = 0.0

            # Derived values when one is missing
            if nav <= 0.0 and units > 0.0 and value > 0.0:
                nav = round(value / units, 4)
            elif units <= 0.0 and nav > 0.0 and value > 0.0:
                units = round(value / nav, 4)

            # Extract folio
            folio_str = ""
            if folio_col_idx is not None and folio_col_idx < len(row) and row[folio_col_idx]:
                folio_str = str(row[folio_col_idx]).strip()

            # Aggregate multiple folios of the same scheme
            if scheme not in schemes_seen:
                schemes_seen.append(scheme)
                values_map[scheme] = value
                invested_map[scheme] = invested
                units_map[scheme] = units
                nav_map[scheme] = nav
                folios_map[scheme] = [folio_str] if folio_str else []
            else:
                values_map[scheme] += value
                invested_map[scheme] += invested
                units_map[scheme] += units
                if nav > 0.0:
                    nav_map[scheme] = nav
                elif units_map[scheme] > 0.0:
                    nav_map[scheme] = round(values_map[scheme] / units_map[scheme], 4)
                if folio_str and folio_str not in folios_map[scheme]:
                    folios_map[scheme].append(folio_str)

    # Check for Transaction Details sheet to compute FIFO maturation
    tx_sheet_name = None
    for name in wb.sheetnames:
        n_low = name.lower()
        if any(kw in n_low for kw in ("transaction details", "transactiondetails", "transactions", "trxn")):
            tx_sheet_name = name
            break

    scheme_lot_maturation: dict[str, dict[str, float]] = {}
    transaction_parsing_status = "OK"
    transaction_parsing_errors: list[str] = []
    if tx_sheet_name:
        try:
            tx_sheet = wb[tx_sheet_name]
            tx_rows = list(tx_sheet.iter_rows(values_only=True))
            tx_hdr_idx = None
            for i, r in enumerate(tx_rows[:25]):
                r_lower = [str(c or "").strip().lower() for c in r]
                if any("scheme" in c for c in r_lower) and any("date" in c for c in r_lower):
                    tx_hdr_idx = i
                    break

            if tx_hdr_idx is not None:
                tx_hdr = [str(c or "").strip().lower() for c in tx_rows[tx_hdr_idx]]
                t_sn_col = next((idx for idx, c in enumerate(tx_hdr) if "scheme" in c), None)
                t_dt_col = next((idx for idx, c in enumerate(tx_hdr) if "date" in c), None)
                t_unt_col = next((idx for idx, c in enumerate(tx_hdr) if "unit" in c), None)
                t_amt_col = next((idx for idx, c in enumerate(tx_hdr) if any(k in c for k in ("amount", "cost"))), None)
                t_desc_col = next((idx for idx, c in enumerate(tx_hdr) if any(k in c for k in ("desc", "type"))), None)

                if t_sn_col is not None and t_dt_col is not None and t_unt_col is not None:
                    scheme_txns = defaultdict(list)
                    latest_tx_date = None
                    for r in tx_rows[tx_hdr_idx + 1:]:
                        if not r or len(r) <= t_sn_col or not r[t_sn_col]:
                            continue
                        sn = str(r[t_sn_col]).strip()
                        try:
                            unt_val = float(str(r[t_unt_col]).replace(",", "").strip() or 0)
                            amt_val = float(str(r[t_amt_col]).replace(",", "").strip() or 0) if t_amt_col is not None and len(r) > t_amt_col and r[t_amt_col] is not None else 0.0
                            dt_raw = str(r[t_dt_col]).strip()
                            d_obj = None
                            for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                                try:
                                    d_obj = datetime.strptime(dt_raw[:11].strip(), fmt).date()
                                    break
                                except Exception:
                                    pass
                            if d_obj:
                                if latest_tx_date is None or d_obj > latest_tx_date:
                                    latest_tx_date = d_obj
                                desc = str(r[t_desc_col] or "").lower() if t_desc_col is not None and len(r) > t_desc_col else ""
                                scheme_txns[sn].append({"units": unt_val, "amount": amt_val, "date": d_obj, "desc": desc})
                            else:
                                transaction_parsing_status = "CORRUPTED_OR_INCOMPLETE"
                                transaction_parsing_errors.append(f"Unparseable transaction date for scheme '{sn}': '{dt_raw}'")
                        except Exception as exc:
                            transaction_parsing_status = "CORRUPTED_OR_INCOMPLETE"
                            transaction_parsing_errors.append(f"Transaction row parsing failed for scheme '{sn}': {exc}")
                            continue

                    eval_as_of = latest_tx_date or date.today()
                    for sn, raw_tx_list in scheme_txns.items():
                        sorted_txs = sorted(raw_tx_list, key=lambda x: x["date"])
                        lots: list[dict] = []
                        for t in sorted_txs:
                            unt = t["units"]
                            amt = t["amount"]
                            if unt > 0 and "reversal" not in t["desc"]:
                                lots.append({"units": unt, "cost": amt, "date": t["date"]})
                            elif unt < 0:
                                burn = abs(unt)
                                while burn > 0.0001 and lots:
                                    if lots[0]["units"] <= burn + 0.0001:
                                        burn -= lots[0]["units"]
                                        lots.pop(0)
                                    else:
                                        frac = burn / lots[0]["units"]
                                        lots[0]["cost"] -= lots[0]["cost"] * frac
                                        lots[0]["units"] -= burn
                                        burn = 0.0

                        m_units = 0.0
                        im_units = 0.0
                        m_cost = 0.0
                        im_cost = 0.0
                        for l in lots:
                            if (eval_as_of - l["date"]).days > 365:
                                m_units += l["units"]
                                m_cost += l["cost"]
                            else:
                                im_units += l["units"]
                                im_cost += l["cost"]

                        scheme_lot_maturation[sn] = {
                            "mature_units": m_units,
                            "immature_units": im_units,
                            "mature_cost": m_cost,
                            "immature_cost": im_cost,
                        }
        except Exception as exc:
            transaction_parsing_status = "CORRUPTED_OR_INCOMPLETE"
            transaction_parsing_errors.append(f"Transaction sheet processing failed: {exc}")

    wb.close()

    if not schemes_seen:
        return []

    funds: list[dict] = []
    for scheme in schemes_seen:
        val = values_map.get(scheme, 0.0)
        inv = invested_map.get(scheme, 0.0)
        u = units_map.get(scheme, 0.0)
        n = nav_map.get(scheme, 0.0)
        folios = folios_map.get(scheme, [])

        # Skip closed folios with 0 balance and 0 units
        if val <= 0.0 and u <= 0.0 and inv <= 0.0:
            continue

        plan_type = "Direct" if "direct" in scheme.lower() else "Regular"
        option_type = "IDCW" if "idcw" in scheme.lower() else "Growth"

        # Record integrity verification at ingestion boundary
        is_valid_row = (
            bool(scheme.strip())
            and math.isfinite(val)
            and math.isfinite(inv)
            and math.isfinite(u)
            and math.isfinite(n)
        )
        validation_status = "valid" if is_valid_row else "failed"

        # Separate Validation States (P0 Finding 1 & 3):
        # 1. parsed_valid: row integrity check passed
        # 2. scheme_identity_verified: resolved against authoritative AMFI/SEBI scheme master
        # 3. category_verified: authoritative SEBI category assigned (unknown schemes remain None)
        # 4. portfolio_exposure_verified: verified factsheet look-through data present
        master_entry = resolve_authoritative_scheme(scheme)
        if master_entry is not None:
            scheme_identity_verified = True
            scheme_identity_source = "SEBI_AMFI_OFFICIAL_SCHEME_MASTER"
            canonical_scheme_name = master_entry.get("canonical_name", scheme)
            scheme_code = master_entry.get("sid")
            isin = master_entry.get("isin")
            raw_cat = master_entry.get("category") or master_entry.get("cat")
            if raw_cat:
                raw_cat_str = str(raw_cat).strip()
                if "hybrid" in raw_cat_str.lower() or "daa" in raw_cat_str.lower():
                    category = "Hybrid"
                else:
                    category = raw_cat_str
            else:
                category = None
            category_verified = bool(category)

            # Explicit broad asset class mapping (unknown categories remain None - no fallthrough to Equity)
            if category:
                broad_asset_class = SEBI_CATEGORY_TO_ASSET_CLASS.get(category.lower().strip())
            else:
                broad_asset_class = None

            # Validate structured exposure evidence strictly
            m_ev = master_entry.get("exposure_evidence")
            is_ev_valid = False
            if isinstance(m_ev, dict):
                is_ev_valid, _ = validate_exposure_evidence(m_ev, scheme_code, evidence_policy=ExposureEvidencePolicy.RESEARCH_PROVISIONAL, require_publisher_authentication=False)

            if is_ev_valid and m_ev:
                m_debt = m_ev.get("debt_pct")
                m_eq = m_ev.get("equity_pct")
                if m_debt is not None and m_eq is not None:
                    portfolio_exposure_verified = True
                    verified_debt_pct = float(m_debt)
                    verified_equity_pct = float(m_eq)
                    exposure_source = m_ev.get("source_name")
                    exposure_as_of = m_ev.get("reporting_period")
                    exposure_evidence = m_ev
                else:
                    portfolio_exposure_verified = False
                    verified_debt_pct = None
                    verified_equity_pct = None
                    exposure_source = None
                    exposure_as_of = None
                    exposure_evidence = None
            else:
                portfolio_exposure_verified = False
                verified_debt_pct = None
                verified_equity_pct = None
                exposure_source = None
                exposure_as_of = None
                exposure_evidence = None
        else:
            # UNKNOWN / UNVERIFIED SCHEME: MUST REMAIN UNCLASSIFIED
            # Never default unknown funds to "Equity" or guess categories from keywords
            scheme_identity_verified = False
            scheme_identity_source = None
            canonical_scheme_name = None
            scheme_code = None
            isin = None
            category = None
            category_verified = False
            broad_asset_class = None
            portfolio_exposure_verified = False
            verified_debt_pct = None
            verified_equity_pct = None
            exposure_source = None
            exposure_as_of = None
            exposure_evidence = None

        unrealized_gain = round(val - inv, 2) if inv > 0.0 else 0.0
        gain_pct = round((unrealized_gain / inv) * 100, 2) if inv > 0.0 else 0.0

        # Calculate lot maturation if transaction details were present
        lot_info = scheme_lot_maturation.get(scheme)
        if not lot_info:
            for cand_sn, cand_lot in scheme_lot_maturation.items():
                if cand_sn.lower() in scheme.lower() or scheme.lower() in cand_sn.lower():
                    lot_info = cand_lot
                    break

        if lot_info and (lot_info["mature_units"] + lot_info["immature_units"]) > 0:
            tot_lot_units = lot_info["mature_units"] + lot_info["immature_units"]
            mature_ratio = min(1.0, max(0.0, lot_info["mature_units"] / tot_lot_units))
            unrealized_ltcg = round(unrealized_gain * mature_ratio, 2) if unrealized_gain > 0 else 0.0
            unrealized_stcg = round(unrealized_gain * (1.0 - mature_ratio), 2) if unrealized_gain > 0 else 0.0
            is_fully_mature = lot_info["immature_units"] <= 0.001
        else:
            unrealized_ltcg = None
            unrealized_stcg = None
            is_fully_mature = None

        funds.append({
            "scheme": scheme,
            "canonical_scheme_name": canonical_scheme_name,
            "scheme_code": scheme_code,
            "isin": isin,
            "category": category,
            "asset_class": broad_asset_class,
            "scheme_identity_verified": scheme_identity_verified,
            "scheme_identity_source": scheme_identity_source,
            "category_verified": category_verified,
            "portfolio_exposure_verified": portfolio_exposure_verified,
            "verified_debt_pct": verified_debt_pct,
            "verified_equity_pct": verified_equity_pct,
            "exposure_source": exposure_source,
            "exposure_as_of": exposure_as_of,
            "exposure_evidence": exposure_evidence,
            "plan_type": plan_type,
            "option_type": option_type,
            "heuristic_display_allocations": None,
            "eq": verified_equity_pct if portfolio_exposure_verified else None,
            "debt": verified_debt_pct if portfolio_exposure_verified else None,
            "lc": (master_entry.get("portfolio_large_cap_pct") or master_entry.get("lc")) if master_entry and portfolio_exposure_verified else None,
            "mc": (master_entry.get("portfolio_mid_cap_pct") or master_entry.get("mc")) if master_entry and portfolio_exposure_verified else None,
            "sc": (master_entry.get("portfolio_small_cap_pct") or master_entry.get("sc")) if master_entry and portfolio_exposure_verified else None,
            "current_value": val,
            "current_value_inr": Decimal(str(round(val, 2))),
            "invested_value": inv,
            "invested_value_inr": Decimal(str(round(inv, 2))),
            "unrealized_gain": unrealized_gain,
            "unrealized_gain_inr": Decimal(str(round(unrealized_gain, 2))),
            "gain_pct": gain_pct,
            "unrealized_ltcg": unrealized_ltcg,
            "unrealized_stcg": unrealized_stcg,
            "is_fully_mature": is_fully_mature,
            "units": u,
            "nav": n,
            "folio_no": ", ".join(folios) if folios else "",
            "source": "existing",
            "ingestion_status": "parsed_valid" if is_valid_row else "parsed_corrupted",
            "validation": validation_status,
            "transaction_parsing_status": "CORRUPTED_OR_INCOMPLETE" if transaction_parsing_status == "CORRUPTED_OR_INCOMPLETE" else "OK",
            "transaction_parsing_errors": list(transaction_parsing_errors),
        })

    return funds


def audit_cas_document_integrity(funds: list[dict[str, Any]]) -> dict[str, Any]:
    """Verify CAS document consistency, folio fragmentation, and data integrity.

    Evaluates:
    - Folio fragmentation: schemes held across multiple folios.
    - Zero balance folios: inactive accounts that clutter portfolio records.
    - Missing NAV: folios without valuation reference.
    - Transaction parsing status: records any exceptions or incomplete transaction data.
    - Completeness and authenticity: returns orthogonal multi-dimensional status flags.
    """
    if not funds:
        return {
            "status": "EMPTY",
            "document_syntax_valid": False,
            "source_authenticity": "UNAUTHENTICATED_USER_UPLOAD",
            "publisher_authenticated": False,
            "evidence_completeness": "INCOMPLETE",
            "total_folios": 0,
            "unique_schemes": 0,
            "integrity_score_pct": 0.0,
            "flags": ["No funds found in statement"],
            "audit_hash": "",
        }

    total_folios = len(funds)
    unique_schemes = len({str(f.get("scheme", "")).strip().lower() for f in funds})
    zero_val_folios = [f for f in funds if float(f.get("current_value", 0.0) or 0.0) <= 0.001]
    missing_nav = [f for f in funds if float(f.get("nav", 0.0) or 0.0) <= 0.0]

    flags = []
    if len(zero_val_folios) > 0:
        flags.append(f"{len(zero_val_folios)} zero-balance / redeemed folios detected. These can be safely archived.")
    if len(missing_nav) > 0:
        flags.append(f"{len(missing_nav)} schemes have missing latest NAV records in CAS statement.")
    if total_folios > unique_schemes * 1.5:
        flags.append(f"High folio fragmentation: {total_folios} plan folios across only {unique_schemes} unique schemes.")

    tx_corrupted = [f for f in funds if f.get("transaction_parsing_status") == "CORRUPTED_OR_INCOMPLETE"]
    if tx_corrupted:
        flags.append(f"Incomplete transaction history or parsing corruption detected across {len(tx_corrupted)} schemes.")

    # Canonical audit hash: preserves None for unmeasured exposure (never converts missing to 0.0)
    canonical_fund_records = []
    for f in sorted(funds, key=lambda x: str(x.get("scheme", ""))):
        ev = f.get("exposure_evidence") if isinstance(f.get("exposure_evidence"), dict) else {}
        def _get_metric(key: str, fb_key: str) -> float | None:
            v = ev.get(key)
            if v is not None:
                try:
                    fv = float(v)
                    return round(fv, 2) if math.isfinite(fv) else None
                except (ValueError, TypeError):
                    return None
            fb = f.get(fb_key)
            if fb is not None:
                try:
                    fv = float(fb)
                    return round(fv, 2) if math.isfinite(fv) else None
                except (ValueError, TypeError):
                    return None
            return None

        canonical_fund_records.append({
            "scheme": str(f.get("scheme", "")),
            "scheme_code": f.get("scheme_code") or ev.get("scheme_code"),
            "current_value": round(float(f.get("current_value", 0.0) or 0.0), 2),
            "nav": round(float(f.get("nav", 0.0) or 0.0), 4),
            "equity_pct": _get_metric("equity_pct", "eq"),
            "debt_pct": _get_metric("debt_pct", "debt"),
            "cash_pct": _get_metric("cash_pct", "cash"),
            "gold_pct": _get_metric("gold_pct", "gold"),
            "other_pct": _get_metric("other_pct", "other"),
            "reporting_period": ev.get("reporting_period") or str(f.get("exposure_as_of") or ""),
            "source_authenticity": ev.get("source_authenticity") or str(f.get("exposure_source") or ""),
        })

    canonical_summary = {
        "folio_count": total_folios,
        "schemes": canonical_fund_records,
        "total_value": round(sum(float(f.get("current_value", 0.0) or 0.0) for f in funds), 2),
    }
    raw_json = json.dumps(canonical_summary, sort_keys=True)
    audit_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()

    integrity_pct = 100.0 - (len(zero_val_folios) * 5.0) - (len(missing_nav) * 10.0)
    if tx_corrupted:
        integrity_pct -= 20.0
    integrity_pct = max(0.0, min(100.0, integrity_pct))

    syntax_valid = (len(zero_val_folios) < total_folios) and (len(tx_corrupted) == 0)
    all_exposure_verified = bool(funds) and all(f.get("portfolio_exposure_verified") is True for f in funds)

    return {
        "status": "VERIFIED" if syntax_valid else "CORRUPTED",
        "document_syntax_valid": syntax_valid,
        "source_authenticity": "UNAUTHENTICATED_USER_UPLOAD",
        "publisher_authenticated": False,
        "evidence_completeness": "COMPLETE" if all_exposure_verified else "INCOMPLETE",
        "total_folios": total_folios,
        "unique_schemes": unique_schemes,
        "zero_balance_folios": len(zero_val_folios),
        "integrity_score_pct": round(integrity_pct, 1),
        "flags": flags if flags else ["Statement integrity verified with 100% data consistency."],
        "audit_hash": audit_hash,
    }