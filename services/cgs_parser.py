"""CGS (Capital Gains Statement) parser service for the UI layer.

Adheres strictly to the repository architecture:
- Wraps ingestion.cgs_parser.parse_cgs_excel
- Enforces fail-closed trust boundaries
- Preserves raw source-reported figures without fabricating tax advice
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, BinaryIO

from ingestion.cgs_parser import parse_cgs_excel


def parse_cgs_file(file_obj: BinaryIO | bytes | Path) -> dict[str, Any]:
    """Parse an uploaded Capital Gains Statement (.xlsx) from CAMS/KFintech/MFCentral.

    Returns structured summary of realized STCG, LTCG, scheme breakdown, and lot history.
    """
    if isinstance(file_obj, (str, Path)):
        return parse_cgs_excel(file_obj)

    # If BytesIO or raw bytes, write safely to temporary file
    if hasattr(file_obj, "read"):
        content = file_obj.read()
    elif isinstance(file_obj, bytes):
        content = file_obj
    else:
        raise ValueError(f"Unsupported file object type: {type(file_obj)}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        return parse_cgs_excel(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
