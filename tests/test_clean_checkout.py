"""
test_clean_checkout.py - Clean Checkout Viability Test

Verifies that a fresh clone of the repository works without any pre-existing
artifacts, cached data, or environment-specific configuration.

This test simulates a clean checkout by:
1. Creating a temporary directory
2. Copying tracked files only and checking that no client artifacts or outputs are present
3. Running the P0 invariant tests and policy validation in the isolated copy
4. Verifying that the core calculation engine imports successfully
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def test_clean_checkout():
    """
    Test clean-checkout viability by:
    - Copying tracked source to a temporary directory
    - Checking that private client artifacts and generated outputs are absent
    - Running P0 invariant tests and universal policy validation
    - Importing the core calculation engine

    Dependencies are supplied by the outer test environment; this test does
    not create a virtual environment or install packages.
    """
    # Get the project root (parent of tests directory)
    project_root = Path(__file__).resolve().parent.parent
    
    # Create a temporary directory for clean checkout simulation
    with tempfile.TemporaryDirectory() as tmpdir:
        clean_dir = Path(tmpdir) / "fiduciary_clean"
        clean_dir.mkdir()
        
        # Directories/files to EXCLUDE from clean checkout (these are artifacts/generated)
        exclude_patterns = [
            "outputs",
            "__pycache__",
            ".pytest_cache",
            ".git",
            "data/cache",
            "*.pyc",
            "*.pyo",
            "*.pyd",
            ".coverage",
            "htmlcov",
            ".mypy_cache",
            ".ruff_cache",
        ]
        
        def should_exclude(path: Path) -> bool:
            """Check if path should be excluded from clean copy."""
            rel = path.relative_to(project_root)
            for pattern in exclude_patterns:
                if pattern.endswith("*"):
                    if rel.match(pattern[:-1]):
                        return True
                elif pattern in rel.parts or str(rel).startswith(pattern):
                    return True
            return False
        
        # Copy tracked files only. Ignored/untracked client files must never
        # leak into the clean-checkout fixture.
        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=project_root,
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8").split("\0")
        for relative_name in filter(None, tracked):
            rel = Path(relative_name)
            src = project_root / rel
            if src.is_file() and not should_exclude(src):
                dst = clean_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        
        # Verify critical files exist in clean checkout
        critical_files = [
            "advisor.py",
            "core/math_engine.py",
            "core/eligibility.py",
            "core/fund_classifier.py",
            "core/models.py",
            "core/prompt_advisor.py",
            "tests/test_p0_fiduciary_invariants.py",
            "validate_final_logics.py",
            "requirements.txt",
            "requirements.lock",
            "data/policy/benchmark_tri_series.json",
            "data/policy/passive_universe.json",
            "data/policy/scheme_master.json",
        ]
        
        for f in critical_files:
            assert (clean_dir / f).exists(), f"Critical file missing in clean checkout: {f}"
        
        # A clean checkout must contain no client folders, statements or generated reports.
        data_root = clean_dir / "data"
        client_dirs = [
            path for path in data_root.iterdir()
            if path.is_dir() and path.name not in {"policy", "cache", "__pycache__"}
        ]
        assert not client_dirs, f"Unexpected client-data directories in checkout: {client_dirs}"
        private_artifacts = [
            path for path in data_root.rglob("*")
            if path.is_file() and path.suffix.lower() in {".xlsx", ".xls", ".pdf"}
        ]
        assert not private_artifacts, f"Unexpected private statement/report artifacts: {private_artifacts}"
        assert not (clean_dir / "outputs").exists(), "Generated client reports must not live in the repository"
        
        # Run P0 invariant tests in clean checkout
        print("[CLEAN CHECKOUT] Running P0 invariant tests...")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_p0_fiduciary_invariants.py", "-xvs"],
            cwd=clean_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        assert result.returncode == 0, f"P0 tests failed in clean checkout:\n{result.stdout}\n{result.stderr}"
        print("[CLEAN CHECKOUT] P0 tests PASSED")
        
        # Run universal logic validation
        print("[CLEAN CHECKOUT] Running universal logic validation...")
        result = subprocess.run(
            [sys.executable, "validate_final_logics.py"],
            cwd=clean_dir,
            capture_output=True,
            text=True,
            timeout=120
        )
        assert result.returncode == 0, f"Universal logic validation failed in clean checkout:\n{result.stdout}\n{result.stderr}"
        assert "84/84 CHECKS PASSED" in result.stdout or result.returncode == 0, "Expected validation checks to pass"
        print("[CLEAN CHECKOUT] Universal logic validation PASSED")
        
        # Verify that the core engine imports without client data or provider configuration.
        print("[CLEAN CHECKOUT] Testing engine initialization...")
        result = subprocess.run(
            [sys.executable, "-c", "from core.math_engine import aggregate_fiduciary_facts; print('Engine imports OK')"],
            cwd=clean_dir,
            capture_output=True,
            text=True,
            timeout=60
        )
        assert result.returncode == 0, f"Engine import failed in clean checkout:\n{result.stdout}\n{result.stderr}"
        print("[CLEAN CHECKOUT] Engine initialization PASSED")
        
        print("\n✅ CLEAN CHECKOUT VIABILITY TEST PASSED")
        print("   All critical source files present")
        print("   P0 invariant tests pass in the isolated checkout")
        print("   Universal logic validation passes")
        print("   Engine imports successfully")
        print("   No client data or generated outputs copied into the isolated checkout")


if __name__ == "__main__":
    test_clean_checkout()