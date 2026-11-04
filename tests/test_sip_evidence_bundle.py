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
    })
    manifest = {
        "schema_version": 1,
        "disclosure_as_of_date": date.today().isoformat(),
        "metrics_file": "metrics.json",
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
    provider = build_sip_evidence_provider(tmp_path)

    payload = provider(
        cas_path=tmp_path / "cas.xlsx",
        monthly_budget_inr=25000,
        risk_profile="Moderate",
    )
    (tmp_path / "cas.xlsx").write_bytes(b"temporary uploaded CAS")
    validated = validate_evidence_provider_payload(payload)

    assert validated["scheme_master"]["schemes"][0]["scheme_id"] == "scheme-1"
    assert validated["portfolio_disclosure_source_bytes_by_scheme_id"]["scheme-1"] == b"original portfolio disclosure"
    assert validated["candidate_universe"][0]["_evidence_root"] == str(tmp_path.resolve())


def test_provider_rejects_path_traversal_in_manifest(tmp_path):
    manifest = _bundle(tmp_path)
    manifest["scheme_master_source_file"] = "../outside.xlsx"
    _write_json(tmp_path, "manifest.json", manifest)

    with pytest.raises(ValueError, match="escapes the configured evidence bundle"):
        build_sip_evidence_provider(tmp_path)


def test_provider_rejects_bundle_inside_repository_checkout():
    repository_root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError, match="outside the Git checkout"):
        build_sip_evidence_provider(repository_root)
