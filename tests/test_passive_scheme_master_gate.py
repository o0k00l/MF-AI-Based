import pytest

from core.fund_classifier import is_verified_passive_scheme
from core.models import InsufficientDataError


def test_checked_in_sample_scheme_master_cannot_verify_test_or_real_isin():
    for isin in ("TEST004", "INF769K01EZ2"):
        with pytest.raises(InsufficientDataError, match="source-verified passive scheme-master envelope"):
            is_verified_passive_scheme(fund_data={"isin": isin})


def test_caller_supplied_raw_isin_mapping_cannot_bypass_passive_master_gate():
    raw_mapping = {
        "INF000000001": {
            "isin": "INF000000001",
            "is_passive": True,
            "benchmark_index": "NIFTY 50 TRI",
            "mandate": "Index Fund",
        }
    }
    with pytest.raises(InsufficientDataError, match="source-verified passive scheme-master envelope"):
        is_verified_passive_scheme(
            fund_data={"isin": "INF000000001"},
            scheme_master=raw_mapping,
        )


def test_verified_status_without_original_source_bytes_is_rejected():
    envelope = {
        "status": "VERIFIED",
        "source_url": "https://amfiindia.com/scheme-master",
        "source_document_sha256": "a" * 64,
        "effective_date": "2026-11-04",
        "reviewer_approval_envelope": {"payload": {}, "signature": "invalid"},
        "schemes_by_isin": {
            "INF000000001": {
                "isin": "INF000000001",
                "is_passive": True,
                "benchmark_index": "NIFTY 50 TRI",
                "mandate": "Index Fund",
            }
        },
    }
    with pytest.raises(InsufficientDataError, match="original source bytes"):
        is_verified_passive_scheme(
            fund_data={"isin": "INF000000001"},
            scheme_master=envelope,
        )
