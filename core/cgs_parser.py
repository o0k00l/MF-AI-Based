"""
core/cgs_parser.py — Official Capital Gains Statement (CGS) Ingestion & Tax Auditor.

Parses CAMS, KFintech, and MFCentral CGS Excel reports ('cgs_detailed_report_*.xlsx'):
1. Summary Sheet: Realized STCG, LTCG under Section 112A, Outflow & Acquisition Cost.
2. Scheme_Level_Summary: Fund-by-fund realized gain/loss breakdown.
3. TransactionDetails: Lot-level subscription and redemption audit.
"""
from __future__ import annotations
import openpyxl
from pathlib import Path
import hashlib
from typing import Dict, List, Any, Optional
import warnings

# Suppress openpyxl styling warnings on non-standard CGS exports
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")


def discover_cgs_report_evidence(
    client_dir: Path,
    *,
    as_of=None,
    max_statement_age_days=None,
):
    """Return validated CGS selection evidence; missing policy is a hard HOLD."""
    from datetime import date
    from ingestion.statement_selection import select_latest_statement

    if not isinstance(as_of, date):
        raise ValueError("An explicit decision as_of date is required for CGS statement selection")
    if max_statement_age_days is None:
        raise ValueError("An approved maximum CGS statement age policy is required")
    candidates = list((client_dir / "statements").glob("*cgs*.xlsx"))
    candidates.extend(client_dir.glob("*cgs*.xlsx"))
    return select_latest_statement(
        candidates,
        document_type="CGS",
        as_of=as_of,
        max_age_days=max_statement_age_days,
    )


def discover_cgs_report(
    client_dir: Path,
    *,
    as_of=None,
    max_statement_age_days=None,
) -> Optional[Path]:
    """Return the uniquely newest fresh CGS statement by embedded date."""
    return discover_cgs_report_evidence(
        client_dir,
        as_of=as_of,
        max_statement_age_days=max_statement_age_days,
    )


def parse_cgs_excel(cgs_path: str | Path, **provenance_options: Any) -> Dict[str, Any]:
    """Compatibility facade; provenance options pass through to the canonical CGS parser."""
    from ingestion.cgs_parser import parse_cgs_excel as parse_source_report
    return parse_source_report(cgs_path, **provenance_options)
