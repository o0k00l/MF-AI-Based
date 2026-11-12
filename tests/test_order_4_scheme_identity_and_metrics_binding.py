"""
tests/test_order_4_scheme_identity_and_metrics_binding.py

Authoritative acceptance test suite for Order 4:
- Issue #16: Candidate universe discovery, exact scheme identity, security master normalization,
  and source-verified portfolio constituent look-through.
- Issue #84: Exact scheme identity tuple binding on metrics and aliases without fuzzy or name-based matching.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from core.math_engine import (
    _find_matching_metric_by_scheme_identity,
    compute_candidate_portfolio_overlap,
    HoldingItem,
)
from core.models import (
    AssetClass,
    PlanType,
)
from core.security_master import (
    canonicalize_security_label,
    normalize_constituent_weights,
    normalize_security_identifier,
)
from ingestion.portfolio_disclosure import validate_portfolio_disclosure
from core.portfolio_sip_controls import calculate_lookthrough_exposure
from core.eligibility import check_eligibility_gates


# =============================================================================
# 1. Issue #84 Acceptance: Exact Scheme Identity Tuple Binding for Metrics
# =============================================================================

def test_issue_84_exact_identity_tuple_match_succeeds():
    """Verify _find_matching_metric_by_scheme_identity matches exact (scheme_id, isin, amc, category, plan)."""
    metric = {
        "scheme_id": "SCH-HDFC-FLEXI",
        "isin": "INF179K01BE2",
        "amc_name": "HDFC Mutual Fund",
        "category": "Flexi Cap Fund",
        "plan_type": "DIRECT",
        "option_type": "GROWTH",
        "eq": 98.5,
        "debt": 1.5,
    }
    metrics_repo = {"SCH-HDFC-FLEXI": metric}

    identity = {
        "scheme_id": "SCH-HDFC-FLEXI",
        "isin": "INF179K01BE2",
        "amc_name": "HDFC Mutual Fund",
        "category": "Flexi Cap Fund",
        "plan_type": "DIRECT",
        "option_type": "GROWTH",
    }
    match = _find_matching_metric_by_scheme_identity(
        "SCH-HDFC-FLEXI", "INF179K01BE2", metrics_repo, identity=identity
    )
    assert match is not None
    assert match["scheme_id"] == "SCH-HDFC-FLEXI"
    assert match["isin"] == "INF179K01BE2"


def test_issue_84_rejects_conflicting_amc_name():
    """Verify conflicting AMC name in identity tuple strictly raises ValueError."""
    metric = {
        "scheme_id": "SCH-001",
        "isin": "INF001",
        "amc_name": "HDFC Mutual Fund",
        "category": "Large Cap",
        "plan_type": "DIRECT",
    }
    metrics_repo = {"SCH-001": metric}

    conflicting_identity = {
        "scheme_id": "SCH-001",
        "isin": "INF001",
        "amc_name": "ICICI Prudential Mutual Fund",  # Conflicting AMC
        "category": "Large Cap",
        "plan_type": "DIRECT",
    }
    with pytest.raises(ValueError, match="conflicts with verified scheme AMC"):
        _find_matching_metric_by_scheme_identity(
            "SCH-001", "INF001", metrics_repo, identity=conflicting_identity
        )


def test_issue_84_rejects_conflicting_sebi_category():
    """Verify conflicting SEBI category in identity tuple strictly raises ValueError."""
    metric = {
        "scheme_id": "SCH-002",
        "isin": "INF002",
        "amc_name": "SBI Mutual Fund",
        "category": "Large Cap",
        "plan_type": "DIRECT",
    }
    metrics_repo = {"SCH-002": metric}

    conflicting_identity = {
        "scheme_id": "SCH-002",
        "isin": "INF002",
        "amc_name": "SBI Mutual Fund",
        "category": "Mid Cap",  # Conflicting Category
        "plan_type": "DIRECT",
    }
    with pytest.raises(ValueError, match="conflicts with verified scheme.*Category"):
        _find_matching_metric_by_scheme_identity(
            "SCH-002", "INF002", metrics_repo, identity=conflicting_identity
        )


def test_issue_84_rejects_conflicting_plan_type():
    """Verify conflicting plan type (Regular vs Direct) strictly raises ValueError."""
    metric = {
        "scheme_id": "SCH-003",
        "isin": "INF003",
        "amc_name": "Nippon India Mutual Fund",
        "category": "Small Cap",
        "plan_type": "DIRECT",
    }
    metrics_repo = {"SCH-003": metric}

    conflicting_identity = {
        "scheme_id": "SCH-003",
        "isin": "INF003",
        "amc_name": "Nippon India Mutual Fund",
        "category": "Small Cap",
        "plan_type": "REGULAR",  # Conflicting Plan Type
    }
    with pytest.raises(ValueError, match="conflicts with verified scheme.*Plan"):
        _find_matching_metric_by_scheme_identity(
            "SCH-003", "INF003", metrics_repo, identity=conflicting_identity
        )


# =============================================================================
# 2. Issue #16 Acceptance: Security Master Normalization & Corporate Actions
# =============================================================================

def test_issue_16_canonicalize_security_label_strips_legal_suffixes():
    """Verify canonicalize_security_label standardizes corporate entity labels."""
    assert canonicalize_security_label("Reliance Industries Limited") == "RELIANCE INDUSTRIES"
    assert canonicalize_security_label("Infosys Ltd.") == "INFOSYS"
    assert canonicalize_security_label("HDFC Bank Ltd") == "HDFC BANK"
    assert canonicalize_security_label("Tata Consultancy Services Corp.") == "TATA CONSULTANCY SERVICES"
    assert canonicalize_security_label("ICICI Bank Ltd.") == "ICICI BANK"


def test_issue_16_normalize_security_identifier_resolves_aliases():
    """Verify normalize_security_identifier maps ISINs, tickers and aliases to canonical security."""
    security_master = {
        "INE002A01018": {"canonical_id": "RELIANCE", "name": "Reliance Industries Limited"},
        "RELIANCE": {"canonical_id": "RELIANCE", "name": "Reliance Industries Limited"},
        "RELIANCE IND": {"canonical_id": "RELIANCE", "name": "Reliance Industries Limited"},
        "INE009A01021": {"canonical_id": "INFY", "name": "Infosys Limited"},
        "INFOSYS": {"canonical_id": "INFY", "name": "Infosys Limited"},
    }

    # Resolve from ISIN
    canon_isin, ok_isin = normalize_security_identifier("INE002A01018", security_master)
    assert canon_isin == "RELIANCE"
    assert ok_isin is True

    # Resolve from alias name
    canon_alias, ok_alias = normalize_security_identifier("Reliance Ind", security_master)
    assert canon_alias == "RELIANCE"
    assert ok_alias is True

    # Strict mode rejects unresolvable security
    with pytest.raises(ValueError, match="Unresolved security identifier"):
        normalize_security_identifier("UNLISTED UNKNOWN ENTITY", security_master, strict=True)


def test_issue_16_normalize_constituent_weights_aggregates_aliases():
    """Verify duplicate alias entities are combined into single canonical holding weight."""
    security_master = {
        "RELIANCE": {
            "canonical_id": "RELIANCE",
            "aliases": ["Reliance Industries", "Reliance Ind", "RELIANCE INDUSTRIES"],
        },
        "TCS": {
            "canonical_id": "TCS",
            "aliases": ["Tata Consultancy Services", "TCS Limited"],
        },
    }
    raw_weights = {
        "Reliance Industries": 25.0,
        "Reliance Ind": 15.0,
        "TCS Limited": 60.0,
    }
    canon_weights, labels = normalize_constituent_weights(raw_weights, security_master=security_master)
    assert canon_weights["RELIANCE"] == 40.0
    assert canon_weights["TCS"] == 60.0


# =============================================================================
# 3. Issue #16 Acceptance: Portfolio Disclosure Look-Through & Coverage Gate
# =============================================================================

def test_issue_16_validate_portfolio_disclosure_success():
    """Verify valid AMC portfolio disclosure passes validation with security master binding."""
    as_of = date.today().isoformat()
    sec_master = {
        "RELIANCE": {"canonical_id": "RELIANCE", "aliases": ["Reliance Industries"]},
        "HDFC BANK": {"canonical_id": "HDFC BANK", "aliases": ["HDFC Bank"]},
    }
    payload = {
        "scheme_id": "SCHEME-101",
        "source_url": "https://amc.example.com/disclosures/sch-101.json",
        "effective_date": as_of,
        "reviewer_attested": True,
        "constituent_weights": {"Reliance Industries": 60.0, "HDFC Bank": 40.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    payload["source_document_sha256"] = hashlib.sha256(raw_bytes).hexdigest()

    result = validate_portfolio_disclosure(
        payload, raw_bytes, as_of=date.today(), max_age_days=45, security_master=sec_master
    )
    assert result["status"] == "VERIFIED"
    assert result["scheme_id"] == "SCHEME-101"
    assert result["constituent_weights"]["RELIANCE"] == 60.0
    assert result["constituent_weights"]["HDFC BANK"] == 40.0


def test_issue_16_validate_portfolio_disclosure_fails_closed_on_low_coverage():
    """Verify disclosure with constituent coverage below 99.5% fails closed."""
    as_of = date.today().isoformat()
    payload = {
        "scheme_id": "SCHEME-102",
        "source_url": "https://amc.example.com/disclosures/sch-102.json",
        "effective_date": as_of,
        "reviewer_attested": True,
        "constituent_weights": {"Stock A": 70.0},
        "constituent_weights_coverage_pct": 70.0,  # Below 99.5% threshold
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    payload["source_document_sha256"] = hashlib.sha256(raw_bytes).hexdigest()

    result = validate_portfolio_disclosure(payload, raw_bytes, as_of=date.today(), max_age_days=45)
    assert result["status"] == "MISSING"
    assert result["constituent_weights"] is None
    assert "99.5" in result["reason"]


def test_issue_16_calculate_lookthrough_exposure_exact_percentages():
    """Verify calculate_lookthrough_exposure computes accurate stock-level exposures."""
    holdings = [
        {
            "holding_value_inr": "60000.00",
            "coverage_pct": 100.0,
            "constituents": {"RELIANCE": 50.0, "TCS": 50.0},
        },
        {
            "holding_value_inr": "40000.00",
            "coverage_pct": 100.0,
            "constituents": {"RELIANCE": 25.0, "INFOSYS": 75.0},
        },
    ]
    # Total portfolio = 100,000 INR
    # Holding 1: RELIANCE = 30,000 (30%), TCS = 30,000 (30%)
    # Holding 2: RELIANCE = 10,000 (10%), INFOSYS = 30,000 (30%)
    # Combined RELIANCE = 40,000 (40%), TCS = 30,000 (30%), INFOSYS = 30,000 (30%)
    lookthrough = calculate_lookthrough_exposure(holdings, required_coverage_pct="99.5")
    assert lookthrough["status"] == "CALCULATED"
    assert Decimal(lookthrough["issuer_exposure_inr"]["RELIANCE"]) == Decimal("40000")
    assert Decimal(lookthrough["issuer_exposure_inr"]["TCS"]) == Decimal("30000")
    assert Decimal(lookthrough["issuer_exposure_inr"]["INFOSYS"]) == Decimal("30000")


# =============================================================================
# 4. Issue #16 & #84 Combined: Candidate Eligibility Gates
# =============================================================================

def test_order_4_candidate_eligibility_enforces_direct_and_provenance(tmp_path):
    """Verify candidate eligibility gate 10 rejects Regular plans and requires provenance."""
    source_bytes = b"%PDF-1.4 sample factsheet source bytes"
    (tmp_path / "factsheet.pdf").write_bytes(source_bytes)
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    as_of = date.today().isoformat()

    valid_direct_candidate = {
        "_evidence_root": tmp_path,
        "as_of_date": date.today(),
        "fund_id": "CAND-DIRECT-01",
        "scheme_id": "CAND-DIRECT-01",
        "fund_name": "Direct Growth Flexi Fund",
        "scheme_name": "Direct Growth Flexi Fund",
        "isin": "INF000000001",
        "amc_name": "Core AMC",
        "category": "Flexi Cap",
        "benchmark": "Nifty 500 TRI",
        "aum_crore": 5000.0,
        "aum_stable": True,
        "top10_concentration_pct": 30.0,
        "max_sector_concentration_pct": 20.0,
        "sharpe_3y": 0.8,
        "alpha_3y": 2.5,
        "downside_capture_ratio": 75.0,
        "upside_capture_ratio": 95.0,
        "manager_tenure_years": 4.5,
        "track_record_years": 5.0,
        "confidence_score": 0.95,
        "benchmark_type": "TRI",
        "is_direct": True,
        "plan": "Direct",
        "option": "Growth",
        "riskometer_score": 4,
        "mandate_suitable": True,
        "data_complete": True,
        "direct_plan_evidence": {
            "source_file": "factsheet.pdf",
            "source_document_sha256": source_sha,
            "source_url": "https://example.com/factsheet.pdf",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Direct Growth Flexi Fund",
            "scheme_id": "CAND-DIRECT-01",
            "isin": "INF000000001",
            "amc_name": "Core AMC",
            "reviewed_at": as_of,
        },
    }

    portfolio = [{"value": 100000.0, "amc_name": "Other AMC"}]
    res_direct = check_eligibility_gates(
        valid_direct_candidate, portfolio_holdings=portfolio, client_risk_tier_num=4, risk_ceiling=4
    )
    assert res_direct.direct_plan_gate is True
    assert res_direct.mandate_suitability_gate is True
    assert res_direct.passed is True

    # Regular plan must fail Gate 10 closed
    regular_candidate = dict(valid_direct_candidate)
    regular_candidate["is_direct"] = False
    regular_candidate["plan"] = "Regular"
    regular_candidate["direct_plan_evidence"] = dict(valid_direct_candidate["direct_plan_evidence"])
    regular_candidate["direct_plan_evidence"]["plan"] = "Regular"

    res_regular = check_eligibility_gates(
        regular_candidate, portfolio_holdings=portfolio, client_risk_tier_num=4, risk_ceiling=4
    )
    assert res_regular.passed is False
    assert res_regular.direct_plan_gate is False