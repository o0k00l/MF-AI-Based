from datetime import date
from io import BytesIO
from pathlib import Path
import openpyxl
import pytest
from advisor import get_default_paths


def _create_cas_xlsx(date_str):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["To Date", date_str])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units", "AMC Name"])
    ws.append(["Fund A", "FOLIO1", 1000, 1200, 10, "AMC A"])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_get_default_paths_selects_by_embedded_date_not_lexical(tmp_path, monkeypatch):
    client_dir = tmp_path / "client_data"
    client_dir.mkdir()
    stmts_dir = client_dir / "statements"
    stmts_dir.mkdir()

    # Create two files:
    # "a_newer.xlsx" has embedded date 2026-11-04
    # "z_older.xlsx" has embedded date 2026-01-01
    (stmts_dir / "a_newer.xlsx").write_bytes(_create_cas_xlsx("04-Nov-2026"))
    (stmts_dir / "z_older.xlsx").write_bytes(_create_cas_xlsx("01-Jan-2026"))

    (client_dir / "fund_metrics.json").write_text("{}")
    (client_dir / "config.json").write_text("{}")
    (client_dir / "fund_aliases.json").write_text("{}")

    monkeypatch.setenv("MF_CLIENT_DATA_DIR", str(client_dir))
    cas, metrics, config, aliases, outputs = get_default_paths(client_dir)

    # In lexical sort, "z_older.xlsx" would come last. But embedded date is newer for "a_newer.xlsx"
    assert cas.name == "a_newer.xlsx"


def test_get_default_paths_rejects_ambiguous_duplicate_embedded_dates(tmp_path, monkeypatch):
    client_dir = tmp_path / "client_data_dup"
    client_dir.mkdir()
    stmts_dir = client_dir / "statements"
    stmts_dir.mkdir()

    # Both have the same embedded date
    (stmts_dir / "statement_1.xlsx").write_bytes(_create_cas_xlsx("04-Nov-2026"))
    (stmts_dir / "statement_2.xlsx").write_bytes(_create_cas_xlsx("04-Nov-2026"))

    monkeypatch.setenv("MF_CLIENT_DATA_DIR", str(client_dir))
    with pytest.raises(ValueError, match="Ambiguous CAS statement selection"):
        get_default_paths(client_dir)
