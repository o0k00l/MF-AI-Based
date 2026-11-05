"""
services/acquisition/adapters/base.py - Base contract for data acquisition adapters.
Issue #110: Deterministic, auditable upstream data retrieval.
"""

from __future__ import annotations

import hashlib
import urllib.request
import urllib.error
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from typing import Optional

from services.acquisition.models import AcquisitionRecord


class BaseSourceAdapter(ABC):
    """Abstract interface for all upstream financial data acquisition adapters."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Human-readable identifier for the upstream data source."""
        pass

    @property
    @abstractmethod
    def canonical_url(self) -> str:
        """The canonical source URL from which authoritative data is fetched."""
        pass

    def _fetch_url(self, url: str, *, timeout_seconds: float = 30.0) -> bytes:
        """Fetch raw bytes from upstream canonical URL with strict timeout and validation."""
        if not url.startswith("https://") and not url.startswith("http://"):
            raise ValueError(f"Insecure or invalid URL scheme for financial acquisition: {url}")

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "MF-AI-Financial-Acquisition/1.0 (+https://github.com/o0k00l/MF-AI-Based)",
                "Accept": "*/*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                status = getattr(resp, "status", 200)
                if status != 200:
                    raise IOError(f"Upstream source {url} returned HTTP status {status}")
                return resp.read()
        except urllib.error.URLError as exc:
            raise IOError(f"Network error acquiring source from {url}: {exc}") from exc

    @abstractmethod
    def acquire(
        self,
        as_of: date,
        *,
        raw_bytes: Optional[bytes] = None,
    ) -> AcquisitionRecord:
        """
        Acquire raw source data, compute cryptographic digest, and parse records.

        If raw_bytes is provided, it uses the provided bytes (hermetic/offline mode)
        instead of issuing network calls.
        """
        pass
