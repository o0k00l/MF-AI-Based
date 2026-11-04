#!/usr/bin/env python3
"""
advisor.py - Shared utilities for test compatibility.
Provides get_default_paths() for test_p0_fiduciary_invariants.py
"""

from pathlib import Path
import os


def get_default_paths(client_target: str | Path | None = None, *, as_of=None, max_statement_age_days=None):
    """Resolve an explicitly configured external client-data directory.

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

    if as_of is not None and max_statement_age_days is not None:
        selected = select_latest_statement(
            candidates,
            document_type="CAS",
            as_of=as_of,
            max_age_days=max_statement_age_days,
        )
        cas = selected.path
    else:
        cas = candidates[0]
    metrics = client_path / "fund_metrics.json"
    config = client_path / "config.json"
    aliases = client_path / "fund_aliases.json"
    outputs = client_path / "outputs"
    return cas, metrics, config, aliases, outputs
