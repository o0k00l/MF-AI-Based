from datetime import date, datetime
import hashlib
from pathlib import Path

import pytest

from services.sip_evidence_contract import (
    EvidenceProviderContractError,
    REQUIRED_EVIDENCE_FIELDS,
    validate_evidence_provider_payload,
)


def _source_metadata(raw):
    return {
        "source_url": "https://amfiindia.com/source",
        "source_document_sha256": hashlib.sha256(raw).hexdigest(),
        "reviewer_attested": True,
        "effective_date": "2026-11-01",
        "source_type": "OFFICIAL_SCHEME_MASTER",
    }


def valid_payload():
    master_bytes = b"source master"
    universe_bytes = b"source candidate universe"
    return {
        "metrics_path": Path(__file__),
        "aliases_path": None,
        "scheme_master": {
            **_source_metadata(master_bytes),
            "status": "VERIFIED",
            "schemes": [{
                "scheme_id": "scheme-1", "isin": "INF000000001",
                "scheme_name": "Example Direct Growth", "amc_name": "Example AMC",
            }],
        },
        "scheme_master_source_bytes": master_bytes,
        "portfolio_disclosures_by_scheme_id": {"scheme-1": {"scheme_id": "scheme-1"}},
        "portfolio_disclosure_source_bytes_by_scheme_id": {"scheme-1": b"source disclosure"},
        "disclosure_as_of_date": date(2026, 11, 4),
        "candidate_universe": [{
            "fund_id": "fund-1", "fund_name": "Example Direct Growth",
            "scheme_id": "scheme-1", "isin": "INF000000001",
            "amc_name": "Example AMC", "category": "Flexi Cap",
        }],
        "candidate_universe_source": {**_source_metadata(universe_bytes), "universe_complete": True, "coverage_scope": "All eligible open-ended equity and debt schemes"},
        "candidate_universe_source_bytes": universe_bytes,
    }


def test_contract_accepts_source_backed_candidate_identity():
    payload = valid_payload()
    result = validate_evidence_provider_payload(payload)

    assert set(result) == REQUIRED_EVIDENCE_FIELDS


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


def test_contract_rejects_source_hash_mismatch():
    payload = valid_payload()
    payload["candidate_universe_source_bytes"] = b"tampered"

    with pytest.raises(EvidenceProviderContractError, match="SHA-256 does not match"):
        validate_evidence_provider_payload(payload)


def test_contract_requires_reviewer_attestation():
    payload = valid_payload()
    payload["candidate_universe_source"]["reviewer_attested"] = False

    with pytest.raises(EvidenceProviderContractError, match="reviewer attestation"):
        validate_evidence_provider_payload(payload)


def test_contract_requires_exact_disclosure_source_key_coverage():
    payload = valid_payload()
    payload["portfolio_disclosure_source_bytes_by_scheme_id"] = {}

    with pytest.raises(EvidenceProviderContractError, match="identical scheme-ID keys"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_disclosure_scheme_id_not_in_master():
    payload = valid_payload()
    payload["portfolio_disclosures_by_scheme_id"] = {"other": {"scheme_id": "other"}}
    payload["portfolio_disclosure_source_bytes_by_scheme_id"] = {"other": b"source"}

    with pytest.raises(EvidenceProviderContractError, match="absent from verified scheme master"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_timestamp_as_decision_date():
    payload = valid_payload()
    payload["disclosure_as_of_date"] = datetime(2026, 11, 4)

    with pytest.raises(EvidenceProviderContractError, match="not a timestamp"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_duplicate_candidate_fund_ids():
    payload = valid_payload()
    payload["candidate_universe"].append(dict(payload["candidate_universe"][0]))

    with pytest.raises(EvidenceProviderContractError, match="Duplicate candidate fund_id"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_candidate_identity_conflicting_with_scheme_master():
    payload = valid_payload()
    payload["candidate_universe"][0]["isin"] = "INF999999999"

    with pytest.raises(EvidenceProviderContractError, match="identity conflicts"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_candidate_missing_required_identity_field():
    payload = valid_payload()
    payload["candidate_universe"][0].pop("amc_name")

    with pytest.raises(EvidenceProviderContractError, match="requires amc_name"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_unattested_incomplete_candidate_universe():
    payload = valid_payload()
    payload["candidate_universe_source"]["universe_complete"] = False

    with pytest.raises(EvidenceProviderContractError, match="explicitly reviewer-attested as complete"):
        validate_evidence_provider_payload(payload)


def test_contract_rejects_stale_candidate_universe_source():
    payload = valid_payload()
    payload["candidate_universe_source"]["effective_date"] = "2026-08-01"

    with pytest.raises(EvidenceProviderContractError, match="source is stale"):
        validate_evidence_provider_payload(payload)
