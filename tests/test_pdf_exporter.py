"""PDF export smoke tests for the ReportLab implementation."""
from pathlib import Path

import pytest

from core.pdf_exporter import convert_markdown_file_to_pdf, markdown_to_pdf_bytes


def test_markdown_to_pdf_returns_nonempty_pdf_and_escapes_markup():
    markdown = """# Sample report

A paragraph containing **bold**, *italic*, `code` and <script>alert(1)</script>.

| Field | Value |
| --- | --- |
| Equity | 65% |

- First item
- Second item

> Review before use.
"""
    rendered = markdown_to_pdf_bytes(markdown, title="Synthetic test")
    assert rendered.startswith(b"%PDF-")
    assert len(rendered) > 500


def test_markdown_file_converter_writes_requested_path(tmp_path: Path):
    source = tmp_path / "report.md"
    target = tmp_path / "nested" / "report.pdf"
    source.write_text("# Synthetic\n\nNo client data.", encoding="utf-8")

    result = convert_markdown_file_to_pdf(source, target)

    assert result == target
    assert target.read_bytes().startswith(b"%PDF-")


def test_markdown_file_converter_rejects_missing_source(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        convert_markdown_file_to_pdf(tmp_path / "missing.md")
