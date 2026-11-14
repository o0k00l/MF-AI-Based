"""Safety contract for the canonical application entry point."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_launcher_never_executes_the_retired_dashboard():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "ui/app.py" not in source
    assert "exec(" not in source
    assert "streamlit" in source
    assert "run" in source


def test_streamlit_entrypoint_is_a_readiness_notice_not_an_advisory_ui():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(
        {"advisor", "tax", "pandas", "openpyxl", "numpy", "scipy", "services", "core"}
    )
    assert "st.stop()" in source
    assert "not yet approved for use" in source


def test_cli_streamlit_command_targets_only_the_root_launcher():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert '"run", os.path.abspath(__file__)' in source
    assert '"api.sip_production:app"' in source


def test_legacy_dashboard_is_not_part_of_the_root_startup_contract():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "ui.app" not in source
    assert "parse_cas_file" not in source
    assert "generate_fiduciary" not in source



def test_retired_ui_entrypoint_is_disabled_even_when_launched_directly():
    source = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported == {"streamlit"}
    assert "st.stop()" in source
    assert "parse_cas_file" not in source
    assert "request_sip_recommendations" not in source
    assert "generate_fiduciary" not in source
    assert "lumpsum" in source.lower()
    assert "disabled" in source.lower()
