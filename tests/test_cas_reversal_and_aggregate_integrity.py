import openpyxl

from ingestion.cas_parser import parse_cas_xlsx, reconcile


def _cas_with_transaction(tmp_path, description):
    workbook = openpyxl.Workbook()
    portfolio = workbook.active
    portfolio.title = "Portfolio Details"
    portfolio.append(["Current Portfolio Value"])
    portfolio.append([1000.0])
    portfolio.append(["To Date", "04-Oct-2026"])
    portfolio.append(["Scheme Name", "Current Value", "Invested Value", "Returns", "Units"])
    portfolio.append(["Fund A", 1000.0, 900.0, 100.0, 100.0])

    transactions = workbook.create_sheet("Transaction Details")
    transactions.append([
        "Scheme Name", "Transaction Date", "Amount", "Units", "NAV",
        "Transaction Description",
    ])
    transactions.append(["Fund A", "04-Oct-2026", 100.0, 10.0, 10.0, description])
    path = tmp_path / "cas.xlsx"
    workbook.save(path)
    return path


def test_reversal_purchase_is_not_classified_as_purchase(tmp_path):
    parsed = parse_cas_xlsx(
        _cas_with_transaction(tmp_path, "Purchase reversal - rejected")
    )
    assert parsed["transactions"][0]["type"] == "UNKNOWN"
    assert parsed["rejected"]
    assert reconcile(parsed)["complete"] is False


def test_dishonoured_sip_is_not_classified_as_sip(tmp_path):
    parsed = parse_cas_xlsx(
        _cas_with_transaction(tmp_path, "SIP dishonoured")
    )
    assert parsed["transactions"][0]["type"] == "UNKNOWN"
    assert parsed["rejected"]


def test_reconciliation_rejects_overflowing_aggregate():
    result = reconcile({
        "holdings": [
            {"current_value": 1e308},
            {"current_value": 1e308},
        ],
        "stated_total": 1e308,
        "rejected": [],
    })
    assert result["complete"] is False
    assert result["agrees"] is False
    assert result["parsed_total"] is None
    assert result["rejected_rows"]


def test_reconciliation_rejects_non_finite_tolerance():
    result = reconcile({
        "holdings": [{"current_value": 100.0}],
        "stated_total": 100.0,
        "rejected": [],
    }, tolerance=float("inf"))
    assert result["complete"] is False
    assert result["agrees"] is False
