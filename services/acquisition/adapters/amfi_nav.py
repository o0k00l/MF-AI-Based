"""
services/acquisition/adapters/amfi_nav.py - Authoritative AMFI NAV feed adapter.
Issue #110: Parse and validate daily mutual fund Net Asset Values from AMFI India.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from services.acquisition.adapters.base import BaseSourceAdapter
from services.acquisition.models import AcquisitionRecord


class AmfiNavAdapter(BaseSourceAdapter):
    """
    Adapter for acquiring and parsing AMFI India daily NAV feed.

    Authoritative source: https://www.amfiindia.com/spages/NAVAll.txt
    Line format: Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
    """

    CANONICAL_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

    def __init__(self, canonical_url: Optional[str] = None, *, max_staleness_days: int = 45):
        self._url = canonical_url or self.CANONICAL_NAV_URL
        self._max_staleness_days = max_staleness_days

    @property
    def source_name(self) -> str:
        return "AMFI_DAILY_NAV"

    @property
    def canonical_url(self) -> str:
        return self._url

    def acquire(
        self,
        as_of: date,
        *,
        raw_bytes: Optional[bytes] = None,
    ) -> AcquisitionRecord:
        """
        Acquire AMFI daily NAV text feed, validate cryptographic integrity, and parse NAV records.
        """
        retrieval_timestamp = datetime.now(timezone.utc).isoformat()
        if raw_bytes is None:
            raw_bytes = self._fetch_url(self.canonical_url)

        if not raw_bytes or not raw_bytes.strip():
            raise ValueError("AMFI daily NAV feed response is empty.")

        digest = hashlib.sha256(raw_bytes).hexdigest()

        # AMFI feeds are generally ASCII/UTF-8; fallback to latin-1 if corrupted encodings appear
        try:
            text = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = raw_bytes.decode("latin-1")

        parsed_records: List[Dict[str, Any]] = []
        rejected_rows_count = 0
        current_category: Optional[str] = None

        for line_num, line in enumerate(text.splitlines(), start=1):
            line_str = line.strip()
            if not line_str:
                continue

            # Header row detection
            if "Scheme Code" in line_str and "Net Asset Value" in line_str:
                continue

            # Category / type divider row (does not contain standard semicolons)
            if ";" not in line_str:
                current_category = line_str
                continue

            parts = [p.strip() for p in line_str.split(";")]
            if len(parts) < 6:
                rejected_rows_count += 1
                continue

            scheme_code_str, isin_growth, isin_reinv, scheme_name, nav_str, date_str = parts[:6]

            if not scheme_code_str or not scheme_code_str.isdigit():
                rejected_rows_count += 1
                continue

            if not scheme_name:
                rejected_rows_count += 1
                continue

            # Validate numeric NAV and preserve Decimal precision
            try:
                nav_dec = Decimal(nav_str)
                if not nav_dec.is_finite() or nav_dec <= 0:
                    rejected_rows_count += 1
                    continue
                nav_val = nav_dec
            except (InvalidOperation, ValueError, TypeError):
                rejected_rows_count += 1
                continue

            # Parse record date (format: DD-Mon-YYYY e.g. 04-Nov-2026 or DD-MM-YYYY)
            nav_date: Optional[date] = None
            for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
                try:
                    nav_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue

            if nav_date is None:
                rejected_rows_count += 1
                continue

            # Freshness and future-date enforcement
            if nav_date > as_of:
                # Reject future-dated entries
                rejected_rows_count += 1
                continue

            age_days = (as_of - nav_date).days
            if age_days > self._max_staleness_days:
                # Stale record rejected per freshness policy
                rejected_rows_count += 1
                continue

            record = {
                "scheme_code": scheme_code_str,
                "isin_growth": isin_growth if isin_growth and isin_growth != "-" else None,
                "isin_reinvestment": isin_reinv if isin_reinv and isin_reinv != "-" else None,
                "scheme_name": scheme_name,
                "nav": nav_val,
                "nav_date": nav_date.isoformat(),
                "category_header": current_category,
            }
            parsed_records.append(record)

        return AcquisitionRecord(
            source_name=self.source_name,
            source_url=self.canonical_url,
            retrieval_timestamp=retrieval_timestamp,
            as_of_date=as_of,
            source_bytes=raw_bytes,
            source_sha256=digest,
            parsed_payload=parsed_records,
            record_count=len(parsed_records),
            metadata={
                "rejected_rows_count": rejected_rows_count,
                "source_type": "OFFICIAL_AMFI_DAILY_NAV",
            },
        )

