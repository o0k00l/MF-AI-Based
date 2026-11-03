#!/usr/bin/env python3
"""Import-safe compatibility entry point for the legacy advisor CLI.

Importing this module never reads client files, creates output directories, or
loads third-party AI providers. Running the module explicitly delegates to the
legacy command-line implementation.
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    """Run the legacy report command only when explicitly invoked."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    runpy.run_path(str(ROOT / "legacy" / "advisor_lean_cli.py"), run_name="__main__")


if __name__ == "__main__":
    main()
