"""Tests for Issue #23: Signed Portfolio Reconciliation Report and Denominator Integrity.

Acceptance criteria:
- A signed-off portfolio reconciliation report shows included/excluded assets, valuation date,
  unmatched items and arithmetic reconciliation.
- No SIP amount is routed against an incomplete denominator or unverified perimeter.
- Fails closed when unmatched items are present or when sign-off attestation is missing/invalid.
- Computes reproducible RFC 8785 (JCS) SHA-256 cryptographic digest over report contents.
"""
from __future__ import annotations

import pytest
from decimal import Decimal
from core.portfolio_sip_controls import (
    reconcile_total_portfolio,
    generate_signed_portfolio_reconciliation_report,
    PortfolioInputError,
    SUPPORTED_PORTFOLIO_PERIMETER,
)


def _valid_asset(asset_id: str = "A1", value: str = "150000.00", asset_class: str = "cas_mutual_fund"):
    return {
        "asset_id": asset_id,
        "asset_class": asset_class,
        "value_inr": value,
        "source_ref": "sha256:abcd1234ef",
        "owner_scope": "primary_investor",
        "as_of_date": "2026-11-01",
    }


def _valid_sign_off():
    return {
        "attested_by": "ADV-9921",
        "attestation_timestamp_utc": "2026-11-01T10:00:00Z",
        "attestation_statement": (
            "I hereby attest that the declared perimeter includes all investible holdings, "
            "bank cash, deposits and debt instruments without undeclared external assets."
        ),
        "signature_ref": "sig:ed25519:test_advisor_signature",
    }


def test_signed_portfolio_reconciliation_report_success():
    assets = [
        _valid_asset("A1", "500000.00", "cas_mutual_fund"),
        _valid_asset("A2", "200000.00", "bank_cash"),
        _valid_asset("A3", "300000.00", "deposit"),
    ]
    excluded = [
        {"asset_id": "EX1", "asset_class": "excluded_asset", "reason": "residential_property"}
    ]
    sign_off = _valid_sign_off()

    report = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=True,
        as_of_date="2026-11-01",
        sign_off=sign_off,
        excluded_assets=excluded,
    )

    assert report["status"] == "RECONCILED"
    assert report["is_approved_for_sip_routing"] is True
    assert report["total_value_inr"] == "1000000.00"
    assert report["included_count"] == 3
    assert report["excluded_count"] == 1
    assert report["unmatched_count"] == 0
    assert report["by_asset_class_inr"]["cas_mutual_fund"] == "500000.00"
    assert report["by_asset_class_inr"]["bank_cash"] == "200000.00"
    assert report["by_asset_class_inr"]["deposit"] == "300000.00"
    assert "report_sha256" in report
    assert len(report["report_sha256"]) == 64
    assert report["sign_off"]["attested_by"] == "ADV-9921"


def test_reconciliation_fails_closed_when_perimeter_not_complete():
    assets = [_valid_asset("A1", "100000.00", "cas_mutual_fund")]
    report = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=False,
        as_of_date="2026-11-01",
        sign_off=_valid_sign_off(),
    )

    assert report["status"] == "HOLD"
    assert report["reason"] == "PORTFOLIO_PERIMETER_NOT_ATTESTED"
    assert report["is_approved_for_sip_routing"] is False
    assert report["total_value_inr"] is None


def test_reconciliation_fails_closed_when_unmatched_items_present():
    assets = [_valid_asset("A1", "100000.00", "cas_mutual_fund")]
    unmatched = [
        {"item_id": "U1", "description": "Pending purchase in folio 123456", "reason": "UNCONFIRMED_TRADE"}
    ]
    report = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=True,
        as_of_date="2026-11-01",
        sign_off=_valid_sign_off(),
        unmatched_items=unmatched,
    )

    assert report["status"] == "HOLD"
    assert report["reason"] == "UNMATCHED_PORTFOLIO_ITEMS_PRESENT"
    assert report["is_approved_for_sip_routing"] is False
    assert report["unmatched_count"] == 1


def test_reconciliation_fails_closed_when_sign_off_missing_or_invalid():
    assets = [_valid_asset("A1", "100000.00", "cas_mutual_fund")]

    # Missing sign_off
    report_none = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=True,
        as_of_date="2026-11-01",
        sign_off=None,
    )
    assert report_none["status"] == "HOLD"
    assert report_none["reason"] == "SIGN_OFF_ATTESTATION_REQUIRED"
    assert report_none["is_approved_for_sip_routing"] is False

    # Invalid empty sign_off fields
    invalid_sign_off = {
        "attested_by": "",
        "attestation_timestamp_utc": "invalid",
        "attestation_statement": "",
    }
    report_invalid = generate_signed_portfolio_reconciliation_report(
        assets,
        perimeter_complete=True,
        as_of_date="2026-11-01",
        sign_off=invalid_sign_off,
    )
    assert report_invalid["status"] == "HOLD"
    assert report_invalid["reason"] == "SIGN_OFF_ATTESTATION_INVALID"
    assert report_invalid["is_approved_for_sip_routing"] is False


def test_reconciliation_rejects_unsupported_asset_class():
    unsupported_asset = _valid_asset("A1", "100000.00", "crypto_currency")
    with pytest.raises(PortfolioInputError, match="unsupported asset class 'crypto_currency'"):
        reconcile_total_portfolio([unsupported_asset], perimeter_complete=True, as_of_date="2026-11-01")


def test_reconciliation_rejects_negative_value():
    negative_asset = _valid_asset("A1", "-5000.00", "cas_mutual_fund")
    with pytest.raises(PortfolioInputError, match="asset value cannot be negative"):
        reconcile_total_portfolio([negative_asset], perimeter_complete=True, as_of_date="2026-11-01")


def test_reconciliation_rejects_duplicate_asset_id():
    a1 = _valid_asset("A1", "50000.00", "cas_mutual_fund")
    a2 = _valid_asset("A1", "60000.00", "bank_cash")
    with pytest.raises(PortfolioInputError, match="duplicate asset_id"):
        reconcile_total_portfolio([a1, a2], perimeter_complete=True, as_of_date="2026-11-01")

