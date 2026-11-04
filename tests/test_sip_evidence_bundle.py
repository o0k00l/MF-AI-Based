import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from services.sip_evidence_bundle import build_sip_evidence_provider
from services.sip_evidence_contract import validate_evidence_provider_payload


def _write_json(root: Path, name: str, value) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _source(raw: bytes, source_type: str) -> dict:
    return {
        "source_url": "https://amfiindia.com/source",
        "source_document_sha256": hashlib.sha256(raw).hexdigest(),
        "reviewer_attested": True,
        "effective_date": date.today().isoformat(),
        "source_type": source_type,
    }


def _bundle(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    (root / "metrics.json").write_text('{"funds": []}', encoding="utf-8")
    metrics_bytes = b"original fund metrics source"
    (root / "originals").mkdir(parents=True, exist_ok=True)
    (root / "originals/metrics.csv").write_bytes(metrics_bytes)
    metrics_metadata = _source(metrics_bytes, "OFFICIAL_FUND_METRICS")
    metrics_metadata["normalized_metrics_sha256"] = hashlib.sha256(
        (root / "metrics.json").read_bytes()
    ).hexdigest()
    _write_json(root, "metrics_metadata.json", metrics_metadata)
    master_bytes = b"original scheme master"
    universe_bytes = b"original candidate universe"
    disclosure_bytes = b"original portfolio disclosure"
    direct_bytes = b"original direct plan factsheet"
    for name, raw in (
        ("originals/master.xlsx", master_bytes),
        ("originals/universe.csv", universe_bytes),
        ("originals/disclosure.xlsx", disclosure_bytes),
        ("originals/direct.pdf", direct_bytes),
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)

    scheme_id = "scheme-1"
    _write_json(root, "scheme_master.json", {
        **_source(master_bytes, "OFFICIAL_SCHEME_MASTER"),
        "status": "VERIFIED",
        "schemes": [{
            "scheme_id": scheme_id,
            "isin": "INF000000001",
            "scheme_name": "Example Direct Growth",
            "amc_name": "Example AMC",
        }],
    })
    _write_json(root, "disclosures/scheme-1.json", {
        **_source(disclosure_bytes, "AMC_PORTFOLIO_DISCLOSURE"),
        "scheme_id": scheme_id,
        "constituent_weights": {"RELIANCE": 100.0},
        "constituent_weights_coverage_pct": 100.0,
    })
    _write_json(root, "candidates.json", [{
        "fund_id": "fund-1",
        "fund_name": "Example Direct Growth",
        "scheme_id": scheme_id,
        "isin": "INF000000001",
        "amc_name": "Example AMC",
        "category": "Flexi Cap",
        "is_direct": True,
        "direct_plan_evidence": {
            "source_file": "originals/direct.pdf",
            "source_document_sha256": hashlib.sha256(direct_bytes).hexdigest(),
            "source_url": "https://amfiindia.com/direct.pdf",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Example Direct Growth",
            "scheme_id": scheme_id,
            "isin": "INF000000001",
            "amc_name": "Example AMC",
            "reviewed_at": date.today().isoformat(),
        },
    }])
    _write_json(root, "candidate_metadata.json", {
        **_source(universe_bytes, "REVIEWED_CANDIDATE_UNIVERSE"),
        "universe_complete": True,
        "coverage_scope": "All reviewed direct equity schemes",
        "normalized_candidate_universe_sha256": hashlib.sha256(
            (root / "candidates.json").read_bytes()
        ).hexdigest(),
    })
    manifest = {
        "schema_version": 1,
        "disclosure_as_of_date": date.today().isoformat(),
        "metrics_file": "metrics.json",
        "metrics_metadata_file": "metrics_metadata.json",
        "metrics_source_file": "originals/metrics.csv",
        "aliases_file": None,
        "scheme_master_file": "scheme_master.json",
        "scheme_master_source_file": "originals/master.xlsx",
        "portfolio_disclosures": {
            scheme_id: {
                "record_file": "disclosures/scheme-1.json",
                "source_file": "originals/disclosure.xlsx",
            }
        },
        "candidate_universe_file": "candidates.json",
        "candidate_universe_metadata_file": "candidate_metadata.json",
        "candidate_universe_source_file": "originals/universe.csv",
    }
    _write_json(root, "manifest.json", manifest)
    return manifest


def test_provider_is_not_configured_when_bundle_path_is_unset(monkeypatch):
    monkeypatch.delenv("MF_SIP_EVIDENCE_BUNDLE_DIR", raising=False)
    assert build_sip_evidence_provider() is None


def test_provider_loads_only_explicit_bundle_and_passes_source_contract(tmp_path):
    _bundle(tmp_path)
    cas_path = tmp_path / "cas.xlsx"
    cas_path.write_bytes(b"temporary uploaded CAS")
    provider = build_sip_evidence_provider(tmp_path)

    payload = provider(
        cas_path=cas_path,
        monthly_budget_inr=25000,
        risk_profile="Moderate",
    )
    validated = validate_evidence_provider_payload(payload)

    assert validated["scheme_master"]["schemes"][0]["scheme_id"] == "scheme-1"
    assert validated["metrics_source_bytes"] == b"original fund metrics source"
    assert validated["portfolio_disclosure_source_bytes_by_scheme_id"]["scheme-1"] == b"original portfolio disclosure"
    assert validated["candidate_universe"][0]["_evidence_root"] == str(tmp_path.resolve())


def test_provider_rejects_path_traversal_in_manifest(tmp_path):
    manifest = _bundle(tmp_path)
    (tmp_path.parent / "outside.xlsx").write_bytes(b"outside")
    manifest["scheme_master_source_file"] = "../outside.xlsx"
    _write_json(tmp_path, "manifest.json", manifest)

    with pytest.raises(ValueError, match="escapes the configured evidence bundle"):
        build_sip_evidence_provider(tmp_path)


def test_provider_rejects_bundle_inside_repository_checkout():
    repository_root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="outside the Git checkout"):
        build_sip_evidence_provider(repository_root)



def test_provider_rejects_tampered_normalized_metrics_file(tmp_path):
    _bundle(tmp_path)
    (tmp_path / "metrics.json").write_text('{"funds": [{"id": "unreviewed"}]}', encoding="utf-8")

    with pytest.raises(ValueError, match="Normalized fund metrics SHA-256"):
        build_sip_evidence_provider(tmp_path)


def test_provider_loads_portfolio_context_and_original_source_bundle(tmp_path):
    manifest = _bundle(tmp_path)
    context_bytes = b"reviewed total portfolio context"
    context_metadata = _source(context_bytes, "REVIEWED_TOTAL_PORTFOLIO_CONTEXT")
    _write_json(tmp_path, "portfolio_context.json", {
        "as_of_date": date.today().isoformat(),
        "perimeter_complete": True,
        "assets": [],
    })
    _write_json(tmp_path, "portfolio_context_metadata.json", context_metadata)
    (tmp_path / "originals/portfolio_context.json").write_bytes(context_bytes)
    manifest.update({
        "portfolio_context_file": "portfolio_context.json",
        "portfolio_context_metadata_file": "portfolio_context_metadata.json",
        "portfolio_context_source_file": "originals/portfolio_context.json",
    })
    _write_json(tmp_path, "manifest.json", manifest)
    cas_path = tmp_path / "cas.xlsx"
    cas_path.write_bytes(b"temporary uploaded CAS")

    provider = build_sip_evidence_provider(tmp_path)
    validated = validate_evidence_provider_payload(provider(
        cas_path=cas_path, monthly_budget_inr=15000, risk_profile="Moderate"
    ))
    assert validated["portfolio_context"]["perimeter_complete"] is True
    assert validated["portfolio_context_source_bytes"] == context_bytes
    assert validated["portfolio_context_source_metadata"]["source_type"] == "REVIEWED_TOTAL_PORTFOLIO_CONTEXT"


def test_provider_rejects_partial_portfolio_context_manifest(tmp_path):
    manifest = _bundle(tmp_path)
    manifest["portfolio_context_file"] = "portfolio_context.json"
    _write_json(tmp_path, "manifest.json", manifest)
    with pytest.raises(ValueError, match="must be configured together"):
        build_sip_evidence_provider(tmp_path)


def test_provider_rejects_tampered_normalized_candidate_universe(tmp_path):
    _bundle(tmp_path)
    _write_json(tmp_path, "candidates.json", [{"fund_id": "tampered"}])
    with pytest.raises(ValueError, match="Normalized candidate universe SHA-256"):
        build_sip_evidence_provider(tmp_path)


def test_provider_loads_separately_reviewed_candidate_score_source_bundle(tmp_path):
    manifest = _bundle(tmp_path)
    score_bytes = b"original reviewed ranking-model score export"
    score_metadata = _source(score_bytes, "REVIEWED_CANDIDATE_RANKING")
    score_metadata["methodology_version"] = "risk-quality-v1"
    candidates = json.loads((tmp_path / "candidates.json").read_text(encoding="utf-8"))
    candidates[0].update({
        "rank_score": "3.5",
        "rank_score_source_ref": "sha256:" + hashlib.sha256(score_bytes).hexdigest(),
        "rank_score_as_of_date": score_metadata["effective_date"],
        "rank_score_methodology_version": "risk-quality-v1",
    })
    _write_json(tmp_path, "candidates.json", candidates)
    candidate_metadata = json.loads((tmp_path / "candidate_metadata.json").read_text(encoding="utf-8"))
    candidate_metadata["normalized_candidate_universe_sha256"] = hashlib.sha256(
        (tmp_path / "candidates.json").read_bytes()
    ).hexdigest()
    _write_json(tmp_path, "candidate_metadata.json", candidate_metadata)
    (tmp_path / "originals/candidate_scores.csv").write_bytes(score_bytes)
    _write_json(tmp_path, "candidate_score_metadata.json", score_metadata)
    manifest.update({
        "candidate_score_metadata_file": "candidate_score_metadata.json",
        "candidate_score_source_file": "originals/candidate_scores.csv",
    })
    _write_json(tmp_path, "manifest.json", manifest)
    cas_path = tmp_path / "cas.xlsx"
    cas_path.write_bytes(b"temporary uploaded CAS")

    provider = build_sip_evidence_provider(tmp_path)
    validated = validate_evidence_provider_payload(provider(
        cas_path=cas_path, monthly_budget_inr=10000, risk_profile="Moderate"
    ))
    assert validated["candidate_score_source_bytes"] == score_bytes
    assert validated["candidate_universe"][0]["rank_score"] == "3.5"


def test_provider_rejects_partial_candidate_score_manifest(tmp_path):
    manifest = _bundle(tmp_path)
    manifest["candidate_score_metadata_file"] = "candidate_score_metadata.json"
    _write_json(tmp_path, "manifest.json", manifest)
    with pytest.raises(ValueError, match="must be configured together"):
        build_sip_evidence_provider(tmp_path)
