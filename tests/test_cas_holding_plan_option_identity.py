import hashlib
from datetime import date
from io import BytesIO

import openpyxl

from core.math_engine import load_holdings_from_cas_excel
from core.models import PlanType


def _cas_bytes(scheme_name):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    sheet.append(["To Date", "04-Nov-2026"])
    sheet.append([
        "Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units", "AMC Name"
    ])
    sheet.append([scheme_name, "FOLIO-1", 900.0, 1000.0, 10.0, "Example AMC"])
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _master(scheme_name, *, plan_type=None, option_type=None):
    record = {
        "scheme_id": "scheme-1",
        "isin": "INF000000001",
        "scheme_name": scheme_name,
        "amc_name": "Example AMC",
    }
    if plan_type is not None:
        record["plan_type"] = plan_type
    if option_type is not None:
        record["option_type"] = option_type
    source_bytes = b"independently reviewed synthetic scheme master"
    return {
        "status": "VERIFIED",
        "source_url": "https://amfiindia.com/scheme-master",
        "source_document_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "reviewer_attested": True,
        "schemes": [record],
    }, source_bytes


def _load(tmp_path, scheme_name, *, plan_type=None, option_type=None):
    path = tmp_path / "cas.xlsx"
    path.write_bytes(_cas_bytes(scheme_name))
    master, source_bytes = _master(
        scheme_name, plan_type=plan_type, option_type=option_type
    )
    return load_holdings_from_cas_excel(
        path,
        None,
        None,
        scheme_master=master,
        scheme_master_source_bytes=source_bytes,
        disclosure_as_of_date=date(2026, 11, 4),
    )[0]


def test_direct_word_in_name_cannot_override_verified_regular_plan(tmp_path):
    holding = _load(
        tmp_path,
        "Example Direct Growth",
        plan_type="Regular",
        option_type="Growth",
    )
    assert holding.plan == PlanType.REGULAR
    assert holding.is_direct is False
    assert holding.plan_option_status == "VERIFIED"
    assert holding.option_type == "GROWTH"


def test_missing_plan_word_in_name_does_not_prevent_verified_direct_plan(tmp_path):
    holding = _load(
        tmp_path,
        "Example Equity Fund",
        plan_type="Direct",
        option_type="Growth",
    )
    assert holding.plan == PlanType.DIRECT
    assert holding.is_direct is True
    assert holding.plan_option_status == "VERIFIED"


def test_missing_master_plan_evidence_remains_unknown_not_regular(tmp_path):
    holding = _load(tmp_path, "Example Equity Fund")
    assert holding.plan == PlanType.UNKNOWN
    assert holding.is_direct is None
    assert holding.plan_option_status == "MISSING"
    assert holding.option_type is None


def test_unrecognized_master_plan_or_option_is_not_inferred(tmp_path):
    holding = _load(
        tmp_path,
        "Example Direct Growth",
        plan_type="Direct Plan",
        option_type="Growth Option",
    )
    assert holding.plan == PlanType.UNKNOWN
    assert holding.is_direct is None
    assert holding.plan_option_status == "CONFLICTING"


def test_growth_and_idcw_option_identity_remains_separate(tmp_path):
    growth = _load(
        tmp_path,
        "Example Equity Fund",
        plan_type="Direct",
        option_type="Growth",
    )
    idcw = _load(
        tmp_path,
        "Example Equity Fund",
        plan_type="Direct",
        option_type="IDCW",
    )
    assert growth.plan == idcw.plan == PlanType.DIRECT
    assert growth.option_type == "GROWTH"
    assert idcw.option_type == "IDCW"
