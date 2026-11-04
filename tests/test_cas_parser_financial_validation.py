"""Fail-closed tests for financial numeric values and CAS transaction semantics."""

import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from ingestion.cas_parser import parse_cas_xlsx, reconcile
from core.math_engine import (
    calculate_portfolio_xirr,
    reconcile_cas_holdings_with_transactions,
)


def _cas_file(
    tmp_path: Path,
    *,
    current=1000.0,
    invested=900.0,
    returns=100.0,
    units=100.0,
    stated_total=1000.0,
    transactions=None,
) -> Path:
    workbook = openpyxl.Workbook()
    portfolio = workbook.active
    portfolio.title = "Portfolio Details"
    portfolio.append(["Current Portfolio Value"])
    portfolio.append([stated_total])
    portfolio.append(["To Date", "04-Oct-2026"])
    portfolio.append(["Scheme Name", "Current Value", "Invested Value", "Returns", "Units"])
    portfolio.append(["Fund A", current, invested, returns, units])

    if transactions is not None:
        sheet = workbook.create_sheet("Transaction Details")
        sheet.append([
            "Scheme Name", "Transaction Date", "Amount", "Units", "NAV",
            "Transaction Description",
        ])
        for row in transactions:
            sheet.append(row)

    path = tmp_path / "statement.xlsx"
    workbook.save(path)
    return path


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_invalid_current_value_is_rejected_not_dormant(tmp_path, value):
    parsed = parse_cas_xlsx(_cas_file(tmp_path, current=value))
    assert parsed["holdings"] == []
    assert parsed["dormant"] == []
    assert parsed["rejected"]
    assert parsed["rejected"][0]["row"] == 5
    assert "current_value" in parsed["rejected"][0]["raw_cells"]
    result = reconcile(parsed)
    assert result["agrees"] is False
    assert result["complete"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("invested", "NaN"),
        ("invested", "Infinity"),
        ("invested", -1.0),
        ("returns", "-Infinity"),
        ("units", "NaN"),
        ("units", -1.0),
    ],
)
def test_invalid_optional_holding_financial_values_reject_whole_row(tmp_path, field, value):
    kwargs = {"invested": 900.0, "returns": 100.0, "units": 100.0}
    kwargs[field] = value
    parsed = parse_cas_xlsx(_cas_file(tmp_path, **kwargs))
    assert parsed["holdings"] == []
    assert parsed["dormant"] == []
    assert parsed["rejected"]
    raw_key = {"invested": "invested_value", "returns": "returns", "units": "units"}[field]
    assert raw_key in parsed["rejected"][0]["raw_cells"]
    assert reconcile(parsed)["agrees"] is False


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), -1.0])
def test_invalid_statement_total_blocks_reconciliation(tmp_path, value):
    parsed = parse_cas_xlsx(_cas_file(tmp_path, stated_total=value))
    assert parsed["stated_total"] is None
    assert parsed["rejected"]
    result = reconcile(parsed)
    assert result["agrees"] is False
    assert result["complete"] is False


def test_zero_current_value_remains_a_valid_dormant_holding(tmp_path):
    parsed = parse_cas_xlsx(_cas_file(tmp_path, current=0.0, stated_total=0.0))
    assert parsed["holdings"] == []
    assert len(parsed["dormant"]) == 1
    assert parsed["dormant"][0]["current_value"] == 0.0
    assert parsed["rejected"] == []


@pytest.mark.parametrize(
    "amount,units,nav",
    [
        ("NaN", 1.0, 10.0),
        (100.0, "Infinity", 10.0),
        (100.0, -1.0, 10.0),
        (100.0, 1.0, "NaN"),
        (100.0, 1.0, 0.0),
    ],
)
def test_invalid_transaction_financial_values_are_rejected(tmp_path, amount, units, nav):
    parsed = parse_cas_xlsx(_cas_file(
        tmp_path,
        transactions=[["Fund A", "04-Oct-2026", amount, units, nav, "Purchase"]],
    ))
    assert parsed["transactions"] == []
    assert parsed["rejected"]
    assert "transaction financial value" in parsed["rejected"][-1]["reason"]


def test_unknown_transaction_description_is_not_assumed_to_be_purchase(tmp_path):
    parsed = parse_cas_xlsx(_cas_file(
        tmp_path,
        transactions=[["Fund A", "04-Oct-2026", 100.0, 10.0, 10.0, "Unclassified adjustment"]],
    ))
    assert parsed["transactions"][0]["type"] == "UNKNOWN"

    transaction_path = tmp_path / "transactions.json"
    transaction_path.write_text(json.dumps({"transactions": parsed["transactions"]}))
    holdings = [SimpleNamespace(scheme="Fund A", units=10.0)]
    result = reconcile_cas_holdings_with_transactions(holdings, transaction_path)
    assert result["status"] == "INVALID_TRANSACTION"


def test_charge_rows_do_not_change_units_and_withhold_xirr(tmp_path):
    parsed = parse_cas_xlsx(_cas_file(
        tmp_path,
        transactions=[
            ["Fund A", "04-Oct-2026", 100.0, 10.0, 10.0, "Purchase"],
            ["Fund A", "04-Oct-2026", 1.0, 0.0, None, "Stamp Duty"],
        ],
    ))
    assert [row["type"] for row in parsed["transactions"]] == ["PURCHASE", "CHARGES"]

    transaction_path = tmp_path / "transactions.json"
    transaction_path.write_text(json.dumps({"transactions": parsed["transactions"]}))
    holdings = [SimpleNamespace(scheme="Fund A", units=10.0)]
    result = reconcile_cas_holdings_with_transactions(holdings, transaction_path)
    assert result["status"] == "VERIFIED_RECONCILED"

    assert calculate_portfolio_xirr(
        transaction_path,
        [{"current_value": 1000.0}],
        cas_current=1000.0,
    ) is None
