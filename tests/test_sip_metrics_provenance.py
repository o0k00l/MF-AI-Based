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
    disclosure_bytes = b"portfolio disclosure for SCHEME_DIRECT_1"
    factsheet_bytes = b"AMC factsheet for Scheme A Direct Growth"

    metrics_file = tmp_path / "fund_metrics.json"
    metrics_record = {
        "id": "SCHEME_DIRECT_1",
        "scheme_id": "SCHEME_DIRECT_1",
        "isin": "INF000000001",
        "amc_name": "AMC One",
        "category": "Flexi Cap Equity",
        "cat": "Flexi Cap Equity",
        "plan_type": "Direct",
        "option_type": "Growth",
        "benchmark_identity": "NIFTY 500 TRI",
        "effective_date": "2026-11-04",
        "source_ref": "sha256:" + hashlib.sha256(metrics_bytes).hexdigest(),
        "eq": 100.0, "debt": 0.0, "lc": 50.0, "mc": 30.0, "sc": 20.0,
        "market_cap_basis": "TOTAL_PORTFOLIO_PCT",
    }
    metrics_file.write_text(json.dumps({"funds": [metrics_record]}), encoding="utf-8")

    # Create actual factsheet file for evidence
    (tmp_path / "factsheet.pdf").write_bytes(factsheet_bytes)

    return {
        "disclosure_as_of_date": date(2026, 11, 4),
        "scheme_master": {
            "status": "VERIFIED",
            "source_url": "https://amfiindia.com/master",
            "source_document_sha256": hashlib.sha256(master_bytes).hexdigest(),
            "reviewer_attested": True,
            "effective_date": "2026-11-04",
            "source_type": "AMFI_SCHEME_MASTER",
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
                "reviewer_attested": True,
                "source_url": "https://example.com/disclosures/SCHEME_DIRECT_1",
                "source_document_sha256": hashlib.sha256(disclosure_bytes).hexdigest(),
                "effective_date": "2026-11-04",
                "source_type": "PORTFOLIO_DISCLOSURE",
                "holdings": [],
            }
        },
        "portfolio_disclosure_source_bytes_by_scheme_id": {
            "SCHEME_DIRECT_1": disclosure_bytes
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
                "direct_plan_evidence": {
                    "source_file": "factsheet.pdf",
                    "source_document_sha256": hashlib.sha256(factsheet_bytes).hexdigest(),
                    "source_url": "https://amc.example/factsheet.pdf",
                    "source_type": "AMC_FACTSHEET",
                    "reviewer_attested": True,
                    "plan": "Direct",
                    "scheme_name": "Scheme A Direct Growth",
                    "scheme_id": "SCHEME_DIRECT_1",
                    "isin": "INF000000001",
                    "amc_name": "AMC One",
                    "reviewed_at": "2026-11-04",
                },
                "_evidence_root": tmp_path,
            }
        ],
        "candidate_universe_source": {
            "status": "VERIFIED",
            "source_url": "https://amfiindia.com/candidates",
            "source_document_sha256": hashlib.sha256(candidate_bytes).hexdigest(),
            "reviewer_attested": True,
            "effective_date": "2026-11-04",
            "source_type": "AMFI_CANDIDATE_UNIVERSE",
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
            "effective_date": "2026-11-04",
            "source_type": "AMFI_FUND_METRICS",
            "normalized_metrics_sha256": hashlib.sha256(metrics_file.read_bytes()).hexdigest(),
            "publisher": "AMFI",
            "coverage_scope": "ALL_REGISTERED_DIRECT_FLEXI_CAP",
            "record_count": 1,
            "reviewer_id": "independent-reviewer",
            "policy_version": "holdings-metrics-v1",
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
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_aliases_path_without_source_metadata_and_bytes_is_rejected(tmp_path):
    payload = _base_payload(tmp_path)
    aliases_file = tmp_path / "aliases.json"
    aliases_file.write_bytes(b'{"aliases": {}}')
    payload["aliases_path"] = aliases_file
    with pytest.raises(EvidenceProviderContractError, match="Fund aliases path requires both aliases_source_metadata and aliases_source_bytes"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_aliases_metadata_and_bytes_must_be_supplied_together(tmp_path):
    payload = _base_payload(tmp_path)
    aliases_file = tmp_path / "aliases.json"
    aliases_file.write_bytes(b'{"aliases": {}}')
    payload["aliases_path"] = aliases_file
    payload["aliases_source_metadata"] = {"status": "VERIFIED"}
    with pytest.raises(EvidenceProviderContractError, match="supplied together"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


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
        "effective_date": "2026-11-04",
        "source_type": "AMFI_ALIASES",
        "publisher": "AMFI",
        "coverage_scope": "Scheme-name variants",
        "record_count": 1,
        "reviewer_id": "independent-reviewer",
        "policy_version": "alias-resolution-v1",
        "normalized_aliases_sha256": "0" * 64,
    }
    payload["aliases_source_bytes"] = raw_source
    with pytest.raises(EvidenceProviderContractError, match="SHA-256 does not match"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


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
        "effective_date": "2026-11-04",
        "source_type": "AMFI_ALIASES",
        "publisher": "AMFI",
        "coverage_scope": "Scheme-name variants",
        "record_count": 1,
        "reviewer_id": "independent-reviewer",
        "policy_version": "alias-resolution-v1",
        "normalized_aliases_sha256": hashlib.sha256(aliases_file.read_bytes()).hexdigest(),
    }
    payload["aliases_source_bytes"] = raw_source
    with pytest.raises(EvidenceProviderContractError, match="absent from verified scheme master"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


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
        "effective_date": "2026-11-04",
        "source_type": "AMFI_ALIASES",
        "publisher": "AMFI",
        "coverage_scope": "Scheme-name variants",
        "record_count": 1,
        "reviewer_id": "independent-reviewer",
        "policy_version": "alias-resolution-v1",
        "normalized_aliases_sha256": hashlib.sha256(aliases_file.read_bytes()).hexdigest(),
    }
    payload["aliases_source_bytes"] = raw_source
    res = validate_evidence_provider_payload(payload, require_reviewer_signature=False)
    assert res["aliases_path"] == aliases_file

@pytest.mark.parametrize(
    "alias_payload",
    [
        [],
        {"aliases": []},
        {"aliases": {"SCHEME_DIRECT_1": []}},
        {"aliases": {"SCHEME_DIRECT_1": ["", "   "]}},
        {"": "SCHEME_DIRECT_1"},
        {"Old Scheme": ""},
    ],
)
def test_aliases_reject_malformed_or_empty_mappings(tmp_path, alias_payload):
    payload = _base_payload(tmp_path)
    aliases_file = tmp_path / "aliases.json"
    aliases_file.write_text(json.dumps(alias_payload))
    raw_source = b"source bytes for malformed aliases"
    payload["aliases_path"] = aliases_file
    payload["aliases_source_metadata"] = {
        "status": "VERIFIED",
        "source_url": "https://amfiindia.com/aliases",
        "source_document_sha256": hashlib.sha256(raw_source).hexdigest(),
        "reviewer_attested": True,
        "effective_date": "2026-11-04",
        "source_type": "AMFI_ALIASES",
        "publisher": "AMFI",
        "coverage_scope": "Scheme-name variants",
        "record_count": 1,
        "reviewer_id": "independent-reviewer",
        "policy_version": "alias-resolution-v1",
        "normalized_aliases_sha256": hashlib.sha256(aliases_file.read_bytes()).hexdigest(),
    }
    payload["aliases_source_bytes"] = raw_source
    with pytest.raises(EvidenceProviderContractError, match="Fund aliases"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)

def _exact_metrics_record(**overrides):
    record = {
        "id": "SCHEME_DIRECT_1",
        "scheme_id": "SCHEME_DIRECT_1",
        "isin": "INF000000001",
        "amc_name": "AMC One",
        "category": "Flexi Cap Equity",
        "plan_type": "Direct",
        "option_type": "Growth",
        "benchmark_identity": "NIFTY 500 TRI",
        "effective_date": "2026-11-04",
        "source_ref": "sha256:" + "a" * 64,
        "eq": 80.0, "debt": 20.0, "lc": 50.0, "mc": 20.0, "sc": 10.0,
        "market_cap_basis": "TOTAL_PORTFOLIO_PCT",
    }
    record.update(overrides)
    return record


def _exact_scheme_master():
    return {
        "status": "VERIFIED",
        "schemes": [{
            "scheme_id": "SCHEME_DIRECT_1",
            "isin": "INF000000001",
            "amc_name": "AMC One",
            "category": "Flexi Cap Equity",
            "plan_type": "Direct",
            "option_type": "Growth",
            "benchmark_identity": "NIFTY 500 TRI",
        }],
    }


def test_exact_metrics_provenance_accepts_one_source_bound_identity_snapshot():
    from core.math_engine import _validate_metrics_provenance

    result = _validate_metrics_provenance(
        {"scheme-direct-1": _exact_metrics_record()},
        _exact_scheme_master(),
        require_exact_identity=True,
    )
    assert result["status"] == "VERIFIED"
    assert result["record_count"] == 1
    assert result["identity_complete"] is True
    assert len(result["effective_dates"]) == 1
    assert len(result["source_refs"]) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("category", "Small Cap Equity"),
        ("plan_type", "Regular"),
        ("option_type", "IDCW"),
        ("benchmark_identity", "NIFTY 50 TRI"),
        ("amc_name", "Different AMC"),
        ("isin", "INF000000999"),
    ],
)
def test_exact_metrics_provenance_rejects_scheme_identity_tuple_conflicts(field, value):
    from core.math_engine import _validate_metrics_provenance

    with pytest.raises(ValueError, match="identity|conflicts"):
        _validate_metrics_provenance(
            {"scheme-direct-1": _exact_metrics_record(**{field: value})},
            _exact_scheme_master(),
            require_exact_identity=True,
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"effective_date": None},
        {"effective_date": "04-11-2026"},
        {"source_ref": None},
        {"source_ref": "not-a-digest"},
    ],
)
def test_exact_metrics_provenance_rejects_missing_or_invalid_record_lineage(overrides):
    from core.math_engine import _validate_metrics_provenance

    with pytest.raises(ValueError, match="provenance|source reference|effective"):
        _validate_metrics_provenance(
            {"scheme-direct-1": _exact_metrics_record(**overrides)},
            _exact_scheme_master(),
            require_exact_identity=True,
        )


def test_exact_metrics_provenance_rejects_missing_or_unverified_scheme_master():
    from core.math_engine import _validate_metrics_provenance

    with pytest.raises(ValueError, match="VERIFIED scheme master"):
        _validate_metrics_provenance(
            {"scheme-direct-1": _exact_metrics_record()},
            {"status": "UNVERIFIED", "schemes": _exact_scheme_master()["schemes"]},
            require_exact_identity=True,
        )
    with pytest.raises(ValueError, match="non-empty VERIFIED scheme master"):
        _validate_metrics_provenance(
            {"scheme-direct-1": _exact_metrics_record()},
            None,
            require_exact_identity=True,
        )


def test_exact_metrics_provenance_rejects_duplicate_scheme_or_isin_records():
    from core.math_engine import _validate_metrics_provenance

    duplicate = _exact_metrics_record(id="SECOND_METRICS_ID")
    with pytest.raises(ValueError, match="duplicates scheme ID or ISIN"):
        _validate_metrics_provenance(
            {
                "scheme-direct-1": _exact_metrics_record(),
                "second-metrics-id": duplicate,
            },
            _exact_scheme_master(),
            require_exact_identity=True,
        )


def test_exact_metrics_provenance_rejects_mixed_snapshot_lineage():
    from core.math_engine import _validate_metrics_provenance

    first = _exact_metrics_record()
    second = _exact_metrics_record(
        id="SCHEME_DIRECT_2",
        scheme_id="SCHEME_DIRECT_2",
        isin="INF000000002",
        effective_date="2026-11-03",
        source_ref="sha256:" + "b" * 64,
    )
    master = _exact_scheme_master()
    second_master = dict(master["schemes"][0])
    second_master.update({
        "scheme_id": "SCHEME_DIRECT_2",
        "isin": "INF000000002",
    })
    master["schemes"].append(second_master)
    with pytest.raises(ValueError, match="mixed snapshot"):
        _validate_metrics_provenance(
            {"first": first, "second": second},
            master,
            require_exact_identity=True,
        )

