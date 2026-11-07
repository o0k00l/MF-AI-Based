"""QA contract tests for the SEBI Risk Profiler Streamlit page.

Validates ui/pages/2_Risk_Profiler.py against the services/risk_profiler.py
interface and the advisory-flow page-structure contract, without requiring a
Streamlit runtime (static source analysis, same convention as test_ui_retirement.py).

Agile note: this file is expected to evolve alongside ui/pages/2_Risk_Profiler.py.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RISK_PROFILER_PAGE = ROOT / "ui" / "pages" / "2_Risk_Profiler.py"


def _page_source() -> str:
    return RISK_PROFILER_PAGE.read_text(encoding="utf-8")


def test_risk_profiler_page_exists():
    """Dedicated Risk Profiler page must exist (advisory flow step 2)."""
    assert RISK_PROFILER_PAGE.exists(), (
        "Advisory flow step 2 (SEBI Risk Profiler) page is missing: "
        f"{RISK_PROFILER_PAGE}"
    )


def test_risk_profiler_page_imports_service_layer():
    """Page must import evaluate_fiduciary_profile and SebiRiskTier from services.risk_profiler."""
    tree = ast.parse(_page_source())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "services.risk_profiler":
            imported.update(alias.name for alias in node.names)
    assert "evaluate_fiduciary_profile" in imported, (
        "Profiler page must import evaluate_fiduciary_profile from services.risk_profiler"
    )
    assert "SebiRiskTier" in imported, (
        "Profiler page must import SebiRiskTier from services.risk_profiler"
    )


def test_risk_profiler_page_calls_service_with_full_parameter_contract():
    """evaluate_fiduciary_profile call must pass all six documented kwargs."""
    source = _page_source()
    # Use AST to find the exact call - more reliable than string matching
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "evaluate_fiduciary_profile":
                kwarg_names = {kw.arg for kw in node.keywords}
                expected = {
                    "horizon_years",
                    "max_drawdown_tolerance_pct",
                    "emergency_fund_months",
                    "income_stability",
                    "emi_burden_pct",
                    "experience_level",
                }
                assert expected <= kwarg_names, (
                    f"Missing kwargs in evaluate_fiduciary_profile call: "
                    f"{expected - kwarg_names}"
                )
                return
    raise AssertionError("evaluate_fiduciary_profile call not found in page source")


def test_risk_profiler_page_persists_session_state_contract():
    """Page must persist the five session keys declared on form submission.

    Verified writers (source lines 158-163):
        fiduciary_profile_result, risk_tier, risk_bucket,
        user_risk_score, saa_target
    """
    source = _page_source()
    for key in (
        "fiduciary_profile_result",
        "risk_tier",
        "risk_bucket",
        "user_risk_score",
        "saa_target",
    ):
        assert re.search(rf'st\.session_state\["{key}"\]\s*=', source), (
            f"Profiler page must persist session key '{key}' on submission"
        )


def test_downstream_pages_read_risk_session_keys():
    """Writer/reader contract: keys written by the profiler page must have readers.

    Verified readers:
        - ui/app.py reads 'user_risk_score' and 'risk_tier' (sidebar step-2 status)
        - ui/pages/5_Fiduciary_Report.py reads 'risk_tier' or 'risk_bucket'
    """
    dashboard = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    report = (ROOT / "ui" / "pages" / "5_Fiduciary_Report.py").read_text(encoding="utf-8")

    assert 'st.session_state.get("user_risk_score")' in dashboard, (
        "Dashboard sidebar must read 'user_risk_score' written by the profiler page"
    )
    assert 'st.session_state.get("risk_tier")' in dashboard, (
        "Dashboard sidebar must read 'risk_tier' written by the profiler page"
    )
    assert (
        'st.session_state.get("risk_tier")' in report
        or 'st.session_state.get("risk_bucket")' in report
    ), "Fiduciary report must read 'risk_tier' or 'risk_bucket' from the profiler page"


def test_profiler_navigation_target_exists():
    """Every st.switch_page target on the profiler page must be an existing page file."""
    source = _page_source()
    targets = re.findall(r'st\.switch_page\("([^"]+)"\)', source)
    assert targets, "Profiler page must navigate to the next advisory step"
    for target in targets:
        assert (ROOT / "ui" / target).exists(), (
            f"Profiler navigation target missing on disk: {target}"
        )
