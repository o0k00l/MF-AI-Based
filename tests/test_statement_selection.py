"""Tests for source-date-based CAS/CGS statement discovery."""

from datetime import date
from pathlib import Path

import openpyxl
import pytest

from ingestion.statement_selection import select_latest_statement


def _cas(path: Path, embedded_date, current=1000.0):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio Details"
    ws.append(["To Date", embedded_date])
    ws.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    ws.append(["Fund A", "123", 900.0, current, 100.0])
    wb.save(path)
    return path


def _cgs(path: Path, embedded_date):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Statement Date", embedded_date])
    ws.append(["Short Term Capital Gain/Loss", 0.0])
    wb.create_sheet("TransactionDetails")
    wb.save(path)
    return path


def test_cas_selection_uses_embedded_date_not_filename(tmp_path):
    older = _cas(tmp_path / "cas_z_latest_name.xlsx", "01-Jan-2026")
    newer = _cas(tmp_path / "cas_a_old_name.xlsx", "01-Oct-2026")
    selected = select_latest_statement(
        [older, newer], document_type="CAS", as_of=date(2026, 10, 10), max_age_days=45
    )
    assert selected.path == newer.resolve()
    assert selected.embedded_date == date(2026, 10, 1)
    assert len(selected.sha256) == 64
    assert "uniquely newest" in selected.rationale.lower()


def test_cgs_selection_combines_root_and_statements_directories(tmp_path):
    statements = tmp_path / "statements"
    statements.mkdir()
    older = _cgs(statements / "z_cgs.xlsx", "01-Jan-2026")
    newer = _cgs(tmp_path / "a_cgs.xlsx", "01-Oct-2026")
    selected = select_latest_statement(
        [older, newer], document_type="CGS", as_of=date(2026, 10, 10), max_age_days=45
    )
    assert selected.path == newer.resolve()


def test_duplicate_date_with_different_contents_is_ambiguous(tmp_path):
    first = _cas(tmp_path / "first.xlsx", "01-Oct-2026", current=1000.0)
    second = _cas(tmp_path / "second.xlsx", "01-Oct-2026", current=1200.0)
    with pytest.raises(ValueError, match="Conflicting CAS statements"):
        select_latest_statement(
            [first, second], document_type="CAS", as_of=date(2026, 10, 10), max_age_days=45
        )


def test_missing_embedded_date_cannot_be_selected(tmp_path):
    missing = _cas(tmp_path / "missing.xlsx", "not a date")
    with pytest.raises(ValueError, match="No verifiable CAS"):
        select_latest_statement(
            [missing], document_type="CAS", as_of=date(2026, 10, 10), max_age_days=45
        )


def test_stale_statement_is_blocked_by_explicit_policy(tmp_path):
    old = _cas(tmp_path / "old.xlsx", "01-Jan-2026")
    with pytest.raises(ValueError, match="stale"):
        select_latest_statement(
            [old], document_type="CAS", as_of=date(2026, 10, 10), max_age_days=45
        )


def test_missing_as_of_policy_is_rejected(tmp_path):
    current = _cas(tmp_path / "current.xlsx", "01-Oct-2026")
    with pytest.raises(ValueError, match="as_of"):
        select_latest_statement(
            [current], document_type="CAS", as_of=None, max_age_days=45
        )


def test_advisor_never_selects_first_cas_without_as_of_policy(tmp_path):
    from advisor import get_default_paths

    _cas(tmp_path / "cas_older.xlsx", "01-Jan-2026")
    with pytest.raises(ValueError, match="explicit decision as_of date"):
        get_default_paths(tmp_path)


def test_advisor_returns_only_embedded_date_selected_cas(tmp_path):
    from advisor import get_default_paths

    older = _cas(tmp_path / "cas_z_name.xlsx", "01-Jan-2026")
    newer = _cas(tmp_path / "cas_a_name.xlsx", "01-Oct-2026")
    selected, *_ = get_default_paths(
        tmp_path, as_of=date(2026, 10, 10), max_statement_age_days=45
    )
    assert selected == newer.resolve()
    assert selected != older.resolve()
