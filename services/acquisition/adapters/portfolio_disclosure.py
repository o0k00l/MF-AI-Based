"""
services/acquisition/adapters/portfolio_disclosure.py - AMC portfolio disclosure adapter.
Issue #110: Acquire and validate scheme portfolio constituent disclosures.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from services.acquisition.adapters.base import BaseSourceAdapter
from services.acquisition.models import AcquisitionRecord


class PortfolioDisclosureAdapter(BaseSourceAdapter):
    """
    Adapter for AMC periodic portfolio holding disclosures.

    Canonical source: AMC monthly / half-yearly portfolio disclosures published per SEBI mandate.
    """

    CANONICAL_DISCLOSURE_URL = "https://www.amfiindia.com/research-information/other-data/portfolio-disclosures"

    def __init__(self, scheme_id: str, canonical_url: Optional[str] = None):
        self._scheme_id = scheme_id
        self._url = canonical_url or f"{self.CANONICAL_DISCLOSURE_URL}/{scheme_id}"

    @property
    def source_name(self) -> str:
        return f"AMC_PORTFOLIO_DISCLOSURE_{self._scheme_id}"

    @property
    def canonical_url(self) -> str:
        return self._url

    def acquire(
        self,
        as_of: date,
        *,
        raw_bytes: Optional[bytes] = None,
        reviewer_attested: bool = True,
    ) -> AcquisitionRecord:
        retrieval_timestamp = datetime.now(timezone.utc).isoformat()
        if raw_bytes is None:
            raw_bytes = self._fetch_url(self.canonical_url)

        if not raw_bytes or not raw_bytes.strip():
            raise ValueError(f"Portfolio disclosure payload for scheme {self._scheme_id} is empty.")

        digest = hashlib.sha256(raw_bytes).hexdigest()

        try:
            payload = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Portfolio disclosure for {self._scheme_id} must be valid JSON.") from exc

        if not isinstance(payload, dict):
            raise ValueError(f"Portfolio disclosure payload for {self._scheme_id} must be a dictionary.")

        raw_weights = payload.get("constituent_weights")
        if not isinstance(raw_weights, dict) or not raw_weights:
            raise ValueError(f"Portfolio disclosure for {self._scheme_id} must contain non-empty constituent_weights.")

        clean_weights: Dict[str, float] = {}
        for asset, weight in raw_weights.items():
            if not isinstance(asset, str) or not asset.strip():
                raise ValueError(f"Portfolio disclosure for {self._scheme_id} has invalid asset identifier.")
            try:
                w_val = float(weight)
                if w_val < 0:
                    raise ValueError(f"Negative constituent weight for {asset} in {self._scheme_id}.")
                clean_weights[asset.strip().upper()] = w_val
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Malformed weight value for {asset} in {self._scheme_id}.") from exc

        coverage_raw = payload.get("constituent_weights_coverage_pct", 100.0)
        try:
            coverage_pct = float(coverage_raw)
            if not (0.0 <= coverage_pct <= 100.0):
                raise ValueError(f"Coverage percentage out of range: {coverage_pct}")
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid coverage percentage for {self._scheme_id}.") from exc

        normalized_record = {
            "source_url": self.canonical_url,
            "source_document_sha256": digest,
            "reviewer_attested": reviewer_attested,
            "effective_date": as_of.isoformat(),
            "source_type": "AMC_PORTFOLIO_DISCLOSURE",
            "scheme_id": self._scheme_id,
            "constituent_weights": clean_weights,
            "constituent_weights_coverage_pct": coverage_pct,
        }

        return AcquisitionRecord(
            source_name=self.source_name,
            source_url=self.canonical_url,
            retrieval_timestamp=retrieval_timestamp,
            as_of_date=as_of,
            source_bytes=raw_bytes,
            source_sha256=digest,
            parsed_payload=normalized_record,
            record_count=len(clean_weights),
            metadata={
                "scheme_id": self._scheme_id,
                "coverage_pct": coverage_pct,
            },
        )
