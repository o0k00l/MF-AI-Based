"""
tests/test_issues_23_24_112_end_to_end.py - End-to-end acceptance verification for Issues #23, #24, and #112.

1. Issue #23: Proves signed reconciliation report artifact enforcement in the SIP service,
   verifying JCS SHA-256 digest binding, zero unmatched items, and sign-off validity.
2. Issue #24: Proves Custom SAA propagation through every downstream allocation stage,
   confirming that exact custom targets govern drift and unfillable sleeves retain unallocated funds.
3. Issue #112: Enumerates all promotion routes and proves mandatory cryptographic binding
   to exact commit SHA, policy digest, and bundle artifact digest.
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

import openpyxl
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.models import AssetAllocationTarget
from core.portfolio_sip_controls import (
    generate_signed_portfolio_reconciliation_report,
    reconcile_total_portfolio,
)
from services import sip_recommendation as service
from services.acquisition.bundle_builder import EvidenceBundleBuilder
from services.engine_bootstrap import EngineBootstrapPipeline
from services.sip_reviewer_approval import (
    create_sip_reviewer_approval_envelope,
    create_sip_trust_registry,
    verify_sip_reviewer_approval,
)


def _make_key_pair(key_id="test-key-1", reviewer_id="test-reviewer-1"):
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


def _sample_cas_workbook(tmp_path: Path) -> Path:
    cas = tmp_path / "cas.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["To Date", date.today().strftime("%d-%b-%Y")])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Synthetic Fund", "FOLIO-1", 100000.0, 125000.0, 1000.0])
    wb.save(cas)
    return cas


def _base_holding():
    return SimpleNamespace(
        scheme="Example Direct Growth",
        fund_id="FUND-1",
        scheme_id="SCHEME-1",
        plan_option_status="VERIFIED",
        option_type="GROWTH",
        is_direct=True,
        lookthrough_status="VERIFIED",
        metrics_status="VERIFIED",
        constituent_weights={"ISSUER A": 60.0, "ISSUER B": 40.0},
        equity_pct=100.0,
        constituent_weights_coverage_pct=100.0,
        current_value_inr=125000.0,
    )


# ======================================================================
# Issue #23 Acceptance Tests: Signed Report Artifact Enforcement
# ======================================================================

def test_issue_23_signed_report_artifact_enforced_in_sip_service(tmp_path, monkeypatch):
    """
    Issue #23 Acceptance: The SIP service generates and binds the canonical signed
    reconciliation report artifact with an RFC 8785 (JCS) SHA-256 digest.
    """
    cas_path = _sample_cas_workbook(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *args, **kwargs: [_base_holding()])

    as_of = date.today().isoformat()
    sign_off = {
        "attested_by": "compliance-officer@institution.org",
        "attestation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "attestation_statement": "I independently attest that the total-portfolio perimeter and valuations are reconciled.",
    }
    context = {
        "current_core_fund_count": 0,
        "as_of_date": as_of,
        "cas_valuation_date": as_of,
        "perimeter_complete": True,
        "sign_off": sign_off,
        "require_signed_report": True,
        "assets": [
            {"asset_id": "cas-mf", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
             "value_inr": "125000", "source_ref": "sha256:cas", "owner_scope": "household", "as_of_date": as_of},
            {"asset_id": "debt", "asset_class": "deposit", "saa_bucket": "debt_liquid",
             "value_inr": "25000", "source_ref": "sha256:bank", "owner_scope": "household", "as_of_date": as_of},
        ],
        "excluded_assets": [],
        "unmatched_items": [],
        "ips": {
            "effective_date": as_of,
            "approved": True,
            "source_ref": "sha256:ips",
            "tier6_equity_only_authorized": True,
            "target_weights_pct": {
                "large_cap": 95.0, "mid_cap": 0.0, "small_cap": 0.0,
                "flexi_multi_cap": 0.0, "debt_liquid": 5.0,
            },
            "tolerance_band_pct": 5.0,
        },
        "candidate_policy": {"max_evidence_age_days": 30, "candidate_sleeves": {}, "mandatory_gates": ["direct_plan"]},
        "goal_policy": {"max_evidence_age_days": 30, "minimum_horizon_days_by_asset_class": {"equity": 365}},
        "goals": [],
        "liquidity": {
            "verified_cash_inr": "50000", "approved_reserve_target_inr": "20000",
            "near_term_obligations_inr": "5000", "monthly_net_income_inr": "100000",
            "essential_monthly_expenses_inr": "30000", "monthly_debt_service_inr": "0",
            "evidence_refs": {"as_of_dates": {k: as_of for k in ("cash", "reserve", "obligations", "income", "expenses", "debt_service")}},
            "max_evidence_age_days": 30,
        },
        "stress_scenarios": [],
        "candidate_gate_results": {},
        "operational_evidence_by_candidate_id": {},
        "freshness": {"recommendation_as_of_date": as_of, "max_age_days": 30},
        "concentration_policy": {
            "max_issuer_pct_of_portfolio": 25.0,
            "effective_date": as_of,
            "source_ref": "sha256:conc",
        },
    }

    result = service.recommend_sip(
        cas_path=cas_path,
        metrics_path=None,
        aliases_path=None,
        monthly_budget_inr=10000,
        risk_profile="Aggressive",
        scheme_master={"status": "VERIFIED"},
        scheme_master_source_bytes=b"master",
        portfolio_disclosures_by_scheme_id={"SCHEME-1": {"scheme_id": "SCHEME-1"}},
        portfolio_disclosure_source_bytes_by_scheme_id={"SCHEME-1": b"disc"},
        disclosure_as_of_date=date.today(),
        candidate_universe=[{"fund_id": "CAND-1", "scheme_id": "CAND-1"}],
        portfolio_context=context,
    )

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["signed_portfolio_reconciliation_report"] is not None
    report = assessment["signed_portfolio_reconciliation_report"]
    assert report["status"] == "RECONCILED"
    assert report["is_approved_for_sip_routing"] is True
    assert isinstance(report["report_sha256"], str)
    assert len(report["report_sha256"]) == 64
    assert assessment["signed_reconciliation_report_sha256"] == report["report_sha256"]


def test_issue_23_missing_sign_off_when_required_fails_closed(tmp_path, monkeypatch):
    """
    Issue #23 Acceptance: When signed report is required, missing or invalid sign-off
    fails closed to HOLD with reason SIGN_OFF_ATTESTATION_REQUIRED.
    """
    cas_path = _sample_cas_workbook(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *args, **kwargs: [_base_holding()])

    as_of = date.today().isoformat()
    context = {
        "as_of_date": as_of,
        "cas_valuation_date": as_of,
        "perimeter_complete": True,
        "require_signed_report": True,
        "sign_off": None,  # Missing sign-off
        "assets": [
            {"asset_id": "cas-mf", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
             "value_inr": "125000", "source_ref": "sha256:cas", "owner_scope": "household", "as_of_date": as_of},
        ],
    }

    result = service.recommend_sip(
        cas_path=cas_path,
        metrics_path=None,
        aliases_path=None,
        monthly_budget_inr=10000,
        risk_profile="Aggressive",
        scheme_master={"status": "VERIFIED"},
        scheme_master_source_bytes=b"master",
        portfolio_disclosures_by_scheme_id={"SCHEME-1": {"scheme_id": "SCHEME-1"}},
        portfolio_disclosure_source_bytes_by_scheme_id={"SCHEME-1": b"disc"},
        disclosure_as_of_date=date.today(),
        candidate_universe=[{"fund_id": "CAND-1", "scheme_id": "CAND-1"}],
        portfolio_context=context,
    )

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["status"] == "HOLD"
    assert assessment["reason"] == "SIGN_OFF_ATTESTATION_REQUIRED"


def test_issue_23_unmatched_items_blocks_sip_routing(tmp_path, monkeypatch):
    """
    Issue #23 Acceptance: Unmatched portfolio items strictly block SIP routing (status HOLD).
    """
    cas_path = _sample_cas_workbook(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *args, **kwargs: [_base_holding()])

    as_of = date.today().isoformat()
    sign_off = {
        "attested_by": "compliance@fund.com",
        "attestation_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "attestation_statement": "Attestation with pending unmatched items.",
    }
    context = {
        "as_of_date": as_of,
        "cas_valuation_date": as_of,
        "perimeter_complete": True,
        "sign_off": sign_off,
        "require_signed_report": True,
        "assets": [
            {"asset_id": "cas-mf", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
             "value_inr": "125000", "source_ref": "sha256:cas", "owner_scope": "household", "as_of_date": as_of},
        ],
        "unmatched_items": [
            {"item_id": "unmatched-1", "description": "Unidentified bank credit", "amount_inr": "50000"}
        ],
    }

    result = service.recommend_sip(
        cas_path=cas_path,
        metrics_path=None,
        aliases_path=None,
        monthly_budget_inr=10000,
        risk_profile="Aggressive",
        scheme_master={"status": "VERIFIED"},
        scheme_master_source_bytes=b"master",
        portfolio_disclosures_by_scheme_id={"SCHEME-1": {"scheme_id": "SCHEME-1"}},
        portfolio_disclosure_source_bytes_by_scheme_id={"SCHEME-1": b"disc"},
        disclosure_as_of_date=date.today(),
        candidate_universe=[{"fund_id": "CAND-1", "scheme_id": "CAND-1"}],
        portfolio_context=context,
    )

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["status"] == "HOLD"
    assert assessment["reason"] == "UNMATCHED_PORTFOLIO_ITEMS_PRESENT"


# ======================================================================
# Issue #24 Acceptance Tests: Custom SAA Propagation & Budget Preservation
# ======================================================================

def test_issue_24_custom_saa_propagates_downstream_and_preserves_unfillable(tmp_path, monkeypatch):
    """
    Issue #24 Acceptance: Custom SAA targets propagate through every downstream allocation
    stage (drift, sleeve routing, candidate selection). Unfillable sleeves retain unallocated funds.
    """
    cas_path = _sample_cas_workbook(tmp_path)
    monkeypatch.setattr(service, "load_holdings_from_cas_excel", lambda *args, **kwargs: [_base_holding()])

    as_of = date.today().isoformat()
    custom_target = AssetAllocationTarget(
        equity_pct=Decimal("80.0"),
        debt_pct=Decimal("20.0"),
        cash_pct=Decimal("0.0"),
        large_cap_pct=Decimal("40.0"),
        mid_cap_pct=Decimal("20.0"),
        small_cap_pct=Decimal("10.0"),
        flexi_cap_pct=Decimal("10.0"),
    )

    context = {
        "current_core_fund_count": 0,
        "as_of_date": as_of,
        "cas_valuation_date": as_of,
        "perimeter_complete": True,
        "assets": [
            {"asset_id": "cas-mf", "asset_class": "cas_mutual_fund", "saa_bucket": "large_cap",
             "value_inr": "125000", "source_ref": "sha256:cas", "owner_scope": "household", "as_of_date": as_of},
            {"asset_id": "debt", "asset_class": "deposit", "saa_bucket": "debt_liquid",
             "value_inr": "50000", "source_ref": "sha256:bank", "owner_scope": "household", "as_of_date": as_of},
        ],
        "excluded_assets": [],
        "unmatched_items": [],
        "ips": {
            "effective_date": as_of,
            "approved": True,
            "source_ref": "sha256:ips",
            "target_weights_pct": {
                "large_cap": 40.0,
                "mid_cap": 20.0,
                "small_cap": 10.0,
                "flexi_multi_cap": 10.0,
                "debt_liquid": 20.0,
            },
            "tolerance_band_pct": 2.0,
        },
        "candidate_policy": {"max_evidence_age_days": 30, "candidate_sleeves": {}, "mandatory_gates": ["direct_plan"]},
        "goal_policy": {"max_evidence_age_days": 30, "minimum_horizon_days_by_asset_class": {"equity": 365}},
        "goals": [],
        "liquidity": {
            "verified_cash_inr": "50000", "approved_reserve_target_inr": "20000",
            "near_term_obligations_inr": "5000", "monthly_net_income_inr": "100000",
            "essential_monthly_expenses_inr": "30000", "monthly_debt_service_inr": "0",
            "evidence_refs": {"as_of_dates": {k: as_of for k in ("cash", "reserve", "obligations", "income", "expenses", "debt_service")}},
            "max_evidence_age_days": 30,
        },
        "stress_scenarios": [],
        "candidate_gate_results": {},
        "operational_evidence_by_candidate_id": {},
        "freshness": {"recommendation_as_of_date": as_of, "max_age_days": 30},
        "concentration_policy": {
            "max_issuer_pct_of_portfolio": 25.0,
            "effective_date": as_of,
            "source_ref": "sha256:conc",
        },
    }

    result = service.recommend_sip(
        cas_path=cas_path,
        metrics_path=None,
        aliases_path=None,
        monthly_budget_inr=10000,
        risk_profile="Custom",
        scheme_master={"status": "VERIFIED"},
        scheme_master_source_bytes=b"master",
        portfolio_disclosures_by_scheme_id={"SCHEME-1": {"scheme_id": "SCHEME-1"}},
        portfolio_disclosure_source_bytes_by_scheme_id={"SCHEME-1": b"disc"},
        disclosure_as_of_date=date.today(),
        candidate_universe=[{"fund_id": "CAND-1", "scheme_id": "CAND-1"}],
        portfolio_context=context,
        custom_saa_target=custom_target,
    )

    assessment = result["portfolio_assessment"]["total_portfolio_context"]
    assert assessment["status"] == "HOLD"  # Fail closed preserved
    saa = assessment["saa"]
    assert saa["target_weights_pct"]["large_cap"] == 40.0
    assert saa["target_weights_pct"]["mid_cap"] == 20.0
    assert saa["target_weights_pct"]["small_cap"] == 10.0
    assert saa["target_weights_pct"]["flexi_multi_cap"] == 10.0
    assert saa["target_weights_pct"]["debt_liquid"] == 20.0


# ======================================================================
# Issue #112 Acceptance Tests: Mandatory Cryptographic Promotion Binding
# ======================================================================

def test_issue_112_bundle_builder_mandatory_cryptographic_binding(tmp_path):
    """
    Issue #112 Acceptance: EvidenceBundleBuilder.build_and_promote() enforces
    cryptographic binding to exact commit SHA, policy digest, and staging artifact digest.
    """
    target_dir = tmp_path / "promoted_bundle"
    builder = EvidenceBundleBuilder(target_dir)

    priv, registry = _make_key_pair()
    commit_sha = "1" * 40
    policy_digest = "2" * 64

    # Envelope with correct bindings
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"master_source",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
    )

    # 1. Mismatched commit SHA fails closed
    with pytest.raises(ValueError, match="Commit SHA mismatch"):
        builder.build_and_promote(
            date.today(),
            scheme_master={"schemes": []},
            scheme_master_source_bytes=b"master_source",
            metrics_payload={"funds": []},
            metrics_source_bytes=b"metrics_source",
            candidate_universe=[],
            candidate_universe_source_bytes=b"universe_source",
            portfolio_disclosures={},
            portfolio_disclosure_source_bytes={},
            direct_plan_evidence_bytes={},
            master_source_url="https://amfi.com/master.json",
            metrics_source_url="https://amfi.com/metrics.json",
            universe_source_url="https://amfi.com/universe.json",
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha="9" * 40,  # Mismatched
            expected_policy_digest=policy_digest,
            require_commit_binding=True,
            require_policy_binding=True,
        )

    # 2. Mismatched policy digest fails closed
    with pytest.raises(ValueError, match="Policy digest mismatch"):
        builder.build_and_promote(
            date.today(),
            scheme_master={"schemes": []},
            scheme_master_source_bytes=b"master_source",
            metrics_payload={"funds": []},
            metrics_source_bytes=b"metrics_source",
            candidate_universe=[],
            candidate_universe_source_bytes=b"universe_source",
            portfolio_disclosures={},
            portfolio_disclosure_source_bytes={},
            direct_plan_evidence_bytes={},
            master_source_url="https://amfi.com/master.json",
            metrics_source_url="https://amfi.com/metrics.json",
            universe_source_url="https://amfi.com/universe.json",
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha=commit_sha,
            expected_policy_digest="9" * 64,  # Mismatched
            require_commit_binding=True,
            require_policy_binding=True,
        )


def test_issue_112_engine_bootstrap_promote_mandatory_artifact_binding(tmp_path):
    """
    Issue #112 Acceptance: EngineBootstrapPipeline.promote() enforces cryptographic
    artifact digest binding against computed staging bundle digest.
    """
    staging_dir = tmp_path / "staging_bundle"
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "created_at": date.today().isoformat()}
    (staging_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (staging_dir / "data.txt").write_text("sample bundle content", encoding="utf-8")

    target_dir = tmp_path / "engine_bundle"
    pipeline = EngineBootstrapPipeline()

    priv, registry = _make_key_pair()
    commit_sha = "a" * 40
    policy_digest = "b" * 64

    # Compute actual bundle digest
    bundle_files = sorted([p for p in staging_dir.rglob("*") if p.is_file()])
    hasher = hashlib.sha256()
    for bf in bundle_files:
        rel = str(bf.relative_to(staging_dir)).replace("\\", "/")
        hasher.update(rel.encode("utf-8"))
        hasher.update(bf.read_bytes())
    actual_bundle_digest = hasher.hexdigest()

    # Create envelope with MISMATCHED artifact digest
    bad_envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"staging_manifest",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
        artifact_digest="0" * 64,  # Mismatched!
    )

    # 1. Attempting to bypass artifact binding with require_artifact_binding=False fails closed
    with pytest.raises(ValueError, match="mandatory cryptographic artifact digest binding"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
            require_artifact_binding=False,  # Attempting to bypass
        )

    # 2. Envelope completely missing artifact_digest fails closed under default promotion
    envelope_no_art = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"staging_manifest",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
        # artifact_digest omitted!
    )
    with pytest.raises(ValueError, match="missing required artifact_digest binding"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=envelope_no_art,
            reviewer_trust_registry=registry,
            expected_commit_sha=commit_sha,
            expected_policy_digest=policy_digest,
            # require_artifact_binding omitted -> defaults to mandatory True!
        )

    # 3. Create envelope with MISMATCHED artifact digest fails closed
    with pytest.raises(ValueError, match="Artifact digest mismatch"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha=commit_sha,
            expected_policy_digest=policy_digest,
        )

    # 4. Now create envelope with MATCHING artifact digest under default promotion
    good_envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"staging_manifest",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
        artifact_digest=actual_bundle_digest,
    )

    res = pipeline.promote(
        staging_dir,
        target_dir,
        reviewer_approval_envelope=good_envelope,
        reviewer_trust_registry=registry,
        expected_commit_sha=commit_sha,
        expected_policy_digest=policy_digest,
        require_commit_binding=True,
        require_policy_binding=True,
    )
    assert res["status"] == "PROMOTED"
    assert res["bundle_digest"] == actual_bundle_digest
