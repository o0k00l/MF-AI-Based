"""Safe Markdown-to-PDF exporter using ReportLab.

HTML-to-PDF conversion is intentionally avoided. Report content is escaped
before it reaches ReportLab's limited paragraph-markup parser.

Includes cryptographic provenance: UTC timestamp and SHA-256 payload hash
in footer for regulatory audit trail and data integrity verification.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Callable
from xml.sax.saxutils import escape

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        Preformatted,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    HAS_REPORTLAB = True
    PAGE_WIDTH, PAGE_HEIGHT = A4
    LEFT_MARGIN = 1.8 * cm
    RIGHT_MARGIN = 1.8 * cm
    TOP_MARGIN = 1.9 * cm
    BOTTOM_MARGIN = 2.0 * cm
    AVAILABLE_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
except (ImportError, ModuleNotFoundError):
    HAS_REPORTLAB = False
    colors = None
    TA_LEFT = None
    A4 = None
    ParagraphStyle = getSampleStyleSheet = None
    cm = None
    HRFlowable = Paragraph = Preformatted = SimpleDocTemplate = Spacer = Table = TableStyle = None
    PAGE_WIDTH = PAGE_HEIGHT = LEFT_MARGIN = RIGHT_MARGIN = TOP_MARGIN = BOTTOM_MARGIN = AVAILABLE_WIDTH = 0
TICK = chr(96)


def _inline_markup(text: str) -> str:
    """Escape untrusted text, then apply a deliberately small Markdown subset."""
    value = escape(text, {'"': "&quot;"})
    value = re.sub(TICK + r"([^" + TICK + r"]+)" + TICK, r'<font name="Courier">\1</font>', value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", value)
    value = re.sub(
        r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
        r'<link href="\2" color="#2B6CB0">\1</link>',
        value,
    )
    return value


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=16, leading=20, textColor=colors.HexColor("#1A365D"),
            alignment=TA_LEFT, spaceAfter=12,
        ),
        "h1": ParagraphStyle(
            "ReportH1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=14, leading=17, textColor=colors.HexColor("#1A365D"),
            spaceBefore=10, spaceAfter=7, keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "ReportH2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11.5, leading=14, textColor=colors.HexColor("#2B6CB0"),
            spaceBefore=9, spaceAfter=5, keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "ReportH3", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=10, leading=12, textColor=colors.HexColor("#2D3748"),
            spaceBefore=7, spaceAfter=4, keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "ReportBody", parent=base["BodyText"], fontName="Helvetica",
            fontSize=9, leading=12, textColor=colors.HexColor("#2D3748"),
            spaceAfter=6, allowWidows=0, allowOrphans=0,
        ),
        "table": ParagraphStyle(
            "ReportTable", parent=base["BodyText"], fontName="Helvetica",
            fontSize=7.2, leading=9, textColor=colors.HexColor("#2D3748"),
        ),
        "table_header": ParagraphStyle(
            "ReportTableHeader", parent=base["BodyText"], fontName="Helvetica-Bold",
            fontSize=7.2, leading=9, textColor=colors.HexColor("#1A202C"),
        ),
        "quote": ParagraphStyle(
            "ReportQuote", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8.5, leading=11, textColor=colors.HexColor("#2B6CB0"),
            leftIndent=5, rightIndent=5, spaceAfter=4,
        ),
        "code": ParagraphStyle(
            "ReportCode", parent=base["Code"], fontName="Courier",
            fontSize=7, leading=9, backColor=colors.HexColor("#F7FAFC"),
            borderColor=colors.HexColor("#CBD5E0"), borderWidth=0.4,
            borderPadding=5, spaceAfter=6,
        ),
    }


def _is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def _parse_table(lines: list[str], styles: dict) -> Table:
    rows = []
    for index, line in enumerate(lines):
        if index == 1 and _is_table_separator(line):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        style = styles["table_header"] if not rows else styles["table"]
        rows.append([Paragraph(_inline_markup(cell), style) for cell in cells])
    if not rows:
        return Table([[""]])
    column_count = max(len(row) for row in rows)
    normalized = [row + [Paragraph("", styles["table"])] * (column_count - len(row)) for row in rows]
    table = Table(
        normalized,
        colWidths=[AVAILABLE_WIDTH / column_count] * column_count,
        repeatRows=1,
        hAlign="LEFT",
        splitByRow=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDF2F7")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7FAFC")]),
    ]))
    return table


def _markdown_story(md_content: str):
    styles = _styles()
    story = []
    paragraph_lines: list[str] = []
    lines = md_content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    in_code = False
    code_lines: list[str] = []

    def flush_paragraph():
        if paragraph_lines:
            text = " ".join(line.strip() for line in paragraph_lines)
            story.append(Paragraph(_inline_markup(text), styles["body"]))
            paragraph_lines.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if stripped.startswith(TICK * 3):
            flush_paragraph()
            if in_code:
                story.append(Preformatted("\n".join(code_lines), styles["code"]))
                code_lines.clear()
                in_code = False
            else:
                in_code = True
            index += 1
            continue

        if in_code:
            code_lines.append(line)
            index += 1
            continue

        if not stripped:
            flush_paragraph()
            index += 1
            continue

        if stripped.startswith("|") and "|" in stripped[1:]:
            flush_paragraph()
            table_lines = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index].strip())
                index += 1
            story.append(_parse_table(table_lines, styles))
            story.append(Spacer(1, 6))
            continue

        if re.fullmatch(r"[-*_]{3,}", stripped):
            flush_paragraph()
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#CBD5E0"), spaceBefore=4, spaceAfter=8))
            index += 1
            continue

        heading = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            story.append(Paragraph(_inline_markup(heading.group(2)), styles[("title", "h1", "h2", "h3")[level]]))
            index += 1
            continue

        if stripped.startswith(">"):
            flush_paragraph()
            quote_lines = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip()[1:].strip())
                index += 1
            quote = Paragraph(_inline_markup(" ".join(quote_lines)), styles["quote"])
            quote_box = Table([[quote]], colWidths=[AVAILABLE_WIDTH])
            quote_box.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EBF8FF")),
                ("LINEBEFORE", (0, 0), (0, -1), 2, colors.HexColor("#3182CE")),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]))
            story.extend([quote_box, Spacer(1, 5)])
            continue

        bullet = re.match(r"^[-*+]\s+(.*)$", stripped)
        numbered = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if bullet or numbered:
            flush_paragraph()
            item_text = bullet.group(1) if bullet else numbered.group(2)
            bullet_text = "•" if bullet else numbered.group(1) + "."
            story.append(Paragraph(_inline_markup(item_text), styles["body"], bulletText=bullet_text))
            index += 1
            continue

        paragraph_lines.append(stripped)
        index += 1

    flush_paragraph()
    if in_code and code_lines:
        story.append(Preformatted("\n".join(code_lines), styles["code"]))
    return story


def generate_provenance_hash(payload_dict: dict) -> str:
    """Generates a reproducible SHA-256 hash of the input payload for audit trail.
    
    The hash is computed over canonical JSON serialization with sorted keys,
    providing cryptographic proof of data integrity for regulatory compliance.
    
    Args:
        payload_dict: The report data dictionary to hash
        
    Returns:
        First 16 hexadecimal characters of SHA-256 hash for compact footer display
    """
    payload_str = json.dumps(payload_dict, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload_str.encode('utf-8')).hexdigest()[:16]


def _draw_page_with_provenance(canvas, doc, payload_hash: str):
    """Page footer with UTC timestamp and payload integrity hash.
    
    Provides regulatory audit trail by showing:
    - Report run timestamp (UTC) for temporal verification
    - Payload hash for data integrity verification
    """
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#718096"))
    
    run_timestamp = datetime.now(timezone.utc).isoformat()
    
    # Left: Hash & Legal
    canvas.drawString(
        72, 20,
        f"Integrity Hash: {payload_hash} | Non-executable analysis · Subject to human review"
    )
    # Right: Timestamp & Pagination
    canvas.drawRightString(
        PAGE_WIDTH - 72, 20,
        f"Run: {run_timestamp[:19]}Z | Page {doc.page}"
    )
    canvas.restoreState()


def _draw_page(canvas, doc):
    """Legacy footer for backward compatibility (no provenance)."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#718096"))
    canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, PAGE_HEIGHT - 0.9 * cm, "Decision-support report")
    canvas.drawString(LEFT_MARGIN, 0.75 * cm, "Non-executable analysis · Subject to independent human review")
    canvas.drawRightString(PAGE_WIDTH - RIGHT_MARGIN, 0.75 * cm, f"Page {doc.page}")
    canvas.restoreState()


def markdown_to_pdf_bytes(md_content: str, title: str = "", payload_hash: Optional[str] = None) -> bytes:
    """Convert Markdown to A4 PDF bytes with escaped content and provenance footer.
    
    Args:
        md_content: Markdown content to convert
        title: Optional report title
        payload_hash: Optional SHA-256 hash for provenance footer. If provided,
                     footer includes timestamp and hash for regulatory audit trail.
                     
    Returns:
        PDF bytes
    """
    if not HAS_REPORTLAB:
        raise RuntimeError("PDF generation requires the 'reportlab' package.")
    from io import BytesIO

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=RIGHT_MARGIN,
        leftMargin=LEFT_MARGIN,
        topMargin=TOP_MARGIN,
        bottomMargin=BOTTOM_MARGIN,
        title=title or "Investment Decision-Support Report",
        author="Investment Decision-Support Engine",
    )
    story = _markdown_story(md_content) or [Paragraph(" ", _styles()["body"])]
    
    if payload_hash is not None:
        # Use provenance-enabled footer
        canvas_factory = lambda c, d: _draw_page_with_provenance(c, d, payload_hash)
        document.build(story, onFirstPage=canvas_factory, onLaterPages=canvas_factory)
    else:
        document.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    return output.getvalue()


def convert_markdown_file_to_pdf(md_path: Path, output_pdf_path: Optional[Path] = None, payload_hash: Optional[str] = None) -> Path:
    """Read a Markdown file, convert it to PDF and save the result.
    
    Args:
        md_path: Path to markdown file
        output_pdf_path: Optional output path for PDF
        payload_hash: Optional SHA-256 hash for provenance footer
    """
    md_path = Path(md_path)
    if not md_path.is_file():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")
    if output_pdf_path is None:
        output_pdf_path = md_path.with_suffix(".pdf")
    else:
        output_pdf_path = Path(output_pdf_path)
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    output_pdf_path.write_bytes(
        markdown_to_pdf_bytes(md_path.read_text(encoding="utf-8"), title=md_path.stem.replace("_", " "), payload_hash=payload_hash)
    )
    return output_pdf_path
