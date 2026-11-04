"""Read-only, filesystem-backed SIP evidence provider.

The provider loads an explicitly curated evidence bundle. It performs no
network access, never reads client data from the repository, and never
manufactures or substitutes source evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Callable


_ENV_NAME = "MF_SIP_EVIDENCE_BUNDLE_DIR"
_MANIFEST_NAME = "manifest.json"


def _json_no_duplicates(raw: bytes, *, label: str) -> Any:
    def pairs_no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate JSON key {key!r}.")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f"{label} contains non-standard JSON constant {value}.")

    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=pairs_no_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON.") from exc


def _resolve_bundle_file(root: Path, relative: Any, *, label: str) -> Path:
    if not isinstance(relative, str) or not relative.strip():
        raise ValueError(f"{label} must be a non-empty relative path.")
    candidate = Path(relative)
    if candidate.is_absolute():
        raise ValueError(f"{label} must not be an absolute path.")
    resolved = (root / candidate).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the configured evidence bundle.") from exc
    if not resolved.is_file():
        raise ValueError(f"{label} must resolve to a regular file.")
    return resolved


def _read_json(root: Path, relative: Any, *, label: str) -> Any:
    path = _resolve_bundle_file(root, relative, label=label)
    return _json_no_duplicates(path.read_bytes(), label=label)


def build_sip_evidence_provider(
    bundle_dir: str | Path | None = None,
) -> Callable[..., dict[str, Any]] | None:
    """Build a provider from MF_SIP_EVIDENCE_BUNDLE_DIR or an explicit path.

    An unset environment variable leaves the SIP app in its existing
    provider-not-configured HOLD state. A configured but invalid bundle fails
    application startup rather than silently falling back to sample data.
    """
    configured = bundle_dir if bundle_dir is not None else os.getenv(_ENV_NAME)
    if configured is None or not str(configured).strip():
        return None

    root = Path(configured).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"{_ENV_NAME} must point to a directory.")
    repository_root = Path(__file__).resolve().parents[1]
    try:
        root.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise ValueError("SIP evidence bundle must be outside the Git checkout.")

    manifest = _read_json(root, _MANIFEST_NAME, label="SIP evidence manifest")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("SIP evidence manifest schema_version must be 1.")

    required_manifest_fields = {
        "schema_version", "disclosure_as_of_date", "metrics_file",
        "metrics_metadata_file", "metrics_source_file",
        "scheme_master_file", "scheme_master_source_file",
        "portfolio_disclosures", "candidate_universe_file",
        "candidate_universe_metadata_file", "candidate_universe_source_file",
    }
    missing = required_manifest_fields - set(manifest)
    portfolio_context_fields = {"portfolio_context_file", "portfolio_context_metadata_file", "portfolio_context_source_file"}
    candidate_score_fields = {"candidate_score_metadata_file", "candidate_score_source_file"}
    unexpected = set(manifest) - (required_manifest_fields | {"aliases_file"} | portfolio_context_fields | candidate_score_fields)
    supplied_portfolio_context_fields = set(manifest) & portfolio_context_fields
    if supplied_portfolio_context_fields and supplied_portfolio_context_fields != portfolio_context_fields:
        raise ValueError("Portfolio context file, metadata and original source file must be configured together.")
    supplied_candidate_score_fields = set(manifest) & candidate_score_fields
    if supplied_candidate_score_fields and supplied_candidate_score_fields != candidate_score_fields:
        raise ValueError("Candidate score metadata and original source file must be configured together.")
    if missing or unexpected:
        raise ValueError(
            "SIP evidence manifest fields invalid; missing="
            + ",".join(sorted(missing))
            + "; unexpected=" + ",".join(sorted(unexpected))
        )

    try:
        as_of = date.fromisoformat(manifest["disclosure_as_of_date"])
    except (TypeError, ValueError) as exc:
        raise ValueError("disclosure_as_of_date must be an ISO date.") from exc

    metrics_path = _resolve_bundle_file(root, manifest["metrics_file"], label="metrics_file")
    metrics_metadata = _read_json(
        root, manifest["metrics_metadata_file"], label="metrics_metadata_file"
    )
    declared_normalized_hash = (
        metrics_metadata.get("normalized_metrics_sha256")
        if isinstance(metrics_metadata, dict) else None
    )
    actual_normalized_hash = hashlib.sha256(metrics_path.read_bytes()).hexdigest()
    if declared_normalized_hash != actual_normalized_hash:
        raise ValueError("Normalized fund metrics SHA-256 does not match the reviewed metadata.")
    metrics_source = _resolve_bundle_file(
        root, manifest["metrics_source_file"], label="metrics_source_file"
    ).read_bytes()
    aliases_relative = manifest.get("aliases_file")
    aliases_path = (
        _resolve_bundle_file(root, aliases_relative, label="aliases_file")
        if aliases_relative is not None else None
    )
    scheme_master = _read_json(root, manifest["scheme_master_file"], label="scheme_master_file")
    scheme_master_source = _resolve_bundle_file(
        root, manifest["scheme_master_source_file"], label="scheme_master_source_file"
    ).read_bytes()
    candidate_universe_path = _resolve_bundle_file(
        root, manifest["candidate_universe_file"], label="candidate_universe_file"
    )
    candidate_universe_bytes = candidate_universe_path.read_bytes()
    candidates = _json_no_duplicates(candidate_universe_bytes, label="candidate_universe_file")
    candidate_metadata = _read_json(
        root, manifest["candidate_universe_metadata_file"],
        label="candidate_universe_metadata_file",
    )
    if not isinstance(candidate_metadata, dict) or candidate_metadata.get(
        "normalized_candidate_universe_sha256"
    ) != hashlib.sha256(candidate_universe_bytes).hexdigest():
        raise ValueError("Normalized candidate universe SHA-256 does not match the reviewed metadata.")
    candidate_source = _resolve_bundle_file(
        root, manifest["candidate_universe_source_file"], label="candidate_universe_source_file"
    ).read_bytes()

    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidate_universe_file must contain a non-empty JSON array.")
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError(f"Candidate row {index} must be a JSON object.")
        if "_evidence_root" in candidate:
            raise ValueError("Candidate JSON must not override the bundle evidence root.")
        direct = candidate.get("direct_plan_evidence")
        if not isinstance(direct, dict):
            raise ValueError(f"Candidate row {index} requires direct_plan_evidence.")
        _resolve_bundle_file(root, direct.get("source_file"), label=f"candidate[{index}].direct_plan_evidence.source_file")
        candidate["_evidence_root"] = str(root)

    disclosure_records: dict[str, dict[str, Any]] = {}
    disclosure_sources: dict[str, bytes] = {}
    disclosures = manifest["portfolio_disclosures"]
    if not isinstance(disclosures, dict):
        raise ValueError("portfolio_disclosures must be a mapping keyed by exact scheme_id.")
    for scheme_id, files in disclosures.items():
        if not isinstance(scheme_id, str) or not scheme_id.strip() or not isinstance(files, dict):
            raise ValueError("Each portfolio disclosure requires a non-empty scheme_id and file mapping.")
        if set(files) != {"record_file", "source_file"}:
            raise ValueError(f"Disclosure {scheme_id!r} requires record_file and source_file only.")
        record = _read_json(root, files["record_file"], label=f"disclosure[{scheme_id}].record_file")
        if not isinstance(record, dict) or record.get("scheme_id") != scheme_id:
            raise ValueError(f"Disclosure {scheme_id!r} record has conflicting scheme identity.")
        disclosure_records[scheme_id] = record
        disclosure_sources[scheme_id] = _resolve_bundle_file(
            root, files["source_file"], label=f"disclosure[{scheme_id}].source_file"
        ).read_bytes()

    payload = {
        "metrics_path": metrics_path,
        "aliases_path": aliases_path,
        "metrics_source_metadata": metrics_metadata,
        "metrics_source_bytes": metrics_source,
        "scheme_master": scheme_master,
        "scheme_master_source_bytes": scheme_master_source,
        "portfolio_disclosures_by_scheme_id": disclosure_records,
        "portfolio_disclosure_source_bytes_by_scheme_id": disclosure_sources,
        "disclosure_as_of_date": as_of,
        "candidate_universe": candidates,
        "candidate_universe_source": candidate_metadata,
        "candidate_universe_source_bytes": candidate_source,
    }

    if supplied_candidate_score_fields:
        score_metadata = _read_json(
            root, manifest["candidate_score_metadata_file"],
            label="candidate_score_metadata_file",
        )
        score_source = _resolve_bundle_file(
            root, manifest["candidate_score_source_file"],
            label="candidate_score_source_file",
        ).read_bytes()
        if not isinstance(score_metadata, dict):
            raise ValueError("candidate_score_metadata_file must contain a JSON object.")
        payload.update({
            "candidate_score_source_metadata": score_metadata,
            "candidate_score_source_bytes": score_source,
        })

    if supplied_portfolio_context_fields:
        portfolio_context = _read_json(root, manifest["portfolio_context_file"], label="portfolio_context_file")
        portfolio_context_metadata = _read_json(root, manifest["portfolio_context_metadata_file"], label="portfolio_context_metadata_file")
        portfolio_context_source = _resolve_bundle_file(root, manifest["portfolio_context_source_file"], label="portfolio_context_source_file").read_bytes()
        if not isinstance(portfolio_context, dict):
            raise ValueError("portfolio_context_file must contain a JSON object.")
        if not isinstance(portfolio_context_metadata, dict):
            raise ValueError("portfolio_context_metadata_file must contain a JSON object.")
        payload.update({
            "portfolio_context": portfolio_context,
            "portfolio_context_source_metadata": portfolio_context_metadata,
            "portfolio_context_source_bytes": portfolio_context_source,
        })

    def provider(*, cas_path: Path, monthly_budget_inr: float, risk_profile: str) -> dict[str, Any]:
        # Request fields are deliberately not allowed to mutate the evidence
        # bundle or be persisted. The uploaded CAS is consumed by the service.
        if not isinstance(cas_path, Path) or not cas_path.is_file():
            raise ValueError("A temporary CAS file is required.")
        if monthly_budget_inr <= 0 or risk_profile not in {"Conservative", "Moderate", "Aggressive", "Custom"}:
            raise ValueError("Invalid request context.")
        return dict(payload)

    return provider
