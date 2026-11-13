from datetime import date, datetime
import json
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


def valid_payload(tmp_path):
    master_bytes = b"source master"
    universe_bytes = b"source candidate universe"
    direct_bytes = b"direct plan factsheet"
    disclosure_bytes = b"source disclosure"
    (tmp_path / "direct.pdf").write_bytes(direct_bytes)
    metrics_source_bytes = b"original current-holdings metrics source"
    metric_record = {
        "id": "scheme-1", "scheme_id": "scheme-1", "isin": "INF000000001",
        "amc_name": "Example AMC", "category": "Flexi Cap", "cat": "Flexi Cap",
        "plan_type": "Direct", "option_type": "Growth",
        "benchmark_identity": "Nifty 500 TRI", "effective_date": "2026-11-01",
        "source_ref": "sha256:" + hashlib.sha256(metrics_source_bytes).hexdigest(),
        "eq": 80.0, "debt": 20.0, "lc": 50.0, "mc": 20.0, "sc": 10.0,
        "market_cap_basis": "TOTAL_PORTFOLIO_PCT",
        "ter_plan": "direct", "er": 0.5,
    }
    metrics_bytes = json.dumps({"funds": [metric_record]}, separators=(",", ":")).encode()
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_bytes(metrics_bytes)
    return {
        "metrics_path": metrics_path,
        "aliases_path": None,
        "metrics_source_metadata": {
            **_source_metadata(metrics_source_bytes),
            "source_type": "OFFICIAL_FUND_METRICS",
            "normalized_metrics_sha256": hashlib.sha256(metrics_bytes).hexdigest(),
            "policy_version": "holdings-metrics-v1",
            "reviewer_id": "reviewer-1",
        },
        "metrics_source_bytes": metrics_source_bytes,
        "scheme_master": {
            **_source_metadata(master_bytes),
            "status": "VERIFIED",
            "schemes": [{
                "scheme_id": "scheme-1", "isin": "INF000000001",
                "scheme_name": "Example Direct Growth", "amc_name": "Example AMC",
                "category": "Flexi Cap", "benchmark_identity": "Nifty 500 TRI",
                "scheme_structure": "OPEN_ENDED_EQUITY",
                "plan_type": "Direct", "option_type": "Growth", "riskometer_score": 5,
            }],
        },
        "scheme_master_source_bytes": master_bytes,
        "portfolio_disclosures_by_scheme_id": {"scheme-1": {
            "scheme_id": "scheme-1",
            "constituent_weights": {"Reliance Industries Limited": 100.0},
            "constituent_weights_coverage_pct": 100.0,
            "source_url": "https://amfiindia.com/disclosure.pdf",
            "source_document_sha256": hashlib.sha256(disclosure_bytes).hexdigest(),
            "reviewer_attested": True,
            "effective_date": "2026-11-04",
            "source_type": "AMFI_DISCLOSURE",
        }},
        "portfolio_disclosure_source_bytes_by_scheme_id": {"scheme-1": disclosure_bytes},
        "disclosure_as_of_date": date(2026, 11, 4),
        "candidate_universe": [{
            "fund_id": "fund-1", "fund_name": "Example Direct Growth",
            "scheme_id": "scheme-1", "isin": "INF000000001",
            "amc_name": "Example AMC", "category": "Flexi Cap",
            "benchmark_identity": "Nifty 500 TRI",
            "scheme_structure": "OPEN_ENDED_EQUITY",
                "plan_type": "Direct", "option_type": "Growth", "riskometer_score": 5,
            "is_direct": True,
            "_evidence_root": str(tmp_path),
            "direct_plan_evidence": {
                "source_file": "direct.pdf",
                "source_document_sha256": hashlib.sha256(direct_bytes).hexdigest(),
                "source_url": "https://amfiindia.com/direct.pdf",
                "source_type": "AMC_FACTSHEET",
                "reviewer_attested": True,
                "plan": "Direct",
                "scheme_name": "Example Direct Growth",
                "scheme_id": "scheme-1",
                "isin": "INF000000001",
                "amc_name": "Example AMC",
                "reviewed_at": "2026-11-01",
            },
        }],
        "candidate_universe_source": {**_source_metadata(universe_bytes), "universe_complete": True, "coverage_scope": "All eligible open-ended equity and debt schemes"},
        "candidate_universe_source_bytes": universe_bytes,
    }


def test_contract_accepts_source_backed_candidate_identity(tmp_path):
    payload = valid_payload(tmp_path)
    result = validate_evidence_provider_payload(payload, require_reviewer_signature=False)

    assert REQUIRED_EVIDENCE_FIELDS <= set(result)


def test_contract_rejects_missing_required_field(tmp_path):
    payload = valid_payload(tmp_path)
    payload.pop("candidate_universe")

    with pytest.raises(EvidenceProviderContractError, match="candidate_universe"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_unexpected_and_request_override_fields(tmp_path):
    payload = valid_payload(tmp_path)
    payload["monthly_budget_inr"] = 50000

    with pytest.raises(EvidenceProviderContractError, match="unsupported fields"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_source_hash_mismatch(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe_source_bytes"] = b"tampered"

    with pytest.raises(EvidenceProviderContractError, match="SHA-256 does not match"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_requires_reviewer_attestation(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe_source"]["reviewer_attested"] = False

    with pytest.raises(EvidenceProviderContractError, match="reviewer attestation"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_requires_exact_disclosure_source_key_coverage(tmp_path):
    payload = valid_payload(tmp_path)
    payload["portfolio_disclosure_source_bytes_by_scheme_id"] = {}

    with pytest.raises(EvidenceProviderContractError, match="identical scheme-ID keys"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_disclosure_scheme_id_not_in_master(tmp_path):
    payload = valid_payload(tmp_path)
    payload["portfolio_disclosures_by_scheme_id"] = {"other": {"scheme_id": "other"}}
    payload["portfolio_disclosure_source_bytes_by_scheme_id"] = {"other": b"source"}

    with pytest.raises(EvidenceProviderContractError, match="absent from verified scheme master"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_timestamp_as_decision_date(tmp_path):
    payload = valid_payload(tmp_path)
    payload["disclosure_as_of_date"] = datetime(2026, 11, 4)

    with pytest.raises(EvidenceProviderContractError, match="not a timestamp"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_duplicate_candidate_fund_ids(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe"].append(dict(payload["candidate_universe"][0]))

    with pytest.raises(EvidenceProviderContractError, match="Duplicate candidate fund_id"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_scheme_master_missing_plan_or_option_identity(tmp_path):
    payload = valid_payload(tmp_path)
    payload["scheme_master"]["schemes"][0].pop("option_type")

    with pytest.raises(EvidenceProviderContractError, match="option_type"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_candidate_option_conflicting_with_scheme_master(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe"][0]["option_type"] = "IDCW"

    with pytest.raises(EvidenceProviderContractError, match="option_type conflicts"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_regular_candidate_for_direct_sip_universe(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe"][0]["plan_type"] = "Regular"
    payload["scheme_master"]["schemes"][0]["plan_type"] = "Regular"
    payload["candidate_universe"][0]["is_direct"] = False

    with pytest.raises(EvidenceProviderContractError, match="explicitly verified Direct"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_candidate_identity_conflicting_with_scheme_master(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe"][0]["isin"] = "INF999999999"

    with pytest.raises(EvidenceProviderContractError, match="identity conflicts"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_candidate_missing_required_identity_field(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe"][0].pop("amc_name")

    with pytest.raises(EvidenceProviderContractError, match="requires amc_name"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_unattested_incomplete_candidate_universe(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe_source"]["universe_complete"] = False

    with pytest.raises(EvidenceProviderContractError, match="explicitly reviewer-attested as complete"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_stale_candidate_universe_source(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe_source"]["effective_date"] = "2026-08-01"

    with pytest.raises(EvidenceProviderContractError, match="source is stale"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_source_url_with_whitespace(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe_source"]["source_url"] = "https://example.com/file name.pdf"

    with pytest.raises(EvidenceProviderContractError, match="source URL must be HTTPS"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_regular_plan_candidate(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe"][0]["direct_plan_evidence"]["plan"] = "Regular"

    with pytest.raises(EvidenceProviderContractError, match="Direct-plan source evidence"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_direct_plan_evidence_for_different_scheme_id(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe"][0]["direct_plan_evidence"]["scheme_id"] = "another-scheme"

    with pytest.raises(EvidenceProviderContractError, match="Direct-plan source evidence"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)



def test_contract_rejects_missing_fund_metrics_provenance(tmp_path):
    payload = valid_payload(tmp_path)
    payload.pop("metrics_source_metadata")
    payload.pop("metrics_source_bytes")

    with pytest.raises(EvidenceProviderContractError, match="mandatory"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_validates_optional_original_fund_metrics_source_bytes(tmp_path):
    payload = valid_payload(tmp_path)
    metrics_bytes = b"original metrics publisher document"
    payload["metrics_source_metadata"] = {
        **_source_metadata(metrics_bytes),
        "source_type": "OFFICIAL_FUND_METRICS",
        "normalized_metrics_sha256": hashlib.sha256(payload["metrics_path"].read_bytes()).hexdigest(),
    }
    payload["metrics_source_bytes"] = metrics_bytes

    result = validate_evidence_provider_payload(payload, require_reviewer_signature=False)

    assert result["metrics_source_bytes"] == metrics_bytes


def test_contract_rejects_tampered_normalized_metrics_file(tmp_path):
    payload = valid_payload(tmp_path)
    payload["metrics_path"].write_bytes(b'{"funds":[{"eq":100}]}')

    with pytest.raises(EvidenceProviderContractError, match="normalized file SHA-256"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_fund_metrics_source_hash_mismatch(tmp_path):
    payload = valid_payload(tmp_path)
    payload["metrics_source_metadata"] = {
        **_source_metadata(b"declared metrics source"),
        "source_type": "OFFICIAL_FUND_METRICS",
    }
    payload["metrics_source_bytes"] = b"tampered metrics source"

    with pytest.raises(EvidenceProviderContractError, match="Fund metrics source SHA-256 does not match"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_partial_fund_metrics_provenance_pair(tmp_path):
    payload = valid_payload(tmp_path)
    payload.pop("metrics_source_metadata")
    payload["metrics_source_bytes"] = b"metrics source without metadata"

    with pytest.raises(EvidenceProviderContractError, match="must be supplied together"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_accepts_provider_attested_total_portfolio_bundle(tmp_path):
    payload = valid_payload(tmp_path)
    context_bytes = b"reviewed total portfolio, IPS, goals and affordability evidence bundle"
    payload["portfolio_context"] = {
        "evidence_attested_by_provider": True,
        "as_of_date": "2026-11-04",
        "perimeter_complete": True,
    }
    payload["portfolio_context_source_metadata"] = {
        **_source_metadata(context_bytes),
        "source_type": "REVIEWED_TOTAL_PORTFOLIO_CONTEXT",
    }
    payload["portfolio_context_source_bytes"] = context_bytes

    result = validate_evidence_provider_payload(payload, require_reviewer_signature=False)

    assert result["portfolio_context"]["evidence_attested_by_provider"] is True
    assert result["portfolio_context_source_bytes"] == context_bytes


def test_contract_rejects_partial_total_portfolio_bundle(tmp_path):
    payload = valid_payload(tmp_path)
    payload["portfolio_context"] = {"evidence_attested_by_provider": True}

    with pytest.raises(EvidenceProviderContractError, match="must be supplied together"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_unverified_total_portfolio_source_bundle(tmp_path):
    payload = valid_payload(tmp_path)
    context_bytes = b"reviewed portfolio evidence"
    payload["portfolio_context"] = {"evidence_attested_by_provider": True}
    payload["portfolio_context_source_metadata"] = {
        **_source_metadata(context_bytes), "reviewer_attested": False,
        "source_type": "REVIEWED_TOTAL_PORTFOLIO_CONTEXT",
    }
    payload["portfolio_context_source_bytes"] = context_bytes

    with pytest.raises(EvidenceProviderContractError, match="reviewer attestation"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_accepts_rank_score_only_with_reviewed_source_bytes(tmp_path):
    payload = valid_payload(tmp_path)
    score_bytes = b"independently reviewed ranking scores"
    _attach_reviewed_rank_score_evidence(payload, score_bytes)

    result = validate_evidence_provider_payload(payload, require_reviewer_signature=False)
    assert result["candidate_universe"][0]["rank_score"] == "2.75"


def test_contract_rejects_rank_score_without_reviewed_source_bundle(tmp_path):
    payload = valid_payload(tmp_path)
    _attach_reviewed_rank_score_evidence(
        payload, b"ranking scores", include_score_bundle=False
    )
    with pytest.raises(EvidenceProviderContractError, match="without a reviewed score source bundle"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_rank_score_source_hash_or_methodology_mismatch(tmp_path):
    payload = valid_payload(tmp_path)
    score_bytes = b"reviewed scores"
    _attach_reviewed_rank_score_evidence(payload, score_bytes)
    payload["candidate_universe"][0]["rank_score_source_ref"] = "sha256:" + "f" * 64
    payload["candidate_universe"][0]["rank_score_methodology_version"] = "wrong-version"
    with pytest.raises(EvidenceProviderContractError, match="source reference does not match"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def _attach_reviewed_rank_score_evidence(payload, score_bytes, *, include_score_bundle=True):
    candidate = payload["candidate_universe"][0]
    score_metadata = _source_metadata(score_bytes)
    score_metadata.update({
        "source_type": "REVIEWED_CANDIDATE_RANKING",
        "methodology_version": "risk-quality-v1",
        "score_scope": "PORTFOLIO_AWARE",
        "missing_overlap_policy": "BLOCK_SCORE",
    })
    candidate.update({
        "rank_score": "2.75",
        "rank_score_source_ref": "sha256:" + hashlib.sha256(score_bytes).hexdigest(),
        "rank_score_as_of_date": score_metadata["effective_date"],
        "rank_score_methodology_version": "risk-quality-v1",
        "rank_score_scope": "PORTFOLIO_AWARE",
        "rank_score_portfolio_overlap_status": "VERIFIED",
        "rank_score_portfolio_overlap_pct": "15.5",
        "rank_score_portfolio_overlap_coverage_pct": "99.8",
        "rank_score_portfolio_overlap_source_ref": "sha256:" + hashlib.sha256(b"portfolio overlap source").hexdigest(),
    })
    anchor_bytes = b"reviewed category benchmark anchor source"
    anchor_digest = hashlib.sha256(anchor_bytes).hexdigest()
    anchor_metadata = _source_metadata(anchor_bytes)
    anchor_metadata.update({
        "source_type": "APPROVED_CATEGORY_BENCHMARK_ANCHORS",
        "reviewer_id": "independent-reviewer",
        "policy_version": "category-anchor-v1",
        "category_anchors": {
            candidate["category"]: {
                "status": "APPROVED",
                "benchmark_identity": "Example Category TRI",
                "reviewer_id": "independent-reviewer",
                "policy_version": "category-anchor-v1",
                "effective_date": anchor_metadata["effective_date"],
                "anchor_set": {
                    "alpha": [0, 10], "ret1y": [0, 30], "sharpe": [0.2, 1.2],
                    "ter": [0.2, 1.2], "buffer": [0, 25], "intl": [0, 50],
                    "overlap": [0, 100],
                },
            }
        },
    })
    candidate.update({
        "rank_score_category_anchor_source_ref": "sha256:" + anchor_digest,
        "rank_score_category_anchor_policy_version": "category-anchor-v1",
        "rank_score_benchmark_identity": "Example Category TRI",
    })
    payload["category_anchor_source_metadata"] = anchor_metadata
    payload["category_anchor_source_bytes"] = anchor_bytes
    if include_score_bundle:
        payload["candidate_score_source_metadata"] = score_metadata
        payload["candidate_score_source_bytes"] = score_bytes



def test_contract_rejects_candidate_category_conflicting_with_verified_scheme_master(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe"][0]["category"] = "Small Cap"
    with pytest.raises(EvidenceProviderContractError, match="category conflicts"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_candidate_suitability_override(tmp_path):
    payload = valid_payload(tmp_path)
    payload["candidate_universe"][0]["riskometer_score"] = 2
    with pytest.raises(EvidenceProviderContractError, match="riskometer_score conflicts"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_rejects_boolean_candidate_riskometer_score(tmp_path):
    payload = valid_payload(tmp_path)
    # bool is a subclass of int in Python; equality with 1 must not pass
    # an integer Riskometer identity check.
    payload["scheme_master"]["schemes"][0]["riskometer_score"] = 1
    payload["candidate_universe"][0]["riskometer_score"] = True

    with pytest.raises(EvidenceProviderContractError, match="must be a verified integer"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_contract_requires_scheme_master_category_benchmark_and_structure(tmp_path):
    payload = valid_payload(tmp_path)
    payload["scheme_master"]["schemes"][0].pop("category")
    with pytest.raises(EvidenceProviderContractError, match="category, benchmark or structure"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)

def test_signed_source_validation_uses_utc_aware_review_time(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from services import sip_reviewer_approval
    from services.sip_evidence_contract import _validate_source_document

    raw = b"independently signed source"
    metadata = {
        **_source_metadata(raw),
        "reviewer_approval_envelope": {"signature": "synthetic"},
    }
    captured = {}

    def verify(envelope, trust_registry, *, expected_scope, expected_source_sha256,
               structured_records, expected_scheme_id=None, repository="o0k00l/MF-AI-Based", now):
        captured["now"] = now
        captured["scope"] = expected_scope
        return SimpleNamespace(ok=True, errors=[])

    monkeypatch.setattr(sip_reviewer_approval, "verify_sip_reviewer_approval", verify)
    _validate_source_document(
        metadata,
        raw,
        label="Test source",
        as_of=date(2026, 11, 4),
        trust_registry={},
        scope="SIP_TEST_SOURCE",
    )

    assert captured["scope"] == "SIP_TEST_SOURCE"
    assert captured["now"].isoformat() == "2026-11-04T00:00:00+00:00"
    assert captured["now"].utcoffset().total_seconds() == 0


def test_contract_requires_independent_signature_by_default(tmp_path):
    payload = valid_payload(tmp_path)
    with pytest.raises(EvidenceProviderContractError, match="verifiable independent reviewer signature"):
        validate_evidence_provider_payload(payload)


def test_production_contract_rejects_missing_independent_trust_registry(tmp_path):
    payload = valid_payload(tmp_path)
    payload["scheme_master"]["reviewer_approval_envelope"] = {
        "payload": {}, "signature": "invalid"
    }
    with pytest.raises(EvidenceProviderContractError, match="independently administered trust registry"):
        validate_evidence_provider_payload(
            payload, trust_registry=None, require_reviewer_signature=True
        )


def test_alias_document_cannot_carry_financial_facts(tmp_path):
    payload = valid_payload(tmp_path)
    alias_data = {"aliases": {"scheme-1": ["Example Direct Growth"]}, "category": "Small Cap"}
    alias_bytes = json.dumps(alias_data, separators=(",", ":")).encode()
    alias_path = tmp_path / "aliases.json"
    alias_path.write_bytes(alias_bytes)
    payload.update({
        "aliases_path": alias_path,
        "aliases_source_bytes": b"alias source",
        "aliases_source_metadata": {
            **_source_metadata(b"alias source"),
            "normalized_aliases_sha256": hashlib.sha256(alias_bytes).hexdigest(),
            "coverage_scope": "Scheme-name variants",
            "record_count": 1, "policy_version": "alias-policy-v1", "reviewer_id": "reviewer-1",
        },
    })
    with pytest.raises(EvidenceProviderContractError, match="financial facts are prohibited"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_aliases_cannot_map_same_name_to_multiple_schemes(tmp_path):
    payload = valid_payload(tmp_path)
    payload["scheme_master"]["schemes"].append({
        "scheme_id": "scheme-2", "isin": "INF000000002",
        "scheme_name": "Another Direct Growth", "amc_name": "Example AMC",
        "category": "Flexi Cap", "benchmark_identity": "Nifty 500 TRI",
        "scheme_structure": "OPEN_ENDED_EQUITY", "plan_type": "Direct",
        "option_type": "Growth", "riskometer_score": 5,
    })
    alias_data = {"aliases": {
        "scheme-1": ["Same alias"], "scheme-2": [" same   alias "],
    }}
    alias_bytes = json.dumps(alias_data, separators=(",", ":")).encode()
    alias_path = tmp_path / "aliases.json"
    alias_path.write_bytes(alias_bytes)
    payload.update({
        "aliases_path": alias_path,
        "aliases_source_bytes": b"alias source",
        "aliases_source_metadata": {
            **_source_metadata(b"alias source"),
            "normalized_aliases_sha256": hashlib.sha256(alias_bytes).hexdigest(),
            "coverage_scope": "Scheme-name variants",
            "record_count": 2, "policy_version": "alias-policy-v1", "reviewer_id": "reviewer-1",
        },
    })
    with pytest.raises(EvidenceProviderContractError, match="ambiguously maps"):
        validate_evidence_provider_payload(payload, require_reviewer_signature=False)


def test_metrics_exact_identity_lineage_and_exposure_reconciliation(tmp_path):
    from core.math_engine import _validate_metrics_provenance

    metric = {
        "id": "scheme-1", "scheme_id": "scheme-1", "isin": "INF000000001",
        "amc_name": "Example AMC", "category": "Flexi Cap",
        "plan_type": "Direct", "option_type": "Growth",
        "benchmark_identity": "Nifty 500 TRI", "effective_date": "2026-11-01",
        "source_ref": "sha256:" + "a" * 64,
        "eq": 80, "debt": 20, "lc": 50, "mc": 20, "sc": 10,
        "market_cap_basis": "TOTAL_PORTFOLIO_PCT",
    }
    master = {
        "status": "VERIFIED",
        "schemes": [{
            "scheme_id": "scheme-1", "isin": "INF000000001",
            "amc_name": "Example AMC", "category": "Flexi Cap",
            "plan_type": "Direct", "option_type": "Growth",
            "benchmark_identity": "Nifty 500 TRI",
        }],
    }
    result = _validate_metrics_provenance(
        {"scheme-1": metric}, master, require_exact_identity=True,
        expected_source_sha256="a" * 64, expected_effective_date="2026-11-01",
    )
    assert result["status"] == "VERIFIED"

    with pytest.raises(ValueError, match="original source bytes"):
        _validate_metrics_provenance(
            {"scheme-1": {**metric, "source_ref": "sha256:" + "b" * 64}},
            master, require_exact_identity=True, expected_source_sha256="a" * 64,
            expected_effective_date="2026-11-01",
        )
    with pytest.raises(ValueError, match="effective date conflicts"):
        _validate_metrics_provenance(
            {"scheme-1": metric}, master, require_exact_identity=True,
            expected_source_sha256="a" * 64, expected_effective_date="2026-11-02",
        )
    for field, wrong in (
        ("scheme_id", "other"), ("isin", "INF999999999"),
        ("amc_name", "Other AMC"), ("category", "Small Cap"),
        ("plan_type", "Regular"), ("option_type", "IDCW"),
    ):
        with pytest.raises(ValueError):
            _validate_metrics_provenance(
                {"scheme-1": {**metric, field: wrong}}, master,
                require_exact_identity=True, expected_source_sha256="a" * 64,
                expected_effective_date="2026-11-01",
            )
    with pytest.raises(ValueError, match="eq exposure"):
        _validate_metrics_provenance(
            {"scheme-1": {**metric, "eq": float("nan")}}, master,
            require_exact_identity=True, expected_source_sha256="a" * 64,
            expected_effective_date="2026-11-01",
        )
    with pytest.raises(ValueError, match="exceeds equity"):
        _validate_metrics_provenance(
            {"scheme-1": {**metric, "eq": 60, "lc": 50, "mc": 20, "sc": 10}},
            master, require_exact_identity=True, expected_source_sha256="a" * 64,
            expected_effective_date="2026-11-01",
        )
