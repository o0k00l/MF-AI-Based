"""
tests/test_financial_data_acquisition.py - Unit and integration tests for acquisition pipeline.
Issue #110 & #112: Test deterministic source retrieval, validation, staging, atomic rollback,
and fail-closed rejection of synthetic or self-attested evidence.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from services.acquisition.adapters.amfi_nav import AmfiNavAdapter
from services.acquisition.adapters.amfi_scheme_master import AmfiSchemeMasterAdapter
from services.acquisition.adapters.portfolio_disclosure import PortfolioDisclosureAdapter
from services.acquisition.bundle_builder import EvidenceBundleBuilder
from services.acquisition.pipeline import FinancialDataRefreshPipeline
from services.sip_evidence_bundle import build_sip_evidence_provider
from services.sip_evidence_contract import validate_evidence_provider_payload
from services.sip_reviewer_approval import (
    create_sip_reviewer_approval_envelope,
    create_sip_trust_registry,
)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import base64

class CallableEnvelope(dict):
    def __init__(self, d, signer, source_signer):
        super().__init__(d)
        self._signer = signer
        self._source_signer = source_signer

    def __call__(self, digest: str) -> dict:
        return self._signer(digest)

    def source_approval(self, source_bytes: bytes, structured_records: Any) -> dict:
        return self._source_signer(source_bytes, structured_records)


def _make_test_approval(
    scope="SIP_EVIDENCE_RELEASE",
    commit_sha: str = "1" * 40,
    policy_digest: str = "2" * 64,
    artifact_digest: Optional[str] = None,
):
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

    def sign(art_dig: str) -> dict:
        return create_sip_reviewer_approval_envelope(
            priv,
            key_id="test-key-1",
            reviewer_id="test-reviewer-1",
            scope=scope,
            source_bytes=b"test_source_bytes",
            structured_records={"verified": True},
            commit_sha=commit_sha,
            policy_digest=policy_digest,
            artifact_digest=art_dig,
        )

    def sign_source(source_bytes: bytes, structured_records: Any) -> dict:
        return create_sip_reviewer_approval_envelope(
            priv,
            key_id="test-key-1",
            reviewer_id="test-reviewer-1",
            scope="SIP_EVIDENCE_RELEASE",
            source_bytes=source_bytes,
            structured_records=structured_records,
        )

    base_env = sign(artifact_digest or "0" * 64)
    if artifact_digest is not None:
        return base_env, registry
    return CallableEnvelope(base_env, sign, sign_source), registry


def _sample_amfi_nav_bytes(as_of: date) -> bytes:
    date_str = as_of.strftime("%d-%b-%Y")
    lines = [
        "Open Ended Schemes ( Equity Scheme - Large Cap Fund )",
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date",
        f"119551;INF200K01TX4;INF200K01TY2;SBI Bluechip Fund - Direct Plan - Growth;82.4532;{date_str}",
        f"119552;INF200K01TZ9;INF200K01UA0;SBI Small Cap Fund - Direct Plan - Growth;142.1200;{date_str}",
        f"119553;INF200K01UB8;-;SBI Liquid Fund - Direct Plan - Growth;3500.1234;{date_str}",
        "",
        "Open Ended Schemes ( Debt Scheme - Overnight Fund )",
        f"119554;INF200K01UC6;-;SBI Overnight Fund - Direct Plan - Growth;1120.4500;{date_str}",
    ]
    return "\r\n".join(lines).encode("utf-8")


def _sample_scheme_master_dict(as_of: date) -> dict:
    return {
        "status": "VERIFIED",
        "source_url": "https://www.amfiindia.com/research-information/other-data/scheme-details",
        "schemes": [
            {
                "scheme_id": "scheme-1",
                "isin": "INF200K01TX4",
                "scheme_name": "SBI Bluechip Fund - Direct Plan - Growth",
                "amc_name": "SBI Mutual Fund",
                "category": "Large Cap",
                "benchmark_identity": "NIFTY 100 TRI",
                "scheme_structure": "OPEN_ENDED_EQUITY",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": 5,
            },
            {
                "scheme_id": "scheme-2",
                "isin": "INF200K01TZ9",
                "scheme_name": "SBI Small Cap Fund - Direct Plan - Growth",
                "amc_name": "SBI Mutual Fund",
                "category": "Small Cap",
                "benchmark_identity": "NIFTY SMALLCAP 250 TRI",
                "scheme_structure": "OPEN_ENDED_EQUITY",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": 6,
            },
        ],
    }


def _metrics_payload_for(master: dict, source_bytes: bytes, as_of: date) -> dict:
    source_ref = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    funds = []
    for scheme in master["schemes"]:
        funds.append({
            "id": scheme["scheme_id"],
            "scheme_id": scheme["scheme_id"],
            "isin": scheme["isin"],
            "amc_name": scheme["amc_name"],
            "category": scheme["category"],
            "cat": scheme["category"],
            "plan_type": scheme["plan_type"],
            "option_type": scheme["option_type"],
            "benchmark_identity": scheme["benchmark_identity"],
            "effective_date": as_of.isoformat(),
            "source_ref": source_ref,
            "eq": 100.0,
            "debt": 0.0,
            "lc": 60.0,
            "mc": 25.0,
            "sc": 15.0,
            "market_cap_basis": "TOTAL_PORTFOLIO_PCT",
            "ter_plan": "direct",
            "er": 0.65,
            "nav": "82.45",
            "h": [],
        })
    return {"funds": funds}


def _metrics_source_metadata(
    metrics_payload: dict, source_bytes: bytes, as_of: date, source_url: str, approval: CallableEnvelope
) -> dict:
    normalized_bytes = json.dumps(metrics_payload, indent=2, sort_keys=True).encode("utf-8")
    metadata = {
        "source_url": source_url,
        "source_document_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "reviewer_attested": True,
        "effective_date": as_of.isoformat(),
        "source_type": "OFFICIAL_FUND_METRICS",
        "normalized_metrics_sha256": hashlib.sha256(normalized_bytes).hexdigest(),
        "publisher": "AMFI",
        "coverage_scope": "All fund metrics records in the reviewed source snapshot",
        "record_count": len(metrics_payload["funds"]),
        "policy_version": "fund-metrics-v1",
        "reviewer_id": "test-reviewer-1",
    }
    signed_records = {
        "funds": metrics_payload["funds"],
        "metadata": metadata,
    }
    metadata["reviewer_approval_envelope"] = approval.source_approval(source_bytes, signed_records)
    return metadata


def test_amfi_nav_adapter_parses_valid_feed_and_preserves_decimal():
    as_of = date.today()
    raw = _sample_amfi_nav_bytes(as_of)
    adapter = AmfiNavAdapter()
    record = adapter.acquire(as_of, raw_bytes=raw)

    assert record.source_name == "AMFI_DAILY_NAV"
    assert record.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert record.record_count == 4
    records = record.parsed_payload
    assert records[0]["scheme_code"] == "119551"
    # Issue #112: Decimal precision must be preserved
    assert records[0]["nav"] == Decimal("82.4532")
    assert records[0]["isin_growth"] == "INF200K01TX4"
    assert records[0]["isin_reinvestment"] == "INF200K01TY2"
    assert records[2]["isin_reinvestment"] is None


def test_amfi_nav_adapter_rejects_corrupted_and_future_records():
    as_of = date.today()
    date_str = as_of.strftime("%d-%b-%Y")
    future_date_str = (as_of + timedelta(days=5)).strftime("%d-%b-%Y")
    stale_date_str = (as_of - timedelta(days=60)).strftime("%d-%b-%Y")

    corrupted_lines = [
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date",
        f"119551;INF200K01TX4;-;SBI Bluechip Fund;N.A.;{date_str}",  # Non-numeric NAV
        f"119552;INF200K01TZ9;-;SBI Small Cap Fund;-15.5;{date_str}",  # Negative NAV
        f"119553;INF200K01UB8;-;SBI Liquid Fund;3500.0;{future_date_str}",  # Future date
        f"119554;INF200K01UC6;-;SBI Overnight Fund;1120.0;{stale_date_str}",  # Stale (>45 days)
        f"abcde;INF200K01UD4;-;Corrupt Scheme;100.0;{date_str}",  # Non-numeric scheme code
        f"119555;INF200K01UE2;-;SBI Valid Fund;55.0;{date_str}",  # Valid
    ]
    raw = "\r\n".join(corrupted_lines).encode("utf-8")
    adapter = AmfiNavAdapter()
    record = adapter.acquire(as_of, raw_bytes=raw)

    assert record.record_count == 1
    assert record.parsed_payload[0]["scheme_code"] == "119555"
    assert record.metadata["rejected_rows_count"] >= 5


def test_amfi_nav_adapter_rejects_empty_payload():
    adapter = AmfiNavAdapter()
    with pytest.raises(ValueError, match="empty"):
        adapter.acquire(date.today(), raw_bytes=b"   \r\n")


def test_amfi_scheme_master_adapter_json_and_validation():
    as_of = date.today()
    master_dict = _sample_scheme_master_dict(as_of)
    raw = json.dumps(master_dict).encode("utf-8")

    adapter = AmfiSchemeMasterAdapter()
    record = adapter.acquire(as_of, raw_bytes=raw, reviewer_attested=True)

    assert record.source_name == "AMFI_SCHEME_MASTER"
    assert record.record_count == 2
    assert record.parsed_payload["status"] == "VERIFIED"
    assert record.parsed_payload["schemes"][0]["scheme_id"] == "scheme-1"


def test_amfi_scheme_master_adapter_rejects_duplicates():
    as_of = date.today()
    dup_schemes = {
        "schemes": [
            {
                "scheme_id": "scheme-1",
                "isin": "INF200K01TX4",
                "scheme_name": "Scheme A",
                "amc_name": "AMC",
                "category": "Large Cap",
                "benchmark_identity": "NIFTY 50 TRI",
                "scheme_structure": "OPEN_ENDED",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": 3,
            },
            {
                "scheme_id": "scheme-1",  # Duplicate scheme_id
                "isin": "INF200K01TX5",
                "scheme_name": "Scheme B",
                "amc_name": "AMC",
                "category": "Large Cap",
                "benchmark_identity": "NIFTY 50 TRI",
                "scheme_structure": "OPEN_ENDED",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": 3,
            },
        ]
    }
    raw = json.dumps(dup_schemes).encode("utf-8")
    adapter = AmfiSchemeMasterAdapter()
    with pytest.raises(ValueError, match="Duplicate scheme_id"):
        adapter.acquire(as_of, raw_bytes=raw, reviewer_attested=True)


def test_portfolio_disclosure_adapter_validation():
    as_of = date.today()
    payload = {
        "constituent_weights": {"RELIANCE": 55.5, "TCS": 44.5},
        "constituent_weights_coverage_pct": 100.0,
    }
    raw = json.dumps(payload).encode("utf-8")
    adapter = PortfolioDisclosureAdapter("scheme-1")
    record = adapter.acquire(as_of, raw_bytes=raw, reviewer_attested=True)

    assert record.record_count == 2
    assert record.parsed_payload["constituent_weights"]["RELIANCE"] == 55.5
    assert record.parsed_payload["scheme_id"] == "scheme-1"


def test_portfolio_disclosure_adapter_rejects_negative_weight():
    as_of = date.today()
    payload = {
        "constituent_weights": {"RELIANCE": -10.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    raw = json.dumps(payload).encode("utf-8")
    adapter = PortfolioDisclosureAdapter("scheme-1")
    with pytest.raises(ValueError, match="Negative constituent weight"):
        adapter.acquire(as_of, raw_bytes=raw, reviewer_attested=True)


def test_evidence_bundle_builder_staging_and_atomic_promotion(tmp_path):
    as_of = date.today()
    target_bundle_dir = tmp_path / "bundle"

    master = _sample_scheme_master_dict(as_of)
    master_bytes = json.dumps(master).encode("utf-8")

    metrics_bytes = b"metrics_source_csv_bytes"
    universe_bytes = b"universe_source_bytes"

    disclosures = {
        "scheme-1": {
            "constituent_weights": {"RELIANCE": 100.0},
            "constituent_weights_coverage_pct": 100.0,
            "source_url": "https://www.amfiindia.com/disclosures/scheme-1",
        },
        "scheme-2": {
            "constituent_weights": {"INFY": 100.0},
            "constituent_weights_coverage_pct": 100.0,
            "source_url": "https://www.amfiindia.com/disclosures/scheme-2",
        },
    }
    disc_bytes = {
        "scheme-1": json.dumps(disclosures["scheme-1"]).encode("utf-8"),
        "scheme-2": json.dumps(disclosures["scheme-2"]).encode("utf-8"),
    }
    direct_evidence = {
        "scheme-1": b"%PDF-1.4 factsheet 1",
        "scheme-2": b"%PDF-1.4 factsheet 2",
    }
    candidates = [
        {
            "fund_id": "fund-1",
            "fund_name": master["schemes"][0]["scheme_name"],
            "scheme_id": "scheme-1",
            "isin": master["schemes"][0]["isin"],
            "amc_name": master["schemes"][0]["amc_name"],
            "category": master["schemes"][0]["category"],
            "benchmark_identity": master["schemes"][0]["benchmark_identity"],
            "scheme_structure": master["schemes"][0]["scheme_structure"],
            "plan_type": "Direct",
            "option_type": "Growth",
            "riskometer_score": master["schemes"][0]["riskometer_score"],
            "is_direct": True,
            "direct_plan_evidence": {
                "source_url": "https://www.amfiindia.com/factsheets/scheme-1.pdf",
            },
        },
        {
            "fund_id": "fund-2",
            "fund_name": master["schemes"][1]["scheme_name"],
            "scheme_id": "scheme-2",
            "isin": master["schemes"][1]["isin"],
            "amc_name": master["schemes"][1]["amc_name"],
            "category": master["schemes"][1]["category"],
            "benchmark_identity": master["schemes"][1]["benchmark_identity"],
            "scheme_structure": master["schemes"][1]["scheme_structure"],
            "plan_type": "Direct",
            "option_type": "Growth",
            "riskometer_score": master["schemes"][1]["riskometer_score"],
            "is_direct": True,
            "direct_plan_evidence": {
                "source_url": "https://www.amfiindia.com/factsheets/scheme-2.pdf",
            },
        },
    ]

    envelope, registry = _make_test_approval()
    metrics_source_metadata = _metrics_source_metadata(
        _metrics_payload_for(master, metrics_bytes, as_of), metrics_bytes, as_of,
        "https://www.amfiindia.com/research-information/other-data/fund-metrics", envelope,
    )
    builder = EvidenceBundleBuilder(target_bundle_dir)
    promoted_dir = builder.build_and_promote(
        as_of,
        scheme_master=master,
        scheme_master_source_bytes=master_bytes,
        metrics_payload=_metrics_payload_for(master, metrics_bytes, as_of),
        metrics_source_bytes=metrics_bytes,
        metrics_source_metadata=metrics_source_metadata,
        candidate_universe=candidates,
        candidate_universe_source_bytes=universe_bytes,
        portfolio_disclosures=disclosures,
        portfolio_disclosure_source_bytes=disc_bytes,
        direct_plan_evidence_bytes=direct_evidence,
        master_source_url="https://www.amfiindia.com/research-information/other-data/scheme-details",
        metrics_source_url="https://www.amfiindia.com/research-information/other-data/fund-metrics",
        universe_source_url="https://www.amfiindia.com/research-information/other-data/candidate-universe",
        reviewer_attested=True,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
    )

    assert promoted_dir == target_bundle_dir
    assert (promoted_dir / "manifest.json").is_file()
    assert (promoted_dir / "scheme_master.json").is_file()
    assert (promoted_dir / "metrics.json").is_file()
    assert (promoted_dir / "candidates.json").is_file()

    # Verify provider loads cleanly from target bundle
    provider = build_sip_evidence_provider(target_bundle_dir)
    assert provider is not None

    cas_file = tmp_path / "cas.xlsx"
    cas_file.write_bytes(b"dummy cas")
    payload = provider(cas_path=cas_file, monthly_budget_inr=25000, risk_profile="Moderate")
    validated = validate_evidence_provider_payload(payload, require_reviewer_signature=False)
    assert len(validated["candidate_universe"]) == 2


def test_evidence_bundle_builder_atomic_rollback_on_failure(tmp_path):
    as_of = date.today()
    target_bundle_dir = tmp_path / "bundle"

    master = _sample_scheme_master_dict(as_of)
    master_bytes = json.dumps(master).encode("utf-8")

    envelope, registry = _make_test_approval()
    metrics_source_bytes = b"metrics_1"
    metrics_payload = _metrics_payload_for(master, metrics_source_bytes, as_of)
    metrics_source_metadata = _metrics_source_metadata(
        metrics_payload, metrics_source_bytes, as_of,
        "https://www.amfiindia.com/research-information/other-data/fund-metrics", envelope,
    )

    # Initial successful build
    builder = EvidenceBundleBuilder(target_bundle_dir)
    builder.build_and_promote(
        as_of,
        scheme_master=master,
        scheme_master_source_bytes=master_bytes,
        metrics_payload=metrics_payload,
        metrics_source_bytes=metrics_source_bytes,
        metrics_source_metadata=metrics_source_metadata,
        candidate_universe=[{
            "fund_id": "fund-1",
            "fund_name": master["schemes"][0]["scheme_name"],
            "scheme_id": "scheme-1",
            "isin": master["schemes"][0]["isin"],
            "amc_name": master["schemes"][0]["amc_name"],
            "category": master["schemes"][0]["category"],
            "benchmark_identity": master["schemes"][0]["benchmark_identity"],
            "scheme_structure": master["schemes"][0]["scheme_structure"],
            "plan_type": "Direct",
            "option_type": "Growth",
            "riskometer_score": master["schemes"][0]["riskometer_score"],
            "is_direct": True,
            "direct_plan_evidence": {
                "source_url": "https://www.amfiindia.com/factsheets/scheme-1.pdf",
            },
        }],
        candidate_universe_source_bytes=b"universe_1",
        portfolio_disclosures={
            "scheme-1": {
                "constituent_weights": {"RELIANCE": 100.0},
                "constituent_weights_coverage_pct": 100.0,
                "source_url": "https://www.amfiindia.com/disclosures/scheme-1",
            }
        },
        portfolio_disclosure_source_bytes={"scheme-1": b"disc_1"},
        direct_plan_evidence_bytes={"scheme-1": b"%PDF-1.4 direct 1"},
        master_source_url="https://www.amfiindia.com/research-information/other-data/scheme-details",
        metrics_source_url="https://www.amfiindia.com/research-information/other-data/fund-metrics",
        universe_source_url="https://www.amfiindia.com/research-information/other-data/candidate-universe",
        reviewer_attested=True,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
    )
    initial_manifest_content = (target_bundle_dir / "manifest.json").read_text(encoding="utf-8")

    # Now attempt invalid build (e.g. empty candidate universe)
    with pytest.raises(ValueError):
        builder.build_and_promote(
            as_of,
            scheme_master=master,
            scheme_master_source_bytes=master_bytes,
            metrics_payload={"funds": []},
            metrics_source_bytes=b"metrics_2",
            metrics_source_metadata=metrics_source_metadata,
            candidate_universe=[],  # Invalid: empty candidate universe
            candidate_universe_source_bytes=b"universe_2",
            portfolio_disclosures={},
            portfolio_disclosure_source_bytes={},
            direct_plan_evidence_bytes={},
            master_source_url="https://www.amfiindia.com/research-information/other-data/scheme-details",
            metrics_source_url="https://www.amfiindia.com/research-information/other-data/fund-metrics",
            universe_source_url="https://www.amfiindia.com/research-information/other-data/candidate-universe",
            reviewer_attested=True,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
        )

    # Verify initial bundle was NOT mutated or removed
    assert target_bundle_dir.exists()
    assert (target_bundle_dir / "manifest.json").read_text(encoding="utf-8") == initial_manifest_content


def test_financial_data_refresh_pipeline_hermetic_success(tmp_path):
    as_of = date.today()
    bundle_target = tmp_path / "production_bundle"

    master = _sample_scheme_master_dict(as_of)
    master_bytes = json.dumps(master).encode("utf-8")
    nav_bytes = _sample_amfi_nav_bytes(as_of)

    candidates = [
        {
            "fund_id": "fund-1",
            "fund_name": master["schemes"][0]["scheme_name"],
            "scheme_id": "scheme-1",
            "isin": master["schemes"][0]["isin"],
            "amc_name": master["schemes"][0]["amc_name"],
            "category": master["schemes"][0]["category"],
            "benchmark_identity": master["schemes"][0]["benchmark_identity"],
            "scheme_structure": master["schemes"][0]["scheme_structure"],
            "plan_type": "Direct",
            "option_type": "Growth",
            "riskometer_score": master["schemes"][0]["riskometer_score"],
            "is_direct": True,
        },
        {
            "fund_id": "fund-2",
            "fund_name": master["schemes"][1]["scheme_name"],
            "scheme_id": "scheme-2",
            "isin": master["schemes"][1]["isin"],
            "amc_name": master["schemes"][1]["amc_name"],
            "category": master["schemes"][1]["category"],
            "benchmark_identity": master["schemes"][1]["benchmark_identity"],
            "scheme_structure": master["schemes"][1]["scheme_structure"],
            "plan_type": "Direct",
            "option_type": "Growth",
            "riskometer_score": master["schemes"][1]["riskometer_score"],
            "is_direct": True,
        },
    ]

    envelope, registry = _make_test_approval()
    metrics_source_bytes = b"scheme_id,nav,alpha\n"
    metrics_payload = _metrics_payload_for(master, metrics_source_bytes, as_of)
    metrics_source_metadata = _metrics_source_metadata(
        metrics_payload, metrics_source_bytes, as_of,
        "https://amfiindia.com/metrics", envelope,
    )
    pipeline = FinancialDataRefreshPipeline()
    result = pipeline.refresh(
        bundle_target,
        as_of,
        hermetic_inputs={
            "scheme_master": master_bytes,
            "daily_nav": nav_bytes,
            "metrics": metrics_source_bytes,
            "metrics_json": json.dumps(metrics_payload).encode("utf-8"),
            "candidate_universe_source": json.dumps(candidates).encode("utf-8"),
            "disclosures": {
                "scheme-1": json.dumps({"constituent_weights": {"RELIANCE": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
                "scheme-2": json.dumps({"constituent_weights": {"INFY": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
            },
            "direct_evidence": {
                "scheme-1": b"%PDF-1.4 factsheet 1",
                "scheme-2": b"%PDF-1.4 factsheet 2",
            },
            "direct_evidence_urls": {
                "scheme-1": "https://amfiindia.com/factsheets/scheme-1.pdf",
                "scheme-2": "https://amfiindia.com/factsheets/scheme-2.pdf",
            },
        },
        metrics_source_url="https://amfiindia.com/metrics",
        metrics_source_metadata=metrics_source_metadata,
        universe_source_url="https://amfiindia.com/universe",
        reviewer_attested=True,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
    )

    assert result.status == "SUCCESS"
    assert result.bundle_dir == bundle_target
    assert "AMFI_SCHEME_MASTER" in result.sources_acquired
    assert "AMFI_DAILY_NAV" in result.sources_acquired
    assert result.is_atomic_rollback is False
    assert (bundle_target / "manifest.json").is_file()

    # Load provider from newly promoted bundle
    provider = build_sip_evidence_provider(bundle_target)
    assert provider is not None
    cas_file = tmp_path / "cas.xlsx"
    cas_file.write_bytes(b"cas content")
    payload = provider(cas_path=cas_file, monthly_budget_inr=20000, risk_profile="Moderate")
    validated = validate_evidence_provider_payload(payload, require_reviewer_signature=False)
    assert len(validated["candidate_universe"]) == 2


def test_financial_data_refresh_pipeline_future_date_fails_closed(tmp_path):
    future_date = date.today() + timedelta(days=10)
    bundle_target = tmp_path / "future_bundle"

    pipeline = FinancialDataRefreshPipeline()
    result = pipeline.refresh(bundle_target, future_date, reviewer_attested=True)

    assert result.status == "FAILED"
    assert result.bundle_dir is None
    assert any("future" in err.lower() for err in result.errors)
    assert result.is_atomic_rollback is True
    assert not bundle_target.exists()


def test_refresh_pipeline_fails_closed_when_required_source_evidence_is_missing(tmp_path):
    envelope, registry = _make_test_approval()
    pipeline = FinancialDataRefreshPipeline()
    target = tmp_path / "bundle"

    result = pipeline.refresh(target, date.today(), reviewer_attested=True, reviewer_approval_envelope=envelope, reviewer_trust_registry=registry)

    assert result.status == "FAILED"
    assert result.bundle_dir is None
    assert result.is_atomic_rollback is True
    assert "synthetic defaults are prohibited" in " ".join(result.errors)
    assert not target.exists()


def test_refresh_pipeline_does_not_default_reviewer_attestation_to_true():
    parameter = inspect.signature(FinancialDataRefreshPipeline.refresh).parameters["reviewer_attested"]
    assert parameter.default is False


def test_refresh_pipeline_fails_closed_on_fabricated_text_direct_evidence(tmp_path):
    as_of = date.today()
    bundle_target = tmp_path / "bad_pdf_bundle"

    master = _sample_scheme_master_dict(as_of)
    master_bytes = json.dumps(master).encode("utf-8")
    nav_bytes = _sample_amfi_nav_bytes(as_of)

    envelope, registry = _make_test_approval()
    metrics_source_bytes = b"scheme_id,nav,alpha\n"
    metrics_payload = _metrics_payload_for(master, metrics_source_bytes, as_of)
    metrics_source_metadata = _metrics_source_metadata(
        metrics_payload, metrics_source_bytes, as_of,
        "https://amfiindia.com/metrics", envelope,
    )
    pipeline = FinancialDataRefreshPipeline()
    result = pipeline.refresh(
        bundle_target,
        as_of,
        hermetic_inputs={
            "scheme_master": master_bytes,
            "daily_nav": nav_bytes,
            "metrics": metrics_source_bytes,
            "metrics_json": json.dumps(metrics_payload).encode("utf-8"),
            "candidate_universe_source": b"candidate_source",
            "disclosures": {
                "scheme-1": json.dumps({"constituent_weights": {"RELIANCE": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
                "scheme-2": json.dumps({"constituent_weights": {"INFY": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
            },
            "direct_evidence": {
                "scheme-1": b"fabricated text placeholder",  # Not a PDF!
                "scheme-2": b"%PDF-1.4 factsheet 2",
            },
        },
        metrics_source_url="https://amfiindia.com/metrics",
        metrics_source_metadata=metrics_source_metadata,
        reviewer_attested=True,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
    )

    assert result.status == "FAILED"
    assert any("PDF direct-plan evidence" in err for err in result.errors)
    assert not bundle_target.exists()


def test_refresh_pipeline_fails_closed_on_empty_metrics_funds(tmp_path):
    as_of = date.today()
    bundle_target = tmp_path / "empty_metrics_bundle"

    master = _sample_scheme_master_dict(as_of)
    master_bytes = json.dumps(master).encode("utf-8")
    nav_bytes = _sample_amfi_nav_bytes(as_of)

    # Build candidates with direct_plan_evidence containing source_url
    candidates = [
        {
            "fund_id": "fund-1",
            "fund_name": master["schemes"][0]["scheme_name"],
            "scheme_id": "scheme-1",
            "isin": master["schemes"][0]["isin"],
            "amc_name": master["schemes"][0]["amc_name"],
            "category": master["schemes"][0]["category"],
            "benchmark_identity": master["schemes"][0]["benchmark_identity"],
            "scheme_structure": master["schemes"][0]["scheme_structure"],
            "plan_type": "Direct",
            "option_type": "Growth",
            "riskometer_score": master["schemes"][0]["riskometer_score"],
            "is_direct": True,
        },
        {
            "fund_id": "fund-2",
            "fund_name": master["schemes"][1]["scheme_name"],
            "scheme_id": "scheme-2",
            "isin": master["schemes"][1]["isin"],
            "amc_name": master["schemes"][1]["amc_name"],
            "category": master["schemes"][1]["category"],
            "benchmark_identity": master["schemes"][1]["benchmark_identity"],
            "scheme_structure": master["schemes"][1]["scheme_structure"],
            "plan_type": "Direct",
            "option_type": "Growth",
            "riskometer_score": master["schemes"][1]["riskometer_score"],
            "is_direct": True,
        },
    ]

    envelope, registry = _make_test_approval()
    pipeline = FinancialDataRefreshPipeline()
    result = pipeline.refresh(
        bundle_target,
        as_of,
        hermetic_inputs={
            "scheme_master": master_bytes,
            "daily_nav": nav_bytes,
            "metrics": b"scheme_id,nav,alpha\n",
            "metrics_json": b'{"funds": []}',  # Empty funds array!
            "candidate_universe_source": json.dumps(candidates).encode("utf-8"),
            "disclosures": {
                "scheme-1": json.dumps({"constituent_weights": {"RELIANCE": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
                "scheme-2": json.dumps({"constituent_weights": {"INFY": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
            },
            "direct_evidence": {
                "scheme-1": b"%PDF-1.4 factsheet 1",
                "scheme-2": b"%PDF-1.4 factsheet 2",
            },
            "direct_evidence_urls": {
                "scheme-1": "https://amfiindia.com/factsheets/scheme-1.pdf",
                "scheme-2": "https://amfiindia.com/factsheets/scheme-2.pdf",
            },
        },
        metrics_source_url="https://amfiindia.com/metrics",
        universe_source_url="https://amfiindia.com/universe",
        reviewer_attested=True,
        reviewer_approval_envelope=envelope,
        reviewer_trust_registry=registry,
    )

    assert result.status == "FAILED", f"Expected FAILED but got {result.status}. Errors: {result.errors}"
    assert any("non-empty funds array" in err for err in result.errors), f"Expected 'non-empty funds array' in errors but got: {result.errors}"
    assert not bundle_target.exists()


def test_builder_fails_closed_on_missing_direct_plan_evidence_bytes(tmp_path):
    as_of = date.today()
    envelope, registry = _make_test_approval()
    builder = EvidenceBundleBuilder(tmp_path / "bundle")
    master = _sample_scheme_master_dict(as_of)
    metrics_source_bytes = b"metrics_1"
    metrics_payload = _metrics_payload_for(master, metrics_source_bytes, as_of)
    metrics_source_metadata = _metrics_source_metadata(
        metrics_payload, metrics_source_bytes, as_of,
        "https://amfiindia.com/metrics", envelope,
    )
    with pytest.raises(ValueError, match="Missing direct plan evidence bytes"):
        builder.build_and_promote(
            as_of,
            scheme_master=master,
            scheme_master_source_bytes=json.dumps(master).encode("utf-8"),
            metrics_payload=metrics_payload,
            metrics_source_bytes=metrics_source_bytes,
            metrics_source_metadata=metrics_source_metadata,
            candidate_universe=[{
                "fund_id": "fund-1",
                "fund_name": "Fund 1",
                "scheme_id": "scheme-1",
                "isin": "INF200K01TX4",
                "amc_name": "SBI",
                "category": "Large Cap",
                "benchmark_identity": "NIFTY 100 TRI",
                "scheme_structure": "OPEN_ENDED_EQUITY",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": 5,
                "is_direct": True,
                "direct_plan_evidence": {"source_url": "https://amfiindia.com/factsheets/scheme-1.pdf"},
            }],
            candidate_universe_source_bytes=b"universe_1",
            portfolio_disclosures={"scheme-1": {"constituent_weights": {}, "source_url": "https://amfi.com/d/1"}},
            portfolio_disclosure_source_bytes={"scheme-1": b"bytes"},
            direct_plan_evidence_bytes={},  # Missing!
            master_source_url="https://amfiindia.com/master",
            metrics_source_url="https://amfiindia.com/metrics",
            universe_source_url="https://amfiindia.com/universe",
            reviewer_attested=True,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
        )


def test_builder_fails_closed_on_missing_direct_plan_evidence_source_url(tmp_path):
    as_of = date.today()
    envelope, registry = _make_test_approval()
    builder = EvidenceBundleBuilder(tmp_path / "bundle")
    master = _sample_scheme_master_dict(as_of)
    metrics_source_bytes = b"metrics_1"
    metrics_payload = _metrics_payload_for(master, metrics_source_bytes, as_of)
    metrics_source_metadata = _metrics_source_metadata(
        metrics_payload, metrics_source_bytes, as_of,
        "https://amfiindia.com/metrics", envelope,
    )
    with pytest.raises(ValueError, match="Missing direct plan evidence source URL"):
        builder.build_and_promote(
            as_of,
            scheme_master=master,
            scheme_master_source_bytes=json.dumps(master).encode("utf-8"),
            metrics_payload=metrics_payload,
            metrics_source_bytes=metrics_source_bytes,
            metrics_source_metadata=metrics_source_metadata,
            candidate_universe=[{
                "fund_id": "fund-1",
                "fund_name": "Fund 1",
                "scheme_id": "scheme-1",
                "isin": "INF200K01TX4",
                "amc_name": "SBI",
                "category": "Large Cap",
                "benchmark_identity": "NIFTY 100 TRI",
                "scheme_structure": "OPEN_ENDED_EQUITY",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": 5,
                "is_direct": True,
                "direct_plan_evidence": {},  # Missing source_url!
            }],
            candidate_universe_source_bytes=b"universe_1",
            portfolio_disclosures={"scheme-1": {"constituent_weights": {}, "source_url": "https://amfi.com/d/1"}},
            portfolio_disclosure_source_bytes={"scheme-1": b"bytes"},
            direct_plan_evidence_bytes={"scheme-1": b"%PDF-1.4 direct 1"},
            master_source_url="https://amfiindia.com/master",
            metrics_source_url="https://amfiindia.com/metrics",
            universe_source_url="https://amfiindia.com/universe",
            reviewer_attested=True,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
        )


def test_builder_fails_closed_on_missing_disclosure_source_bytes(tmp_path):
    as_of = date.today()
    envelope, registry = _make_test_approval()
    builder = EvidenceBundleBuilder(tmp_path / "bundle")
    master = _sample_scheme_master_dict(as_of)
    metrics_source_bytes = b"metrics_1"
    metrics_payload = _metrics_payload_for(master, metrics_source_bytes, as_of)
    metrics_source_metadata = _metrics_source_metadata(
        metrics_payload, metrics_source_bytes, as_of,
        "https://amfiindia.com/metrics", envelope,
    )
    with pytest.raises(ValueError, match="Missing original portfolio disclosure source bytes"):
        builder.build_and_promote(
            as_of,
            scheme_master=master,
            scheme_master_source_bytes=json.dumps(master).encode("utf-8"),
            metrics_payload=metrics_payload,
            metrics_source_bytes=metrics_source_bytes,
            metrics_source_metadata=metrics_source_metadata,
            candidate_universe=[{
                "fund_id": "fund-1",
                "fund_name": "Fund 1",
                "scheme_id": "scheme-1",
                "isin": "INF200K01TX4",
                "amc_name": "SBI",
                "category": "Large Cap",
                "benchmark_identity": "NIFTY 100 TRI",
                "scheme_structure": "OPEN_ENDED_EQUITY",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": 5,
                "is_direct": True,
                "direct_plan_evidence": {"source_url": "https://amfiindia.com/factsheets/scheme-1.pdf"},
            }],
            candidate_universe_source_bytes=b"universe_1",
            portfolio_disclosures={"scheme-1": {"constituent_weights": {}, "source_url": "https://amfi.com/d/1"}},
            portfolio_disclosure_source_bytes={},  # Missing!
            direct_plan_evidence_bytes={"scheme-1": b"%PDF-1.4 direct 1"},
            master_source_url="https://amfiindia.com/master",
            metrics_source_url="https://amfiindia.com/metrics",
            universe_source_url="https://amfiindia.com/universe",
            reviewer_attested=True,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
        )


def test_builder_fails_closed_on_missing_disclosure_source_url(tmp_path):
    as_of = date.today()
    envelope, registry = _make_test_approval()
    builder = EvidenceBundleBuilder(tmp_path / "bundle")
    master = _sample_scheme_master_dict(as_of)
    metrics_source_bytes = b"metrics_1"
    metrics_payload = _metrics_payload_for(master, metrics_source_bytes, as_of)
    metrics_source_metadata = _metrics_source_metadata(
        metrics_payload, metrics_source_bytes, as_of,
        "https://amfiindia.com/metrics", envelope,
    )
    with pytest.raises(ValueError, match="Missing portfolio disclosure source URL"):
        builder.build_and_promote(
            as_of,
            scheme_master=master,
            scheme_master_source_bytes=json.dumps(master).encode("utf-8"),
            metrics_payload=metrics_payload,
            metrics_source_bytes=metrics_source_bytes,
            metrics_source_metadata=metrics_source_metadata,
            candidate_universe=[{
                "fund_id": "fund-1",
                "fund_name": "Fund 1",
                "scheme_id": "scheme-1",
                "isin": "INF200K01TX4",
                "amc_name": "SBI",
                "category": "Large Cap",
                "benchmark_identity": "NIFTY 100 TRI",
                "scheme_structure": "OPEN_ENDED_EQUITY",
                "plan_type": "Direct",
                "option_type": "Growth",
                "riskometer_score": 5,
                "is_direct": True,
                "direct_plan_evidence": {"source_url": "https://amfiindia.com/factsheets/scheme-1.pdf"},
            }],
            candidate_universe_source_bytes=b"universe_1",
            portfolio_disclosures={"scheme-1": {"constituent_weights": {}}},  # Missing source_url!
            portfolio_disclosure_source_bytes={"scheme-1": b"bytes"},
            direct_plan_evidence_bytes={"scheme-1": b"%PDF-1.4 direct 1"},
            master_source_url="https://amfiindia.com/master",
            metrics_source_url="https://amfiindia.com/metrics",
            universe_source_url="https://amfiindia.com/universe",
            reviewer_attested=True,
            reviewer_approval_envelope=envelope,
            reviewer_trust_registry=registry,
        )


def test_pipeline_fails_closed_when_reviewer_signature_required_but_missing(tmp_path):
    pipeline = FinancialDataRefreshPipeline()
    result = pipeline.refresh(
        tmp_path / "sig_bundle",
        date.today(),
        reviewer_attested=True,
        require_reviewer_signature=True,
    )
    assert result.status == "FAILED"
    assert any("reviewer approval envelope and trust registry are required" in err for err in result.errors)
