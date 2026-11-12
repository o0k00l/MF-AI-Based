"""
tests/test_engine_bootstrap_and_lumpsum.py - Tests for engine bootstrap pipeline and portfolio-aware lumpsum decision workflow.
Addresses Issues #120 & #121:
- Issue #120: Make lump-sum decisions portfolio-aware and fail closed on incomplete investor evidence.
- Issue #121: Make engine bootstrap its own configuration and fund evidence; implement an operable promotion workflow.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import openpyxl
import pytest

from services.engine_bootstrap import (
    EngineBootstrapPipeline,
    InvestorMandateInput,
    ValidationReport,
)
from services.lumpsum_recommendation import (
    evaluate_portfolio_aware_lumpsum,
    LumpsumDecisionResult,
)
from services.sip_reviewer_approval import (
    create_sip_reviewer_approval_envelope,
    create_sip_trust_registry,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import base64

def _make_test_approval(scope="SIP_EVIDENCE_RELEASE", artifact_digest: Optional[str] = None):
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    b64_pub = base64.urlsafe_b64encode(pub_bytes).decode("ascii").rstrip("=")
    key_dict = {
        "key_id": "test-key-1",
        "reviewer_id": "test-reviewer-1",
        "reviewer_role": "independent",
        "public_key": b64_pub,
        "valid_from": "2025-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
    }
    registry = create_sip_trust_registry([key_dict])
    envelope = create_sip_reviewer_approval_envelope(
        priv,
        key_id="test-key-1",
        reviewer_id="test-reviewer-1",
        scope=scope,
        source_bytes=b"test_source_bytes",
        structured_records={"verified": True},
        artifact_digest=artifact_digest,
    )
    return envelope, registry


def _create_synthetic_cas(tmp_path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["Scheme Name", "Folio No.", "Units", "Current Value", "Invested Value"])
    ws.append(["SBI Bluechip Fund - Direct Plan - Growth", "12345/67", 100.0, 100000.0, 80000.0])
    ws.append(["SBI Small Cap Fund - Regular Plan - Growth", "98765/43", 50.0, 50000.0, 45000.0])
    cas_path = tmp_path / "synthetic_cas.xlsx"
    wb.save(cas_path)
    return cas_path


def test_mandate_rejects_free_text_aggressive_without_explicit_tier():
    # Issue #120 Observation 2: Risk comfort plus 5-7Y horizon does not authorize Tier 6
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=6.0,
        goal="Wealth Creation",
        lumpsum_budget_inr=Decimal("400000"),
        risk_comfort_text="Aggressive",
        explicit_authorized_risk_tier=None,  # Missing!
        bank_cash_inr=Decimal("600000"),
        emergency_reserve_inr=Decimal("150000"),
    )
    is_valid, errors = mandate.validate_for_lumpsum()
    assert is_valid is False
    assert any("Missing investor-authorized risk tier" in err for err in errors)


def test_mandate_rejects_missing_cash_or_reserve():
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=5.0,
        goal="Growth",
        lumpsum_budget_inr=Decimal("400000"),
        explicit_authorized_risk_tier="Tier 4",
        bank_cash_inr=None,  # Missing!
        emergency_reserve_inr=None,
    )
    is_valid, errors = mandate.validate_for_lumpsum()
    assert is_valid is False
    assert any("Verified bank cash evidence is missing" in err for err in errors)


def test_mandate_rejects_insufficient_deployable_surplus():
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=5.0,
        goal="Growth",
        lumpsum_budget_inr=Decimal("400000"),
        explicit_authorized_risk_tier="Tier 4",
        bank_cash_inr=Decimal("450000"),
        emergency_reserve_inr=Decimal("100000"),  # Deployable surplus is 350,000 < 400,000
    )
    is_valid, errors = mandate.validate_for_lumpsum()
    assert is_valid is False
    assert any("does not cover requested lump sum" in err for err in errors)


def test_engine_bootstrap_pipeline_validation_report(tmp_path):
    # Issue #121: Engine bootstraps evidence and produces deterministic validation report
    pipeline = EngineBootstrapPipeline()
    staging_dir = tmp_path / "staging"
    as_of = date.today()

    # Incomplete inputs should produce BLOCKED status
    report = pipeline.build_staging_bundle(
        staging_dir,
        as_of,
        hermetic_inputs={},  # Empty
        reviewer_attested=False,
    )
    assert report.status == "BLOCKED"
    assert report.can_provide_read_only_report is True
    assert report.unpromoted_reason is not None
    assert len(report.gates) >= 5
    assert not all(g.passed for g in report.gates)

    # Complete inputs with valid cryptographic reviewer envelope produce PROMOTABLE status
    envelope, registry = _make_test_approval()
    report_valid = pipeline.build_staging_bundle(
        staging_dir,
        as_of,
        hermetic_inputs={
            "scheme_master": json.dumps({"schemes": [{"scheme_code": "100001", "scheme_name": "Scheme 1"}]}).encode("utf-8"),
            "daily_nav": b"100001|INF001|INF002|Scheme 1|123.45|04-Nov-2026\n",
            "metrics": b"scheme_id,nav\n",
            "metrics_json": json.dumps({"funds": [{"fund_id": "100001", "nav": "123.45"}]}).encode("utf-8"),
            "direct_evidence": {"100001": b"%PDF-1.4 factsheet direct evidence"},
            "disclosures": {"100001": json.dumps({"constituent_weights": {"RELIANCE": 100.0}}).encode("utf-8")},
        },
        reviewer_attested=True,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
    )
    assert report_valid.status == "PROMOTABLE"
    assert all(g.passed for g in report_valid.gates)


def test_evaluate_portfolio_aware_lumpsum_fails_closed_without_complete_evidence(tmp_path):
    cas_path = _create_synthetic_cas(tmp_path)
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=6.0,
        goal="Wealth Creation",
        lumpsum_budget_inr=Decimal("400000"),
        risk_comfort_text="Aggressive",
        explicit_authorized_risk_tier=None,  # Missing authorization
        bank_cash_inr=Decimal("600000"),
        emergency_reserve_inr=Decimal("150000"),
    )

    result = evaluate_portfolio_aware_lumpsum(cas_path, mandate)

    # Fail closed: Entire budget remains unallocated
    assert result.status == "HOLD"
    assert result.total_lumpsum_inr == Decimal("400000")
    assert result.allocated_amount_inr == Decimal("0")
    assert result.unallocated_amount_inr == Decimal("400000")
    assert result.parking_allocation_inr == Decimal("160000.00")  # 40% parking
    assert result.stp_allocation_inr == Decimal("240000.00")      # 60% STP
    assert result.parking_ratio_pct == 40.0
    assert result.stp_ratio_pct == 60.0
    assert result.stp_duration_months == 6
    assert result.policy_branch == "STANDARD_PARKING_STP_WATERFALL"
    assert result.is_execution_authorized is False
    assert len(result.missing_evidence) > 0
    assert any("Missing investor-authorized risk tier" in err for err in result.missing_evidence)


def test_evaluate_portfolio_aware_lumpsum_tier6_override(tmp_path):
    cas_path = _create_synthetic_cas(tmp_path)
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=8.0,
        goal="Wealth Creation",
        lumpsum_budget_inr=Decimal("400000"),
        explicit_authorized_risk_tier="Tier 6",
        tier6_equity_only_authorized=True,
        bank_cash_inr=Decimal("700000"),
        emergency_reserve_inr=Decimal("150000"),
    )

    result = evaluate_portfolio_aware_lumpsum(cas_path, mandate)
    # 20% parking / 80% STP for authorized Tier 6 with >= 7Y horizon
    assert result.policy_branch == "TIER6_AGGRESSIVE_STP_WATERFALL"
    assert result.parking_allocation_inr == Decimal("80000.00")
    assert result.stp_allocation_inr == Decimal("320000.00")
    assert result.parking_ratio_pct == 20.0
    assert result.stp_ratio_pct == 80.0


def test_engine_bootstrap_pipeline_promotion_atomic_and_rollback(tmp_path):
    # Tests atomic promotion and rollback preserving last-known-good
    pipeline = EngineBootstrapPipeline()
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir(parents=True)
    (staging_dir / "manifest.json").write_text(json.dumps({"schema_version": 1, "test": "data"}), encoding="utf-8")
    (staging_dir / "scheme_master.json").write_text(json.dumps({"schemes": []}), encoding="utf-8")

    target_dir = tmp_path / "promoted_bundle"
    target_dir.mkdir(parents=True)
    (target_dir / "manifest.json").write_text(json.dumps({"schema_version": 1, "version": "v1_original"}), encoding="utf-8")

    bundle_files = sorted([p for p in staging_dir.rglob("*") if p.is_file()])
    hasher = hashlib.sha256()
    for bf in bundle_files:
        rel = str(bf.relative_to(staging_dir)).replace("\\", "/")
        hasher.update(rel.encode("utf-8"))
        hasher.update(bf.read_bytes())
    bundle_digest = hasher.hexdigest()

    envelope, registry = _make_test_approval(artifact_digest=bundle_digest)

    # 1. Successful promotion
    result = pipeline.promote(
        staging_dir,
        target_dir,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
    )
    assert result["status"] == "PROMOTED"
    assert result["bundle_digest"] is not None
    assert (target_dir / "scheme_master.json").is_file()

    # 2. Failed promotion preserves prior target state
    invalid_staging = tmp_path / "staging_corrupt"
    invalid_staging.mkdir(parents=True)
    # Missing manifest.json in staging
    with pytest.raises(ValueError, match="missing manifest.json"):
        pipeline.promote(
            invalid_staging,
            target_dir,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
        )
    # Target directory remains intact
    assert (target_dir / "manifest.json").is_file()
    assert (target_dir / "scheme_master.json").is_file()


def test_clean_install_bootstrap_to_advisor_workflow(tmp_path, monkeypatch):
    # Test clean-install bootstrap-to-advisor workflow: no client-authored JSON required
    from advisor import get_engine_data_paths
    from services.engine_fund_data import EngineRuntimeConfig, refresh_engine_fund_data

    store_dir = tmp_path / "engine-store"
    monkeypatch.setenv("MF_ENGINE_DATA_DIR", str(store_dir))
    monkeypatch.delenv("MF_CLIENT_DATA_DIR", raising=False)

    # Clean install: not acquired yet
    paths_before = get_engine_data_paths()
    assert paths_before["status"] == "NOT_ACQUIRED"
    assert paths_before["is_acquired"] is False

    # Refresh builds engine snapshot
    cfg = EngineRuntimeConfig(data_dir=store_dir)
    sample_nav = (
        "Scheme Code|ISIN Div Payout/ISIN Growth|ISIN Div Reinvestment|Scheme Name|Net Asset Value|Date\n"
        "100001|INF000000001|INF000000002|Example Equity Fund - Direct Plan - Growth|123.45|04-Nov-2026\n"
    ).encode()

    class _MockResponse:
        content = sample_nav
        def raise_for_status(self): pass
    class _MockSession:
        def get(self, *args, **kwargs): return _MockResponse()

    from datetime import datetime, timezone
    refresh_engine_fund_data(cfg, session=_MockSession(), now=datetime(2026, 11, 5, tzinfo=timezone.utc))

    # Advisor now resolves engine-owned dataset paths from manifest.json
    paths_after = get_engine_data_paths()
    assert paths_after["status"] == "ACQUIRED_UNVERIFIED"
    assert paths_after["is_acquired"] is True
    assert paths_after["scheme_master"].is_file()
    assert paths_after["fund_metrics"].is_file()
    assert paths_after["fund_aliases"].is_file()


def test_lumpsum_weighted_lookthrough_and_parking_validation(tmp_path, monkeypatch):
    cas_path = _create_synthetic_cas(tmp_path)
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=5.0,
        goal="Wealth Preservation",
        lumpsum_budget_inr=Decimal("400000"),
        explicit_authorized_risk_tier="Tier 3",
        bank_cash_inr=Decimal("500000"),
        emergency_reserve_inr=Decimal("100000"),
    )

    dummy_metrics = tmp_path / "metrics.json"
    dummy_metrics.write_text("{}", encoding="utf-8")
    dummy_aliases = tmp_path / "aliases.json"
    dummy_aliases.write_text("{}", encoding="utf-8")

    # 1. Candidate universe with NO qualifying Direct Arbitrage parking fund
    def fake_provider_no_parking(**kwargs):
        return {
            "metrics_path": dummy_metrics,
            "aliases_path": dummy_aliases,
            "scheme_master": {"schemes": []},
            "scheme_master_source_bytes": b"master",
            "candidate_universe": [
                {"category": "Flexi Cap", "plan_type": "Direct", "is_direct": True}
            ],
        }

    res_no_parking = evaluate_portfolio_aware_lumpsum(
        cas_path, mandate, evidence_provider=fake_provider_no_parking
    )
    assert res_no_parking.status == "HOLD"
    assert any("HOLD_NO_QUALIFYING_PARKING" in err for err in res_no_parking.missing_evidence)

    # 2. Candidate universe with qualifying Direct Arbitrage parking fund + mock holdings
    from types import SimpleNamespace
    mock_holding = SimpleNamespace(
        scheme="SBI Bluechip Fund Direct",
        fund_name="SBI Bluechip Fund Direct",
        isin="INF200K01123",
        current_value_inr=Decimal("100000.00"),
        lookthrough_status="VERIFIED",
        constituent_weights_coverage_pct=95.0,
    )
    import services.lumpsum_recommendation as lumpsum_mod
    monkeypatch.setattr(lumpsum_mod, "load_holdings_from_cas_excel", lambda *a, **k: [mock_holding])

    def fake_provider_valid(**kwargs):
        return {
            "metrics_path": dummy_metrics,
            "aliases_path": dummy_aliases,
            "scheme_master": {"schemes": []},
            "scheme_master_source_bytes": b"master",
            "candidate_universe": [
                {
                    "category": "Arbitrage",
                    "plan_type": "Direct",
                    "is_direct": True,
                    "lifecycle_status": "ACTIVE",
                    "is_eligible": True,
                    "scheme_name": "Kotak Equity Arbitrage Direct Growth",
                    "fund_id": "KOTAK-ARB-DIR",
                    "isin": "INF174K01LS2",
                    "source_url": "https://kotakmf.com/factsheet",
                    "as_of_date": "2026-10-31",
                    "source_document_sha256": "a" * 64,
                }
            ],
        }

    res_valid = evaluate_portfolio_aware_lumpsum(
        cas_path, mandate, evidence_provider=fake_provider_valid
    )
    assert res_valid.status == "ELIGIBLE_FOR_HUMAN_REVIEW"
    assert res_valid.lookthrough_coverage_pct == 95.0
    assert res_valid.allocated_amount_inr == Decimal("0")  # Retained unallocated pending review
    assert res_valid.unallocated_amount_inr == Decimal("400000")
    assert len(res_valid.candidate_allocations) == 1
    assert res_valid.candidate_allocations[0]["scheme_name"] == "Kotak Equity Arbitrage Direct Growth"


def test_lumpsum_rejects_candidate_with_weak_or_unhashed_source_evidence(tmp_path, monkeypatch):
    """P1 invariant: Parking candidates with only bare source URL/date and no
    valid source_document_sha256 or exact scheme identity must fail closed to HOLD.
    """
    cas_path = _create_synthetic_cas(tmp_path)
    mandate = InvestorMandateInput(
        as_of_date=date.today(),
        horizon_years=5.0,
        goal="Wealth Accumulation",
        lumpsum_budget_inr=Decimal("500000"),
        explicit_authorized_risk_tier="Tier 4",
        bank_cash_inr=Decimal("1000000"),
        emergency_reserve_inr=Decimal("500000"),
    )
    dummy_metrics = tmp_path / "metrics.json"
    dummy_metrics.write_text("{}", encoding="utf-8")
    dummy_aliases = tmp_path / "aliases.json"
    dummy_aliases.write_text("{}", encoding="utf-8")

    from types import SimpleNamespace
    mock_holding = SimpleNamespace(
        scheme="SBI Bluechip Fund Direct",
        fund_name="SBI Bluechip Fund Direct",
        isin="INF200K01123",
        current_value_inr=Decimal("100000.00"),
        lookthrough_status="VERIFIED",
        constituent_weights_coverage_pct=95.0,
    )
    import services.lumpsum_recommendation as lumpsum_mod
    monkeypatch.setattr(lumpsum_mod, "load_holdings_from_cas_excel", lambda *a, **k: [mock_holding])

    # Candidate has source_url and as_of_date, but NO source_document_sha256 digest!
    def weak_source_provider(**kwargs):
        return {
            "metrics_path": dummy_metrics,
            "aliases_path": dummy_aliases,
            "scheme_master": {"schemes": []},
            "scheme_master_source_bytes": b"master",
            "candidate_universe": [
                {
                    "category": "Arbitrage",
                    "plan_type": "Direct",
                    "is_direct": True,
                    "lifecycle_status": "ACTIVE",
                    "is_eligible": True,
                    "scheme_name": "Kotak Equity Arbitrage Direct Growth",
                    "fund_id": "KOTAK-ARB-DIR",
                    "isin": "INF174K01LS2",
                    "source_url": "https://kotakmf.com/factsheet",
                    "as_of_date": "2026-10-31",
                    # Missing source_document_sha256!
                }
            ],
        }

    res = evaluate_portfolio_aware_lumpsum(cas_path, mandate, evidence_provider=weak_source_provider)
    assert res.status == "HOLD"
    assert any("HOLD_NO_QUALIFYING_PARKING" in err for err in res.missing_evidence)
    assert res.allocated_amount_inr == Decimal("0")
    assert res.unallocated_amount_inr == Decimal("500000")
    assert len(res.candidate_allocations) == 0
