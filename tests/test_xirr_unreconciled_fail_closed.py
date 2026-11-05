import math
from datetime import date
import pytest
from core.math.xirr import calculate_xirr
from core.math_engine import calculate_portfolio_xirr


def test_xirr_solver_rejects_non_finite_amounts():
    cashflows = [
        (date(2025, 1, 1), -100000.0),
        (date(2026, 1, 1), float("nan")),
    ]
    assert calculate_xirr(cashflows) is None

    cashflows_inf = [
        (date(2025, 1, 1), -100000.0),
        (date(2026, 1, 1), float("inf")),
    ]
    assert calculate_xirr(cashflows_inf) is None


def test_xirr_solver_rejects_boolean_amounts():
    cashflows = [
        (date(2025, 1, 1), -100000.0),
        (date(2026, 1, 1), True),
    ]
    assert calculate_xirr(cashflows) is None


def test_xirr_solver_requires_both_inflows_and_outflows():
    only_investments = [
        (date(2025, 1, 1), -50000.0),
        (date(2025, 6, 1), -50000.0),
    ]
    assert calculate_xirr(only_investments) is None

    only_returns = [
        (date(2025, 1, 1), 50000.0),
        (date(2025, 6, 1), 60000.0),
    ]
    assert calculate_xirr(only_returns) is None


def test_xirr_solver_converges_for_normal_cash_flows():
    flows = [
        (date(2025, 1, 1), -100000.0),
        (date(2026, 1, 1), 112000.0),
    ]
    rate = calculate_xirr(flows)
    assert rate is not None
    assert abs(rate - 0.12) < 0.005


def test_calculate_portfolio_xirr_requires_valid_as_of_date(tmp_path):
    txn_file = tmp_path / "transactions.json"
    txn_file.write_text(
        '{"transactions": [{"date": "2025-01-01", "type": "PURCHASE", "amount": 100000.0}]}'
    )
    assert calculate_portfolio_xirr(txn_file, [], cas_current=110000.0, as_of_date=None) is None
