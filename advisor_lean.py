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
    """Refuse to launch the retired, unvalidated advisory CLI."""
    raise SystemExit(
        "The legacy advisor CLI is retired and disabled. It contains unapproved "
        "tax, exit-load and allocation logic. No client data was read and no report "
        "or recommendation was generated. Use only a separately release-approved "
        "application build."
    )


if __name__ == "__main__":
    main()
