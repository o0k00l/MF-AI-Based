from datetime import date
import pytest
from ingestion.cas_parser import detect_active_sips_from_cas


def test_detect_active_sips_rejects_ordinary_purchases():
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
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-08-05", "type": "SIP", "description": "Systematic Investment Plan", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "description": "Systematic Investment Plan", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "Systematic Investment Plan", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},
    ]
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15")
    assert res["active_sip_count"] == 1
    assert res["total_monthly_sip"] == 5000.0
    assert res["history_coverage"]["history_status"] == "SUFFICIENT"


def test_detect_active_sips_enforces_bounded_history_window():
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-06-01", "type": "SIP", "description": "SIP installment", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-07-01", "type": "SIP", "description": "SIP installment", "amount": 5000.0},
    ]
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15", max_history_days=60)
    assert res["active_sip_count"] == 0
    assert res["rejection_stats"]["rejected_outside_history_window"] == 2
    assert res["history_coverage"]["history_status"] == "INSUFFICIENT"


def test_detect_active_sips_requires_continuous_mandate_classification():
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "PURCHASE", "description": "Cheque purchase", "amount": 5000.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "SIP installment", "amount": 5000.0},
    ]
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15")
    assert res["active_sip_count"] == 0
    assert res["unverified_count"] == 1
    assert res["unverified_patterns"][0]["confidence"] == "UNVERIFIED"


def test_detect_active_sips_requires_explicit_as_of():
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "description": "SIP installment", "amount": 5000.0, "mandate_id": "MND102", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "SIP installment", "amount": 5000.0, "mandate_id": "MND102", "mandate_status": "ACTIVE"},
    ]
    with pytest.raises(ValueError, match="Explicit 'as_of' date is required"):
        detect_active_sips_from_cas(transactions, as_of=None, require_explicit_as_of=True)

    # Optional derivation allowed when explicitly opting out
    res = detect_active_sips_from_cas(transactions, as_of=None, require_explicit_as_of=False)
    assert res["as_of_reference_mode"] == "DERIVED_MAX_TRANSACTION_DATE"
    assert res["active_sip_count"] == 1


def test_detect_active_sips_exhaustive_rejection_accounting():
    transactions = [
        # 1. Missing amount
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-01", "type": "SIP", "amount": None},
        # 2. Non-positive amount
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-02", "type": "SIP", "amount": 0.0},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-03", "type": "SIP", "amount": -500.0},
        # 3. Missing date
        {"folio": "F1", "scheme": "Scheme A", "date": None, "type": "SIP", "amount": 1000.0},
        # 4. Malformed date
        {"folio": "F1", "scheme": "Scheme A", "date": "invalid-date", "type": "SIP", "amount": 1000.0},
        # 5. Future dated relative to as_of (2026-10-15)
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-11-01", "type": "SIP", "amount": 1000.0},
        # 6. Non-SIP transaction
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-10", "type": "PURCHASE", "description": "Lump sum", "amount": 5000.0},
    ]
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15")
    stats = res["rejection_stats"]
    assert stats["rejected_missing_or_non_positive_amount"] == 3
    assert stats["rejected_missing_date"] == 1
    assert stats["rejected_malformed_date"] == 1
    assert stats["rejected_future_dated"] == 1
    assert stats["rejected_non_sip"] == 1
    assert stats["total_rejected"] == 7
    assert len(stats["rejected_details"]) == 7


def test_detect_active_sips_mixed_step_up_streak_consistency():
    transactions = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-07-05", "type": "SIP", "description": "SIP installment", "amount": 5000.0, "mandate_id": "MND103", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-08-05", "type": "SIP", "description": "SIP installment", "amount": 5000.0, "mandate_id": "MND103", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "description": "SIP step up", "amount": 6000.0, "mandate_id": "MND103", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "SIP installment", "amount": 6000.0, "mandate_id": "MND103", "mandate_status": "ACTIVE"},
    ]
    res = detect_active_sips_from_cas(transactions, as_of="2026-10-15")
    assert res["active_sip_count"] == 1
    sip = res["active_sips"][0]
    assert sip["monthly_amount"] == 6000.0
    # Consistent step-up streak across all 4 installments
    assert sip["streak_months"] == 4


def test_detect_active_sips_mandate_verified_vs_transaction_text_verified():
    # Mandate verified: explicit mandate ID / active status
    auth_mandate_txs = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "description": "SIP debit", "amount": 5000.0, "mandate_id": "MND123", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "SIP debit", "amount": 5000.0, "mandate_id": "MND123", "mandate_status": "ACTIVE"},
    ]
    res1 = detect_active_sips_from_cas(auth_mandate_txs, as_of="2026-10-15")
    assert res1["active_sip_count"] == 1
    assert res1["active_sips"][0]["confidence"] in ("ACTIVE_MANDATE_VERIFIED", "MANDATE_VERIFIED")
    assert res1["active_sips"][0]["evidence_level"] == "MANDATE"

    # Transaction text pattern: keyword in description, no explicit mandate ID
    # Must NOT be reported as active mandate; goes to recurring_transaction_patterns with 0 active monthly sip
    text_verified_txs = [
        {"folio": "F2", "scheme": "Scheme B", "date": "2026-09-05", "type": "SIP", "description": "NACH SIP Debit", "amount": 3000.0},
        {"folio": "F2", "scheme": "Scheme B", "date": "2026-10-05", "type": "SIP", "description": "NACH SIP Debit", "amount": 3000.0},
    ]
    res2 = detect_active_sips_from_cas(text_verified_txs, as_of="2026-10-15")
    assert res2["active_sip_count"] == 0
    assert res2["total_monthly_sip"] == 0.0
    assert res2["recurring_transaction_pattern_count"] == 1
    pattern = res2["recurring_transaction_patterns"][0]
    assert pattern["confidence"] in ("SIP_LABELLED_TRANSACTION_PATTERN", "TRANSACTION_TEXT_VERIFIED")
    assert pattern["evidence_level"] == "TRANSACTION_TEXT"
    assert pattern["is_active_mandate"] is False


def test_detect_active_sips_rejects_paused_or_cancelled_mandates():
    txs = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "amount": 5000.0, "mandate_id": "MND999", "mandate_status": "PAUSED"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "amount": 5000.0, "mandate_id": "MND999", "mandate_status": "CANCELLED"},
    ]
    res = detect_active_sips_from_cas(txs, as_of="2026-10-15")
    assert res["active_sip_count"] == 0
    assert res["rejection_stats"]["rejected_paused_or_cancelled"] == 2


def test_detect_active_sips_rejects_duplicate_transactions():
    txs = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},  # duplicate
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},
    ]
    res = detect_active_sips_from_cas(txs, as_of="2026-10-15")
    assert res["active_sip_count"] == 1
    assert res["rejection_stats"]["rejected_duplicate"] == 1
