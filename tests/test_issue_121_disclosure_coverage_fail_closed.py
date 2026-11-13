import json

import pytest

from services.acquisition.adapters.portfolio_disclosure import PortfolioDisclosureAdapter


AS_OF = __import__("datetime").date(2026, 11, 14)


def _payload(**overrides):
    payload = {
        "scheme_id": "scheme-123",
        "constituent_weights": {"RELIANCE": 40.0, "HDFCBANK": 40.0},
        "constituent_weights_coverage_pct": 80.0,
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def test_disclosure_requires_explicit_coverage_instead_of_inventing_full_coverage():
    raw = json.dumps({
        "scheme_id": "scheme-123",
        "constituent_weights": {"RELIANCE": 100.0},
    }).encode()
    with pytest.raises(ValueError, match="explicitly state"):
        PortfolioDisclosureAdapter("scheme-123").acquire(AS_OF, raw_bytes=raw)


@pytest.mark.parametrize("coverage", [float("nan"), float("inf"), float("-inf"), 0, -1, 100.01])
def test_disclosure_rejects_non_finite_or_out_of_range_coverage(coverage):
    with pytest.raises(ValueError, match="Invalid coverage"):
        PortfolioDisclosureAdapter("scheme-123").acquire(
            AS_OF, raw_bytes=_payload(constituent_weights_coverage_pct=coverage)
        )


@pytest.mark.parametrize("weight", [float("nan"), float("inf"), float("-inf"), -0.01])
def test_disclosure_rejects_non_finite_or_negative_weights(weight):
    with pytest.raises(ValueError, match="finite and non-negative"):
        PortfolioDisclosureAdapter("scheme-123").acquire(
            AS_OF, raw_bytes=_payload(constituent_weights={"RELIANCE": weight})
        )


def test_disclosure_rejects_weights_exceeding_declared_coverage():
    with pytest.raises(ValueError, match="exceed disclosed coverage"):
        PortfolioDisclosureAdapter("scheme-123").acquire(
            AS_OF,
            raw_bytes=_payload(
                constituent_weights={"RELIANCE": 60.0, "HDFCBANK": 40.0},
                constituent_weights_coverage_pct=80.0,
            ),
        )


def test_disclosure_rejects_scheme_identity_mismatch():
    with pytest.raises(ValueError, match="does not match requested scheme"):
        PortfolioDisclosureAdapter("scheme-123").acquire(
            AS_OF, raw_bytes=_payload(scheme_id="different-scheme")
        )


def test_disclosure_does_not_default_reviewer_attestation_and_preserves_explicit_coverage():
    record = PortfolioDisclosureAdapter("scheme-123").acquire(AS_OF, raw_bytes=_payload())
    assert record.parsed_payload["constituent_weights_coverage_pct"] == 80.0
    assert record.parsed_payload["reviewer_attested"] is False
    assert record.parsed_payload["source_document_sha256"] == record.source_sha256
