"""Safety contract for the functional Streamlit dashboard."""
from __future__ import annotations

import ast
from pathlib import Path


def test_dashboard_does_not_load_client_data_or_planning_modules():
    """Dashboard must not directly load client data or run planning modules."""
    source_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

    # Dashboard must not import core planning modules or heavy data libs directly
    assert imported_modules.isdisjoint(
        {"advisor", "tax", "pandas", "openpyxl", "numpy", "scipy"}
    ), f"Dashboard imported forbidden modules: {imported_modules}"


def test_dashboard_uses_streamlit_components():
    """Dashboard must use Streamlit for UI rendering."""
    source_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    source = source_path.read_text(encoding="utf-8")

    # Must import streamlit
    assert "import streamlit" in source

    # Must have page config
    assert "st.set_page_config" in source


def test_dashboard_requires_cas_upload():
    """Dashboard must require CAS upload — no demo/fallback data."""
    source_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    source = source_path.read_text(encoding="utf-8")

    # Must have file uploader for CAS
    assert "file_uploader" in source
    assert "parse_cas_file" in source

    # Must stop if no file uploaded
    assert "st.stop()" in source


def test_no_hardcoded_demo_data():
    """NO HARDCODING: dashboard must not contain demo/fallback fund data."""
    source_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    source = source_path.read_text(encoding="utf-8")

    forbidden = [
        "get_demo_funds",
        "get_demo_policies",
        "DEMO_POLICIES",
        "demo_data",
        "HDFC Top 100",
        "Axis Long Term",
        "sample_data",
        "fallback",
    ]
    for term in forbidden:
        assert term not in source, (
            f"Hardcoded/demo data found in dashboard: '{term}'. "
            "Every user uploads their own CAS. No hardcoded funds allowed."
        )


def test_legacy_dashboard_pages_are_not_shipped():
    """Verify legacy pages are not in the repository."""
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


def test_root_launcher_delegates_to_streamlit():
    """Root launcher must properly delegate to Streamlit."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "app.py").read_text(encoding="utf-8")
    assert '"ui/app.py"' in source
    assert "streamlit" in source

