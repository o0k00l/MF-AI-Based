import hashlib
from datetime import date
from pathlib import Path

import pytest

from core.eligibility import _reviewed_direct_plan_evidence_status


def _fund(tmp_path: Path):
    source = b"AMC factsheet bytes"
    (tmp_path / "factsheet.pdf").write_bytes(source)
    return {
        "_evidence_root": tmp_path,
        "fund_name": "Example Direct Growth",
        "scheme_id": "123456",
        "isin": "INF000000001",
        "amc_name": "Example Asset Management Company",
        "direct_plan_evidence": {
            "source_file": "factsheet.pdf",
            "source_document_sha256": hashlib.sha256(source).hexdigest(),
            "source_url": "https://amc.example/factsheet.pdf",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Example Direct Growth",
            "scheme_id": "123456",
            "isin": "INF000000001",
            "amc_name": "Example Asset Management Company",
            "reviewed_at": date.today().isoformat(),
        },
    }


def test_direct_plan_evidence_requires_exact_scheme_identity(tmp_path):
    fund = _fund(tmp_path)
    assert _reviewed_direct_plan_evidence_status(fund) == "REVIEWER_ATTESTED_HASH_MATCH"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scheme_id", "999999"),
        ("isin", "INF999999999"),
        ("amc_name", "Different AMC"),
        ("plan", "Regular"),
        ("scheme_name", "Different Scheme"),
    ],
)
def test_direct_plan_evidence_rejects_identity_or_plan_mismatch(tmp_path, field, value):
    fund = _fund(tmp_path)
    fund["direct_plan_evidence"][field] = value

    assert _reviewed_direct_plan_evidence_status(fund) == "INVALID"


def test_direct_plan_evidence_rejects_missing_exact_identity(tmp_path):
    fund = _fund(tmp_path)
    fund.pop("isin")

    assert _reviewed_direct_plan_evidence_status(fund) == "INVALID"


def test_direct_plan_evidence_rejects_tampered_source_bytes(tmp_path):
    fund = _fund(tmp_path)
    (tmp_path / "factsheet.pdf").write_bytes(b"tampered")

    assert _reviewed_direct_plan_evidence_status(fund) == "INVALID"


def test_direct_plan_evidence_rejects_path_escape(tmp_path):
    fund = _fund(tmp_path)
    outside = tmp_path.parent / "outside.pdf"
    outside.write_bytes(b"outside")
    fund["direct_plan_evidence"]["source_file"] = "../outside.pdf"

    assert _reviewed_direct_plan_evidence_status(fund) == "INVALID"


def test_direct_plan_evidence_rejects_malformed_https_url(tmp_path):
    fund = _fund(tmp_path)
    fund["direct_plan_evidence"]["source_url"] = "https://amc.example/file name.pdf"

    assert _reviewed_direct_plan_evidence_status(fund) == "INVALID"
