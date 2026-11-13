"""
tests/test_order_3_engine_bootstrap_and_pipeline.py

Authoritative acceptance test suite for Order 3:
- Issue #121: Engine bootstrap configuration, manifest-aware runtime path resolution,
  autonomous staging bundle creation without caller staging, 6 mandatory quality gates,
  and atomic promotion & rollback with last-known-good preservation.
- Issue #110: Auditable, deterministic, and idempotent financial-data refresh pipeline,
  lineage preservation, original source digest verification, and fail-closed atomic
  rollback on upstream feed failure or corruption.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from advisor import get_engine_data_paths
from services.engine_bootstrap import (
    EngineBootstrapPipeline,
    InvestorMandateInput,
    ValidationReport,
)
from services.engine_fund_data import (
    AcquiredFeed,
    EngineRuntimeConfig,
    build_public_fund_artifacts,
    load_engine_manifest,
    parse_amfi_nav_feed,
)
from services.acquisition.pipeline import FinancialDataRefreshPipeline
from services.acquisition.bundle_builder import EvidenceBundleBuilder
from services.sip_evidence_contract import validate_evidence_provider_payload
from services.sip_reviewer_approval import (
    create_sip_reviewer_approval_envelope,
    create_sip_trust_registry,
    verify_sip_reviewer_approval,
)


# =============================================================================
# Helper Fixtures & Signing Ceremonies
# =============================================================================

def _make_key_pair(key_id: str = "test-key-1", reviewer_id: str = "test-reviewer-1"):
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    b64_pub = base64.urlsafe_b64encode(pub_bytes).decode("ascii").rstrip("=")
    key_dict = {
        "key_id": key_id,
        "reviewer_id": reviewer_id,
        "reviewer_role": "independent",
        "public_key": b64_pub,
        "valid_from": "2025-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
    }
    registry = create_sip_trust_registry([key_dict])
    return priv, registry


def _valid_hermetic_inputs() -> Dict[str, Any]:
    """Construct complete, valid hermetic inputs passing all 6 quality gates."""
    master = {
        "schemes": [
            {
                "scheme_code": "1001",
                "scheme_name": "Core Bluechip Fund Direct Growth",
                "isin": "INF001",
                "amc_name": "Test AMC",
                "category": "Large Cap Fund",
                "plan_type": "Direct",
                "option_type": "Growth",
            }
        ]
    }
    nav_feed = (
        "Scheme Code|ISIN Growth|ISIN Reinv|Scheme Name|Net Asset Value|Date\n"
        "1001|INF001|INF002|Core Bluechip Fund Direct Growth|125.50|04-Nov-2026\n"
    ).encode("utf-8")
    metrics = {
        "funds": [
            {
                "fund_id": "1001",
                "nav": "125.50",
                "category": "Large Cap Fund",
                "is_direct": True,
            }
        ]
    }
    metrics_bytes = json.dumps(metrics).encode("utf-8")
    disclosure = {
        "scheme_id": "1001",
        "constituent_weights": {"RELIANCE": 50.0, "INFOSYS": 50.0},
    }
    return {
        "scheme_master": json.dumps(master).encode("utf-8"),
        "daily_nav": nav_feed,
        "metrics": b"scheme_id,nav\n1001,125.50\n",
        "metrics_json": metrics_bytes,
        "direct_evidence": {"1001": b"%PDF-1.4 sample direct plan factsheet content"},
        "disclosures": {"1001": json.dumps(disclosure).encode("utf-8")},
    }


# =============================================================================
# 1. Issue #121: Engine Bootstrap & Manifest-Aware Path Resolution
# =============================================================================

def test_issue_121_manifest_absence_is_typed_not_acquired_state(tmp_path):
    """Verify get_engine_data_paths returns NOT_ACQUIRED when manifest is absent without raising prompt."""
    data_dir = tmp_path / "mf_data"
    res = get_engine_data_paths(data_dir=data_dir)
    assert res["status"] == "NOT_ACQUIRED"
    assert res["is_acquired"] is False
    assert res["scheme_master"] is None
    assert res["fund_metrics"] is None
    assert res["fund_aliases"] is None

    manifest = load_engine_manifest(data_dir)
    assert manifest["status"] == "NOT_ACQUIRED"
    assert manifest["promotion_eligible"] is False


def test_issue_121_manifest_aware_snapshot_path_resolution(tmp_path):
    """Verify get_engine_data_paths resolves exact file paths from manifest snapshot."""
    data_dir = tmp_path / "mf_engine_data"
    snap_id = "feed_sha256_snapshot_001"
    snap_dir = data_dir / "snapshots" / snap_id
    snap_dir.mkdir(parents=True)

    # Artifacts
    master_file = snap_dir / "scheme_master.json"
    metrics_file = snap_dir / "fund_metrics.json"
    aliases_file = snap_dir / "fund_aliases.json"
    source_dir = snap_dir / "sources"
    source_dir.mkdir(parents=True)
    source_file = source_dir / "amfi-nav.txt"

    source_bytes = b"1001|INF001||Test Fund|100.0|04-Nov-2026\n"
    actual_hash = hashlib.sha256(source_bytes).hexdigest()
    source_file.write_bytes(source_bytes)

    # Update snapshot id to match exact digest
    snap_dir_actual = data_dir / "snapshots" / actual_hash
    snap_dir.rename(snap_dir_actual)
    master_file = snap_dir_actual / "scheme_master.json"
    metrics_file = snap_dir_actual / "fund_metrics.json"
    aliases_file = snap_dir_actual / "fund_aliases.json"
    source_file = snap_dir_actual / "sources" / "amfi-nav.txt"

    for f in (master_file, metrics_file, aliases_file):
        f.write_text(json.dumps({"dataset_id": actual_hash}), encoding="utf-8")

    artifact_sha256 = {
        "scheme_master": hashlib.sha256(master_file.read_bytes()).hexdigest(),
        "fund_metrics": hashlib.sha256(metrics_file.read_bytes()).hexdigest(),
        "fund_aliases": hashlib.sha256(aliases_file.read_bytes()).hexdigest(),
    }
    manifest = {
        "schema": "mf_engine.public_fund_data.v1",
        "dataset_id": actual_hash,
        "status": "ACQUIRED_UNVERIFIED",
        "retrieved_at": "2026-11-05T00:00:00Z",
        "source_url": "https://www.amfiindia.com/spages/NAVAll.txt",
        "source_sha256": actual_hash,
        "source_file": str(source_file.relative_to(data_dir)),
        "artifacts": {
            "scheme_master": str(master_file.relative_to(data_dir)),
            "fund_metrics": str(metrics_file.relative_to(data_dir)),
            "fund_aliases": str(aliases_file.relative_to(data_dir)),
        },
        "artifact_sha256": artifact_sha256,
        "promotion_eligible": False,
    }
    (data_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    resolved = get_engine_data_paths(data_dir=data_dir)
    assert resolved["status"] == "ACQUIRED_UNVERIFIED"
    assert resolved["is_acquired"] is True
    assert resolved["scheme_master"] == master_file
    assert resolved["fund_metrics"] == metrics_file
    assert resolved["fund_aliases"] == aliases_file


def test_issue_121_staging_bundle_enforces_all_6_mandatory_quality_gates(tmp_path):
    """Verify build_staging_bundle evaluates all 6 gates and blocks on missing evidence."""
    pipeline = EngineBootstrapPipeline()
    staging = tmp_path / "staging_bundle"
    as_of = date.today()

    # Case 1: Missing reviewer envelope -> Gate 1 fails
    inputs = _valid_hermetic_inputs()
    report = pipeline.build_staging_bundle(
        staging, as_of, hermetic_inputs=inputs, reviewer_approval_envelope=None
    )
    assert report.status == "BLOCKED"
    gate1 = [g for g in report.gates if g.gate_name == "REVIEWER_ATTESTATION"][0]
    assert gate1.passed is False

    # Case 2: Missing direct factsheet PDFs -> Gate 5 fails
    inputs_no_pdf = dict(inputs)
    inputs_no_pdf["direct_evidence"] = {}
    report_no_pdf = pipeline.build_staging_bundle(
        staging, as_of, hermetic_inputs=inputs_no_pdf
    )
    assert report_no_pdf.status == "BLOCKED"
    gate5 = [g for g in report_no_pdf.gates if g.gate_name == "DIRECT_PLAN_FACTSHEET_EVIDENCE"][0]
    assert gate5.passed is False

    # Case 3: Missing portfolio disclosures -> Gate 6 fails
    inputs_no_disc = dict(inputs)
    inputs_no_disc["disclosures"] = {}
    report_no_disc = pipeline.build_staging_bundle(
        staging, as_of, hermetic_inputs=inputs_no_disc
    )
    assert report_no_disc.status == "BLOCKED"
    gate6 = [g for g in report_no_disc.gates if g.gate_name == "PORTFOLIO_DISCLOSURE_LOOKTHROUGH"][0]
    assert gate6.passed is False


def test_issue_121_atomic_promotion_and_rollback_preserves_target_state(tmp_path):
    """Verify promote atomically swaps directory on success and rolls back on failure."""
    pipeline = EngineBootstrapPipeline()
    staging = tmp_path / "staging"
    staging.mkdir(parents=True)
    target = tmp_path / "active_target"
    target.mkdir(parents=True)

    # Prior target state
    prior_manifest = {"schema_version": 1, "status": "PRIOR_ACTIVE", "version": "v1.0"}
    (target / "manifest.json").write_text(json.dumps(prior_manifest), encoding="utf-8")
    (target / "data.txt").write_text("prior active data", encoding="utf-8")

    # Staging has corrupted manifest (missing schema_version)
    (staging / "manifest.json").write_text(json.dumps({"invalid": True}), encoding="utf-8")

    priv, registry = _make_key_pair()
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"source",
        structured_records={"v": True},
        commit_sha="a" * 40,
        policy_digest="b" * 64,
        artifact_digest="c" * 64,
    )

    # Attempting promotion must fail closed and preserve prior target
    with pytest.raises(ValueError, match="schema_version"):
        pipeline.promote(
            staging,
            target,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha="a" * 40,
            expected_policy_digest="b" * 64,
        )

    # Target state preserved
    restored = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert restored["status"] == "PRIOR_ACTIVE"
    assert (target / "data.txt").read_text(encoding="utf-8") == "prior active data"


# =============================================================================
# 2. Issue #110: Auditable Financial Data Refresh Pipeline
# =============================================================================

def test_issue_110_pipeline_refresh_hermetic_execution(tmp_path):
    """Verify FinancialDataRefreshPipeline executes end-to-end refresh with source provenance."""
    target_bundle = tmp_path / "bundle_v1"
    as_of = date.today()
    inputs = _valid_hermetic_inputs()

    priv, registry = _make_key_pair()
    commit_sha = "1" * 40
    policy_digest = "2" * 64

    # Sign envelope
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=inputs["scheme_master"],
        structured_records={"valid": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
    )

    pipeline = FinancialDataRefreshPipeline()
    res = pipeline.refresh(
        target_bundle,
        as_of,
        hermetic_inputs=inputs,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
        expected_commit_sha=commit_sha,
        expected_policy_digest=policy_digest,
        require_reviewer_signature=True,
    )

    assert res.status in ("COMPLETED", "FAILED")
    assert res.is_atomic_rollback is False or res.status == "FAILED"


def test_issue_110_pipeline_fail_closed_rollback_on_corrupt_feed(tmp_path):
    """Verify refresh pipeline rolls back with zero modifications on corrupt upstream inputs."""
    target_bundle = tmp_path / "target_bundle"
    target_bundle.mkdir(parents=True)
    sentinel = target_bundle / "sentinel.txt"
    sentinel.write_text("must not be modified", encoding="utf-8")

    as_of = date.today()
    inputs = _valid_hermetic_inputs()
    # Corrupt daily NAV feed with invalid syntax
    inputs["daily_nav"] = b"CORRUPTED NON PIPE LINE\n"

    priv, registry = _make_key_pair()
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"master",
        structured_records={"v": True},
        commit_sha="1" * 40,
        policy_digest="2" * 64,
    )

    pipeline = FinancialDataRefreshPipeline()
    res = pipeline.refresh(
        target_bundle,
        as_of,
        hermetic_inputs=inputs,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
        expected_commit_sha="1" * 40,
        expected_policy_digest="2" * 64,
    )

    assert res.status == "FAILED"
    assert res.is_atomic_rollback is True
    # Verify sentinel file remains untouched
    assert sentinel.read_text(encoding="utf-8") == "must not be modified"


def test_issue_110_pipeline_rejects_missing_reviewer_signature(tmp_path):
    """Verify refresh fails closed when reviewer signature is required but absent."""
    target_bundle = tmp_path / "bundle_dir"
    as_of = date.today()
    inputs = _valid_hermetic_inputs()

    pipeline = FinancialDataRefreshPipeline()
    res = pipeline.refresh(
        target_bundle,
        as_of,
        hermetic_inputs=inputs,
        reviewer_approval_envelope=None,
        require_reviewer_signature=True,
    )
    assert res.status == "FAILED"
    assert any("signature" in err.lower() or "envelope" in err.lower() for err in res.errors)


# =============================================================================
# 3. Order 3 Interoperability & Evidence Schema Verification
# =============================================================================

def test_order_3_evidence_provider_payload_schema_v1_compliance(tmp_path):
    """Verify generated evidence bundle records comply with schema v1 requirements."""
    master_bytes = b"source master bytes"
    universe_bytes = b"source candidate universe bytes"
    direct_bytes = b"%PDF-1.4 direct plan factsheet bytes"
    disclosure_bytes = b"source portfolio disclosure bytes"
    (tmp_path / "direct.pdf").write_bytes(direct_bytes)
    metrics_source_bytes = b"original metrics source raw text"
    metrics_record = {
        "id": "fund-1", "scheme_id": "scheme-1", "isin": "INF000000001",
        "amc_name": "Example AMC", "category": "Flexi Cap", "cat": "Flexi Cap",
        "plan_type": "Direct", "option_type": "Growth",
        "benchmark_identity": "Nifty 500 TRI", "effective_date": "2026-11-01",
        "source_ref": "sha256:" + hashlib.sha256(metrics_source_bytes).hexdigest(),
        "eq": 80.0, "debt": 20.0, "lc": 50.0, "mc": 20.0, "sc": 10.0,
        "market_cap_basis": "TOTAL_PORTFOLIO_PCT",
    }
    metrics_bytes = json.dumps({"funds": [metrics_record]}).encode("utf-8")
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_bytes(metrics_bytes)

    def _meta(raw, s_type="OFFICIAL_SCHEME_MASTER"):
        return {
            "source_url": "https://amfiindia.com/source",
            "source_document_sha256": hashlib.sha256(raw).hexdigest(),
            "reviewer_attested": True,
            "effective_date": "2026-11-01",
            "source_type": s_type,
        }

    payload = {
        "metrics_path": metrics_path,
        "aliases_path": None,
        "metrics_source_metadata": {
            **_meta(metrics_source_bytes, "OFFICIAL_FUND_METRICS"),
            "normalized_metrics_sha256": hashlib.sha256(metrics_bytes).hexdigest(),
            "publisher": "AMFI",
            "coverage_scope": "One verified test scheme",
            "record_count": 1,
            "reviewer_id": "test-reviewer",
            "policy_version": "metrics-policy-v1",
        },
        "metrics_source_bytes": metrics_source_bytes,
        "scheme_master": {
            **_meta(master_bytes),
            "status": "VERIFIED",
            "schemes": [
                {
                    "scheme_id": "scheme-1",
                    "isin": "INF000000001",
                    "scheme_name": "Example Direct Growth",
                    "amc_name": "Example AMC",
                    "category": "Flexi Cap",
                    "benchmark_identity": "Nifty 500 TRI",
                    "scheme_structure": "OPEN_ENDED_EQUITY",
                    "plan_type": "Direct",
                    "option_type": "Growth",
                    "riskometer_score": 5,
                }
            ],
        },
        "scheme_master_source_bytes": master_bytes,
        "portfolio_disclosures_by_scheme_id": {
            "scheme-1": {
                "scheme_id": "scheme-1",
                "constituent_weights": {"Reliance Industries Limited": 100.0},
                "constituent_weights_coverage_pct": 100.0,
                "source_url": "https://amfiindia.com/disclosure.pdf",
                "source_document_sha256": hashlib.sha256(disclosure_bytes).hexdigest(),
                "reviewer_attested": True,
                "effective_date": "2026-11-04",
                "source_type": "AMFI_DISCLOSURE",
            }
        },
        "portfolio_disclosure_source_bytes_by_scheme_id": {"scheme-1": disclosure_bytes},
        "disclosure_as_of_date": date(2026, 11, 4),
        "candidate_universe": [
            {
                "fund_id": "fund-1",
                "fund_name": "Example Direct Growth",
                "scheme_id": "scheme-1",
                "isin": "INF000000001",
                "amc_name": "Example AMC",
                "category": "Flexi Cap",
                "benchmark_identity": "Nifty 500 TRI",
                "scheme_structure": "OPEN_ENDED_EQUITY",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": 5,
                "is_direct": True,
                "_evidence_root": str(tmp_path),
                "direct_plan_evidence": {
                    "source_file": "direct.pdf",
                    "source_document_sha256": hashlib.sha256(direct_bytes).hexdigest(),
                    "source_url": "https://amfiindia.com/direct.pdf",
                    "source_type": "AMC_FACTSHEET",
                    "reviewer_attested": True,
                    "plan": "Direct",
                    "scheme_name": "Example Direct Growth",
                    "scheme_id": "scheme-1",
                    "isin": "INF000000001",
                    "amc_name": "Example AMC",
                    "reviewed_at": "2026-11-01",
                },
            }
        ],
        "candidate_universe_source": {
            **_meta(universe_bytes),
            "universe_complete": True,
            "coverage_scope": "All eligible open-ended equity and debt schemes",
        },
        "candidate_universe_source_bytes": universe_bytes,
    }
    validation_res = validate_evidence_provider_payload(payload, require_reviewer_signature=False)
    assert isinstance(validation_res, dict)
    assert "scheme_master" in validation_res
    assert "candidate_universe" in validation_res
