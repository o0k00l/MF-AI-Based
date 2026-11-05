import hashlib
import json
from datetime import date
from pathlib import Path
import pytest

from services.sip_evidence_contract import (
    validate_evidence_provider_payload,
    EvidenceProviderContractError,
)


def _base_payload(tmp_path):
    master_bytes = b"authoritative scheme master synthetic bytes"
    metrics_bytes = b"metrics raw data"
    candidate_bytes = b"candidate universe raw data"

    metrics_file = tmp_path / "fund_metrics.json"
    metrics_file.write_bytes(b'{"funds": []}')

    return {
        "disclosure_as_of_date": date(2026, 11, 4),
        "scheme_master": {
            "status": "VERIFIED",
            "source_url": "https://amfiindia.com/master",
            "source_document_sha256": hashlib.sha256(master_bytes).hexdigest(),
            "reviewer_attested": True,
            "schemes": [
                {
                    "scheme_id": "SCHEME_DIRECT_1",
                    "isin": "INF000000001",
                    "scheme_name": "Scheme A Direct Growth",
                    "amc_name": "AMC One",
                    "category": "Flexi Cap Equity",
                    "benchmark_identity": "NIFTY 500 TRI",
                    "scheme_structure": "Open Ended",
                    "plan_type": "Direct",
                    "option_type": "Growth",
                    "riskometer_score": 4,
                }
            ],
        },
        "scheme_master_source_bytes": master_bytes,
        "portfolio_disclosures_by_scheme_id": {
            "SCHEME_DIRECT_1": {
                "scheme_id": "SCHEME_DIRECT_1",
                "isin": "INF000000001",
                "as_of_date": "2026-11-04",
                "status": "VERIFIED",
                "holdings": [],
            }
        },
        "portfolio_disclosure_source_bytes_by_scheme_id": {
            "SCHEME_DIRECT_1": b"disclosure bytes"
        },
        "candidate_universe": [
            {
                "fund_id": "SCHEME_DIRECT_1",
                "scheme_id": "SCHEME_DIRECT_1",
                "isin": "INF000000001",
                "fund_name": "Scheme A Direct Growth",
                "amc_name": "AMC One",
                "category": "Flexi Cap Equity",
                "plan_type": "Direct",
                "option_type": "Growth",
                "is_direct": True,
                "benchmark_identity": "NIFTY 500 TRI",
                "scheme_structure": "Open Ended",
                "riskometer_score": 4,
                "direct_plan_evidence": {"plan_type": "Direct"},
                "_evidence_root": tmp_path,
            }
        ],
        "candidate_universe_source": {
            "status": "VERIFIED",
            "source_url": "https://amfiindia.com/candidates",
            "source_document_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "reviewer_attested": True,
            "universe_complete": True,
            "coverage_scope": "ALL_REGISTERED_DIRECT_FLEXI_CAP",
        },
        "candidate_universe_source_bytes": candidate_bytes,
        "metrics_path": metrics_file,
        "metrics_source_metadata": {
            "status": "VERIFIED",
            "source_url": "https://amfiindia.com/metrics",
            "source_document_sha256": hashlib.sha256(metrics_bytes).hexdigest(),
            "reviewer_attested": True,
            "normalized_metrics_sha256": hashlib.sha256(metrics_file.read_bytes()).hexdigest(),
        },
        "metrics_source_bytes": metrics_bytes,
        "aliases_path": None,
    }


def test_aliases_file_must_be_regular_non_symlink(tmp_path):
    payload = _base_payload(tmp_path)
    aliases_dir = tmp_path / "aliases_dir"
    aliases_dir.mkdir()
    payload["aliases_path"] = aliases_dir
    with pytest.raises(EvidenceProviderContractError, match="regular, non-symlink file"):
        validate_evidence_provider_payload(payload)


def test_aliases_path_without_source_metadata_and_bytes_is_rejected(tmp_path):
    payload = _base_payload(tmp_path)
    aliases_file = tmp_path / "aliases.json"
    aliases_file.write_bytes(b'{"aliases": {}}')
    payload["aliases_path"] = aliases_file
    with pytest.raises(EvidenceProviderContractError, match="Fund aliases path requires both aliases_source_metadata and aliases_source_bytes"):
        validate_evidence_provider_payload(payload)


def test_aliases_metadata_and_bytes_must_be_supplied_together(tmp_path):
    payload = _base_payload(tmp_path)
    aliases_file = tmp_path / "aliases.json"
    aliases_file.write_bytes(b'{"aliases": {}}')
    payload["aliases_path"] = aliases_file
    payload["aliases_source_metadata"] = {"status": "VERIFIED"}
    with pytest.raises(EvidenceProviderContractError, match="supplied together"):
        validate_evidence_provider_payload(payload)


def test_aliases_file_sha_mismatch_is_rejected(tmp_path):
    payload = _base_payload(tmp_path)
    aliases_file = tmp_path / "aliases.json"
    aliases_file.write_bytes(b'{"aliases": {"SCHEME_DIRECT_1": ["Alias A"]}}')
    raw_source = b"source bytes for aliases"
    payload["aliases_path"] = aliases_file
    payload["aliases_source_metadata"] = {
        "status": "VERIFIED",
        "source_url": "https://amfiindia.com/aliases",
        "source_document_sha256": hashlib.sha256(raw_source).hexdigest(),
        "reviewer_attested": True,
        "normalized_aliases_sha256": "0" * 64,
    }
    payload["aliases_source_bytes"] = raw_source
    with pytest.raises(EvidenceProviderContractError, match="SHA-256 does not match"):
        validate_evidence_provider_payload(payload)


def test_alias_target_absent_from_scheme_master_is_rejected(tmp_path):
    payload = _base_payload(tmp_path)
    aliases_file = tmp_path / "aliases.json"
    aliases_file.write_text(json.dumps({"aliases": {"UNKNOWN_SCHEME_XYZ": ["Old Name"]}}))
    raw_source = b"source bytes"
    payload["aliases_path"] = aliases_file
    payload["aliases_source_metadata"] = {
        "status": "VERIFIED",
        "source_url": "https://amfiindia.com/aliases",
        "source_document_sha256": hashlib.sha256(raw_source).hexdigest(),
        "reviewer_attested": True,
        "normalized_aliases_sha256": hashlib.sha256(aliases_file.read_bytes()).hexdigest(),
    }
    payload["aliases_source_bytes"] = raw_source
    with pytest.raises(EvidenceProviderContractError, match="absent from verified scheme master"):
        validate_evidence_provider_payload(payload)


def test_verified_aliases_file_passes_validation(tmp_path):
    payload = _base_payload(tmp_path)
    aliases_file = tmp_path / "aliases.json"
    aliases_file.write_text(json.dumps({"aliases": {"SCHEME_DIRECT_1": ["Scheme A Direct"]}}))
    raw_source = b"source bytes"
    payload["aliases_path"] = aliases_file
    payload["aliases_source_metadata"] = {
        "status": "VERIFIED",
        "source_url": "https://amfiindia.com/aliases",
        "source_document_sha256": hashlib.sha256(raw_source).hexdigest(),
        "reviewer_attested": True,
        "normalized_aliases_sha256": hashlib.sha256(aliases_file.read_bytes()).hexdigest(),
    }
    payload["aliases_source_bytes"] = raw_source
    res = validate_evidence_provider_payload(payload)
    assert res["aliases_path"] == aliases_file
