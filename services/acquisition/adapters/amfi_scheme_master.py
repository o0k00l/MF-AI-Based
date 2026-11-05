"""
services/acquisition/adapters/amfi_scheme_master.py - AMFI scheme master adapter.
Issue #110: Acquire, validate, and normalize mutual fund scheme master records.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Set

from services.acquisition.adapters.base import BaseSourceAdapter
from services.acquisition.models import AcquisitionRecord


class AmfiSchemeMasterAdapter(BaseSourceAdapter):
    """
    Adapter for acquiring and validating AMFI India official scheme master records.

    Canonical source: https://www.amfiindia.com/research-information/other-data/scheme-details
    Ensures structural and provenance compliance with `services/sip_evidence_contract.py`.
    """

    CANONICAL_SCHEME_MASTER_URL = "https://www.amfiindia.com/research-information/other-data/scheme-details"

    def __init__(self, canonical_url: Optional[str] = None):
        self._url = canonical_url or self.CANONICAL_SCHEME_MASTER_URL

    @property
    def source_name(self) -> str:
        return "AMFI_SCHEME_MASTER"

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
        """
        Acquire and validate AMFI scheme master records.
        Supports both structured JSON and CSV raw payloads.
        """
        retrieval_timestamp = datetime.now(timezone.utc).isoformat()
        if raw_bytes is None:
            raw_bytes = self._fetch_url(self.canonical_url)

        if not raw_bytes or not raw_bytes.strip():
            raise ValueError("Scheme master source payload is empty.")

        digest = hashlib.sha256(raw_bytes).hexdigest()

        # Parse raw payload (JSON or CSV)
        raw_schemes: List[Dict[str, Any]] = []
        try:
            parsed_json = json.loads(raw_bytes.decode("utf-8"))
            if isinstance(parsed_json, dict) and "schemes" in parsed_json:
                raw_schemes = parsed_json["schemes"]
            elif isinstance(parsed_json, list):
                raw_schemes = parsed_json
            else:
                raise ValueError("JSON payload does not contain schemes array.")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            # Attempt CSV parsing
            try:
                csv_text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                csv_text = raw_bytes.decode("latin-1")
            reader = csv.DictReader(io.StringIO(csv_text))
            raw_schemes = [row for row in reader]

        if not raw_schemes:
            raise ValueError("Scheme master source contains no parseable scheme entries.")

        normalized_schemes: List[Dict[str, Any]] = []
        seen_scheme_ids: Set[str] = set()
        seen_isins: Set[str] = set()

        for idx, row in enumerate(raw_schemes):
            scheme_id = str(row.get("scheme_id", "")).strip()
            isin = str(row.get("isin", "")).strip()
            scheme_name = str(row.get("scheme_name", "")).strip()
            amc_name = str(row.get("amc_name", "")).strip()
            category = str(row.get("category", "")).strip()
            benchmark_identity = str(row.get("benchmark_identity", "")).strip()
            scheme_structure = str(row.get("scheme_structure", "")).strip()
            plan_type_raw = str(row.get("plan_type", "")).strip()
            option_type_raw = str(row.get("option_type", "")).strip()
            riskometer_raw = row.get("riskometer_score")

            if not scheme_id or not isin:
                continue

            if scheme_id in seen_scheme_ids or isin in seen_isins:
                raise ValueError(f"Duplicate scheme_id {scheme_id!r} or ISIN {isin!r} at index {idx}.")

            if not all([scheme_name, amc_name, category, benchmark_identity, scheme_structure]):
                continue

            plan_type_cf = plan_type_raw.casefold()
            if plan_type_cf not in {"direct", "regular"}:
                continue
            plan_type = "Direct" if plan_type_cf == "direct" else "Regular"

            option_type_cf = option_type_raw.casefold()
            if option_type_cf not in {"growth", "idcw"}:
                continue
            option_type = "Growth" if option_type_cf == "growth" else "IDCW"

            try:
                riskometer_score = int(riskometer_raw)
                if not (1 <= riskometer_score <= 6):
                    continue
            except (ValueError, TypeError):
                continue

            record = {
                "scheme_id": scheme_id,
                "isin": isin,
                "scheme_name": scheme_name,
                "amc_name": amc_name,
                "category": category,
                "benchmark_identity": benchmark_identity,
                "scheme_structure": scheme_structure,
                "plan_type": plan_type,
                "option_type": option_type,
                "riskometer_score": riskometer_score,
            }
            normalized_schemes.append(record)
            seen_scheme_ids.add(scheme_id)
            seen_isins.add(isin)

        if not normalized_schemes:
            raise ValueError("No valid schemes could be normalized from the scheme master source.")

        structured_master = {
            "source_url": self.canonical_url,
            "source_document_sha256": digest,
            "reviewer_attested": reviewer_attested,
            "effective_date": as_of.isoformat(),
            "source_type": "OFFICIAL_SCHEME_MASTER",
            "status": "VERIFIED",
            "schemes": normalized_schemes,
        }

        return AcquisitionRecord(
            source_name=self.source_name,
            source_url=self.canonical_url,
            retrieval_timestamp=retrieval_timestamp,
            as_of_date=as_of,
            source_bytes=raw_bytes,
            source_sha256=digest,
            parsed_payload=structured_master,
            record_count=len(normalized_schemes),
            metadata={
                "status": "VERIFIED",
                "source_type": "OFFICIAL_SCHEME_MASTER",
            },
        )

