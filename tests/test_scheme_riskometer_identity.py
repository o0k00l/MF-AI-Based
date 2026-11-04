import hashlib

import pytest

from ingestion.portfolio_disclosure import resolve_scheme_identity


def _master(score):
    source = b"reviewed scheme master"
    return source, {
        "status": "VERIFIED",
        "source_url": "https://amfiindia.com/scheme-master",
        "source_document_sha256": hashlib.sha256(source).hexdigest(),
        "reviewer_attested": True,
        "schemes": [{
            "scheme_id": "scheme-123",
            "isin": "INF000000123",
            "scheme_name": "Example Equity Fund Direct Growth",
            "amc_name": "Example AMC",
            "category": "Flexi Cap",
            "benchmark_identity": "NIFTY 500 TRI",
            "scheme_structure": "OPEN_ENDED_EQUITY",
            "plan_type": "Direct",
            "option_type": "Growth",
            "riskometer_score": score,
        }],
    }


def test_exact_scheme_identity_returns_verified_scheme_riskometer_score():
    source, master = _master(5)
    result = resolve_scheme_identity(
        {"scheme": "Example Equity Fund Direct Growth", "amc_name": "Example AMC"},
        master,
        source_bytes=source,
    )
    assert result["status"] == "VERIFIED"
    assert result["riskometer_score"] == 5


@pytest.mark.parametrize("score", [None, 0, 7, True, "5"])
def test_scheme_identity_rejects_missing_or_invalid_riskometer_score(score):
    source, master = _master(score)
    result = resolve_scheme_identity(
        {"scheme": "Example Equity Fund Direct Growth", "amc_name": "Example AMC"},
        master,
        source_bytes=source,
    )
    assert result["status"] == "MISSING"
    assert result["riskometer_score"] is None if "riskometer_score" in result else True
