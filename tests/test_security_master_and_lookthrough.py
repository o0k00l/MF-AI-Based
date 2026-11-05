import hashlib
import json
from datetime import date
from types import SimpleNamespace
import pytest

from core.security_master import (
    canonicalize_security_label,
    normalize_security_identifier,
    normalize_constituent_weights,
)
from ingestion.portfolio_disclosure import validate_portfolio_disclosure
from core.math_engine import compute_candidate_portfolio_overlap, HoldingItem
from core.portfolio_sip_controls import calculate_lookthrough_exposure


def test_canonicalize_security_label():
    assert canonicalize_security_label("Reliance Industries Limited") == "RELIANCE INDUSTRIES"
    assert canonicalize_security_label("Infosys Ltd.") == "INFOSYS"
    assert canonicalize_security_label("HDFC Bank Ltd") == "HDFC BANK"
    assert canonicalize_security_label("TATA CONSULTANCY SERVICES CORP.") == "TATA CONSULTANCY SERVICES"


def test_normalize_security_identifier_with_master():
    sec_master = {
        "INE002A01018": {"canonical_id": "RELIANCE", "name": "Reliance Industries Limited"},
        "RELIANCE": {"canonical_id": "RELIANCE", "name": "Reliance Industries Limited"},
        "RELIANCE IND": {"canonical_id": "RELIANCE", "name": "Reliance Industries Limited"},
        "INFOSYS": {"canonical_id": "INFY", "name": "Infosys Limited"},
    }

    canon, resolved = normalize_security_identifier("Reliance Ind", sec_master)
    assert canon == "RELIANCE"
    assert resolved is True

    canon_isin, resolved_isin = normalize_security_identifier("INE002A01018", sec_master)
    assert canon_isin == "RELIANCE"
    assert resolved_isin is True

    # Strict mode rejects unresolvable identifier
    with pytest.raises(ValueError, match="Unresolved security identifier"):
        normalize_security_identifier("UNKNOWN CORP XYZ", sec_master, strict=True)


def test_normalize_constituent_weights_aggregates_duplicates():
    sec_master = {
        "RELIANCE": "RELIANCE",
        "RELIANCE IND": "RELIANCE",
        "TCS": "TCS",
    }
    raw_weights = {
        "Reliance": 30.0,
        "Reliance Ind": 10.0,
        "TCS": 60.0,
    }
    canon_weights, original_labels = normalize_constituent_weights(raw_weights, security_master=sec_master)
    assert canon_weights["RELIANCE"] == 40.0
    assert canon_weights["TCS"] == 60.0
    assert "RELIANCE" in original_labels


def test_validate_portfolio_disclosure_with_security_master():
    as_of = date.today()
    sec_master = {
        "RELIANCE": "RELIANCE",
        "TCS": "TCS",
    }
    payload = {
        "scheme_id": "scheme-1",
        "source_url": "https://amfiindia.com/disclosures/scheme-1",
        "effective_date": as_of.isoformat(),
        "reviewer_attested": True,
        "constituent_weights": {"Reliance Limited": 50.0, "TCS Ltd": 50.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    payload["source_document_sha256"] = hashlib.sha256(raw_bytes).hexdigest()

    # Pass security master
    res = validate_portfolio_disclosure(
        payload, raw_bytes, as_of=as_of, max_age_days=45, security_master=sec_master
    )
    assert res["status"] == "VERIFIED"
    assert res["constituent_weights"]["RELIANCE"] == 50.0
    assert res["constituent_weights"]["TCS"] == 50.0
    assert res["original_constituent_labels"]["RELIANCE"] == "Reliance Limited"


def test_validate_portfolio_disclosure_strict_rejects_unresolved_security():
    as_of = date.today()
    sec_master = {
        "RELIANCE": "RELIANCE",
    }
    payload = {
        "scheme_id": "scheme-1",
        "source_url": "https://amfiindia.com/disclosures/scheme-1",
        "effective_date": as_of.isoformat(),
        "reviewer_attested": True,
        "constituent_weights": {"Reliance": 50.0, "UNKNOWN NON_SECURITY": 50.0},
        "constituent_weights_coverage_pct": 100.0,
    }
    raw_bytes = json.dumps(payload).encode("utf-8")
    payload["source_document_sha256"] = hashlib.sha256(raw_bytes).hexdigest()

    # Strict mode requires all constituents in security master
    res = validate_portfolio_disclosure(
        payload, raw_bytes, as_of=as_of, max_age_days=45,
        security_master=sec_master, require_security_master=True
    )
    assert res["status"] == "MISSING"
    assert "Unresolved security identifier" in res["reason"]


def test_compute_candidate_portfolio_overlap_resolves_aliases():
    sec_master = {
        "RELIANCE": "RELIANCE",
        "RELIANCE IND": "RELIANCE",
        "RELIANCE INDUSTRIES LIMITED": "RELIANCE",
        "TCS": "TCS",
        "TATA CONSULTANCY SERVICES": "TCS",
    }

    # Holding reports "Reliance Ind"
    holding = HoldingItem(
        fund_id="fund-1",
        scheme_id="scheme-1",
        scheme_name="Existing Scheme",
        current_value_inr=100000.0,
        invested_value_inr=90000.0,
        units=1000.0,
        nav=100.0,
        equity_pct=100.0,
        debt_pct=0.0,
        cash_pct=0.0,
        constituent_weights={"Reliance Ind": 50.0, "TCS": 50.0},
        constituent_weights_coverage_pct=100.0,
    )

    # Candidate reports "Reliance Industries Limited"
    candidate = {
        "fund_id": "cand-1",
        "constituent_weights": {"Reliance Industries Limited": 50.0, "TATA CONSULTANCY SERVICES": 50.0},
        "constituent_weights_coverage_pct": 100.0,
    }

    # Overlap calculation with security master resolves aliases and correctly measures 100% overlap
    overlap = compute_candidate_portfolio_overlap(
        candidate, holdings=[holding], security_master=sec_master
    )
    assert overlap == 100.0


def test_calculate_lookthrough_exposure_normalizes_issuers():
    sec_master = {
        "INFY": "INFOSYS",
        "INFOSYS": "INFOSYS",
        "INFOSYS LIMITED": "INFOSYS",
    }
    holdings = [
        {
            "holding_value_inr": "50000",
            "coverage_pct": "100",
            "constituents": {"Infosys Limited": "100"},
        },
        {
            "holding_value_inr": "50000",
            "coverage_pct": "100",
            "constituents": {"INFY": "100"},
        },
    ]
    res = calculate_lookthrough_exposure(
        holdings, required_coverage_pct=100, security_master=sec_master
    )
    assert res["status"] == "CALCULATED"
    # Both holdings aggregate under the canonical issuer "INFOSYS"
    assert "INFOSYS" in res["issuer_exposure_inr"]
    assert float(res["issuer_exposure_inr"]["INFOSYS"]) == 100000.0
