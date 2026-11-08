#!/usr/bin/env python3
"""Add provenance to report_generator.py"""
import re

REPORT_FILE = r'C:\Users\l9999\Documents\VSworks\Mutual funds only prompt Based\services\report_generator.py'

with open(REPORT_FILE, 'r') as f:
    content = f.read()

# 1. Update generate_fiduciary_pdf_report function
# Find and replace the function
old_func_start = 'def generate_fiduciary_pdf_report(data: dict[str, Any]) -> bytes:'
old_func_end = '    return pdf_bytes\n\n\ndef generate_fiduciary_html_report'

# Find the function
start_idx = content.find(old_func_start)
end_idx = content.find(old_func_end, start_idx)

if start_idx != -1 and end_idx != -1:
    new_func = '''def generate_fiduciary_pdf_report(data: dict[str, Any]) -> bytes:
    """Generate a professional PDF fiduciary report from portfolio analysis data with cryptographic provenance."""
    buffer = io.BytesIO()
    
    # Compute provenance hash for audit trail
    payload_hash = _generate_provenance_hash(data)
    
    doc = BaseDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
        title="Executive Fiduciary Report",
        author="Fiduciary Advisory Engine",
        subject="Portfolio Diagnostic & Investment Advisory",
    )
    
    styles = _get_styles()
    
    frame_cover = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="cover")
    frame_content = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="content")
    
    cover_template = PageTemplate(id="cover", frames=[frame_cover])
    content_template = PageTemplate(id="content", frames=[frame_content])
    
    doc.addPageTemplates([cover_template, content_template])
    
    story = []
    
    story.append(NextPageTemplate("cover"))
    _build_cover_page(story, styles, data)
    
    story.append(NextPageTemplate("content"))
    _build_executive_summary(story, styles, data)
    _build_portfolio_overview(story, styles, data)
    _build_saa_analysis(story, styles, data)
    _build_sip_blueprint(story, styles, data)
    _build_lumpsum_plan(story, styles, data)
    _build_monte_carlo(story, styles, data)
    _build_fiduciary_disclosures(story, styles, data, payload_hash)
    
    # Build with provenance-enabled footer
    canvas_factory = lambda c, d: _draw_page_with_provenance(c, d, payload_hash)
    doc.build(story, onFirstPage=canvas_factory, onLaterPages=canvas_factory)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes

'''
    content = content[:start_idx] + new_func + content[end_idx + len('\n\n')]

# 2. Update _build_fiduciary_disclosures to use hash in disclosures
old_disclosures = '''        ("Statutory Mandate", "SEBI (Investment Advisers) Regulations, 2013 — Regulation 15(1) & Schedule III Code of Conduct."),
        ("Direct Plan Enforcement", "All proposed switches and SIP allocations strictly mandate Direct Plans to eliminate intermediary commissions and distributor trail leakage."),
        ("Conflict of Interest Prohibition", "The adviser receives zero consideration, referral fees, or commissions from any Asset Management Company (AMC) or intermediary."),
        ("Non-Execution Authority", "The adviser operates solely on a fee-only, non-execution advisory basis; order execution remains exclusively in client control via MFCentral, AMC portals, or RTAs."),
        ("Fee Transparency", "Advisory fees are agreed in writing upfront, deducted only from client's bank account — never from portfolio assets."),
        ("Data Provenance", f"Portfolio data sourced from CAS (CAMS/Karvy) with integrity verification. Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC."),'''

new_disclosures = '''        ("Statutory Mandate", "SEBI (Investment Advisers) Regulations, 2013 — Regulation 15(1) & Schedule III Code of Conduct."),
        ("Direct Plan Enforcement", "All proposed switches and SIP allocations strictly mandate Direct Plans to eliminate intermediary commissions and distributor trail leakage."),
        ("Conflict of Interest Prohibition", "The adviser receives zero consideration, referral fees, or commissions from any Asset Management Company (AMC) or intermediary."),
        ("Non-Execution Authority", "The adviser operates solely on a fee-only, non-execution advisory basis; order execution remains exclusively in client control via MFCentral, AMC portals, or RTAs."),
        ("Fee Transparency", "Advisory fees are agreed in writing upfront, deducted only from client's bank account — never from portfolio assets."),
        ("Data Provenance", f"{integrity_info}Portfolio data sourced from CAS (CAMS/Karvy) with integrity verification. Report generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC."),'''

content = content.replace(old_disclosures, new_disclosures)

# 3. Add integrity_info line before disclosures
old_disclosures_block = '''    disclosures = [
        ("Statutory Mandate", "SEBI (Investment Advisers) Regulations, 2013 — Regulation 15(1) & Schedule III Code of Conduct."),'''

new_disclosures_block = '''    # Build disclosures with integrity hash
    integrity_info = f"Integrity Hash: {payload_hash or 'N/A'} · " if payload_hash else ""
    disclosures = [
        ("Statutory Mandate", "SEBI (Investment Advisers) Regulations, 2013 — Regulation 15(1) & Schedule III Code of Conduct."),'''

content = content.replace(old_disclosures_block, new_disclosures_block)

with open(REPORT_FILE, 'w') as f:
    f.write(content)

print('SUCCESS: Updated report_generator.py with provenance support')