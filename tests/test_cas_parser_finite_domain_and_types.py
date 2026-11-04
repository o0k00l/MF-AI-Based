from io import BytesIO
import math

import openpyxl
import pytest

from ingestion.cas_parser import parse_cas_xlsx, reconcile


def _workbook(*, current=1000.0, invested=900.0, returns=100.0, units=10.0,
              stated_total=1000.0, transaction=None):
    def excel_value(value):
        if isinstance(value, float) and not math.isfinite(value):
            return str(value)
        return value

    workbook = openpyxl.Workbook()
    portfolio = workbook.active
    portfolio.title = "Portfolio Details"
    portfolio.append(["Current Portfolio Value"])
    portfolio.append([excel_value(stated_total)])
    portfolio.append(["To Date", "04-Nov-2026"])
    portfolio.append([
        "Scheme Name", "AMC Name", "Category", "Folio No.",
        "Invested Value", "Current Value", "Returns", "Units",
    ])
    portfolio.append([
        "Example Equity Fund - Direct Growth", "Example AMC", "Flexi Cap",
        "FOLIO-1", excel_value(invested), excel_value(current), excel_value(returns), excel_value(units),
    ])
    if transaction is not None:
        sheet = workbook.create_sheet("Transaction Details")
        sheet.append(["Scheme Name", "Date", "Amount", "Units", "Description"])
        sheet.append([
            "Example Equity Fund - Direct Growth",
            transaction.get("date", "04-Nov-2026"),
            excel_value(transaction.get("amount", 100.0)),
            excel_value(transaction.get("units", 1.0)),
            transaction.get("description", "Purchase"),
        ])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_current_value_is_rejected_and_breaks_reconciliation(value):
    parsed = parse_cas_xlsx(_workbook(current=value))
    assert not parsed["holdings"]
    assert parsed["rejected"]
    result = reconcile(parsed)
    assert result["complete"] is False
    assert result["agrees"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("invested", float("inf")),
        ("invested", -1.0),
        ("returns", float("nan")),
        ("units", float("-inf")),
        ("units", -1.0),
    ],
)
def test_invalid_holding_financial_fields_are_rejected(field, value):
    kwargs = {
        "invested": 900.0,
        "returns": 100.0,
        "units": 10.0,
    }
    kwargs[field] = value
    parsed = parse_cas_xlsx(_workbook(**kwargs))
    assert not parsed["holdings"]
    assert parsed["rejected"]
    assert reconcile(parsed)["complete"] is False


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_invalid_statement_total_is_rejected(value):
    parsed = parse_cas_xlsx(_workbook(stated_total=value))
    assert parsed["stated_total"] is None
    assert parsed["rejected"]
    assert reconcile(parsed)["complete"] is False


def test_unmapped_transaction_description_never_defaults_to_purchase():
    parsed = parse_cas_xlsx(_workbook(transaction={"description": "Corporate action adjustment"}))
    assert parsed["transactions"][0]["type"] == "UNKNOWN"
    assert parsed["transactions"][0]["source_row"] == 2
    assert parsed["rejected"]
    assert reconcile(parsed)["complete"] is False


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Purchase", "PURCHASE"),
        ("SIP installment", "SIP"),
        ("Switch In", "SWITCH_IN"),
        ("Switch Out", "SWITCH_OUT"),
        ("Dividend Payout", "DIVIDEND"),
        ("Dividend Reinvestment", "DIVIDEND_REINVEST"),
        ("Stamp Duty", "CHARGES"),
        ("STT", "CHARGES"),
    ],
)
def test_explicit_transaction_descriptions_have_typed_mapping(description, expected):
    parsed = parse_cas_xlsx(
        _workbook(transaction={"description": description, "units": 0.0 if expected in {"DIVIDEND", "CHARGES"} else 1.0})
    )
    assert parsed["transactions"][0]["type"] == expected
    assert not parsed["rejected"]


@pytest.mark.parametrize("description", ["Dividend Payout", "Stamp Duty"])
def test_cash_only_transaction_cannot_change_units(description):
    parsed = parse_cas_xlsx(
        _workbook(transaction={"description": description, "units": 0.5})
    )
    assert not parsed["transactions"]
    assert parsed["rejected"]
    assert reconcile(parsed)["complete"] is False


@pytest.mark.parametrize("amount,units", [(float("nan"), 0.0), (100.0, float("inf"))])
def test_non_finite_transaction_amount_or_units_is_rejected(amount, units):
    parsed = parse_cas_xlsx(
        _workbook(transaction={"description": "Stamp Duty", "amount": amount, "units": units})
    )
    assert parsed["rejected"]
    assert reconcile(parsed)["complete"] is False


def test_charge_row_is_preserved_as_cash_only_with_source_location():
    parsed = parse_cas_xlsx(
        _workbook(transaction={
            "description": "Stamp Duty",
            "amount": -1.5,
            "units": 0.0,
        })
    )
    transaction = parsed["transactions"][0]
    assert transaction["type"] == "CHARGES"
    assert transaction["units"] == 0.0
    assert transaction["source_row"] == 2
    assert transaction["raw_description"] == "Stamp Duty"
    assert not parsed["rejected"]
