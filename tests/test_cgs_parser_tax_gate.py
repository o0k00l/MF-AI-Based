"""
Unit tests verifying tax-free headroom and statutory exemption calculation is disabled in CGS ingestion.
Addresses Issue #51: Remove hardcoded tax exemption and LTCG headroom conclusions from CGS ingestion.
"""
from __future__ import annotations

import openpyxl
import pytest
from pathlib import Path

from ingestion.cgs_parser import parse_cgs_excel as parse_ingestion_cgs
from core.cgs_parser import parse_cgs_excel as parse_core_cgs


def _create_synthetic_cgs_workbook(path: Path) -> Path:
    wb = openpyxl.Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["Capital Gains Statement Summary"])
    summary.append(["Short Term Capital Gain/Loss", 50000.0])
    summary.append(["LongTermWithoutIndex-CapitalGain/Loss", 80000.0])
    summary.append(["Full Value Consideration", 500000.0])
    summary.append(["Cost of Acquisition", 370000.0])

    wb.save(path)
    return path


@pytest.mark.parametrize("parser_fn", [parse_ingestion_cgs, parse_core_cgs])
def test_cgs_parser_does_not_output_hardcoded_tax_exemption_or_headroom(tmp_path, parser_fn):
    cgs_file = _create_synthetic_cgs_workbook(tmp_path / "cgs_test.xlsx")
    result = parser_fn(cgs_file)

    summary = result["summary"]
    # Hardcoded exemption limits must not exist
    assert "exemption_limit" not in summary
    assert "remaining_ltcg_exemption" not in summary

    # Tax advice must be explicitly flagged as disabled
    assert result.get("tax_advice_enabled") is False

    # Headroom status must not promise tax-free amounts
    assert "tax-free" not in result["headroom_status"].lower()
    assert "disabled pending independent tax review" in result["headroom_status"]

    # SHA256 digest must be present
    assert "source_sha256" in result
    assert len(result["source_sha256"]) == 64

