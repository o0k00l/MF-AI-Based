from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from core.math_engine import load_holdings_from_cas_excel
from services.sip_recommendation import recommend_sip


AS_OF = date(2026, 11, 4)
SCHEME_NAME = "Example Equity Fund - Direct Plan - Growth"
AMC_NAME = "Example Asset Management Company"
SCHEME_ID = "EXAMPLE-SCHEME-001"
ISIN = "INF000000001"


def _cas_workbook(path: Path, *, include_amc: bool = True) -> Path:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["CAS synthetic integration fixture"])
    headers = ["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"]
    if include_amc:
        headers.append("AMC Name")
    sheet.append(headers)
    row = [SCHEME_NAME, "FOLIO-001", 90000.0, 100000.0, 1000.0]
    if include_amc:
        row.append(AMC_NAME)
    sheet.append(row)
    workbook.save(path)
    return path


def _scheme_master():
    source_bytes = b"synthetic independently reviewed scheme-master source"
    return ({
        "status": "VERIFIED",
        "reviewer_attested": True,
        "source_url": "https://example.test/scheme-master",
        "source_document_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "schemes": [{
            "scheme_id": SCHEME_ID,
            "isin": ISIN,
            "scheme_name": SCHEME_NAME,
            "amc_name": AMC_NAME,
        }],
    }, source_bytes)


def _disclosure(scheme_id: str = SCHEME_ID):
    source_bytes = b"synthetic independently reviewed portfolio disclosure"
    return ({
        "scheme_id": scheme_id,
        "source_url": "https://example.test/portfolio-disclosure",
        "source_document_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "reviewer_attested": True,
        "effective_date": AS_OF.isoformat(),
        "constituent_weights": {"RELIANCE": 50.0, "HDFCBANK": 50.0},
        "constituent_weights_coverage_pct": 100.0,
    }, source_bytes)


def _recommendation(cas_path, scheme_master, scheme_master_bytes, disclosures, disclosure_bytes):
    return recommend_sip(
        cas_path=cas_path,
        metrics_path=None,
        aliases_path=None,
        monthly_budget_inr=25000.0,
        risk_profile="Aggressive",
        scheme_master=scheme_master,
        scheme_master_source_bytes=scheme_master_bytes,
        portfolio_disclosures_by_scheme_id=disclosures,
        portfolio_disclosure_source_bytes_by_scheme_id=disclosure_bytes,
        disclosure_as_of_date=AS_OF,
        candidate_universe=[{"candidate_id": "synthetic-candidate"}],
    )


def test_cas_workbook_exact_identity_and_verified_disclosure_are_attached(tmp_path):
    cas_path = _cas_workbook(tmp_path / "cas.xlsx")
    scheme_master, scheme_master_bytes = _scheme_master()
    disclosure, disclosure_bytes = _disclosure()

    holdings = load_holdings_from_cas_excel(
        cas_path,
        scheme_master=scheme_master,
        scheme_master_source_bytes=scheme_master_bytes,
        portfolio_disclosures_by_scheme_id={SCHEME_ID: disclosure},
        portfolio_disclosure_source_bytes_by_scheme_id={SCHEME_ID: disclosure_bytes},
        disclosure_as_of_date=AS_OF,
    )

    assert len(holdings) == 1
    holding = holdings[0]
    assert holding.scheme_id == SCHEME_ID
    assert holding.isin == ISIN
    assert holding.amc_name == AMC_NAME
    assert holding.is_direct is True
    assert holding.lookthrough_status == "VERIFIED"
    assert holding.metrics_status == "MISSING"
    assert holding.constituent_weights == {"RELIANCE": 50.0, "HDFCBANK": 50.0}
    assert holding.constituent_weights_coverage_pct == 100.0


def test_missing_disclosure_from_real_cas_workbook_keeps_entire_budget_unallocated(tmp_path):
    cas_path = _cas_workbook(tmp_path / "cas.xlsx")
    scheme_master, scheme_master_bytes = _scheme_master()

    result = _recommendation(cas_path, scheme_master, scheme_master_bytes, {}, {})

    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["items"] == []
    assert result["plan"]["total_monthly_budget_inr"] == 25000.0
    assert result["plan"]["unallocated_budget_inr"] == 25000.0
    assert any("constituent disclosure is MISSING" in reason for reason in result["reasons"])


def test_conflicting_disclosure_identity_from_real_cas_workbook_keeps_budget_unallocated(tmp_path):
    cas_path = _cas_workbook(tmp_path / "cas.xlsx")
    scheme_master, scheme_master_bytes = _scheme_master()
    conflicting, disclosure_bytes = _disclosure("A-DIFFERENT-SCHEME")

    result = _recommendation(
        cas_path, scheme_master, scheme_master_bytes,
        {SCHEME_ID: conflicting}, {SCHEME_ID: disclosure_bytes},
    )

    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["items"] == []
    assert result["plan"]["unallocated_budget_inr"] == 25000.0
    assert any("constituent disclosure is CONFLICTING" in reason for reason in result["reasons"])


def test_missing_amc_column_cannot_be_resolved_by_scheme_name_alone(tmp_path):
    cas_path = _cas_workbook(tmp_path / "cas.xlsx", include_amc=False)
    scheme_master, scheme_master_bytes = _scheme_master()
    disclosure, disclosure_bytes = _disclosure()

    holdings = load_holdings_from_cas_excel(
        cas_path,
        scheme_master=scheme_master,
        scheme_master_source_bytes=scheme_master_bytes,
        portfolio_disclosures_by_scheme_id={SCHEME_ID: disclosure},
        portfolio_disclosure_source_bytes_by_scheme_id={SCHEME_ID: disclosure_bytes},
        disclosure_as_of_date=AS_OF,
    )

    assert len(holdings) == 1
    assert holdings[0].scheme_id is None
    assert holdings[0].lookthrough_status == "MISSING"


@pytest.mark.parametrize(
    "headers",
    [
        ["Scheme Name", "Invested Value", "Current Value", "Units"],
        ["Scheme Name", "Folio No.", "Current Value", "Units"],
        ["Scheme Name", "Folio No.", "Invested Value", "Units"],
        ["Scheme Name", "Folio No.", "Invested Value", "Current Value"],
    ],
)
def test_cas_rejects_missing_required_financial_headers(tmp_path, headers):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["Synthetic CAS"])
    sheet.append(headers)
    sheet.append(["Example Direct Fund", "FOLIO", 100.0, 100.0, 10.0][:len(headers)])
    path = tmp_path / "incomplete.xlsx"
    workbook.save(path)

    with pytest.raises(ValueError, match="missing required .* columns"):
        load_holdings_from_cas_excel(path)


def test_cas_rejects_missing_scheme_header_instead_of_using_legacy_positions(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["not", "a", "supported", "header"])
    for _ in range(15):
        sheet.append(["Example Direct Fund", None, None, 100.0, 90.0, 100.0, None, 10.0])
    path = tmp_path / "legacy-layout.xlsx"
    workbook.save(path)

    with pytest.raises(ValueError, match="no 'Scheme Name' header"):
        load_holdings_from_cas_excel(path)


def test_cas_rejects_duplicate_headers(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units", "Units"])
    sheet.append([SCHEME_NAME, "FOLIO", 90000.0, 100000.0, 1000.0, 1000.0])
    path = tmp_path / "duplicate-headers.xlsx"
    workbook.save(path)

    with pytest.raises(ValueError, match="duplicate column headers"):
        load_holdings_from_cas_excel(path)


def test_cas_rejects_malformed_financial_row_instead_of_silently_skipping_it(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    sheet.append([SCHEME_NAME, "FOLIO", "not-a-number", 100000.0, 1000.0])
    path = tmp_path / "malformed-values.xlsx"
    workbook.save(path)

    with pytest.raises(ValueError, match="malformed financial values"):
        load_holdings_from_cas_excel(path)


def test_cas_uses_header_positions_not_fixed_legacy_column_positions(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["Scheme Name", "Units", "Current Value", "Folio No.", "Invested Value", "AMC Name"])
    sheet.append([SCHEME_NAME, 1000.0, 100000.0, "FOLIO-SHIFTED", 90000.0, AMC_NAME])
    path = tmp_path / "shifted-columns.xlsx"
    workbook.save(path)

    holdings = load_holdings_from_cas_excel(
        path,
        scheme_master=_scheme_master()[0],
        scheme_master_source_bytes=_scheme_master()[1],
        disclosure_as_of_date=AS_OF,
    )

    assert len(holdings) == 1
    assert holdings[0].folio == "FOLIO-SHIFTED"
    assert holdings[0].invested_value_inr == 90000.0
    assert holdings[0].current_value_inr == 100000.0
    assert holdings[0].units == 1000.0


def test_recommendation_surfaces_invalid_cas_as_hold_with_full_budget(tmp_path):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["Synthetic CAS with unsupported columns"])
    sheet.append(["Scheme", "Folio", "Value"])
    sheet.append(["Example Equity Fund", "FOLIO-INVALID", 100000.0])
    cas_path = tmp_path / "invalid-cas.xlsx"
    workbook.save(cas_path)
    scheme_master, scheme_master_bytes = _scheme_master()

    result = _recommendation(
        cas_path, scheme_master, scheme_master_bytes, {}, {}
    )

    assert result["status"] == "HOLD"
    assert result["decision"] == "NO_ACTION"
    assert result["plan"]["items"] == []
    assert result["plan"]["total_monthly_budget_inr"] == 25000.0
    assert result["plan"]["unallocated_budget_inr"] == 25000.0
    assert any(
        "CAS or evidence validation failed closed (ValueError)" in reason
        for reason in result["reasons"]
    )
