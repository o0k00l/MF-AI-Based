from datetime import date
import io
import openpyxl
import pytest
from ingestion.cas_parser import (
    detect_active_sips_from_cas,
    parse_cas_xlsx,
    extract_mandate_evidence_from_transaction,
)


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

def test_detect_active_sips_rejects_reversals_and_cancellations():
    txs = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "description": "SIP installment", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "REVERSAL OF SIP DEBIT", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},
    ]
    res = detect_active_sips_from_cas(txs, as_of="2026-10-15")
    assert res["active_sip_count"] == 0
    assert res["total_monthly_sip"] == 0.0
    assert res["rejection_stats"]["rejected_reversals_or_conflicts"] == 1


def test_detect_active_sips_rejects_conflicting_transaction_types():
    txs = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "REDEMPTION", "description": "SIP Redemption", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SWITCH", "description": "Switch-out SIP", "amount": 5000.0, "mandate_id": "MND101", "mandate_status": "ACTIVE"},
    ]
    res = detect_active_sips_from_cas(txs, as_of="2026-10-15")
    assert res["active_sip_count"] == 0
    assert res["rejection_stats"]["rejected_reversals_or_conflicts"] == 2


def test_detect_active_sips_supports_registrar_descriptors():
    # CAMS and KFintech ACH descriptors
    txs = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "description": "CAMS SIP DEBIT", "amount": 5000.0, "mandate_id": "MND_CAMS", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "ACH DR - KFINTECH", "amount": 5000.0, "mandate_id": "MND_CAMS", "mandate_status": "ACTIVE"},
    ]
    res = detect_active_sips_from_cas(txs, as_of="2026-10-15")
    assert res["active_sip_count"] == 1
    assert res["total_monthly_sip"] == 5000.0


def test_detect_active_sips_multi_step_up_streak_consistency():
    txs = [
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-07-05", "type": "SIP", "description": "SIP installment", "amount": 4000.0, "mandate_id": "MND_STP", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-08-05", "type": "SIP", "description": "SIP installment", "amount": 5000.0, "mandate_id": "MND_STP", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-09-05", "type": "SIP", "description": "SIP step up", "amount": 6000.0, "mandate_id": "MND_STP", "mandate_status": "ACTIVE"},
        {"folio": "F1", "scheme": "Scheme A", "date": "2026-10-05", "type": "SIP", "description": "SIP installment", "amount": 6000.0, "mandate_id": "MND_STP", "mandate_status": "ACTIVE"},
    ]
    res = detect_active_sips_from_cas(txs, as_of="2026-10-15")
    assert res["active_sip_count"] == 1
    assert res["active_sips"][0]["streak_months"] == 4

def test_extract_mandate_evidence_distinguishes_found_from_confirmed():
    # 1. Mandate ID found without explicit active status keyword:
    # Must yield MANDATE_ID_FOUND with UNCONFIRMED status, NOT ACTIVE!
    desc1 = "SIP PUR - UMRN: NACH00000000012345"
    m1 = extract_mandate_evidence_from_transaction(desc1, "SIP")
    assert m1["mandate_id"] == "NACH00000000012345"
    assert m1["mandate_status"] == "UNCONFIRMED"
    assert m1["mandate_evidence_level"] == "MANDATE_ID_FOUND"
    assert m1["has_auth_mandate"] is False

    # 2. Mandate ID with explicit ACTIVE keyword:
    # Confirms active status and yields ACTIVE_MANDATE_CONFIRMED
    desc2 = "Systematic Investment - Mandate ID: MND7829104 - Status: ACTIVE"
    m2 = extract_mandate_evidence_from_transaction(desc2, "SIP")
    assert m2["mandate_id"] == "MND7829104"
    assert m2["mandate_status"] == "ACTIVE"
    assert m2["mandate_evidence_level"] == "ACTIVE_MANDATE_CONFIRMED"
    assert m2["has_auth_mandate"] is True
    assert m2["mandate_source"] == "REGISTRAR_CAS_REGN"

    # 3. Explicit UMRN with STATUS: LIVE
    desc3 = "SIP PUR - UMRN: NACH00000000099999 - STATUS: LIVE"
    m3 = extract_mandate_evidence_from_transaction(desc3, "SIP")
    assert m3["mandate_id"] == "NACH00000000099999"
    assert m3["mandate_status"] == "ACTIVE"
    assert m3["mandate_evidence_level"] == "ACTIVE_MANDATE_CONFIRMED"
    assert m3["has_auth_mandate"] is True

    # 4. Cancelled mandate description
    desc4 = "SIP DEBIT - UMRN: NACH00000000012345 - CANCELLED"
    m4 = extract_mandate_evidence_from_transaction(desc4, "SIP")
    assert m4["mandate_id"] == "NACH00000000012345"
    assert m4["mandate_status"] == "CANCELLED"
    assert m4["mandate_evidence_level"] == "CANCELLED_OR_INACTIVE"
    assert m4["has_auth_mandate"] is False

    # 5. Ordinary manual purchase without mandate
    desc5 = "PURCHASE - CHEQUE DEBIT"
    m5 = extract_mandate_evidence_from_transaction(desc5, "PURCHASE")
    assert m5["mandate_id"] is None
    assert m5["mandate_status"] == "UNKNOWN"
    assert m5["mandate_evidence_level"] == "NONE"
    assert m5["has_auth_mandate"] is False


def test_e2e_cas_workbook_extracts_and_authenticates_genuine_sips():
    # Build a genuine multi-scheme CAS Excel workbook
    wb = openpyxl.Workbook()
    
    # Portfolio Details sheet
    ws_port = wb.active
    ws_port.title = "Portfolio Details"
    ws_port.append(["Current Portfolio Value"])
    ws_port.append([30000.0])
    ws_port.append(["To Date", "15-Oct-2026"])
    ws_port.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws_port.append(["Scheme Genuine SIP", "FOLIO-1", 10000.0, 10000.0, 100.0])
    ws_port.append(["Scheme Unconfirmed Mandate", "FOLIO-2", 10000.0, 10000.0, 100.0])
    ws_port.append(["Scheme Manual Purchases", "FOLIO-3", 5000.0, 5000.0, 50.0])
    ws_port.append(["Scheme Cancelled SIP", "FOLIO-4", 5000.0, 5000.0, 50.0])

    # Transaction Details sheet
    ws_tx = wb.create_sheet("Transaction Details")
    ws_tx.append(["Scheme Name", "Date", "Amount", "Units", "Description"])
    
    # Scheme 1: Genuine Active SIP with explicit ACTIVE confirmation
    ws_tx.append(["Scheme Genuine SIP", "05-Sep-2026", 5000.0, 50.0, "SIP PUR - UMRN: NACH00000000012345 - STATUS: ACTIVE"])
    ws_tx.append(["Scheme Genuine SIP", "05-Oct-2026", 5000.0, 50.0, "SIP PUR - UMRN: NACH00000000012345 - STATUS: ACTIVE"])

    # Scheme 2: Mandate ID found but NO active confirmation (MANDATE_ID_FOUND, UNCONFIRMED)
    ws_tx.append(["Scheme Unconfirmed Mandate", "05-Sep-2026", 5000.0, 50.0, "SIP PUR - UMRN: NACH00000000077777"])
    ws_tx.append(["Scheme Unconfirmed Mandate", "05-Oct-2026", 5000.0, 50.0, "SIP PUR - UMRN: NACH00000000077777"])

    # Scheme 3: Two recurring manual purchases (NO mandate ID)
    ws_tx.append(["Scheme Manual Purchases", "05-Sep-2026", 2500.0, 25.0, "PURCHASE - CHEQUE DEBIT"])
    ws_tx.append(["Scheme Manual Purchases", "05-Oct-2026", 2500.0, 25.0, "PURCHASE - CHEQUE DEBIT"])

    # Scheme 4: Cancelled SIP
    ws_tx.append(["Scheme Cancelled SIP", "05-Sep-2026", 2500.0, 25.0, "SIP DEBIT - UMRN: NACH99999999999999 - CANCELLED"])
    ws_tx.append(["Scheme Cancelled SIP", "05-Oct-2026", 2500.0, 25.0, "SIP DEBIT - UMRN: NACH99999999999999 - CANCELLED"])

    buf = io.BytesIO()
    wb.save(buf)
    cas_bytes = buf.getvalue()

    # Step 1: Upstream CAS parsing extracts mandate evidence directly from workbook
    parsed = parse_cas_xlsx(cas_bytes)
    assert len(parsed["transactions"]) == 8
    
    # Verify transaction-level extracted metadata
    t_sip = [t for t in parsed["transactions"] if t["scheme"] == "Scheme Genuine SIP"]
    assert len(t_sip) == 2
    assert t_sip[0]["mandate_id"] == "NACH00000000012345"
    assert t_sip[0]["mandate_status"] == "ACTIVE"

    t_unconf = [t for t in parsed["transactions"] if t["scheme"] == "Scheme Unconfirmed Mandate"]
    assert len(t_unconf) == 2
    assert t_unconf[0]["mandate_id"] == "NACH00000000077777"
    assert t_unconf[0]["mandate_status"] == "UNCONFIRMED"

    t_man = [t for t in parsed["transactions"] if t["scheme"] == "Scheme Manual Purchases"]
    assert len(t_man) == 2
    assert t_man[0]["mandate_id"] is None
    assert t_man[0]["mandate_status"] == "UNKNOWN"

    t_can = [t for t in parsed["transactions"] if t["scheme"] == "Scheme Cancelled SIP"]
    assert len(t_can) == 2
    assert t_can[0]["mandate_status"] == "CANCELLED"

    # Step 2: Downstream active SIP discovery strictly requires active confirmation
    res = detect_active_sips_from_cas(parsed["transactions"], as_of="2026-10-15")
    
    # EXACTLY 1 active SIP (Scheme Genuine SIP with confirmed active status)
    assert res["active_sip_count"] == 1
    assert res["total_monthly_sip"] == 5000.0
    active_entry = res["active_sips"][0]
    assert active_entry["scheme"] == "Scheme Genuine SIP"
    assert active_entry["monthly_amount"] == 5000.0
    assert active_entry["confidence"] == "ACTIVE_MANDATE_VERIFIED"
    assert active_entry["evidence_level"] == "ACTIVE_MANDATE_CONFIRMED"
    assert active_entry["is_active_mandate"] is True

    # Scheme Unconfirmed Mandate must be in recurring_transaction_patterns with MANDATE_ID_FOUND, NOT active_sips
    unconf_patterns = [p for p in res["recurring_transaction_patterns"] if p["scheme"] == "Scheme Unconfirmed Mandate"]
    assert len(unconf_patterns) == 1
    assert unconf_patterns[0]["evidence_level"] == "MANDATE_ID_FOUND"
    assert unconf_patterns[0]["is_active_mandate"] is False

    # Cancelled SIP rejected in rejection stats
    assert res["rejection_stats"]["rejected_paused_or_cancelled"] >= 2


def test_e2e_cas_workbook_with_active_mandate_sheet_schedule():
    wb = openpyxl.Workbook()
    
    # Portfolio Details sheet
    ws_port = wb.active
    ws_port.title = "Portfolio Details"
    ws_port.append(["Current Portfolio Value"])
    ws_port.append([20000.0])
    ws_port.append(["To Date", "15-Oct-2026"])
    ws_port.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws_port.append(["Scheme Confirmed Schedule", "FOLIO-101", 10000.0, 10000.0, 100.0])
    ws_port.append(["Scheme Missing Status Schedule", "FOLIO-102", 10000.0, 10000.0, 100.0])

    # Active SIP Mandates schedule sheet
    ws_mand = wb.create_sheet("Active SIPs")
    ws_mand.append(["Scheme Name", "Folio No", "Mandate ID", "Amount", "Status"])
    # Row 1: Explicit ACTIVE status
    ws_mand.append(["Scheme Confirmed Schedule", "FOLIO-101", "MND-CONFIRMED-999", 5000.0, "ACTIVE"])
    # Row 2: Missing status (must NOT default to ACTIVE!)
    ws_mand.append(["Scheme Missing Status Schedule", "FOLIO-102", "MND-NOSTATUS-888", 5000.0, None])

    # Transaction Details sheet
    ws_tx = wb.create_sheet("Transaction Details")
    ws_tx.append(["Scheme Name", "Folio No.", "Date", "Amount", "Units", "Description"])
    ws_tx.append(["Scheme Confirmed Schedule", "FOLIO-101", "05-Sep-2026", 5000.0, 50.0, "NACH SIP Debit"])
    ws_tx.append(["Scheme Confirmed Schedule", "FOLIO-101", "05-Oct-2026", 5000.0, 50.0, "NACH SIP Debit"])

    ws_tx.append(["Scheme Missing Status Schedule", "FOLIO-102", "05-Sep-2026", 5000.0, 50.0, "NACH SIP Debit"])
    ws_tx.append(["Scheme Missing Status Schedule", "FOLIO-102", "05-Oct-2026", 5000.0, 50.0, "NACH SIP Debit"])

    buf = io.BytesIO()
    wb.save(buf)
    cas_bytes = buf.getvalue()

    # Step 1: Upstream CAS parsing parses both transactions and active mandate schedule
    parsed = parse_cas_xlsx(cas_bytes)
    assert len(parsed["active_mandates"]) == 2
    assert parsed["active_mandates"][0]["status"] == "ACTIVE"
    # Missing status in mandate sheet must be UNKNOWN, NOT ACTIVE!
    assert parsed["active_mandates"][1]["status"] == "UNKNOWN"

    # Step 2: detect_active_sips_from_cas binds transactions to the mandate schedule
    res = detect_active_sips_from_cas(
        parsed["transactions"],
        as_of="2026-10-15",
        active_mandates=parsed["active_mandates"]
    )
    # Only Scheme Confirmed Schedule is authenticated as active SIP
    assert res["active_sip_count"] == 1
    assert res["total_monthly_sip"] == 5000.0
    assert res["active_sips"][0]["scheme"] == "Scheme Confirmed Schedule"
    assert res["active_sips"][0]["confidence"] == "ACTIVE_MANDATE_VERIFIED"
    assert res["active_sips"][0]["evidence_level"] == "ACTIVE_MANDATE_CONFIRMED"
