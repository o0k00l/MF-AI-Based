"""Regression tests for the #106 mandate-authentication boundary."""

from ingestion.cas_parser import extract_mandate_evidence_from_transaction


def test_transaction_text_umrn_and_active_label_never_authenticate_mandate():
    evidence = extract_mandate_evidence_from_transaction(
        "SIP UMRN ABCDEFGHIJKL STATUS ACTIVE",
        tx_type="SIP",
    )

    assert evidence["mandate_id"] == "ABCDEFGHIJKL"
    assert evidence["mandate_status"] == "ACTIVE"
    assert evidence["mandate_evidence_level"] == "TRANSACTION_TEXT_ACTIVE_STATUS"
    assert evidence["has_auth_mandate"] is False


def test_caller_supplied_mandate_id_and_active_status_are_still_unverified():
    evidence = extract_mandate_evidence_from_transaction(
        "SIP instalment",
        tx_type="SIP",
        extra_fields={
            "mandate_id": "REG-12345",
            "mandate_status": "ACTIVE",
            "mandate_source": "REGISTRAR_CAS_MANDATE_TABLE",
        },
    )

    assert evidence["mandate_id"] == "REG-12345"
    assert evidence["mandate_status"] == "ACTIVE"
    assert evidence["has_auth_mandate"] is False


def test_inactive_mandate_text_remains_inactive_and_unverified():
    evidence = extract_mandate_evidence_from_transaction(
        "SIP UMRN ABCDEFGHIJKL STATUS CANCELLED",
        tx_type="SIP",
    )

    assert evidence["mandate_status"] == "CANCELLED"
    assert evidence["mandate_evidence_level"] == "CANCELLED_OR_INACTIVE"
    assert evidence["has_auth_mandate"] is False
