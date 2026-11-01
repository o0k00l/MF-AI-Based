"""
ui/pages/page_report.py — Institutional Reports & PDF Deliverables Hub.
Allows downloading verified PDF audit reports and the MFCentral Action Checklist CSV.
"""
from __future__ import annotations

import streamlit as st
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.pdf_exporter import convert_markdown_file_to_pdf


def render_report_page() -> None:
    st.header("📑 Institutional Reports & Execution Checklists")
    st.caption("Download verified PDF audit reports and execution CSV checklists for zero-brokerage direct execution.")

    # 1. MFCentral CSV Download Strip
    csv_path = ROOT / "outputs" / "MFCentral_Action_Checklist.csv"
    if not csv_path.exists():
        csv_path = ROOT / "MFCentral_Action_Checklist.csv"

    if csv_path.exists():
        c_bytes = csv_path.read_bytes()
        st.markdown("""
        <div style="background:#161b22; border:1px solid #30363d; border-radius:6px; padding:14px; margin-bottom:15px;">
            <div style="font-weight:bold; color:#58a6ff; font-size:1.05rem;">📥 MFCentral Action Checklist (Direct Plan Switches)</div>
            <div style="font-size:0.85rem; color:#8b949e; margin-top:4px;">
                Ready-to-execute fund switch list for MFCentral. Details folio numbers, target direct schemes, and tax-safe dates to save ₹39,020/year in commissions.
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.download_button(
            label="📥 Download Master MFCentral Action Checklist (CSV)",
            data=c_bytes,
            file_name="MFCentral_Action_Checklist.csv",
            mime="text/csv",
            type="primary",
            use_container_width=True
        )

    st.divider()

    # 2. PDF Deliverables
    st.subheader("📄 Fiduciary Audit Reports (PDF)")

    reports = {
        "1. Portfolio Health & Commission Bleed Audit": ROOT / "outputs" / "Portfolio_Health_Audit.md",
        "2. Fund-by-Fund Switch & Consolidation Plan": ROOT / "outputs" / "Switch_and_Consolidation_Plan.md",
        "3. Fresh Money Deployment Plan (SIP & Lumpsum)": ROOT / "outputs" / "Fresh_Money_Deployment_Plan.md",
    }

    selected_report_label = st.radio(
        "Select a report to preview and download:",
        list(reports.keys()),
        horizontal=True
    )

    md_path = reports[selected_report_label]
    if md_path.exists():
        content = md_path.read_text(encoding="utf-8")
        pdf_path = md_path.with_suffix(".pdf")
        if not pdf_path.exists():
            pdf_path = convert_markdown_file_to_pdf(md_path)

        if pdf_path.exists():
            p_bytes = pdf_path.read_bytes()
            dcol1, dcol2 = st.columns([1.5, 2.5])
            with dcol1:
                st.download_button(
                    label=f"📥 Download {pdf_path.name} (PDF)",
                    data=p_bytes,
                    file_name=pdf_path.name,
                    mime="application/pdf",
                    use_container_width=True
                )
            with dcol2:
                st.caption("A4 Institutional PDF with statement-verified tables and statutory disclaimers.")

        st.markdown("---")
        st.markdown(content)
    else:
        st.warning(f"Report file `{md_path.name}` not found in outputs/ directory.")


if __name__ == "__main__":
    render_report_page()

