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

    builder = EvidenceBundleBuilder(target_bundle_dir)
    promoted_dir = builder.build_and_promote(
        as_of,
        scheme_master=master,
        scheme_master_source_bytes=master_bytes,
        metrics_payload={"funds": [{"fund_id": "fund-1", "nav": Decimal("82.45")}]},
        metrics_source_bytes=metrics_bytes,
        candidate_universe=candidates,
        candidate_universe_source_bytes=universe_bytes,
        portfolio_disclosures=disclosures,
        portfolio_disclosure_source_bytes=disc_bytes,
        direct_plan_evidence_bytes=direct_evidence,
        master_source_url="https://www.amfiindia.com/research-information/other-data/scheme-details",
        metrics_source_url="https://www.amfiindia.com/research-information/other-data/fund-metrics",
        universe_source_url="https://www.amfiindia.com/research-information/other-data/candidate-universe",
        reviewer_attested=True,
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

    # Initial successful build
    builder = EvidenceBundleBuilder(target_bundle_dir)
    builder.build_and_promote(
        as_of,
        scheme_master=master,
        scheme_master_source_bytes=master_bytes,
        metrics_payload={"funds": [{"fund_id": "fund-1", "nav": "82.45"}]},
        metrics_source_bytes=b"metrics_1",
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
            candidate_universe=[],  # Invalid: empty candidate universe
            candidate_universe_source_bytes=b"universe_2",
            portfolio_disclosures={},
            portfolio_disclosure_source_bytes={},
            direct_plan_evidence_bytes={},
            master_source_url="https://www.amfiindia.com/research-information/other-data/scheme-details",
            metrics_source_url="https://www.amfiindia.com/research-information/other-data/fund-metrics",
            universe_source_url="https://www.amfiindia.com/research-information/other-data/candidate-universe",
            reviewer_attested=True,
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

    pipeline = FinancialDataRefreshPipeline()
    result = pipeline.refresh(
        bundle_target,
        as_of,
        hermetic_inputs={
            "scheme_master": master_bytes,
            "daily_nav": nav_bytes,
            "metrics": b"scheme_id,nav,alpha\n",
            "metrics_json": json.dumps({"funds": [{"fund_id": "fund-1", "nav": "82.4532"}]}).encode("utf-8"),
            "candidate_universe_source": json.dumps(candidates).encode("utf-8"),
            "disclosures": {
                "scheme-1": json.dumps({"constituent_weights": {"RELIANCE": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
                "scheme-2": json.dumps({"constituent_weights": {"INFY": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
            },
            "direct_evidence": {
                "scheme-1": b"%PDF-1.4 factsheet 1",
                "scheme-2": b"%PDF-1.4 factsheet 2",
            },
        },
        reviewer_attested=True,
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
    pipeline = FinancialDataRefreshPipeline()
    target = tmp_path / "bundle"

    result = pipeline.refresh(target, date.today(), reviewer_attested=True)

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

    pipeline = FinancialDataRefreshPipeline()
    result = pipeline.refresh(
        bundle_target,
        as_of,
        hermetic_inputs={
            "scheme_master": master_bytes,
            "daily_nav": nav_bytes,
            "metrics": b"scheme_id,nav,alpha\n",
            "metrics_json": json.dumps({"funds": [{"fund_id": "fund-1", "nav": "82.4532"}]}).encode("utf-8"),
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
        reviewer_attested=True,
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

    pipeline = FinancialDataRefreshPipeline()
    result = pipeline.refresh(
        bundle_target,
        as_of,
        hermetic_inputs={
            "scheme_master": master_bytes,
            "daily_nav": nav_bytes,
            "metrics": b"scheme_id,nav,alpha\n",
            "metrics_json": b'{"funds": []}',  # Empty funds array!
            "candidate_universe_source": b"candidate_source",
            "disclosures": {
                "scheme-1": json.dumps({"constituent_weights": {"RELIANCE": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
                "scheme-2": json.dumps({"constituent_weights": {"INFY": 100.0}, "constituent_weights_coverage_pct": 100.0}).encode("utf-8"),
            },
            "direct_evidence": {
                "scheme-1": b"%PDF-1.4 factsheet 1",
                "scheme-2": b"%PDF-1.4 factsheet 2",
            },
        },
        reviewer_attested=True,
    )

    assert result.status == "FAILED"
    assert any("non-empty funds array" in err for err in result.errors)
    assert not bundle_target.exists()


def test_builder_fails_closed_on_missing_direct_plan_evidence_bytes(tmp_path):
    as_of = date.today()
    builder = EvidenceBundleBuilder(tmp_path / "bundle")
    master = _sample_scheme_master_dict(as_of)
    with pytest.raises(ValueError, match="Missing direct plan evidence bytes"):
        builder.build_and_promote(
            as_of,
            scheme_master=master,
            scheme_master_source_bytes=json.dumps(master).encode("utf-8"),
            metrics_payload={"funds": [{"fund_id": "fund-1", "nav": "82.45"}]},
            metrics_source_bytes=b"metrics_1",
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
        )


def test_builder_fails_closed_on_missing_direct_plan_evidence_source_url(tmp_path):
    as_of = date.today()
    builder = EvidenceBundleBuilder(tmp_path / "bundle")
    master = _sample_scheme_master_dict(as_of)
    with pytest.raises(ValueError, match="Missing direct plan evidence source URL"):
        builder.build_and_promote(
            as_of,
            scheme_master=master,
            scheme_master_source_bytes=json.dumps(master).encode("utf-8"),
            metrics_payload={"funds": [{"fund_id": "fund-1", "nav": "82.45"}]},
            metrics_source_bytes=b"metrics_1",
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
        )


def test_builder_fails_closed_on_missing_disclosure_source_bytes(tmp_path):
    as_of = date.today()
    builder = EvidenceBundleBuilder(tmp_path / "bundle")
    master = _sample_scheme_master_dict(as_of)
    with pytest.raises(ValueError, match="Missing original portfolio disclosure source bytes"):
        builder.build_and_promote(
            as_of,
            scheme_master=master,
            scheme_master_source_bytes=json.dumps(master).encode("utf-8"),
            metrics_payload={"funds": [{"fund_id": "fund-1", "nav": "82.45"}]},
            metrics_source_bytes=b"metrics_1",
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
            direct_plan_evidence_bytes={"scheme-1": b"%PDF-1.4 direct 1"},
            master_source_url="https://amfiindia.com/master",
            metrics_source_url="https://amfiindia.com/metrics",
            universe_source_url="https://amfiindia.com/universe",
            reviewer_attested=True,
        )


def test_builder_fails_closed_on_missing_disclosure_source_url(tmp_path):
    as_of = date.today()
    builder = EvidenceBundleBuilder(tmp_path / "bundle")
    master = _sample_scheme_master_dict(as_of)
    with pytest.raises(ValueError, match="Missing portfolio disclosure source URL"):
        builder.build_and_promote(
            as_of,
            scheme_master=master,
            scheme_master_source_bytes=json.dumps(master).encode("utf-8"),
            metrics_payload={"funds": [{"fund_id": "fund-1", "nav": "82.45"}]},
            metrics_source_bytes=b"metrics_1",
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
