"""
core/security_master.py - Security master normalization and alias resolution.
Issue #26: Resolve underlying constituent identifiers to canonical securities
before portfolio overlap, concentration, and look-through aggregation.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
from typing import Any, Dict, Mapping, Optional, Tuple


# Common legal entity suffixes to strip during canonicalization
_LEGAL_SUFFIXES = re.compile(
    r"\b(LIMITED|LTD\.?|CORP\.?|CORPORATION|INC\.?|INCORPORATED|PLC|HOLDINGS?|CO\.?|COMPANY)\b",
    re.IGNORECASE,
)
_PUNCTUATION = re.compile(r"[^A-Za-z0-9\s]")
_CORPORATE_ACTION_ANNOTATIONS = re.compile(
    r"(\((?:MERGED|AMALGAMATED|BONUS|SPLIT)[^)]*\)|-\s*(?:PP|PARTLY\s+PAID|DVR|RE|RIGHTS|EQ)|\b(?:PP|PARTLY\s+PAID|DVR|EQUITY)\b)",
    re.IGNORECASE,
)


def canonicalize_security_label(label: str) -> str:
    """
    Produce a deterministic base string representation of a security or issuer label.
    Handles punctuation, corporate action parentheticals, and legal entity suffixes.
    """
    if not isinstance(label, str):
        return ""
    text = label.strip().upper()
    text = _CORPORATE_ACTION_ANNOTATIONS.sub(" ", text)
    # Convert & to AND before punctuation stripping
    text = re.sub(r"\s*&\s*", " AND ", text)
    text = _PUNCTUATION.sub(" ", text)
    text = _LEGAL_SUFFIXES.sub("", text)
    # Collapse consecutive whitespace
    tokens = [t for t in text.split() if t]
    return " ".join(tokens)


def load_security_master(master_path: Optional[pathlib.Path] = None) -> Dict[str, Any]:
    """
    Load, validate and bind the central versioned security master.
    """
    if master_path is None:
        master_path = pathlib.Path(__file__).resolve().parents[1] / "data" / "policy" / "security_master.json"
    if not isinstance(master_path, pathlib.Path):
        master_path = pathlib.Path(master_path)
    if not master_path.is_file():
        raise FileNotFoundError(f"Security master file not found: {master_path}")

    try:
        data = json.loads(master_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Security master file is invalid JSON: {master_path}") from exc

    if not isinstance(data, dict):
        raise ValueError("Security master root must be a JSON object")
    if data.get("_schema") != "fiduciary.security_master.v1":
        raise ValueError("Security master schema must be fiduciary.security_master.v1")

    data["_master_digest"] = hashlib.sha256(master_path.read_bytes()).hexdigest()
    data["_master_path"] = str(master_path)
    return data


def normalize_security_identifier(
    raw_identifier: str,
    security_master: Optional[Mapping[str, Any]] = None,
    *,
    strict: bool = False,
) -> Tuple[str, bool]:
    """
    Resolve a constituent security identifier against an authoritative security master.

    Returns (canonical_identifier, is_resolved):
    - If security_master is supplied and the identifier (or canonical form) is found,
      returns (master_canonical_id, True).
    - If security_master is supplied and not found:
      - If strict=True: raises ValueError("Unresolved security identifier: ...").
      - If strict=False: returns (base_canonical_label, False).
    - If security_master is None:
      - If strict=True: raises ValueError("Strict security resolution requested but security master is missing").
      - If strict=False: returns (base_canonical_label, True).
    """
    if not isinstance(raw_identifier, str) or not raw_identifier.strip():
        raise ValueError("Security identifier must be a non-empty string.")

    raw = raw_identifier.strip()
    canon_base = canonicalize_security_label(raw)
    if not canon_base:
        canon_base = raw.upper()

    if security_master is None:
        if strict:
            raise ValueError(f"Strict security resolution requested but security master is missing for: {raw!r}")
        return canon_base, True

    # Unwrap if wrapped in {"securities": {...}}
    master_dict = security_master.get("securities", security_master) if isinstance(security_master, Mapping) else security_master

    # 0a. Check corporate_actions dictionary (e.g. Mergers, Spinoffs)
    corporate_actions = security_master.get("corporate_actions", {}) if isinstance(security_master, Mapping) else {}
    for key in (raw, raw.upper(), canon_base):
        if key in corporate_actions:
            ca = corporate_actions[key]
            successor = ca.get("successor_canonical_id", ca.get("canonical_id", ca)) if isinstance(ca, dict) else str(ca)
            return successor, True

    # 0b. Check cross-AMC aliases dictionary
    amc_aliases = security_master.get("amc_aliases", {}) if isinstance(security_master, Mapping) else {}
    for key in (raw, raw.upper(), canon_base):
        if key in amc_aliases:
            alias_target = amc_aliases[key]
            if alias_target in master_dict:
                resolved = master_dict[alias_target]
                canonical_id = resolved.get("canonical_id", alias_target) if isinstance(resolved, dict) else str(resolved)
                return canonical_id, True
            return alias_target, True

    # 1. Exact match in security_master
    if raw in master_dict:
        resolved = master_dict[raw]
        canonical_id = resolved.get("canonical_id", raw) if isinstance(resolved, dict) else str(resolved)
        return canonical_id, True

    # 2. Case-insensitive / upper match
    raw_upper = raw.upper()
    if raw_upper in master_dict:
        resolved = master_dict[raw_upper]
        canonical_id = resolved.get("canonical_id", raw_upper) if isinstance(resolved, dict) else str(resolved)
        return canonical_id, True

    # 3. Canonicalized base match (with and without whitespace collapsing)
    if canon_base in master_dict:
        resolved = master_dict[canon_base]
        canonical_id = resolved.get("canonical_id", canon_base) if isinstance(resolved, dict) else str(resolved)
        return canonical_id, True

    canon_nospace = canon_base.replace(" ", "")
    if canon_nospace in master_dict:
        resolved = master_dict[canon_nospace]
        canonical_id = resolved.get("canonical_id", canon_nospace) if isinstance(resolved, dict) else str(resolved)
        return canonical_id, True

    # 4. Alias resolution: scan all securities for aliases or ISIN matching the identifier
    if isinstance(master_dict, Mapping):
        for security_id, security_info in master_dict.items():
            if isinstance(security_info, dict):
                aliases = security_info.get("aliases", [])
                if isinstance(aliases, list):
                    clean_aliases = [str(a).strip().upper() for a in aliases]
                    if raw_upper in clean_aliases or canon_base in clean_aliases:
                        canonical_id = security_info.get("canonical_id", security_id)
                        return canonical_id, True
                isin = str(security_info.get("isin", "")).strip().upper()
                if isin and (raw_upper == isin or canon_base == isin):
                    canonical_id = security_info.get("canonical_id", security_id)
                    return canonical_id, True

    if strict:
        raise ValueError(f"Unresolved security identifier: {raw!r}")

    return canon_base, False


def normalize_constituent_weights(
    raw_weights: Mapping[str, float],
    security_master: Optional[Mapping[str, Any]] = None,
    *,
    strict: bool = False,
) -> Tuple[Dict[str, float], Dict[str, str]]:
    """
    Normalize constituent weight mappings to canonical security identifiers.

    Aggregates percentages if multiple variants resolve to the same underlying security.
    Returns: (canonical_weights, original_labels_by_canonical_id)
    """
    canonical_weights: Dict[str, float] = {}
    original_labels: Dict[str, str] = {}

    for raw_label, weight in raw_weights.items():
        canonical_id, is_resolved = normalize_security_identifier(
            raw_label, security_master=security_master, strict=strict
        )
        canonical_weights[canonical_id] = canonical_weights.get(canonical_id, 0.0) + float(weight)
        if canonical_id not in original_labels:
            original_labels[canonical_id] = str(raw_label).strip()

    return canonical_weights, original_labels
