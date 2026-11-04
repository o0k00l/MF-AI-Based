"""Tests for the normative architecture specification and entry-point startup contracts.

Covers Issues #37 and #39:
- #37: Clarify the two app.py entry points and define the canonical UI startup contract.
- #39: Establish and verify a normative architecture specification.
"""
from __future__ import annotations

import ast
from pathlib import Path


def test_normative_architecture_specification_is_present_and_complete():
    root = Path(__file__).resolve().parents[1]
    arch_path = root / "ARCHITECTURE.md"
    assert arch_path.is_file(), "ARCHITECTURE.md must exist in repository root."

    content = arch_path.read_text(encoding="utf-8")
    assert "Specification Version: 1.0.0" in content
    assert "Authority: Normative architecture baseline" in content
    assert "NOT APPROVED FOR PRODUCTION" in content
    assert "Execution Authority: NONE" in content

    # Canonical entry points documented
    assert "api/sip_production.py" in content
    assert "app.py" in content
    assert "ui/app.py" in content
    assert "advisor.py" in content

    # Core subsystems documented
    assert "CAS Ingestion and Statement Selection" in content
    assert "Evidence Provider Contract & Provenance" in content
    assert "Deterministic Financial & Allocation Engine" in content
    assert "Suitability & Central Allocation Policy" in content
    assert "Whole-Budget HOLD Behavior" in content

    # Security and fiduciary invariants
    assert "Trust Boundaries, Security, and Data Privacy" in content
    assert "Blocked and Gated Capabilities" in content


def test_root_launcher_strictly_preserves_ui_retirement_contract():
    root = Path(__file__).resolve().parents[1]
    launcher_path = root / "app.py"
    assert launcher_path.is_file(), "Root app.py launcher must exist."

    tree = ast.parse(launcher_path.read_text(encoding="utf-8"))
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

    # Launcher must only import standard library process management
    assert imported_modules <= {"subprocess", "sys"}

    source = launcher_path.read_text(encoding="utf-8")
    assert "streamlit" in source
    assert "ui/app.py" in source
    # Must never directly touch financial calculation or planning modules
    assert "core" not in source
    assert "advisor" not in source


def test_ui_app_retirement_boundary_remains_intact():
    root = Path(__file__).resolve().parents[1]
    ui_app_path = root / "ui" / "app.py"
    assert ui_app_path.is_file(), "ui/app.py must exist."

    source = ui_app_path.read_text(encoding="utf-8")
    assert "The legacy dashboard has been retired and is unavailable." in source
    assert "No portfolio data has been loaded" in source

    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])

    # Must only import streamlit and typing annotations
    assert imported_modules <= {"streamlit", "__future__"}
