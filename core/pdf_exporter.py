"""
core/pdf_exporter.py — Professional Fiduciary Advisory PDF Exporter.
Converts markdown advisory reports into institutional, publication-ready A4 PDF documents.
Uses xhtml2pdf with institutional financial styling.
"""
from __future__ import annotations
import io
import re
from pathlib import Path
from typing import Optional
import markdown
from xhtml2pdf import pisa

PDF_CSS = """
@page {
    size: a4 portrait;
    margin-top: 1.8cm;
    margin-bottom: 2.0cm;
    margin-left: 1.8cm;
    margin-right: 1.8cm;
    @top-right {
        content: "Fiduciary Wealth Advisory";
        font-family: Helvetica, Arial, sans-serif;
        font-size: 7pt;
        color: #718096;
    }
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-family: Helvetica, Arial, sans-serif;
        font-size: 8pt;
        color: #718096;
    }
    @bottom-right {
        content: "Strictly Private & Confidential";
        font-family: Helvetica, Arial, sans-serif;
        font-size: 7pt;
        color: #a0aec0;
    }
}

body {
    font-family: Helvetica, Arial, sans-serif;
    font-size: 9.5pt;
    line-height: 1.45;
    color: #2d3748;
}

h1 {
    color: #1a365d;
    font-size: 16pt;
    font-weight: bold;
    border-bottom: 2px solid #3182ce;
    padding-bottom: 5px;
    margin-top: 0;
    margin-bottom: 12pt;
}

h2 {
    color: #2b6cb0;
    font-size: 12pt;
    font-weight: bold;
    margin-top: 12pt;
    margin-bottom: 6pt;
    border-bottom: 0.5px solid #e2e8f0;
    padding-bottom: 2px;
}

h3 {
    color: #2d3748;
    font-size: 10.5pt;
    font-weight: bold;
    margin-top: 8pt;
    margin-bottom: 4pt;
}

p {
    margin-top: 0;
    margin-bottom: 6pt;
}

table {
    width: 100%;
    margin-top: 6pt;
    margin-bottom: 10pt;
    font-size: 8pt;
}

th, td {
    border: 0.5px solid #cbd5e0;
    padding: 4pt 6pt;
    text-align: left;
    vertical-align: middle;
}

th {
    background-color: #edf2f7;
    color: #1a202c;
    font-weight: bold;
}

tr:nth-child(even) {
    background-color: #f7fafc;
}

blockquote {
    background-color: #ebf8ff;
    border-left: 3px solid #3182ce;
    padding: 5pt 8pt;
    margin: 6pt 0;
    color: #2b6cb0;
    font-size: 8.5pt;
}

ul, ol {
    margin-top: 2pt;
    margin-bottom: 6pt;
    padding-left: 16pt;
}

li {
    margin-bottom: 2pt;
}

em {
    font-size: 8pt;
    color: #718096;
}

.statutory-box {
    margin-top: 16pt;
    padding: 8pt 10pt;
    background-color: #f7fafc;
    border: 0.5px solid #cbd5e0;
    font-size: 7.5pt;
    color: #718096;
    line-height: 1.35;
}
"""


def markdown_to_pdf_bytes(md_content: str, title: str = "") -> bytes:
    """Converts markdown content string into professional A4 PDF bytes."""
    # Replace Rupee symbol and non-standard unicode arrows for PDF Helvetica compatibility
    clean_md = (
        md_content.replace("₹", "Rs ")
        .replace("•", "*")
        .replace("→", " -> ")
        .replace("↔", " <-> ")
        .replace("←", " <- ")
        .replace("⇒", " => ")
    )
    
    # Strip any backtick code block wraps around whole markdown
    clean_md = re.sub(r"^```markdown\s*", "", clean_md)
    clean_md = re.sub(r"```$", "", clean_md.strip())

    html_body = markdown.markdown(
        clean_md,
        extensions=["tables", "fenced_code", "sane_lists"]
    )

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title or 'Fiduciary Wealth Report'}</title>
<style>
{PDF_CSS}
</style>
</head>
<body>
{html_body}
</body>
</html>
"""
    pdf_buffer = io.BytesIO()
    pisa_status = pisa.CreatePDF(
        io.BytesIO(full_html.encode("utf-8")),
        dest=pdf_buffer
    )

    if pisa_status.err:
        raise RuntimeError(f"xhtml2pdf rendering error: {pisa_status.err}")

    return pdf_buffer.getvalue()


def convert_markdown_file_to_pdf(md_path: Path, output_pdf_path: Optional[Path] = None) -> Path:
    """Reads a markdown file, converts to PDF, and saves to output_pdf_path."""
    md_path = Path(md_path)
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    if output_pdf_path is None:
        output_pdf_path = md_path.with_suffix(".pdf")
    else:
        output_pdf_path = Path(output_pdf_path)

    md_content = md_path.read_text(encoding="utf-8")
    pdf_bytes = markdown_to_pdf_bytes(md_content, title=md_path.stem.replace("_", " "))
    output_pdf_path.write_bytes(pdf_bytes)
    return output_pdf_path
