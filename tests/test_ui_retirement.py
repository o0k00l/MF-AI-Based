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


def test_streamlit_pages_exist_with_correct_naming():
    """Verify active Streamlit pages exist with correct numbered naming convention."""
    root = Path(__file__).resolve().parents[1]
    
    # Active pages following Streamlit multi-page convention (numbered)
    _LIVE_PAGES = [
        "ui/pages/1_Advisory_Flow.py",
        "ui/pages/2_Risk_Profiler.py",
        "ui/pages/3_Financial_Goals.py",
        "ui/pages/4_Debt_Allocation.py",
        "ui/pages/5_Fiduciary_Report.py",
    ]
    
    for relative_path in _LIVE_PAGES:
        assert (root / relative_path).exists(), (
            f"Expected Streamlit page missing: {relative_path}"
        )
    
    # Retired legacy pages must NOT exist (old naming convention)
    _RETIRED_PAGES = [
        "ui/pages/page_upload.py",
        "ui/pages/page_profile.py",
        "ui/pages/page_goals.py",
        "ui/pages/page_report.py",
    ]
    
    for relative_path in _RETIRED_PAGES:
        assert not (root / relative_path).exists(), (
            f"Retired legacy dashboard module still exists: {relative_path}"
        )


def test_root_launcher_delegates_to_streamlit():
    """Root launcher must properly delegate to Streamlit."""
    root = Path(__file__).resolve().parents[1]
    source = (root / "app.py").read_text(encoding="utf-8")
    assert '"ui/app.py"' in source
    assert "streamlit" in source


def test_lumpsum_ui_no_bank_cash_input():
    """Verify dev removed bank_cash_input from lump-sum section (ui/app.py).

    After dev change: bank_cash_input was removed; lump sum decisions are now
    portfolio-aware and do not require explicit bank cash estimation.
    """
    source_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    source = source_path.read_text(encoding="utf-8")
    assert "bank_cash_input" not in source, (
        "bank_cash_input should not exist in ui/app.py after dev refactoring: "
        "lump-sum decisions now portfolio-aware without explicit bank cash input"
    )


def test_lumpsum_ui_no_monthly_expenses():
    """Verify dev removed monthly_expenses_inr from evaluate_fiduciary_lumpsum_blueprint call.

    ui/app.py call to evaluate_fiduciary_lumpsum_blueprint() must no longer pass
    monthly_expenses_inr (previously used for 6-month reserve calculation).
    """
    source_path = Path(__file__).resolve().parents[1] / "ui" / "app.py"
    source = source_path.read_text(encoding="utf-8")
    assert "monthly_expenses_inr" not in source, (
        "monthly_expenses_inr should not be in ui/app.py after dev refactoring"
    )


def test_lumpsum_blueprint_ui_call_contract():
    """Verify ui/app.py calls evaluate_fiduciary_lumpsum_blueprint with updated signature.

    The dev update removed bank_cash_inr and monthly_expenses_inr parameters.
    Current contract: lumpsum_amount_inr, stp_duration_months, target_saa, funds
    """
    source = (Path(__file__).resolve().parents[1] / "ui" / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    call_nodes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "evaluate_fiduciary_lumpsum_blueprint":
                    call_nodes.append(node)
            elif isinstance(node.func, ast.Name):
                if node.func.id == "evaluate_fiduciary_lumpsum_blueprint":
                    call_nodes.append(node)

    assert call_nodes, "evaluate_fiduciary_lumpsum_blueprint call not found in ui/app.py"

    for call in call_nodes:
        kwargs = {kw.arg for kw in call.keywords if kw.arg}
        # Updated contract: these four kwargs must be present; bank_cash_inr and monthly_expenses_inr should be absent
        assert "lumpsum_amount_inr" in kwargs, "Missing kwarg: lumpsum_amount_inr"
        assert "stp_duration_months" in kwargs, "Missing kwarg: stp_duration_months"
        assert "target_saa" in kwargs, "Missing kwarg: target_saa"
        assert "funds" in kwargs, "Missing kwarg: funds"
        # Removed parameters should not be in call
        assert "bank_cash_inr" not in kwargs, "bank_cash_inr should have been removed by dev"
        assert "monthly_expenses_inr" not in kwargs, "monthly_expenses_inr should have been removed by dev"

