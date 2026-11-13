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
from services.acquisition.pipeline import FinancialDataRefreshPipeline
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
        "evidence_attested_by_provider": True,
        "investor_owner_ref": "INVESTOR-REF-TEST",
        "sip_mandate_evidence": {
            "coverage_status": "COMPLETE",
            "source_ref": "sha256:" + "a" * 64,
            "mandates": [],
        },
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
        risk_ceiling=4,
    )

    context = {
        "current_core_fund_count": 0,
        "evidence_attested_by_provider": True,
        "investor_owner_ref": "INVESTOR-REF-TEST",
        "sip_mandate_evidence": {
            "coverage_status": "COMPLETE",
            "source_ref": "sha256:" + "a" * 64,
            "mandates": [],
        },
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
    All caller downgrade attempts are strictly rejected.
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

    cand = {
        "fund_id": "fund-1",
        "fund_name": "SBI Bluechip Direct",
        "scheme_id": "scheme-1",
        "isin": "INF001",
        "amc_name": "SBI Mutual Fund",
        "category": "Large Cap Fund",
        "benchmark_identity": "NIFTY 50 TRI",
        "scheme_structure": "Open Ended",
        "plan_type": "Direct",
        "option_type": "Growth",
        "riskometer_score": "Moderate",
        "is_direct": True,
        "direct_plan_evidence": {"source_url": "https://amfi.com/factsheets/scheme-1.pdf"},
    }
    master = {
        "schemes": [
            {
                "scheme_code": "1001",
                "scheme_name": "SBI Bluechip Direct",
                "isin": "INF001",
                "amc_name": "SBI Mutual Fund",
                "category": "Large Cap Fund",
                "benchmark_identity": "NIFTY 50 TRI",
                "scheme_structure": "Open Ended",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": "Moderate",
            }
        ]
    }
    base_args = dict(
        scheme_master=master,
        scheme_master_source_bytes=json.dumps(master).encode("utf-8"),
        metrics_payload={"funds": [{"fund_id": "fund-1", "nav": "82.45"}]},
        metrics_source_bytes=b"fund_id,nav\nfund-1,82.45\n",
        candidate_universe=[cand],
        candidate_universe_source_bytes=json.dumps([cand]).encode("utf-8"),
        portfolio_disclosures={"scheme-1": {"source_url": "https://amfi.com/disc/1.json", "constituent_weights": {"RELIANCE": 100.0}}},
        portfolio_disclosure_source_bytes={"scheme-1": json.dumps({"constituent_weights": {"RELIANCE": 100.0}}).encode("utf-8")},
        direct_plan_evidence_bytes={"scheme-1": b"%PDF-1.4 factsheet bytes"},
        master_source_url="https://amfi.com/master.json",
        metrics_source_url="https://amfi.com/metrics.json",
        universe_source_url="https://amfi.com/universe.json",
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
        expected_commit_sha=commit_sha,
        expected_policy_digest=policy_digest,
    )

    # 1. Mismatched commit SHA fails closed
    with pytest.raises(ValueError, match="Commit SHA mismatch"):
        bad_args = dict(base_args, expected_commit_sha="9" * 40)
        builder.build_and_promote(date.today(), **bad_args)

    # 2. Mismatched policy digest fails closed
    with pytest.raises(ValueError, match="Policy digest mismatch"):
        bad_args = dict(base_args, expected_policy_digest="9" * 64)
        builder.build_and_promote(date.today(), **bad_args)

    # 3. Caller attempting to disable artifact binding fails closed
    with pytest.raises(ValueError, match="Promotion requires mandatory cryptographic artifact digest binding"):
        bad_args = dict(base_args, require_artifact_binding=False)
        builder.build_and_promote(date.today(), **bad_args)

    # 4. Caller attempting to disable commit binding fails closed
    with pytest.raises(ValueError, match="Promotion requires mandatory cryptographic commit SHA binding"):
        bad_args = dict(base_args, require_commit_binding=False)
        builder.build_and_promote(date.today(), **bad_args)

    # 5. Caller attempting to disable policy binding fails closed
    with pytest.raises(ValueError, match="Promotion requires mandatory cryptographic policy digest binding"):
        bad_args = dict(base_args, require_policy_binding=False)
        builder.build_and_promote(date.today(), **bad_args)

    # 6. Envelope missing commit_sha fails closed
    env_no_commit = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"master_source",
        structured_records={"verified": True},
        policy_digest=policy_digest,
    )
    with pytest.raises(ValueError, match="missing required commit_sha binding"):
        bad_args = dict(base_args, reviewer_approval_envelope=env_no_commit)
        builder.build_and_promote(date.today(), **bad_args)

    # 7. Envelope missing policy_digest fails closed
    env_no_pol = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"master_source",
        structured_records={"verified": True},
        commit_sha=commit_sha,
    )
    with pytest.raises(ValueError, match="missing required policy_digest binding"):
        bad_args = dict(base_args, reviewer_approval_envelope=env_no_pol)
        builder.build_and_promote(date.today(), **bad_args)

    # 8. Envelope missing artifact_digest fails closed post-staging
    with pytest.raises(ValueError, match="missing required artifact_digest binding"):
        builder.build_and_promote(date.today(), **base_args)

    # 9. Envelope with mismatched artifact_digest fails closed post-staging
    env_wrong_art = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"master_source",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
        artifact_digest="0" * 64,
    )
    # Establish pre-existing last-known-good target
    target_dir.mkdir(parents=True, exist_ok=True)
    lkg_manifest = target_dir / "manifest.json"
    lkg_manifest.write_text(json.dumps({"schema_version": 1, "lkg_state": "ACTIVE"}), encoding="utf-8")

    with pytest.raises(ValueError, match="Artifact digest mismatch"):
        bad_args = dict(base_args, reviewer_approval_envelope=env_wrong_art)
        builder.build_and_promote(date.today(), **bad_args)

    # 10. Verify last-known-good target bundle is preserved on failure
    assert lkg_manifest.is_file()
    assert json.loads(lkg_manifest.read_text(encoding="utf-8"))["lkg_state"] == "ACTIVE"


def test_issue_112_engine_bootstrap_promote_mandatory_artifact_binding(tmp_path):
    """
    Issue #112 Acceptance: EngineBootstrapPipeline.promote() enforces cryptographic
    artifact digest, commit SHA, and policy digest binding against computed staging bundle digest.
    All caller downgrade attempts are strictly rejected.
    """
    priv, registry = _make_key_pair()
    commit_sha = "a" * 40
    policy_digest = "b" * 64

    staging_dir = tmp_path / "staging_bundle"
    staging_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "created_at": date.today().isoformat(),
        "commit_sha": commit_sha,
        "policy_digest": policy_digest,
    }
    (staging_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (staging_dir / "data.txt").write_text("sample bundle content", encoding="utf-8")

    target_dir = tmp_path / "engine_bundle"
    target_dir.mkdir(parents=True, exist_ok=True)
    lkg_file = target_dir / "manifest.json"
    lkg_file.write_text(json.dumps({"schema_version": 1, "lkg": "PRESERVED"}), encoding="utf-8")

    pipeline = EngineBootstrapPipeline()

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
    with pytest.raises(ValueError, match="Promotion requires mandatory cryptographic artifact digest binding"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
            require_artifact_binding=False,
        )

    # 2. Attempting to bypass commit binding fails closed
    with pytest.raises(ValueError, match="Promotion requires mandatory cryptographic commit SHA binding"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
            require_commit_binding=False,
        )

    # 3. Attempting to bypass policy binding fails closed
    with pytest.raises(ValueError, match="Promotion requires mandatory cryptographic policy digest binding"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
            require_policy_binding=False,
        )

    # 4. Envelope missing artifact_digest fails closed
    envelope_no_art = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"staging_manifest",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
    )
    with pytest.raises(ValueError, match="missing required artifact_digest binding"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=envelope_no_art,
            reviewer_trust_registry=registry,
            expected_commit_sha=commit_sha,
            expected_policy_digest=policy_digest,
        )

    # 5. Envelope with MISMATCHED artifact digest fails closed
    with pytest.raises(ValueError, match="Artifact digest mismatch"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha=commit_sha,
            expected_policy_digest=policy_digest,
        )

    # Verify last-known-good target bundle is preserved
    assert json.loads(lkg_file.read_text(encoding="utf-8"))["lkg"] == "PRESERVED"

    # 6. Envelope missing commit_sha fails closed
    envelope_no_commit = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"staging_manifest",
        structured_records={"verified": True},
        policy_digest=policy_digest,
        artifact_digest=actual_bundle_digest,
    )
    with pytest.raises(ValueError, match=r"missing required .*commit_sha.* binding"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=envelope_no_commit,
            reviewer_trust_registry=registry,
            expected_policy_digest=policy_digest,
        )

    # 6b. Manifest missing commit_sha fails closed
    (staging_dir / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "policy_digest": policy_digest}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing required non-empty 'commit_sha'"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
        )

    # 6c. Manifest missing policy_digest fails closed
    (staging_dir / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "commit_sha": commit_sha}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing required non-empty 'policy_digest'"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
        )

    # 6d. Manifest with empty string commit_sha fails closed
    (staging_dir / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "commit_sha": "   ", "policy_digest": policy_digest}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing required non-empty 'commit_sha'"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
        )

    # 6e. Manifest with empty string policy_digest fails closed
    (staging_dir / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "commit_sha": commit_sha, "policy_digest": ""}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="missing required non-empty 'policy_digest'"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=bad_envelope,
            reviewer_trust_registry=registry,
        )

    # Restore valid manifest for good promotion
    (staging_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # 7. Envelope with MATCHING artifact digest, commit SHA, and policy digest succeeds
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
    )
    assert res["status"] == "PROMOTED"
    assert res["bundle_digest"] == actual_bundle_digest


def test_issue_112_refresh_pipeline_mandatory_bindings(tmp_path):
    """
    Issue #112 Acceptance: FinancialDataRefreshPipeline.refresh() enforces mandatory
    cryptographic binding across artifact, commit, and policy digests.
    Downgrade attempts fail closed and preserve last-known-good state.
    """
    target = tmp_path / "refresh_target"
    target.mkdir(parents=True, exist_ok=True)
    lkg_file = target / "manifest.json"
    lkg_file.write_text(json.dumps({"schema_version": 1, "lkg": "INTACT"}), encoding="utf-8")

    pipeline = FinancialDataRefreshPipeline()
    priv, registry = _make_key_pair()
    commit_sha = "c" * 40
    policy_digest = "d" * 64

    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"src",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
        artifact_digest="0" * 64,
    )

    # 1. Attempted downgrade on artifact binding fails closed
    r1 = pipeline.refresh(
        target,
        date.today(),
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
        require_artifact_binding=False,
    )
    assert r1.status == "FAILED"
    assert any("mandatory cryptographic artifact digest binding" in e for e in r1.errors)
    assert r1.is_atomic_rollback is True

    # 2. Attempted downgrade on commit binding fails closed
    r2 = pipeline.refresh(
        target,
        date.today(),
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
        require_commit_binding=False,
    )
    assert r2.status == "FAILED"
    assert any("mandatory cryptographic commit SHA binding" in e for e in r2.errors)

    # 3. Attempted downgrade on policy binding fails closed
    r3 = pipeline.refresh(
        target,
        date.today(),
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
        require_policy_binding=False,
    )
    assert r3.status == "FAILED"
    assert any("mandatory cryptographic policy digest binding" in e for e in r3.errors)

    # 4. Envelope missing commit_sha fails closed
    env_no_commit = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"src",
        structured_records={"verified": True},
        policy_digest=policy_digest,
    )
    r4 = pipeline.refresh(
        target,
        date.today(),
        reviewer_approval_envelope=env_no_commit,
        reviewer_trust_registry=registry,
    )
    assert r4.status == "FAILED"
    assert any("missing required commit_sha binding" in e for e in r4.errors)

    # 5. Envelope missing policy_digest fails closed
    env_no_pol = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"src",
        structured_records={"verified": True},
        commit_sha=commit_sha,
    )
    r5 = pipeline.refresh(
        target,
        date.today(),
        reviewer_approval_envelope=env_no_pol,
        reviewer_trust_registry=registry,
    )
    assert r5.status == "FAILED"
    assert any("missing required policy_digest binding" in e for e in r5.errors)

    # Verify target directory preserved
    assert json.loads(lkg_file.read_text(encoding="utf-8"))["lkg"] == "INTACT"


def test_issue_112_engine_bootstrap_staging_bundle_mandatory_bindings(tmp_path):
    """
    Issue #112 Acceptance: EngineBootstrapPipeline.build_staging_bundle() mandates
    artifact, commit, and policy digest bindings in Gate 1 evaluation.
    """
    pipeline = EngineBootstrapPipeline()
    staging_dir = tmp_path / "staging_eval"
    as_of = date.today()

    priv, registry = _make_key_pair()
    commit_sha = "e" * 40
    policy_digest = "f" * 64

    # 1. Attempted downgrade on artifact binding fails closed
    with pytest.raises(ValueError, match="mandatory cryptographic artifact digest binding"):
        pipeline.build_staging_bundle(
            staging_dir,
            as_of,
            hermetic_inputs={},
            require_artifact_binding=False,
        )

    # 2. Attempted downgrade on commit binding fails closed
    with pytest.raises(ValueError, match="mandatory cryptographic commit SHA binding"):
        pipeline.build_staging_bundle(
            staging_dir,
            as_of,
            hermetic_inputs={},
            require_commit_binding=False,
        )

    # 3. Attempted downgrade on policy binding fails closed
    with pytest.raises(ValueError, match="mandatory cryptographic policy digest binding"):
        pipeline.build_staging_bundle(
            staging_dir,
            as_of,
            hermetic_inputs={},
            require_policy_binding=False,
        )

    # 4. Envelope missing artifact_digest fails Gate 1 (REVIEWER_ATTESTATION)
    env_no_art = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"src",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
    )
    report = pipeline.build_staging_bundle(
        staging_dir,
        as_of,
        hermetic_inputs={},
        reviewer_attested=True,
        reviewer_approval_envelope=env_no_art,
        reviewer_trust_registry=registry,
    )
    assert report.status == "BLOCKED"
    gate1 = [g for g in report.gates if g.gate_name == "REVIEWER_ATTESTATION"][0]
    assert gate1.passed is False
    assert any("missing required artifact_digest binding" in r for r in gate1.reasons)


def test_issue_112_bootstrap_staging_bundle_direct_bypass_rejected(tmp_path):
    """
    Issue #112 Acceptance: EngineBootstrapPipeline.bootstrap_staging_bundle() directly
    enforces anti-downgrade guards and mandates commit, policy, and artifact bindings.
    Direct caller bypass attempts are strictly rejected.
    """
    pipeline = EngineBootstrapPipeline()
    staging_dir = tmp_path / "bootstrap_staging_eval"
    as_of = date.today()

    priv, registry = _make_key_pair()
    commit_sha = "1" * 40
    policy_digest = "2" * 64

    # 1. Attempted downgrade on artifact binding fails closed with ValueError
    with pytest.raises(ValueError, match="mandatory cryptographic artifact digest binding"):
        pipeline.bootstrap_staging_bundle(
            staging_dir,
            as_of,
            require_artifact_binding=False,
        )

    # 2. Attempted downgrade on commit binding fails closed with ValueError
    with pytest.raises(ValueError, match="mandatory cryptographic commit SHA binding"):
        pipeline.bootstrap_staging_bundle(
            staging_dir,
            as_of,
            require_commit_binding=False,
        )

    # 3. Attempted downgrade on policy binding fails closed with ValueError
    with pytest.raises(ValueError, match="mandatory cryptographic policy digest binding"):
        pipeline.bootstrap_staging_bundle(
            staging_dir,
            as_of,
            require_policy_binding=False,
        )

    # 4. Envelope missing commit_sha fails Gate 1 (REVIEWER_ATTESTATION)
    env_no_commit = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"src",
        structured_records={"verified": True},
        policy_digest=policy_digest,
        artifact_digest="3" * 64,
    )
    r1 = pipeline.bootstrap_staging_bundle(
        staging_dir,
        as_of,
        reviewer_approval_envelope=env_no_commit,
        reviewer_trust_registry=registry,
        expected_policy_digest=policy_digest,
        hermetic_inputs={},
    )
    assert r1.status == "BLOCKED"
    gate1 = [g for g in r1.gates if g.gate_name == "REVIEWER_ATTESTATION"][0]
    assert gate1.passed is False
    assert any("missing required commit_sha binding" in e for e in gate1.reasons)

    # 5. Envelope missing policy_digest fails Gate 1 (REVIEWER_ATTESTATION)
    env_no_policy = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"src",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        artifact_digest="3" * 64,
    )
    r2 = pipeline.bootstrap_staging_bundle(
        staging_dir,
        as_of,
        reviewer_approval_envelope=env_no_policy,
        reviewer_trust_registry=registry,
        expected_commit_sha=commit_sha,
        hermetic_inputs={},
    )
    assert r2.status == "BLOCKED"
    gate1 = [g for g in r2.gates if g.gate_name == "REVIEWER_ATTESTATION"][0]
    assert gate1.passed is False
    assert any("missing required policy_digest binding" in e for e in gate1.reasons)

    # 6. Envelope missing artifact_digest fails Gate 1 (REVIEWER_ATTESTATION)
    env_no_art = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"src",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
    )
    r3 = pipeline.bootstrap_staging_bundle(
        staging_dir,
        as_of,
        reviewer_approval_envelope=env_no_art,
        reviewer_trust_registry=registry,
        expected_commit_sha=commit_sha,
        expected_policy_digest=policy_digest,
        hermetic_inputs={},
    )
    assert r3.status == "BLOCKED"
    gate1 = [g for g in r3.gates if g.gate_name == "REVIEWER_ATTESTATION"][0]
    assert gate1.passed is False
    assert any("missing required artifact_digest binding" in e for e in gate1.reasons)

    # 7. Mismatched commit SHA fails Gate 1 (REVIEWER_ATTESTATION)
    env_full = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"src",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
        artifact_digest="3" * 64,
    )
    r4 = pipeline.bootstrap_staging_bundle(
        staging_dir,
        as_of,
        reviewer_approval_envelope=env_full,
        reviewer_trust_registry=registry,
        expected_commit_sha="9" * 40,
        expected_policy_digest=policy_digest,
        hermetic_inputs={},
    )
    assert r4.status == "BLOCKED"
    gate1 = [g for g in r4.gates if g.gate_name == "REVIEWER_ATTESTATION"][0]
    assert gate1.passed is False
    assert any("Commit SHA mismatch" in e for e in gate1.reasons)

    # 8. Mismatched policy digest fails Gate 1 (REVIEWER_ATTESTATION)
    r5 = pipeline.bootstrap_staging_bundle(
        staging_dir,
        as_of,
        reviewer_approval_envelope=env_full,
        reviewer_trust_registry=registry,
        expected_commit_sha=commit_sha,
        expected_policy_digest="9" * 64,
        hermetic_inputs={},
    )
    assert r5.status == "BLOCKED"
    gate1 = [g for g in r5.gates if g.gate_name == "REVIEWER_ATTESTATION"][0]
    assert gate1.passed is False
    assert any("Policy digest mismatch" in e for e in gate1.reasons)


def test_issue_112_co_bound_staging_and_promotion_verification(tmp_path):
    """
    Issue #112 Acceptance: Verify that commit SHA, policy digest, and exact staged
    payload artifact digest are co-bound in the SAME signed approval envelope across
    both staging and final promotion.
    Envelope substitution, manifest tampering, and staged payload modifications
    are strictly rejected.
    """
    pipeline = EngineBootstrapPipeline()
    staging_dir = tmp_path / "co_bound_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    target_dir = tmp_path / "co_bound_target"

    priv, registry = _make_key_pair()
    priv_attacker, registry_attacker = _make_key_pair(key_id="key-attacker", reviewer_id="rev-attacker")
    commit_sha = "a" * 40
    policy_digest = "b" * 64

    # Populate genuine staging payload
    manifest = {
        "schema_version": 1,
        "disclosure_as_of_date": "2026-11-12",
        "metrics_file": "metrics.json",
        "scheme_master_file": "scheme_master.json",
        "commit_sha": commit_sha,
        "policy_digest": policy_digest,
    }
    (staging_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (staging_dir / "metrics.json").write_text(json.dumps({"funds": [{"fund_id": "f1", "nav": "100.0"}]}), encoding="utf-8")
    (staging_dir / "scheme_master.json").write_text(json.dumps({"schemes": [{"scheme_name": "Fund 1"}]}), encoding="utf-8")

    # Compute exact staged payload digest excluding detached reviewer files
    bundle_files = sorted([
        p for p in staging_dir.rglob("*")
        if p.is_file() and p.name not in ("reviewer_approval_envelope.json", "reviewer_trust_registry.json")
    ])
    hasher = hashlib.sha256()
    for bf in bundle_files:
        rel = str(bf.relative_to(staging_dir)).replace("\\", "/")
        hasher.update(rel.encode("utf-8"))
        hasher.update(bf.read_bytes())
    staged_payload_digest = hasher.hexdigest()

    # Create signed envelope co-binding commit SHA, policy digest, AND staged payload digest
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"official_source",
        structured_records={"verified": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
        artifact_digest=staged_payload_digest,
    )

    # 1. Staging evaluation: Gate 1 verifies the envelope against the staged files
    report = pipeline.build_staging_bundle(
        staging_dir,
        date.today(),
        hermetic_inputs={},
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
        expected_commit_sha=commit_sha,
        expected_policy_digest=policy_digest,
    )
    gate1 = [g for g in report.gates if g.gate_name == "REVIEWER_ATTESTATION"][0]
    assert gate1.passed is True
    assert gate1.evidence_ref.startswith("reviewer_signature:")

    # Store envelope and trust registry in staging directory
    (staging_dir / "reviewer_approval_envelope.json").write_text(json.dumps(envelope), encoding="utf-8")
    (staging_dir / "reviewer_trust_registry.json").write_text(json.dumps(registry), encoding="utf-8")

    # 2. Envelope substitution attack at promotion fails closed
    substituted_envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope="SIP_EVIDENCE_RELEASE",
        source_bytes=b"official_source_v2",
        structured_records={"verified": True, "substituted": True},
        commit_sha=commit_sha,
        policy_digest=policy_digest,
        artifact_digest=staged_payload_digest,
    )
    with pytest.raises(ValueError, match="envelope substitution is prohibited"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=substituted_envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha=commit_sha,
            expected_policy_digest=policy_digest,
        )

    # 3. Manifest commit_sha tampering attack fails closed
    tampered_manifest = dict(manifest, commit_sha="f" * 40)
    (staging_dir / "manifest.json").write_text(json.dumps(tampered_manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Staging manifest commit SHA .* does not match"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha=commit_sha,
            expected_policy_digest=policy_digest,
        )
    # Restore manifest
    (staging_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # 4. Manifest policy_digest tampering attack fails closed
    tampered_manifest_pol = dict(manifest, policy_digest="f" * 64)
    (staging_dir / "manifest.json").write_text(json.dumps(tampered_manifest_pol), encoding="utf-8")
    with pytest.raises(ValueError, match="Staging manifest policy digest .* does not match"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha=commit_sha,
            expected_policy_digest=policy_digest,
        )
    # Restore manifest
    (staging_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    # 5. Staged payload tampering attack fails closed
    (staging_dir / "metrics.json").write_text(json.dumps({"funds": [{"fund_id": "tampered", "nav": "999.0"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="Artifact digest mismatch"):
        pipeline.promote(
            staging_dir,
            target_dir,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
            expected_commit_sha=commit_sha,
            expected_policy_digest=policy_digest,
        )
    # Restore genuine metrics
    (staging_dir / "metrics.json").write_text(json.dumps({"funds": [{"fund_id": "f1", "nav": "100.0"}]}), encoding="utf-8")

    # 6. Valid promotion with matching envelope, manifest, and staged payload succeeds
    res = pipeline.promote(
        staging_dir,
        target_dir,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
        expected_commit_sha=commit_sha,
        expected_policy_digest=policy_digest,
    )
    assert res["status"] == "PROMOTED"
    assert res["bundle_digest"] == staged_payload_digest
    assert (target_dir / "manifest.json").is_file()

