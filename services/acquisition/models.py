"""
services/acquisition/models.py - Data models for financial source acquisition.
Issue #110: Auditable provenance and metadata models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class AcquisitionRecord:
    """Immutable representation of acquired source material with full cryptographic provenance."""

    source_name: str
    source_url: str
    retrieval_timestamp: str
    as_of_date: date
    source_bytes: bytes
    source_sha256: str
    parsed_payload: Any
    record_count: int
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RefreshResult:
    """Summary of an acquisition and bundle refresh execution."""

    status: str  # "SUCCESS" or "FAILED"
    bundle_dir: Optional[Path] = None
    sources_acquired: List[str] = field(default_factory=list)
    records_count_by_source: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    completed_at: Optional[str] = None
    is_atomic_rollback: bool = False
