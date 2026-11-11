"""
tests/test_issue_26_security_master_cross_amc.py - Acceptance tests for Issue #26.
Reconcile constituent security-master across AMC aliases, corporate actions, and ticker variations.
"""
from __future__ import annotations

from decimal import Decimal
import pytest
from core.security_master import (
    canonicalize_security_label,
    normalize_security_identifier,
    normalize_constituent_weights,
    load_security_master,
)
from core.portfolio_sip_controls import calculate_lookthrough_exposure


def test_canonicalize_security_label_strips_corporate_action_annotations():
    assert canonicalize_security_label("Reliance Industries Limited - PP") == "RELIANCE INDUSTRIES"
    assert canonicalize_security_label("HDFC Ltd (Merged with HDFC Bank)") == "HDFC"
    assert canonicalize_security_label("Tata Motors Limited - DVR") == "TATA MOTORS"
    assert canonicalize_security_label("L&T Limited") == "L AND T"
    assert canonicalize_security_label("Bharti Airtel Ltd - Partly Paid") == "BHARTI AIRTEL"


def test_normalize_security_identifier_resolves_corporate_actions():
    sec_master = {
        "securities": {
            "HDFCBANK": {"canonical_id": "HDFCBANK", "name": "HDFC Bank Limited"},
            "RELIANCE": {"canonical_id": "RELIANCE", "name": "Reliance Industries Limited"},
        },
        "corporate_actions": {
            "HDFC": {"action": "MERGER", "successor_canonical_id": "HDFCBANK"},
            "HDFC LIMITED": {"action": "MERGER", "successor_canonical_id": "HDFCBANK"},
        },
    }

    # HDFC Ltd resolves to successor HDFCBANK due to corporate action merger
    canon, resolved = normalize_security_identifier("HDFC Limited", sec_master)
    assert canon == "HDFCBANK"
    assert resolved is True

    # Annotation-stripped resolution
    canon_merged, resolved_merged = normalize_security_identifier("HDFC (Merged into HDFC Bank)", sec_master)
    assert canon_merged == "HDFCBANK"
    assert resolved_merged is True


def test_normalize_security_identifier_resolves_cross_amc_aliases():
    sec_master = {
        "securities": {
            "LT": {"canonical_id": "LT", "name": "Larsen & Toubro Limited"},
            "TCS": {"canonical_id": "TCS", "name": "Tata Consultancy Services Limited"},
        },
        "amc_aliases": {
            "L AND T": "LT",
            "LARSEN AND TOUBRO": "LT",
            "TATA CONSULTANCY SERVICES": "TCS",
        },
    }

    canon_lt, res_lt = normalize_security_identifier("L&T Ltd.", sec_master)
    assert canon_lt == "LT"
    assert res_lt is True

    canon_tcs, res_tcs = normalize_security_identifier("Tata Consultancy Services Corp.", sec_master)
    assert canon_tcs == "TCS"
    assert res_tcs is True


def test_normalize_constituent_weights_aggregates_across_amc_aliases_and_mergers():
    sec_master = {
        "securities": {
            "HDFCBANK": {"canonical_id": "HDFCBANK", "name": "HDFC Bank Limited"},
            "RELIANCE": {
                "canonical_id": "RELIANCE",
                "name": "Reliance Industries Limited",
                "aliases": ["RELIANCE INDUSTRIES", "RIL"],
            },
        },
        "corporate_actions": {
            "HDFC": {"action": "MERGER", "successor_canonical_id": "HDFCBANK"},
            "HDFC LIMITED": {"action": "MERGER", "successor_canonical_id": "HDFCBANK"},
        },
        "amc_aliases": {
            "RELIANCE IND": "RELIANCE",
        },
    }

    # Disclosure holding both pre-merger entity and post-merger entity
    raw_weights = {
        "HDFC Bank Ltd": 30.0,
        "HDFC Limited": 20.0,
        "Reliance Industries - PP": 15.0,
        "Reliance Ind.": 35.0,
    }

    canon_weights, labels = normalize_constituent_weights(raw_weights, security_master=sec_master)

    # Both HDFC entries merged into HDFCBANK: 30 + 20 = 50.0%
    assert canon_weights["HDFCBANK"] == 50.0
    # Both Reliance entries merged into RELIANCE: 15 + 35 = 50.0%
    assert canon_weights["RELIANCE"] == 50.0


def test_lookthrough_exposure_aggregates_corporate_actions():
    master = load_security_master()

    holdings = [
        {
            "holding_value_inr": "100000",
            "coverage_pct": "100",
            "constituents": {
                "HDFC Bank": "60.0",
                "HDFC Limited": "40.0",
            },
        }
    ]

    res = calculate_lookthrough_exposure(
        holdings=holdings,
        required_coverage_pct="85.0",
        security_master=master,
    )

    assert res["status"] == "CALCULATED"
    # Both HDFC Bank and HDFC Limited aggregate under canonical HDFCBANK
    assert "HDFCBANK" in res["issuer_exposure_inr"]
    assert Decimal(res["issuer_exposure_inr"]["HDFCBANK"]) == Decimal("100000.00")
