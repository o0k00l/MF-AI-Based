from datetime import date

import pytest

from services.sip_evidence_contract import (
    EvidenceProviderContractError,
    REQUIRED_EVIDENCE_FIELDS,
    validate_evidence_provider_payload,
)


def valid_payload():
    return {
        "metrics_path": None,
        "aliases_path": None,
        "scheme_master": {"status": "PROVISIONAL", "schemes": []},
        "scheme_master_source_bytes": b"source master",
        "portfolio_disclosures_by_scheme_id": {"scheme-1": {"scheme_id": "scheme-1"}},
        "portfolio_disclosure_source_bytes_by_scheme_id": {"scheme-1": b"source disclosure"},
        "disclosure_as_of_date": date(2026, 11, 4),
        "candidate_universe": [{"candidate_id": "candidate-1"}],
    }


def test_contract_accepts_complete_structural_payload_without_certifying_it():
    payload = valid_payload()
    result = validate_evidence_provider_payload(payload)

    assert set(result) == REQUIRED_EVIDENCE_FIELDS
    assert result["scheme_master"]["status"] == "PROVISIONAL"


def test_contract_rejects_missing_required_field():
    payload = valid_payload()
    payload.pop("candidate_universe")

    with pytest.raises(EvidenceProviderContractError, match="candidate_universe"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_unexpected_and_request_override_fields():
    payload = valid_payload()
    payload["monthly_budget_inr"] = 50000

    with pytest.raises(EvidenceProviderContractError, match="unsupported fields"):
        validate_evidence_provider_payload(payload)


def test_contract_requires_original_scheme_master_bytes():
    payload = valid_payload()
    payload["scheme_master_source_bytes"] = b""

    with pytest.raises(EvidenceProviderContractError, match="scheme_master_source_bytes"):
        validate_evidence_provider_payload(payload)


def test_contract_requires_exact_disclosure_source_key_coverage():
    payload = valid_payload()
    payload["portfolio_disclosure_source_bytes_by_scheme_id"] = {}

    with pytest.raises(EvidenceProviderContractError, match="identical scheme-ID keys"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_missing_disclosure_source_bytes():
    payload = valid_payload()
    payload["portfolio_disclosure_source_bytes_by_scheme_id"]["scheme-1"] = None

    with pytest.raises(EvidenceProviderContractError, match="source bytes"):
        validate_evidence_provider_payload(payload)


def test_contract_requires_date_object_for_as_of_date():
    payload = valid_payload()
    payload["disclosure_as_of_date"] = "2026-11-04"

    with pytest.raises(EvidenceProviderContractError, match="must be a date"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_empty_or_malformed_candidate_universe():
    payload = valid_payload()
    payload["candidate_universe"] = []

    with pytest.raises(EvidenceProviderContractError, match="non-empty list"):
        validate_evidence_provider_payload(payload)

    payload["candidate_universe"] = ["not-a-candidate"]
    with pytest.raises(EvidenceProviderContractError, match="Every candidate"):
        validate_evidence_provider_payload(payload)
