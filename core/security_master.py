"""
core/security_master.py - Security master normalization and alias resolution.
Issue #26: Resolve underlying constituent identifiers to canonical securities
before portfolio overlap, concentration, and look-through aggregation.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Tuple


# Common legal entity suffixes to strip during canonicalization
_LEGAL_SUFFIXES = re.compile(
    r"\b(LIMITED|LTD\.?|CORP\.?|CORPORATION|INC\.?|INCORPORATED|PLC|HOLDINGS?|CO\.?|COMPANY)\b",
    re.IGNORECASE,
)
_PUNCTUATION = re.compile(r"[^A-Za-z0-9\s]")


def canonicalize_security_label(label: str) -> str:
    """
    Produce a deterministic base string representation of a security or issuer label.
    """
    if not isinstance(label, str):
        return ""
    text = label.strip().upper()
    text = _PUNCTUATION.sub(" ", text)
    text = _LEGAL_SUFFIXES.sub("", text)
    # Collapse consecutive whitespace
    tokens = [t for t in text.split() if t]
    return " ".join(tokens)


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
    - If security_master is None: returns (base_canonical_label, True).
    """
    if not isinstance(raw_identifier, str) or not raw_identifier.strip():
        raise ValueError("Security identifier must be a non-empty string.")

    raw = raw_identifier.strip()
    canon_base = canonicalize_security_label(raw)
    if not canon_base:
        canon_base = raw.upper()

    if security_master is None:
        return canon_base, True

    # 1. Exact match in security_master
    if raw in security_master:
        resolved = security_master[raw]
        canonical_id = resolved.get("canonical_id", raw) if isinstance(resolved, dict) else str(resolved)
        return canonical_id, True

    # 2. Case-insensitive / upper match
    raw_upper = raw.upper()
    if raw_upper in security_master:
        resolved = security_master[raw_upper]
        canonical_id = resolved.get("canonical_id", raw_upper) if isinstance(resolved, dict) else str(resolved)
        return canonical_id, True

    # 3. Canonicalized base match
    if canon_base in security_master:
        resolved = security_master[canon_base]
        canonical_id = resolved.get("canonical_id", canon_base) if isinstance(resolved, dict) else str(resolved)
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
