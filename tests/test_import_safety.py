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
