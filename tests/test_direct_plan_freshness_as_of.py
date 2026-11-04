"""
Unit tests for deterministic as-of date binding in Direct-plan evidence freshness.
Addresses Issue #60: Evaluate Direct-plan evidence freshness against decision as-of date, not today.
"""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest
from core.eligibility import (
    _reviewed_direct_plan_evidence_status,
    check_eligibility_gates,
    load_candidate_universe,
)


def _make_fund_evidence(tmp_path: Path, reviewed_at_str: str) -> dict:
    source_bytes = b"AMC factsheet source bytes 2026"
    doc_path = tmp_path / "factsheet.pdf"
    doc_path.write_bytes(source_bytes)
    return {
        "_evidence_root": tmp_path,
        "fund_name": "Example Direct Fund",
        "scheme_id": "SCHEME-001",
        "isin": "INF000000001",
        "amc_name": "Example AMC",
        "plan": "Direct",
        "is_direct": True,
        "direct_plan_evidence": {
            "source_file": "factsheet.pdf",
            "source_document_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "source_url": "https://amc.example/factsheet.pdf",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Example Direct Fund",
            "scheme_id": "SCHEME-001",
            "isin": "INF000000001",
            "amc_name": "Example AMC",
            "reviewed_at": reviewed_at_str,
        },
    }


def test_direct_plan_evidence_freshness_binds_to_explicit_as_of_date(tmp_path):
    fund = _make_fund_evidence(tmp_path, "2026-01-15")

    # Within 180 days of 2026-01-15 -> Valid
    status_fresh = _reviewed_direct_plan_evidence_status(fund, as_of_date=date(2026, 3, 1))
    assert status_fresh == "REVIEWER_ATTESTED_HASH_MATCH"

    # Beyond 180 days (e.g. 2026-08-01 is ~198 days later) -> STALE
    status_stale = _reviewed_direct_plan_evidence_status(fund, as_of_date=date(2026, 8, 1))
    assert status_stale == "STALE"

    # Before reviewed_at (negative age) -> STALE
    status_future = _reviewed_direct_plan_evidence_status(fund, as_of_date=date(2025, 12, 1))
    assert status_future == "STALE"


def test_missing_as_of_date_returns_missing_as_of_date(tmp_path):
    fund = _make_fund_evidence(tmp_path, "2026-01-15")
    # Neither parameter nor fund dict provides as_of_date
    status = _reviewed_direct_plan_evidence_status(fund)
    assert status == "MISSING_AS_OF_DATE"


def test_as_of_date_can_be_provided_in_fund_data(tmp_path):
    fund = _make_fund_evidence(tmp_path, "2026-01-15")
    fund["as_of_date"] = date(2026, 3, 1)
    status = _reviewed_direct_plan_evidence_status(fund)
    assert status == "REVIEWER_ATTESTED_HASH_MATCH"


def test_historical_replay_is_completely_deterministic(tmp_path):
    fund = _make_fund_evidence(tmp_path, "2024-05-01")
    # Evaluating a 2024 decision using its 2024 as-of date succeeds regardless of current wall-clock
    status_replay = _reviewed_direct_plan_evidence_status(fund, as_of_date=date(2024, 6, 1))
    assert status_replay == "REVIEWER_ATTESTED_HASH_MATCH"

    # Replay evaluated against a date > 180 days later fails closed
    status_replay_stale = _reviewed_direct_plan_evidence_status(fund, as_of_date=date(2024, 12, 1))
    assert status_replay_stale == "STALE"


def test_check_eligibility_gates_propagates_as_of_date(tmp_path):
    fund = _make_fund_evidence(tmp_path, "2026-01-15")
    fund["category"] = "Large Cap"
    fund["aum_crore"] = 5000.0
    fund["top10_concentration_pct"] = 40.0
    fund["sector_concentration_pct"] = 25.0
    fund["sharpe_ratio"] = 0.8
    fund["alpha_3y"] = 2.5
    fund["downside_capture_ratio"] = 80.0
    fund["upside_capture_ratio"] = 95.0
    fund["riskometer_score"] = 4
    fund["benchmark_tri"] = "NIFTY 50 TRI"
    fund["data_confidence_score"] = 0.95
    fund["manager_tenure_years"] = 4.0

    # With fresh as_of_date
    res_fresh = check_eligibility_gates(
        fund,
        portfolio_holdings=[{"amc_name": "Other AMC", "value": 10000.0}],
        client_risk_tier_num=4,
        as_of_date=date(2026, 3, 1),
    )
    assert res_fresh.direct_plan_gate is True

    # With stale as_of_date
    res_stale = check_eligibility_gates(
        fund,
        portfolio_holdings=[{"amc_name": "Other AMC", "value": 10000.0}],
        client_risk_tier_num=4,
        as_of_date=date(2026, 9, 1),
    )
    assert res_stale.direct_plan_gate is False



def test_eligibility_does_not_substitute_wall_clock_when_decision_date_missing(tmp_path):
    fund = _make_fund_evidence(tmp_path, "2026-01-15")
    fund.update({
        "category": "Large Cap",
        "aum_crore": 5000.0,
        "top10_concentration_pct": 40.0,
        "sector_concentration_pct": 25.0,
        "sharpe_ratio": 0.8,
        "alpha_3y": 2.5,
        "downside_capture_ratio": 80.0,
        "upside_capture_ratio": 95.0,
        "riskometer_score": 4,
        "benchmark_tri": "NIFTY 50 TRI",
        "data_confidence_score": 0.95,
        "manager_tenure_years": 4.0,
    })
    result = check_eligibility_gates(
        fund,
        portfolio_holdings=[{"amc_name": "Other AMC", "value": 10000.0}],
        client_risk_tier_num=4,
    )
    assert result.direct_plan_gate is False
    assert any("Direct Plan Mandate" in reason for reason in result.failed_gates)
