#!/usr/bin/env python3
"""
advisor.py - Shared utilities for test compatibility.
Provides get_default_paths() for test_p0_fiduciary_invariants.py
"""

from pathlib import Path


def discover_client_portfolios(base_dir: Path | None = None) -> dict[str, Path]:
    if base_dir is None:
        base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data"
    portfolios = {}
    if not data_dir.exists():
        return portfolios
    for p in sorted(data_dir.iterdir()):
        if p.is_dir() and p.name not in ("policy", "cache", "__pycache__"):
            if (p / "config.json").exists() or (p / "statements").exists() or list(p.glob("*.xlsx")):
                portfolios[p.name] = p
    return portfolios


def get_default_paths(client_target: str | Path | None = None):
    base = Path(__file__).resolve().parent
    ports = discover_client_portfolios(base)

    if client_target:
        client_path = Path(client_target)
        if not client_path.is_dir() and client_target in ports:
            client_path = ports[client_target]
        elif not client_path.is_dir() and (base / "data" / client_target).is_dir():
            client_path = base / "data" / client_target
    else:
        if "lalit_portfolio" in ports:
            client_path = ports["lalit_portfolio"]
        elif ports:
            client_path = next(iter(ports.values()))
        else:
            client_path = base / "data" / "lalit_portfolio"

    if not client_path.exists():
        raise FileNotFoundError(f"Client portfolio directory not found: {client_path}")

    # Look for statements in statements/ subdir or root of client dir
    stmts = sorted((client_path / "statements").glob("cas_detailed_report_*.xlsx"))
    if not stmts:
        stmts = sorted((client_path / "statements").glob("*.xlsx"))
    if not stmts:
        stmts = sorted(client_path.glob("cas_detailed_report_*.xlsx"))
    if not stmts:
        stmts = sorted(client_path.glob("*.xlsx"))

    if not stmts:
        raise FileNotFoundError(f"No CAS Excel statements found in {client_path}")

    cas = stmts[-1]
    metrics = client_path / "fund_metrics.json"
    config = client_path / "config.json"
    aliases = client_path / "fund_aliases.json"
    outputs = base / "outputs"
    return cas, metrics, config, aliases, outputs