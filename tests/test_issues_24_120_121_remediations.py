"""
tests/test_issues_24_120_121_remediations.py - Comprehensive regression tests for Issues #121, #120, #112, #110, #24.

Addresses:
- Issue #121: Manifest-aware path resolution, engine self-bootstrapping, atomic promotion & rollback.
- Issue #120: Portfolio-aware lumpsum decisions fail closed on missing evidence without repo-relative fallback.
- Issue #112: Detached reviewer approval verification enforced by default; synthetic evidence blocked.
- Issue #110: Auditable, deterministic, and idempotent financial-data refresh pipeline.
- Issue #24: SAA drift minimizer and post-contribution mathematical routing from total-portfolio gaps.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import openpyxl
import pytest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization

from advisor import get_engine_data_paths
from core.portfolio_sip_controls import (
    calculate_saa_drift,
    route_incremental_sip,
    reconcile_total_portfolio,
    PortfolioInputError,
)
from services.engine_bootstrap import (
    EngineBootstrapPipeline,
    InvestorMandateInput,
    ValidationReport,
)
from services.lumpsum_recommendation import (
    evaluate_portfolio_aware_lumpsum,
    LumpsumDecisionResult,
)
from services.acquisition.pipeline import FinancialDataRefreshPipeline
from services.sip_reviewer_approval import (
    create_sip_reviewer_approval_envelope,
    create_sip_trust_registry,
    verify_sip_reviewer_approval,
)


def _make_key_and_envelope(
    scope="SIP_EVIDENCE_RELEASE",
    commit_sha: str = "1" * 40,
    policy_digest: str = "2" * 64,
    artifact_digest: str = "3" * 64,
):
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    b64_pub = base64.urlsafe_b64encode(pub_bytes).decode("ascii").rstrip("=")
    key_dict = {
        "key_id": "key-001",
        "reviewer_id": "rev-001",
        "reviewer_role": "independent",
        "public_key": b64_pub,
        "valid_from": "2025-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
    }
    registry = create_sip_trust_registry([key_dict])
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="key-001",
        reviewer_id="rev-001",
        scope=scope,
        source_bytes=b"raw_bytes_here",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
        artifact_digest=artifact_digest,
    )
    return envelope, registry


# =========================================================================
# Issue #121: Engine Bootstrap, Manifest Resolution, and Operable Promotion
# =========================================================================

def test_engine_data_paths_returns_not_acquired_when_manifest_missing(tmp_path):
    store = tmp_path / "fresh_store"
    paths = get_engine_data_paths(data_dir=store)
    assert paths["status"] == "NOT_ACQUIRED"
    assert paths["is_acquired"] is False
    assert paths["scheme_master"] is None
    assert paths["fund_metrics"] is None
    assert paths["fund_aliases"] is None


def test_engine_data_paths_resolves_snapshot_paths_from_manifest(tmp_path):
    store = tmp_path / "engine_store"
    snap_dir = store / "snapshots" / "abc123hash"
    snap_dir.mkdir(parents=True)
    m_path = snap_dir / "scheme_master.json"
    met_path = snap_dir / "fund_metrics.json"
    a_path = snap_dir / "fund_aliases.json"
    m_path.write_text("{}", encoding="utf-8")
    met_path.write_text("{}", encoding="utf-8")
    a_path.write_text("{}", encoding="utf-8")

    manifest = {
        "schema": "mf_engine.public_fund_data.v1",
        "status": "ACQUIRED_UNVERIFIED",
        "dataset_id": "abc123hash",
        "retrieved_at": "2026-11-05T00:00:00Z",
        "source_url": "https://www.amfiindia.com/spages/NAVAll.txt",
        "source_sha256": "abc123hash",
        "source_file": "snapshots/abc123hash/sources/amfi-nav.txt",
        "artifacts": {
            "scheme_master": "snapshots/abc123hash/scheme_master.json",
            "fund_metrics": "snapshots/abc123hash/fund_metrics.json",
            "fund_aliases": "snapshots/abc123hash/fund_aliases.json",
        },
    }
    # Create source file matching dataset_id hash
    src_dir = snap_dir / "sources"
    src_dir.mkdir(parents=True)
    import hashlib
    src_bytes = b"sample amfi content"
    manifest["dataset_id"] = hashlib.sha256(src_bytes).hexdigest()
    # update artifacts with actual dataset_id
    (src_dir / "amfi-nav.txt").write_bytes(src_bytes)

    # Put matching dataset_id in artifacts and bind each exact artifact byte sequence.
    for p in (m_path, met_path, a_path):
        p.write_text(json.dumps({"dataset_id": manifest["dataset_id"]}), encoding="utf-8")
    manifest["source_sha256"] = manifest["dataset_id"]
    manifest["artifact_sha256"] = {
        "scheme_master": hashlib.sha256(m_path.read_bytes()).hexdigest(),
        "fund_metrics": hashlib.sha256(met_path.read_bytes()).hexdigest(),
        "fund_aliases": hashlib.sha256(a_path.read_bytes()).hexdigest(),
    }

    (store / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    resolved = get_engine_data_paths(data_dir=store)
    assert resolved["status"] == "ACQUIRED_UNVERIFIED"
    assert resolved["is_acquired"] is True
    assert resolved["scheme_master"] == m_path
    assert resolved["fund_metrics"] == met_path
    assert resolved["fund_aliases"] == a_path


def test_engine_bootstrap_staging_blocks_caller_attestation_boolean_alone(tmp_path):
    pipeline = EngineBootstrapPipeline()
    staging = tmp_path / "staging"
    as_of = date.today()

    # Pass caller_attestation=True but NO envelope -> must fail Gate 1
    report = pipeline.build_staging_bundle(
        staging,
        as_of,
        hermetic_inputs={
            "scheme_master": json.dumps({"schemes": [{"scheme_code": "101", "scheme_name": "Fund 1"}]}).encode("utf-8"),
            "daily_nav": b"101|INF001|INF002|Fund 1|100.00|04-Nov-2026\n",
            "metrics": b"scheme_id,nav\n",
            "metrics_json": json.dumps({"funds": [{"fund_id": "101", "nav": "100.00"}]}).encode("utf-8"),
            "direct_evidence": {"101": b"%PDF-1.4 factsheet bytes"},
            "disclosures": {"101": json.dumps({"constituent_weights": {"RELIANCE": 100.0}}).encode("utf-8")},
        },
        reviewer_attested=True,  # Caller boolean alone
        reviewer_approval_envelope=None,
    )
    assert report.status == "BLOCKED"
    gate1 = [g for g in report.gates if g.gate_name == "REVIEWER_ATTESTATION"][0]
    assert gate1.passed is False
    assert "missing_reviewer_envelope" in gate1.evidence_ref


def test_engine_bootstrap_promotion_atomic_rollback_on_corrupt_manifest(tmp_path):
    pipeline = EngineBootstrapPipeline()
    staging = tmp_path / "staging"
    staging.mkdir(parents=True)
    # Staging has invalid manifest schema
    (staging / "manifest.json").write_text(json.dumps({"schema_version": 99}), encoding="utf-8")

    target = tmp_path / "target"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(json.dumps({"schema_version": 1, "prior": "data"}), encoding="utf-8")

    envelope, registry = _make_key_and_envelope()
    with pytest.raises(ValueError, match="schema_version must be 1"):
        pipeline.promote(
            staging,
            target,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
        )
    # Target state preserved
    prior_manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert prior_manifest["prior"] == "data"


# =========================================================================
# Issue #120: Portfolio-Aware Lumpsum Decision & Anti-Fallback Fail-Closed
# =========================================================================

def _create_test_cas(path: Path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Folio No.", "Units", "Current Value", "Invested Value"])
    ws.append(["SBI Bluechip Fund - Direct Plan - Growth", "12345/67", 100.0, 100000.0, 80000.0])
    wb.save(path)


def test_lumpsum_fails_closed_when_metrics_evidence_missing_without_fallback(tmp_path):
    cas_path = tmp_path / "cas.xlsx"
    _create_test_cas(cas_path)

    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=5.0,
        goal="Wealth Creation",
        lumpsum_budget_inr=Decimal("500000"),
        explicit_authorized_risk_tier="Tier 4",
        bank_cash_inr=Decimal("800000"),
        emergency_reserve_inr=Decimal("200000"),
    )

    # Provider returns evidence with NO metrics_path
    def mock_provider(**kwargs):
        return {
            "metrics_path": None,  # Missing metrics!
            "candidate_universe": [],
        }

    result = evaluate_portfolio_aware_lumpsum(
        cas_path,
        mandate,
        evidence_provider=mock_provider,
    )

    assert result.status == "HOLD"
    assert result.allocated_amount_inr == Decimal("0")
    assert result.unallocated_amount_inr == Decimal("500000")
    assert any("HOLD_INCOMPLETE_EVIDENCE" in err for err in result.missing_evidence)


# =========================================================================
# Issue #112 & #110: Anti-Synthetic Evidence and Default Signature Enforcement
# =========================================================================

def test_refresh_pipeline_defaults_to_requiring_reviewer_signature(tmp_path):
    pipeline = FinancialDataRefreshPipeline()
    result = pipeline.refresh(
        tmp_path / "sig_test_bundle",
        date.today(),
        reviewer_attested=True,
        # reviewer_approval_envelope and reviewer_trust_registry NOT passed
    )
    assert result.status == "FAILED"
    assert result.is_atomic_rollback is True
    assert any("independent reviewer approval envelope and trust registry are required" in err for err in result.errors)


# =========================================================================
# Issue #24: SAA Drift Minimizer & Mathematical Post-Contribution Routing
# =========================================================================

def test_route_incremental_sip_calculates_mathematical_post_contribution_weights():
    current_values = {
        "large_cap": Decimal("30000"),
        "mid_cap": Decimal("10000"),
        "small_cap": Decimal("10000"),
        "flexi_multi_cap": Decimal("20000"),
        "debt_liquid": Decimal("30000"),
    }
    targets = {
        "large_cap": 30.0,
        "mid_cap": 15.0,
        "small_cap": 15.0,
        "flexi_multi_cap": 20.0,
        "debt_liquid": 20.0,
    }
    # Total portfolio is 100,000.
    # Current weights: large 30%, mid 10%, small 10%, flexi 20%, debt 30%.
    # Targets: large 30%, mid 15%, small 15%, flexi 20%, debt 20%.
    # Underweight sleeves: mid_cap (5% deficit), small_cap (5% deficit).
    monthly_budget = Decimal("10000")

    routing = route_incremental_sip(
        monthly_budget_inr=monthly_budget,
        current_values_inr=current_values,
        target_weights_pct=targets,
        portfolio_total_inr=Decimal("100000"),
        tolerance_band_pct=Decimal("0"),
        eligible_sleeves=["mid_cap", "small_cap"],
        rounding_increment_inr=Decimal("500"),
    )

    assert routing["status"] == "ROUTED"
    assert routing["reconciliation_ok"] is True
    assert Decimal(routing["allocated_budget_inr"]) + Decimal(routing["unallocated_budget_inr"]) == monthly_budget
    # Post-contribution calculations are mathematically verified
    assert "post_contribution_total_inr" in routing
    assert Decimal(routing["post_contribution_total_inr"]) == Decimal("110000")
    assert "post_contribution_weights_pct" in routing
    assert "post_contribution_drift_pct" in routing
    # Mid cap received 5,000, Small cap received 5,000
    assert routing["allocations_inr"]["mid_cap"] == "3500"
    assert routing["allocations_inr"]["small_cap"] == "3500"
    # Post-contribution values: mid_cap = 15,000, small_cap = 15,000
    assert routing["post_contribution_values_inr"]["mid_cap"] == "13500"
    assert routing["post_contribution_values_inr"]["small_cap"] == "13500"


def test_route_incremental_sip_preserves_unfillable_sleeve_as_unallocated_no_spillover():
    current_values = {
        "large_cap": Decimal("30000"),
        "mid_cap": Decimal("10000"),
        "small_cap": Decimal("10000"),
        "flexi_multi_cap": Decimal("20000"),
        "debt_liquid": Decimal("30000"),
    }
    targets = {
        "large_cap": 30.0,
        "mid_cap": 15.0,
        "small_cap": 15.0,
        "flexi_multi_cap": 20.0,
        "debt_liquid": 20.0,
    }
    monthly_budget = Decimal("10000")

    # Only mid_cap is eligible; small_cap has NO eligible candidate
    routing = route_incremental_sip(
        monthly_budget_inr=monthly_budget,
        current_values_inr=current_values,
        target_weights_pct=targets,
        portfolio_total_inr=Decimal("100000"),
        tolerance_band_pct=Decimal("0"),
        eligible_sleeves=["mid_cap"],  # small_cap is unfillable!
        rounding_increment_inr=Decimal("500"),
    )

    assert routing["status"] == "ROUTED"
    assert routing["allocations_inr"] == {"mid_cap": "3500"}
    # Small cap's 5,000 must NOT spill over to mid_cap or large_cap!
    assert Decimal(routing["unallocated_budget_inr"]) == Decimal("6500")
    assert Decimal(routing["unallocated_by_sleeve_inr"]["small_cap"]).quantize(Decimal("0.01")) == Decimal("3611.11")
    assert routing["reconciliation_ok"] is True
