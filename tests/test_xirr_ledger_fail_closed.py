import json
from datetime import date

from core.math_engine import calculate_portfolio_xirr


def _write_ledger(tmp_path, rows):
    path = tmp_path / "transactions.json"
    path.write_text(json.dumps({"transactions": rows}), encoding="utf-8")
    return path


def _valid_rows():
    return [
        {"date": "2024-01-01", "type": "PURCHASE", "amount": 1000.0},
        {"date": "2025-01-01", "type": "PURCHASE", "amount": 1000.0},
    ]


def test_xirr_rejects_malformed_row_instead_of_silently_dropping_it(tmp_path):
    rows = _valid_rows() + [{"date": "not-a-date", "type": "PURCHASE", "amount": 500.0}]
    assert calculate_portfolio_xirr(
        _write_ledger(tmp_path, rows), [], cas_current=2200.0, as_of_date=date(2025, 2, 1)
    ) is None


def test_xirr_rejects_unknown_transaction_type(tmp_path):
    rows = _valid_rows() + [{"date": "2025-01-15", "type": "UNCLASSIFIED", "amount": 100.0}]
    assert calculate_portfolio_xirr(
        _write_ledger(tmp_path, rows), [], cas_current=2200.0, as_of_date=date(2025, 2, 1)
    ) is None


def test_xirr_rejects_non_finite_cashflow(tmp_path):
    rows = _valid_rows() + [{"date": "2025-01-15", "type": "SIP", "amount": float("nan")}]
    assert calculate_portfolio_xirr(
        _write_ledger(tmp_path, rows), [], cas_current=2200.0, as_of_date=date(2025, 2, 1)
    ) is None


def test_xirr_rejects_valuation_date_before_latest_transaction(tmp_path):
    assert calculate_portfolio_xirr(
        _write_ledger(tmp_path, _valid_rows()), [], cas_current=2200.0, as_of_date=date(2024, 12, 31)
    ) is None


def test_xirr_calculates_when_all_transaction_rows_are_valid(tmp_path):
    result = calculate_portfolio_xirr(
        _write_ledger(tmp_path, _valid_rows()), [], cas_current=2200.0, as_of_date=date(2025, 2, 1)
    )
    assert result is not None


def test_xirr_is_unavailable_when_charge_cashflow_semantics_are_unverified(tmp_path):
    rows = _valid_rows() + [
        {"date": "2025-01-15", "type": "CHARGES", "amount": -25.0, "units": 0.0}
    ]
    assert calculate_portfolio_xirr(
        _write_ledger(tmp_path, rows), [], cas_current=2200.0, as_of_date=date(2025, 2, 1)
    ) is None
