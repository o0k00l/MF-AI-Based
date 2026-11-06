import hashlib
import json
from datetime import date
from pathlib import Path

from core.eligibility import load_candidate_universe, _reviewed_direct_plan_evidence_status


def test_candidate_loader_binds_direct_evidence_to_scheme_id_isin_and_amc(tmp_path):
    source = b"reviewed AMC factsheet"
    (tmp_path / "direct.pdf").write_bytes(source)
    record = {
        "id": "fund-1",
        "name": "Example Direct Growth",
        "scheme_id": "scheme-1",
        "isin": "INF000000001",
        "amc_name": "Example AMC",
        "category": "Flexi Cap",
        "is_direct": True,
        "_evidence_root": str(tmp_path),
        "as_of_date": date.today().isoformat(),
        "direct_plan_evidence": {
            "source_file": "direct.pdf",
            "source_document_sha256": hashlib.sha256(source).hexdigest(),
            "source_url": "https://amc.example/direct.pdf",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Example Direct Growth",
            "scheme_id": "scheme-1",
            "isin": "INF000000001",
            "amc_name": "Example AMC",
            "reviewed_at": date.today().isoformat(),
        },
    }
    metrics = tmp_path / "fund_metrics.json"
    metrics.write_text(json.dumps({"funds": [record]}), encoding="utf-8")

    candidates = load_candidate_universe(metrics)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["scheme_id"] == "scheme-1"
    assert candidate["isin"] == "INF000000001"
    assert candidate["amc_name"] == "Example AMC"
    assert candidate["is_direct"] is True


def test_candidate_loader_rejects_direct_evidence_for_another_isin(tmp_path):
    source = b"reviewed AMC factsheet"
    (tmp_path / "direct.pdf").write_bytes(source)
    record = {
        "id": "fund-1",
        "name": "Example Direct Growth",
        "scheme_id": "scheme-1",
        "isin": "INF000000001",
        "amc_name": "Example AMC",
        "category": "Flexi Cap",
        "is_direct": True,
        "_evidence_root": str(tmp_path),
        "as_of_date": date.today().isoformat(),
        "direct_plan_evidence": {
            "source_file": "direct.pdf",
            "source_document_sha256": hashlib.sha256(source).hexdigest(),
            "source_url": "https://amc.example/direct.pdf",
            "source_type": "AMC_FACTSHEET",
            "reviewer_attested": True,
            "plan": "Direct",
            "scheme_name": "Example Direct Growth",
            "scheme_id": "scheme-1",
            "isin": "INF999999999",  # MISMATCH - different ISIN
            "amc_name": "Example AMC",
            "reviewed_at": date.today().isoformat(),
        },
    }
    metrics = tmp_path / "fund_metrics.json"
    metrics.write_text(json.dumps({"funds": [record]}), encoding="utf-8")

    candidates = load_candidate_universe(metrics)

    # ISIN mismatch should cause rejection
    assert candidates[0]["is_direct"] is None
    assert candidates[0]["direct_plan_evidence_status"] == "INVALID"
