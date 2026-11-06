"""Import-safety tests for CLI compatibility modules."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_advisor_lean_import_does_not_read_client_data_or_create_outputs(tmp_path):
    repository_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repository_root)
    env["MF_CLIENT_DATA_DIR"] = str(tmp_path / "deliberately-missing-client-data")

    result = subprocess.run(
        [sys.executable, "-c", "import advisor_lean; print('import-safe')"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "import-safe" in result.stdout
    assert not (tmp_path / "outputs").exists()

def test_advisor_requires_explicit_external_client_data(monkeypatch, tmp_path):
    import pytest
    import openpyxl
    from unittest.mock import patch
    from advisor import get_default_paths

    # Mock the engine data paths to return acquired data (required for this test)
    mock_paths = {
        "status": "ACQUIRED",
        "data_dir": Path("/tmp/fake-data"),
        "manifest": {"dataset_id": "test-dataset", "retrieved_at": "2026-11-01"},
        "scheme_master": None,
        "fund_metrics": Path("/tmp/fake-data/fund_metrics.json"),
        "fund_aliases": Path("/tmp/fake-data/fund_aliases.json"),
        "is_acquired": True,
    }
    with patch("advisor.get_engine_data_paths", return_value=mock_paths):
        monkeypatch.delenv("MF_CLIENT_DATA_DIR", raising=False)
        with pytest.raises(FileNotFoundError, match="MF_CLIENT_DATA_DIR is required"):
            get_default_paths()

        repository_root = Path(__file__).resolve().parents[1]
        monkeypatch.setenv("MF_CLIENT_DATA_DIR", str(repository_root / "data"))
        with pytest.raises(ValueError, match="outside the Git repository"):
            get_default_paths()

        external_client_dir = tmp_path / "private-client-data"
        statements = external_client_dir / "statements"
        statements.mkdir(parents=True)

        # Create a valid CAS Excel file
        cas_path = statements / "synthetic-cas.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Portfolio Details"
        ws.append(["To Date", "01-Nov-2026"])  # Use Nov 1st date so it's not stale
        ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
        ws.append(["Test Fund", "123", 100000.0, 110000.0, 1000.0])
        wb.save(cas_path)

        from datetime import date
        monkeypatch.setenv("MF_CLIENT_DATA_DIR", str(external_client_dir))
        _, _, _, _, outputs = get_default_paths(as_of=date(2026, 11, 1), max_statement_age_days=30)
        assert outputs == external_client_dir / "outputs"


def test_legacy_cli_requires_external_client_data_before_creating_outputs(tmp_path):
    import subprocess

    repository_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env.pop("MF_CLIENT_DATA_DIR", None)
    env["PYTHONPATH"] = str(repository_root)
    completed = subprocess.run(
        [sys.executable, str(repository_root / "advisor_lean.py"), "--no-ai"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode != 0
    assert "legacy advisor CLI is retired and disabled" in completed.stderr
    # Note: outputs directory may already exist from previous test runs
    # The key assertion is that no NEW outputs were created
    assert not (tmp_path / "outputs").exists()

