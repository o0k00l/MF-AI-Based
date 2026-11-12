#!/usr/bin/env python3
"""
advisor.py - Shared utilities for test compatibility.
Provides get_default_paths() for test_p0_fiduciary_invariants.py
"""
from __future__ import annotations

from pathlib import Path
import os
from typing import Any


def get_engine_data_paths(data_dir: Path | None = None) -> dict[str, Any]:
    """Return engine-owned dataset paths; never resolve these from client files.

    Resolves snapshot paths from manifest.json. Returns a typed NOT_ACQUIRED
    or INVALID state when public fund data has not yet been acquired or is corrupt,
    rather than falling back to flat paths.
    """
    from services.engine_fund_data import (
        EngineRuntimeConfig,
        FundDataAcquisitionError,
        load_engine_manifest,
    )

    if data_dir is None:
        target_dir = EngineRuntimeConfig.from_environment().data_dir
    else:
        target_dir = Path(data_dir).expanduser().resolve()

    manifest_path = target_dir / "manifest.json"
    if not manifest_path.is_file():
        return {
            "status": "NOT_ACQUIRED",
            "data_dir": target_dir,
            "manifest": manifest_path,
            "scheme_master": None,
            "fund_metrics": None,
            "fund_aliases": None,
            "is_acquired": False,
            "is_decision_eligible": False,
            "promotion_eligible": False,
            "promotion_blockers": ["Engine-managed public fund data has not yet been acquired"],
            "error": "Engine-managed public fund data has not yet been acquired",
        }

    try:
        manifest = load_engine_manifest(target_dir)
    except FundDataAcquisitionError as exc:
        return {
            "status": "INVALID",
            "data_dir": target_dir,
            "manifest": manifest_path,
            "scheme_master": None,
            "fund_metrics": None,
            "fund_aliases": None,
            "is_acquired": False,
            "is_decision_eligible": False,
            "promotion_eligible": False,
            "promotion_blockers": [str(exc)],
            "error": str(exc),
        }

    status = manifest.get("status", "UNVERIFIED")
    artifacts = manifest.get("artifacts") or {}

    def _resolve(key: str) -> Path | None:
        rel = artifacts.get(key)
        if not rel or not isinstance(rel, str):
            return None
        candidate = (target_dir / rel).resolve()
        return candidate if candidate.is_file() else None

    master_path = _resolve("scheme_master")
    metrics_path = _resolve("fund_metrics")
    aliases_path = _resolve("fund_aliases")

    acquired = all(path is not None for path in (master_path, metrics_path, aliases_path))
    decision_eligible = (
        status == "PROMOTED"
        and manifest.get("promotion_eligible") is True
        and acquired
    )
    return {
        "status": status,
        "data_dir": target_dir,
        "manifest": manifest_path,
        "scheme_master": master_path,
        "fund_metrics": metrics_path,
        "fund_aliases": aliases_path,
        "is_acquired": acquired,
        "is_decision_eligible": decision_eligible,
        "promotion_eligible": decision_eligible,
        "dataset_id": manifest.get("dataset_id"),
        "retrieved_at": manifest.get("retrieved_at"),
        "promotion_blockers": manifest.get("promotion_blockers", []),
    }


def get_default_paths(client_target: str | Path | None = None, *, as_of=None, max_statement_age_days=None):
    """Legacy CAS path resolver; fund datasets are now engine-owned.

    New runtime code must use get_engine_data_paths() for public fund data and
    must not ask an investor to create fund_metrics.json or fund_aliases.json.

    The application never scans the repository for client folders and never
    chooses a default investor. Generated reports stay beside the local data.
    """
    repo_root = Path(__file__).resolve().parent
    if client_target is None:
        env_client_dir = os.environ.get("MF_CLIENT_DATA_DIR")
        if not env_client_dir:
            raise FileNotFoundError(
                "MF_CLIENT_DATA_DIR is required. Set it to a private directory outside the repository."
            )
        client_path = Path(env_client_dir).expanduser().resolve()
    else:
        client_path = Path(client_target).expanduser().resolve()

    try:
        client_path.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise ValueError("Client data directory must be outside the Git repository")

    if not client_path.is_dir():
        raise FileNotFoundError(f"Client portfolio directory not found: {client_path}")

    candidates = list((client_path / "statements").glob("*.xlsx"))
    candidates.extend(client_path.glob("*.xlsx"))
    if not candidates:
        raise FileNotFoundError(f"No CAS Excel statements found in {client_path}")

    from datetime import date
    from ingestion.statement_selection import select_latest_statement

    if as_of is None or max_statement_age_days is None:
        raise ValueError(
            "CAS selection requires an explicit decision as_of date and approved maximum statement age; "
            "no filename, directory-order or first-file fallback is permitted."
        )
    selected = select_latest_statement(
        candidates,
        document_type="CAS",
        as_of=as_of,
        max_age_days=max_statement_age_days,
    )
    cas = selected.path
    engine_paths = get_engine_data_paths()
    if not engine_paths.get("is_decision_eligible"):
        status = engine_paths.get("status", "UNKNOWN")
        blockers = engine_paths.get("promotion_blockers") or []
        detail = "; ".join(str(item) for item in blockers) or engine_paths.get("error") or (
            "engine-owned dataset has not passed independent evidence review and promotion"
        )
        raise FileNotFoundError(
            f"Public fund evidence is not decision-eligible (status={status}) in "
            f"{engine_paths.get('data_dir')}: {detail}"
        )
    metrics = engine_paths["fund_metrics"]
    aliases = engine_paths["fund_aliases"]

    # Investor-specific facts remain a separate mandate input; this is not
    # engine configuration and must never contain shared fund research data.
    config = client_path / "investor_mandate.json"
    outputs = client_path / "outputs"
    return cas, metrics, config, aliases, outputs
