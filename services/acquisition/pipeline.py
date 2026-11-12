"""
services/acquisition/pipeline.py - Financial data acquisition and refresh pipeline.
Issue #110: Auditable, deterministic, and idempotent financial-data refresh pipeline.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from services.acquisition.adapters.amfi_nav import AmfiNavAdapter
from services.acquisition.adapters.amfi_scheme_master import AmfiSchemeMasterAdapter
from services.acquisition.adapters.portfolio_disclosure import PortfolioDisclosureAdapter
from services.acquisition.bundle_builder import EvidenceBundleBuilder
from services.acquisition.models import AcquisitionRecord, RefreshResult
from services.sip_evidence_bundle import build_sip_evidence_provider
from services.sip_evidence_contract import validate_evidence_provider_payload


class FinancialDataRefreshPipeline:
    """
    Coordinates multi-source financial data acquisition, validation, and atomic bundle refresh.

    Guarantees:
    - Zero modification of last-known-good bundle on upstream failure or corruption (fail-closed).
    - Source cryptographic digest binding and lineage tracing.
    - Full schema v1 compliance with SIP evidence bundle contracts.
    - Idempotency and hermetic replay support.
    """

    def __init__(
        self,
        *,
        nav_adapter: Optional[AmfiNavAdapter] = None,
        scheme_master_adapter: Optional[AmfiSchemeMasterAdapter] = None,
        max_staleness_days: int = 45,
    ):
        self.nav_adapter = nav_adapter or AmfiNavAdapter(max_staleness_days=max_staleness_days)
        self.scheme_master_adapter = scheme_master_adapter or AmfiSchemeMasterAdapter()
        self.max_staleness_days = max_staleness_days

    def refresh(
        self,
        target_bundle_dir: Path,
        as_of: date,
        *,
        hermetic_inputs: Optional[Dict[str, bytes]] = None,
        reviewer_attested: bool = False,
        reviewer_approval_envelope: Optional[Union[Dict[str, Any], Callable[[str], Dict[str, Any]]]] = None,
        reviewer_trust_registry: Optional[Dict[str, Any]] = None,
        master_source_url: Optional[str] = None,
        metrics_source_url: Optional[str] = None,
        universe_source_url: Optional[str] = None,
        require_reviewer_signature: bool = True,
        expected_commit_sha: Optional[str] = None,
        expected_policy_digest: Optional[str] = None,
        require_commit_binding: bool = True,
        require_policy_binding: bool = True,
        require_artifact_binding: bool = True,
    ) -> RefreshResult:
        """
        Execute an end-to-end financial data acquisition and bundle refresh.

        hermetic_inputs: Optional mapping of source keys to raw bytes for hermetic / offline execution:
            - "scheme_master": raw bytes for AMFI scheme master
            - "daily_nav": raw bytes for AMFI NAV feed
            - "metrics": raw bytes for metrics.csv / metrics source
            - "metrics_json": optional JSON bytes for metrics.json
            - "disclosures": dict of scheme_id -> raw bytes
            - "direct_evidence": dict of scheme_id -> raw bytes
        """
        start_time = datetime.now(timezone.utc).isoformat()
        sources_acquired: List[str] = []
        counts_by_source: Dict[str, int] = {}
        errors: List[str] = []
        bundle_target = Path(target_bundle_dir).expanduser().resolve()

        # Issue #112: In every production promotion path, cryptographic artifact digest,
        # commit SHA, and policy digest binding are strictly mandatory and cannot be disabled.
        if require_artifact_binding is False:
            errors.append("Promotion requires mandatory cryptographic artifact digest binding; caller cannot disable it.")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=[],
                records_count_by_source={},
                errors=errors,
                completed_at=start_time,
                is_atomic_rollback=True,
            )
        if require_commit_binding is False:
            errors.append("Promotion requires mandatory cryptographic commit SHA binding; caller cannot disable it.")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=[],
                records_count_by_source={},
                errors=errors,
                completed_at=start_time,
                is_atomic_rollback=True,
            )
        if require_policy_binding is False:
            errors.append("Promotion requires mandatory cryptographic policy digest binding; caller cannot disable it.")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=[],
                records_count_by_source={},
                errors=errors,
                completed_at=start_time,
                is_atomic_rollback=True,
            )

        # 1. Freshness Policy: Ensure as_of is not future-dated
        today = date.today()
        if as_of > today:
            errors.append(f"Refresh as_of date ({as_of}) cannot be in the future relative to system date ({today}).")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=[],
                records_count_by_source={},
                errors=errors,
                completed_at=start_time,
                is_atomic_rollback=True,
            )

        inputs = hermetic_inputs or {}

        # Issue #112: Promotion requires valid detached Ed25519 reviewer approval envelope and trust registry.
        # Boolean caller attestation alone without cryptographic verification cannot promote evidence.
        if reviewer_approval_envelope is None or reviewer_trust_registry is None:
            errors.append(
                "Promotion blocked: independent reviewer approval envelope and trust registry are required; "
                "caller-attested booleans cannot satisfy evidence release gates."
            )
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=[],
                records_count_by_source={},
                errors=errors,
                completed_at=start_time,
                is_atomic_rollback=True,
            )

        from services.sip_reviewer_approval import verify_sip_reviewer_approval
        if isinstance(reviewer_approval_envelope, dict):
            v_res = verify_sip_reviewer_approval(
                envelope=reviewer_approval_envelope,
                trust_registry=reviewer_trust_registry,
                expected_scope="SIP_EVIDENCE_RELEASE",
                expected_commit_sha=expected_commit_sha,
                expected_policy_digest=expected_policy_digest,
                require_commit_binding=True,
                require_policy_binding=True,
                require_artifact_binding=False,
            )
            if not v_res.ok:
                errors.extend(v_res.errors)
                return RefreshResult(
                    status="FAILED",
                    bundle_dir=None,
                    sources_acquired=[],
                    records_count_by_source={},
                    errors=errors,
                    completed_at=start_time,
                    is_atomic_rollback=True,
                )

        # Online retrieval orchestration if hermetic inputs omitted
        if not inputs.get("metrics") and metrics_source_url:
            try:
                raw_m = self.nav_adapter._fetch_url(metrics_source_url)
                inputs["metrics"] = raw_m
                inputs["metrics_json"] = raw_m
            except Exception as exc:
                errors.append(f"Failed online retrieval of metrics from {metrics_source_url}: {exc}")

        if not inputs.get("candidate_universe_source") and universe_source_url:
            try:
                inputs["candidate_universe_source"] = self.nav_adapter._fetch_url(universe_source_url)
            except Exception as exc:
                errors.append(f"Failed online retrieval of candidate universe from {universe_source_url}: {exc}")

        required_keys = ("metrics", "metrics_json", "candidate_universe_source", "disclosures", "direct_evidence")
        missing_keys = [k for k in required_keys if not inputs.get(k)]
        if missing_keys:
            errors.append(
                f"Required source evidence is missing; synthetic defaults are prohibited: {', '.join(sorted(missing_keys))}"
            )
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=[],
                records_count_by_source={},
                errors=errors,
                completed_at=start_time,
                is_atomic_rollback=True,
            )

        # 2. Acquire AMFI Scheme Master
        try:
            master_record: AcquisitionRecord = self.scheme_master_adapter.acquire(
                as_of,
                raw_bytes=inputs.get("scheme_master"),
                reviewer_attested=reviewer_attested,
            )
            sources_acquired.append(master_record.source_name)
            counts_by_source[master_record.source_name] = master_record.record_count
        except Exception as exc:
            errors.append(f"Failed to acquire Scheme Master: {exc}")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=sources_acquired,
                records_count_by_source=counts_by_source,
                errors=errors,
                completed_at=datetime.now(timezone.utc).isoformat(),
                is_atomic_rollback=True,
            )

        # 3. Acquire AMFI Daily NAV Feed
        try:
            nav_record: AcquisitionRecord = self.nav_adapter.acquire(
                as_of,
                raw_bytes=inputs.get("daily_nav"),
            )
            sources_acquired.append(nav_record.source_name)
            counts_by_source[nav_record.source_name] = nav_record.record_count
        except Exception as exc:
            errors.append(f"Failed to acquire AMFI Daily NAV feed: {exc}")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=sources_acquired,
                records_count_by_source=counts_by_source,
                errors=errors,
                completed_at=datetime.now(timezone.utc).isoformat(),
                is_atomic_rollback=True,
            )

        # 4. Filter & Build Candidates and Disclosures
        # Select Direct Growth schemes from the verified scheme master
        verified_schemes = master_record.parsed_payload["schemes"]
        direct_schemes = [
            s for s in verified_schemes
            if s.get("plan_type") == "Direct" and s.get("option_type") == "Growth"
        ]

        if not direct_schemes:
            errors.append("Acquired scheme master contains no Direct Growth schemes for candidate universe.")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=sources_acquired,
                records_count_by_source=counts_by_source,
                errors=errors,
                completed_at=datetime.now(timezone.utc).isoformat(),
                is_atomic_rollback=True,
            )

        # Disclosures acquisition
        disclosures_raw_map = inputs.get("disclosures") or {}
        portfolio_disclosures: Dict[str, Dict[str, Any]] = {}
        portfolio_disclosure_source_bytes: Dict[str, bytes] = {}

        for scheme in direct_schemes:
            scheme_id = scheme["scheme_id"]
            raw_bytes = disclosures_raw_map.get(scheme_id)
            if not isinstance(raw_bytes, bytes) or not raw_bytes.strip():
                errors.append(f"Missing original portfolio disclosure bytes for scheme {scheme_id}.")
                return RefreshResult(
                    status="FAILED",
                    bundle_dir=None,
                    sources_acquired=sources_acquired,
                    records_count_by_source=counts_by_source,
                    errors=errors,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    is_atomic_rollback=True,
                )

            disc_adapter = PortfolioDisclosureAdapter(scheme_id)
            try:
                disc_record = disc_adapter.acquire(
                    as_of,
                    raw_bytes=raw_bytes,
                    reviewer_attested=reviewer_attested,
                )
                disc_payload = dict(disc_record.parsed_payload)
                disc_payload.setdefault("source_url", disc_record.source_url)
                portfolio_disclosures[scheme_id] = disc_payload
                portfolio_disclosure_source_bytes[scheme_id] = disc_record.source_bytes
            except Exception as exc:
                errors.append(f"Disclosure validation failed for scheme {scheme_id}: {exc}")
                return RefreshResult(
                    status="FAILED",
                    bundle_dir=None,
                    sources_acquired=sources_acquired,
                    records_count_by_source=counts_by_source,
                    errors=errors,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    is_atomic_rollback=True,
                )

        sources_acquired.append("PORTFOLIO_DISCLOSURES")
        counts_by_source["PORTFOLIO_DISCLOSURES"] = len(portfolio_disclosures)

        # 5. Direct Plan Evidence & Candidates
        direct_evidence_inputs = inputs.get("direct_evidence") or {}
        candidate_universe: List[Dict[str, Any]] = []
        direct_evidence_bytes: Dict[str, bytes] = {}

        for idx, scheme in enumerate(direct_schemes, start=1):
            scheme_id = scheme["scheme_id"]
            pdf_bytes = direct_evidence_inputs.get(scheme_id)
            if not isinstance(pdf_bytes, bytes) or not pdf_bytes.startswith(b"%PDF-"):
                errors.append(f"Missing or invalid original PDF direct-plan evidence for scheme {scheme_id}.")
                return RefreshResult(
                    status="FAILED",
                    bundle_dir=None,
                    sources_acquired=sources_acquired,
                    records_count_by_source=counts_by_source,
                    errors=errors,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    is_atomic_rollback=True,
                )
            direct_evidence_bytes[scheme_id] = pdf_bytes

            direct_urls = inputs.get("direct_evidence_urls") or {}
            cand_url = (
                direct_urls.get(scheme_id)
                or (scheme.get("direct_plan_evidence") or {}).get("source_url")
            )
            if not cand_url or not str(cand_url).strip():
                errors.append(f"Direct plan factsheet source URL missing for candidate {scheme_id}; synthetic URLs are prohibited.")
                return RefreshResult(
                    status="FAILED",
                    bundle_dir=None,
                    sources_acquired=sources_acquired,
                    records_count_by_source=counts_by_source,
                    errors=errors,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                    is_atomic_rollback=True,
                )
            candidate_record = {
                "fund_id": f"fund-{idx}",
                "fund_name": scheme["scheme_name"],
                "scheme_id": scheme_id,
                "isin": scheme["isin"],
                "amc_name": scheme["amc_name"],
                "category": scheme["category"],
                "benchmark_identity": scheme["benchmark_identity"],
                "scheme_structure": scheme["scheme_structure"],
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": scheme["riskometer_score"],
                "is_direct": True,
                "direct_plan_evidence": {
                    "source_url": str(cand_url).strip(),
                },
            }
            candidate_universe.append(candidate_record)

        candidate_universe_source_bytes = inputs.get(
            "candidate_universe_source",
            json.dumps(candidate_universe, sort_keys=True).encode("utf-8"),
        )
        sources_acquired.append("REVIEWED_CANDIDATE_UNIVERSE")
        counts_by_source["REVIEWED_CANDIDATE_UNIVERSE"] = len(candidate_universe)

        # 6. Metrics Payload
        metrics_source_bytes = inputs["metrics"]
        raw_metrics_json = inputs["metrics_json"]
        try:
            metrics_payload = json.loads(raw_metrics_json.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            errors.append(f"Metrics source is not valid UTF-8 JSON: {exc}")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=sources_acquired,
                records_count_by_source=counts_by_source,
                errors=errors,
                completed_at=datetime.now(timezone.utc).isoformat(),
                is_atomic_rollback=True,
            )
        if not isinstance(metrics_payload, dict) or not isinstance(metrics_payload.get("funds"), list) or not metrics_payload["funds"]:
            errors.append("Metrics source must contain a non-empty funds array.")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=sources_acquired,
                records_count_by_source=counts_by_source,
                errors=errors,
                completed_at=datetime.now(timezone.utc).isoformat(),
                is_atomic_rollback=True,
            )
        sources_acquired.append("OFFICIAL_FUND_METRICS")
        counts_by_source["OFFICIAL_FUND_METRICS"] = len(metrics_payload.get("funds", []))

        # 7. Atomically build and promote the bundle
        builder = EvidenceBundleBuilder(bundle_target)
        try:
            builder.build_and_promote(
                as_of,
                scheme_master=master_record.parsed_payload,
                scheme_master_source_bytes=master_record.source_bytes,
                metrics_payload=metrics_payload,
                metrics_source_bytes=metrics_source_bytes,
                candidate_universe=candidate_universe,
                candidate_universe_source_bytes=candidate_universe_source_bytes,
                portfolio_disclosures=portfolio_disclosures,
                portfolio_disclosure_source_bytes=portfolio_disclosure_source_bytes,
                direct_plan_evidence_bytes=direct_evidence_bytes,
                master_source_url=master_source_url or master_record.source_url,
                metrics_source_url=metrics_source_url or metrics_payload.get("source_url"),
                universe_source_url=universe_source_url or inputs.get("candidate_universe_source_url"),
                reviewer_attested=reviewer_attested,
                reviewer_approval_envelope=reviewer_approval_envelope,
                reviewer_trust_registry=reviewer_trust_registry,
                expected_commit_sha=expected_commit_sha,
                expected_policy_digest=expected_policy_digest,
                require_commit_binding=True,
                require_policy_binding=True,
                require_artifact_binding=True,
            )
        except Exception as exc:
            errors.append(f"Atomic bundle build/promotion failed: {exc}")
            return RefreshResult(
                status="FAILED",
                bundle_dir=None,
                sources_acquired=sources_acquired,
                records_count_by_source=counts_by_source,
                errors=errors,
                completed_at=datetime.now(timezone.utc).isoformat(),
                is_atomic_rollback=True,
            )

        # 8. Post-promotion integration verification
        try:
            provider = build_sip_evidence_provider(bundle_target)
            if provider is None:
                raise ValueError("Promoted bundle failed build_sip_evidence_provider initialization.")
        except Exception as exc:
            errors.append(f"Promoted bundle failed provider verification: {exc}")
            return RefreshResult(
                status="FAILED",
                bundle_dir=bundle_target,
                sources_acquired=sources_acquired,
                records_count_by_source=counts_by_source,
                errors=errors,
                completed_at=datetime.now(timezone.utc).isoformat(),
                is_atomic_rollback=True,
            )

        return RefreshResult(
            status="SUCCESS",
            bundle_dir=bundle_target,
            sources_acquired=sources_acquired,
            records_count_by_source=counts_by_source,
            errors=[],
            completed_at=datetime.now(timezone.utc).isoformat(),
            is_atomic_rollback=False,
        )

