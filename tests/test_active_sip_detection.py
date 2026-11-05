from datetime import date
import pytest
from ingestion.cas_parser import detect_active_sips_from_cas


def test_detect_active_sips_rejects_ordinary_purchases():
    # Ordinary purchases without SIP keywords/mandate descriptions
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-08-01", "type": "PURCHASE", "description": "Lump sum purchase", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-01", "type": "PURCHASE", "description": "Lump sum purchase", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-01", "type": "PURCHASE", "description": "Lump sum purchase", "amount": 5000.0},
    ]
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15")
    assert res["active_sip_count"] == 0
    assert res["total_monthly_sip"] == 0.0


def test_detect_active_sips_rejects_future_dated_transactions():
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-01", "type": "SIP", "description": "SIP installment", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-11-01", "type": "SIP", "description": "SIP installment", "amount": 5000.0},
    ]
    # as_of is 2026-10-15, so 2026-11-01 is in the future relative to as_of
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15")
    assert res["active_sip_count"] == 0
    assert res["rejection_stats"]["rejected_future_dated"] >= 1


def test_detect_active_sips_identifies_valid_recurring_sip():
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-08-05", "type": "SIP", "description": "Systematic Investment Plan", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "description": "Systematic Investment Plan", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "Systematic Investment Plan", "amount": 5000.0},
    ]
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15")
    assert res["active_sip_count"] == 1
    assert res["total_monthly_sip"] == 5000.0
    assert res["history_coverage"]["history_status"] == "SUFFICIENT"


def test_detect_active_sips_enforces_bounded_history_window():
    # Transactions older than max_history_days (e.g. 60 days) are excluded
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-06-01", "type": "SIP", "description": "SIP installment", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-07-01", "type": "SIP", "description": "SIP installment", "amount": 5000.0},
    ]
    # as_of is 2026-10-15, max_history_days is 60 (window reaches back to 2026-08-16)
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15", max_history_days=60)
    assert res["active_sip_count"] == 0
    assert res["rejection_stats"]["rejected_outside_history_window"] == 2
    assert res["history_coverage"]["history_status"] == "INSUFFICIENT"


def test_detect_active_sips_requires_continuous_mandate_classification():
    # If one transaction has SIP keyword but the other is a manual purchase, reported as UNVERIFIED pattern
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "PURCHASE", "description": "Cheque purchase", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "SIP installment", "amount": 5000.0},
    ]
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15")
    assert res["active_sip_count"] == 0
    assert res["unverified_count"] == 1
    assert res["unverified_patterns"][0]["confidence"] == "UNVERIFIED"
