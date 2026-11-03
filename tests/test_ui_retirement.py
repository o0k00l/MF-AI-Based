"""Safety contract for the retired legacy Streamlit dashboard."""
from __future__ import annotations

import ast
from pathlib import Path


def test_retired_dashboard_does_not_load_client_data_or_planning_modules():
    source_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules = set()
    called_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    assert imported_modules.isdisjoint(
        {"advisor", "core", "tax", "pandas", "openpyxl"}
    )
    assert called_names.isdisjoint(
        {"open", "read_text", "read_bytes", "load_workbook", "get_default_paths"}
    )
    source = source_path.read_text(encoding="utf-8")
    assert "legacy dashboard has been retired" in source
    assert "No portfolio data has been loaded" in source



def test_legacy_dashboard_pages_are_not_shipped():
    root = Path(__file__).resolve().parents[1]
    retired_pages = (
        "ui/pages/page_upload.py",
        "ui/pages/page_profile.py",
        "ui/pages/page_goals.py",
        "ui/pages/page_report.py",
    )
    for relative_path in retired_pages:
        assert not (root / relative_path).exists(), (
            f"Retired legacy dashboard module still exists: {relative_path}"
        )


def test_root_launcher_only_starts_retirement_notice():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app.py").read_text(encoding="utf-8")
    assert '"ui/app.py"' in source
    assert "ui/pages" not in source
