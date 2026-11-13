"""
services/acquisition/adapters/portfolio_disclosure.py - AMC portfolio disclosure adapter.
Issue #110: Acquire and validate scheme portfolio constituent disclosures.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
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
        reviewer_attested: bool = False,
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

        if not self._scheme_id or not self._scheme_id.strip():
            raise ValueError("A non-empty canonical scheme ID is required for disclosure acquisition.")
        if not self.canonical_url.startswith("https://"):
            raise ValueError("Portfolio disclosure source URL must use HTTPS.")
        payload_scheme_id = payload.get("scheme_id")
        if payload_scheme_id is not None and str(payload_scheme_id).strip() != self._scheme_id:
            raise ValueError(
                f"Disclosure scheme ID {payload_scheme_id!r} does not match requested scheme {self._scheme_id!r}."
            )

        raw_weights = payload.get("constituent_weights")
        if not isinstance(raw_weights, dict) or not raw_weights:
            raise ValueError(f"Portfolio disclosure for {self._scheme_id} must contain non-empty constituent_weights.")

        coverage_raw = payload.get("constituent_weights_coverage_pct")
        if coverage_raw is None:
            raise ValueError(
                f"Portfolio disclosure for {self._scheme_id} must explicitly state constituent_weights_coverage_pct; "
                "coverage is never inferred as 100%."
            )
        try:
            coverage_decimal = Decimal(str(coverage_raw))
            if not coverage_decimal.is_finite() or not (Decimal("0") < coverage_decimal <= Decimal("100")):
                raise ValueError("Coverage percentage must be finite and in (0, 100].")
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"Invalid coverage percentage for {self._scheme_id}.") from exc

        clean_weights: Dict[str, float] = {}
        total_weight = Decimal("0")
        for asset, weight in raw_weights.items():
            if not isinstance(asset, str) or not asset.strip():
                raise ValueError(f"Portfolio disclosure for {self._scheme_id} has invalid asset identifier.")
            try:
                weight_decimal = Decimal(str(weight))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError(f"Malformed weight value for {asset} in {self._scheme_id}.") from exc
            if not weight_decimal.is_finite() or weight_decimal < 0:
                raise ValueError(f"Weight for {asset} in {self._scheme_id} must be finite and non-negative.")
            normalized_asset = asset.strip().upper()
            if normalized_asset in clean_weights:
                raise ValueError(f"Duplicate constituent identifier after normalization: {normalized_asset}.")
            total_weight += weight_decimal
            clean_weights[normalized_asset] = float(weight_decimal)

        if total_weight > coverage_decimal + Decimal("0.10"):
            raise ValueError(
                f"Constituent weights ({total_weight}) exceed disclosed coverage ({coverage_decimal}) "
                f"for scheme {self._scheme_id}."
            )
        coverage_pct = float(coverage_decimal)

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

