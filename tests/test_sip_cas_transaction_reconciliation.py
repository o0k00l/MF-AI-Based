"""Fail-closed CAS/transaction reconciliation tests for portfolio-aware SIP."""
import json
from types import SimpleNamespace

from core.math_engine import reconcile_cas_holdings_with_transactions


def holding(scheme, units, folio="F1"):
    return SimpleNamespace(scheme=scheme, units=units, folio=folio)


def write_transactions(tmp_path, rows):
    path = tmp_path / "transactions.json"
    path.write_text(json.dumps({"transactions": rows}), encoding="utf-8")
    return path


def txn(scheme, units, kind="PURCHASE"):
    return {"scheme": scheme, "units": units, "type": kind}


def test_reconciliation_aggregates_same_scheme_across_multiple_folios(tmp_path):
    path = write_transactions(tmp_path, [txn("ABC Equity Direct Growth", 10)])
    result = reconcile_cas_holdings_with_transactions(
        [holding("ABC Equity Direct Growth", 4, "F1"),
         holding("ABC Equity Direct Growth", 6, "F2")],
        path,
    )
    assert result["status"] == "VERIFIED_RECONCILED"
    assert result["reconciled_schemes"] == 1


def test_reconciliation_does_not_use_substring_scheme_matching(tmp_path):
    path = write_transactions(tmp_path, [txn("ABC Equity", 10)])
    result = reconcile_cas_holdings_with_transactions(
        [holding("ABC Equity Fund Direct", 10)], path
    )
    assert result["status"] == "PARTIALLY_RECONCILED"
    assert result["discrepancies"][0]["reason"] == "NO_EXACT_TRANSACTION_SCHEME_MATCH"


def test_reconciliation_detects_unmatched_active_transaction_scheme(tmp_path):
    path = write_transactions(
        tmp_path,
        [txn("ABC Equity Direct Growth", 10), txn("XYZ Debt Direct Growth", 20)],
    )
    result = reconcile_cas_holdings_with_transactions(
        [holding("ABC Equity Direct Growth", 10)], path
    )
    assert result["status"] == "PARTIALLY_RECONCILED"
    assert result["unmatched_transaction_schemes"][0]["scheme"] == "XYZ Debt Direct Growth"


def test_reconciliation_rejects_negative_or_nonfinite_transaction_units(tmp_path):
    path = write_transactions(tmp_path, [txn("ABC Equity Direct Growth", -10)])
    result = reconcile_cas_holdings_with_transactions(
        [holding("ABC Equity Direct Growth", 10)], path
    )
    assert result["status"] == "INVALID_TRANSACTION"


def test_reconciliation_rejects_malformed_transaction_rows(tmp_path):
    path = write_transactions(tmp_path, ["not-an-object"])
    result = reconcile_cas_holdings_with_transactions(
        [holding("ABC Equity Direct Growth", 10)], path
    )
    assert result["status"] == "INVALID_TRANSACTION"


def test_reconciliation_rejects_invalid_transactions_container(tmp_path):
    path = tmp_path / "transactions.json"
    path.write_text('{"transactions": {}}', encoding="utf-8")
    result = reconcile_cas_holdings_with_transactions(
        [holding("ABC Equity Direct Growth", 10)], path
    )
    assert result["status"] == "READ_ERROR"


def test_reconciliation_missing_file_is_explicitly_not_verified(tmp_path):
    result = reconcile_cas_holdings_with_transactions(
        [holding("ABC Equity Direct Growth", 10)],
        tmp_path / "missing-transactions.json",
    )
    assert result["status"] == "NO_TRANSACTION_FILE"


def test_cash_dividend_does_not_change_reconciled_unit_balance(tmp_path):
    path = write_transactions(
        tmp_path,
        [txn("ABC Equity Direct Growth", 10), txn("ABC Equity Direct Growth", 0, "DIVIDEND")],
    )
    result = reconcile_cas_holdings_with_transactions(
        [holding("ABC Equity Direct Growth", 10)], path
    )
    assert result["status"] == "VERIFIED_RECONCILED"


def test_reconciliation_rejects_nonfinite_transaction_units(tmp_path):
    path = tmp_path / "transactions.json"
    path.write_text(
        '{"transactions":[{"scheme":"ABC Equity Direct Growth","type":"PURCHASE","units":NaN}]}',
        encoding="utf-8",
    )
    result = reconcile_cas_holdings_with_transactions(
        [holding("ABC Equity Direct Growth", 10)], path
    )
    # JSON NaN is parsed by Python but rejected by the finite-number gate.
    assert result["status"] == "INVALID_TRANSACTION"
