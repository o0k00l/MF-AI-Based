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
    # Future dated transaction is excluded or rejected from active recency
    assert res["active_sip_count"] == 0


def test_detect_active_sips_identifies_valid_recurring_sip():
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-08-05", "type": "SIP", "description": "Systematic Investment Plan", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "description": "Systematic Investment Plan", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "Systematic Investment Plan", "amount": 5000.0},
    ]
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15")
    assert res["active_sip_count"] == 1
    assert res["total_monthly_sip"] == 5000.0
