"""
ui/pages/page_upload.py — CAS & CGS Statement Ingestion Module with Strict Pre-Flight Validation.
Strictly verifies file integrity, RTA signatures, and schema before ingestion to reject
random, invalid, or corrupted uploads (e.g. bills, resumes, arbitrary spreadsheets).
"""
from __future__ import annotations

import streamlit as st
from pathlib import Path
import tempfile
import pandas as pd
import sys

# Ensure workspace root is in path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ingestion.statement_validator import inspect_and_validate_statement, StatementValidationResult
import ingestion.cas_parser as cas_p
import ingestion.cgs_parser as cgs_p


def render_upload_page() -> None:
    st.header("📤 Ingest Mutual Fund Statements (CAS & CGS)")
    st.caption("Upload your official CAMS, KFintech, or MFCentral Consolidated Account Statement (CAS) and Capital Gains Statement (CGS).")

    col_info1, col_info2 = st.columns([1.5, 1.0])
    with col_info1:
        st.markdown("""
        **🛡️ Strict Validation & Security Policy:**
        - **Authenticity Gate:** Uploads are strictly verified against official AMFI / CAMS / KFintech schemas. Arbitrary files (invoices, utility bills, random spreadsheets) are rejected automatically.
        - **Data Privacy:** Statements are parsed 100% locally on your machine. No PAN, personal data, or credentials leave your environment.
        - **Supported Formats:** Official detailed CAS (`.xlsx` or `.pdf`) and Capital Gains Statements (`.xlsx`).
        """)
    with col_info2:
        st.info("💡 **Where to get your CAS:**\n- [MFCentral](https://www.mfcentral.com) → Portfolio → Download CAS (Detailed)\n- [CAMS Online](https://www.camsonline.com) → Statements → CAS Detailed")

    st.divider()

    u_col1, u_col2 = st.columns(2)
    cas_validation: StatementValidationResult | None = None
    cgs_validation: StatementValidationResult | None = None

    with u_col1:
        st.subheader("1. CAS Statement (Holdings & Transactions)")
        uploaded_cas = st.file_uploader(
            "Select CAS detailed statement (.xlsx or .pdf):",
            type=["xlsx", "pdf"],
            key="cas_uploader_input",
            help="Official CAMS, KFintech, or MFCentral detailed statement."
        )

        cas_password = None
        if uploaded_cas and uploaded_cas.name.lower().endswith(".pdf"):
            cas_password = st.text_input(
                "PDF Password (PAN in UPPERCASE):",
                type="password",
                key="cas_pdf_password_input",
                help="CAS PDFs are encrypted with your PAN (uppercase) or DOB (DDMMYYYY)."
            )

        if uploaded_cas:
            cas_bytes = uploaded_cas.getvalue()
            cas_validation = inspect_and_validate_statement(
                file_bytes=cas_bytes,
                file_name=uploaded_cas.name,
                password=cas_password
            )

            if cas_validation.is_valid:
                st.markdown(f"""
                <div style="background:#13231b; border:1px solid #238636; border-radius:6px; padding:12px; margin-top:10px;">
                    <div style="font-weight:bold; color:#68d391; font-size:0.95rem;">✅ Verified Authentic Mutual Fund CAS</div>
                    <div style="font-size:0.82rem; color:#c9d1d9; margin-top:4px; line-height:1.4;">
                        • <strong>RTA Authority:</strong> {cas_validation.rta_source}<br>
                        • <strong>Investor:</strong> {cas_validation.client_name or 'Verified Account'} &nbsp;|&nbsp; <strong>PAN:</strong> {cas_validation.masked_pan or 'Protected'}<br>
                        • <strong>Active Holdings Detected:</strong> {cas_validation.holdings_count} funds<br>
                        • <strong>Portfolio Base Value:</strong> ₹{cas_validation.total_portfolio_value_inr:,.0f}<br>
                        • <strong>Statement As-Of:</strong> {cas_validation.as_of_date or 'Recent'}
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="background:#2d1517; border:1px solid #da3633; border-radius:6px; padding:12px; margin-top:10px;">
                    <div style="font-weight:bold; color:#fc8181; font-size:0.95rem;">❌ Statement Verification Failed</div>
                    <div style="font-size:0.82rem; color:#c9d1d9; margin-top:4px; line-height:1.4;">
                        {'<br>'.join(f'• {err}' for err in cas_validation.errors)}
                    </div>
                </div>
                """, unsafe_allow_html=True)

    with u_col2:
        st.subheader("2. Capital Gains Statement (Optional)")
        uploaded_cgs = st.file_uploader(
            "Select CGS statement (.xlsx):",
            type=["xlsx"],
            key="cgs_uploader_input",
            help="Official Capital Gains Statement with Section 112A ledger."
        )

        if uploaded_cgs:
            cgs_bytes = uploaded_cgs.getvalue()
            cgs_validation = inspect_and_validate_statement(
                file_bytes=cgs_bytes,
                file_name=uploaded_cgs.name
            )

            if cgs_validation.is_valid:
                st.markdown(f"""
                <div style="background:#13231b; border:1px solid #238636; border-radius:6px; padding:12px; margin-top:10px;">
                    <div style="font-weight:bold; color:#68d391; font-size:0.95rem;">✅ Verified Capital Gains Statement (CGS)</div>
                    <div style="font-size:0.82rem; color:#c9d1d9; margin-top:4px; line-height:1.4;">
                        • <strong>Document Type:</strong> Section 112A Tax Statement<br>
                        • <strong>Tax Authority:</strong> {cgs_validation.rta_source}<br>
                        • <strong>Status:</strong> Ready for lot-level tax harvesting analysis
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div style="background:#2d1517; border:1px solid #da3633; border-radius:6px; padding:12px; margin-top:10px;">
                    <div style="font-weight:bold; color:#fc8181; font-size:0.95rem;">❌ Invalid Capital Gains Document</div>
                    <div style="font-size:0.82rem; color:#c9d1d9; margin-top:4px; line-height:1.4;">
                        {'<br>'.join(f'• {err}' for err in cgs_validation.errors)}
                    </div>
                </div>
                """, unsafe_allow_html=True)

    st.write("")

    can_ingest = cas_validation is not None and cas_validation.is_valid
    if uploaded_cgs and (cgs_validation is None or not cgs_validation.is_valid):
        can_ingest = False

    button_help = "Statements verified and ready to ingest." if can_ingest else "Upload a valid mutual fund CAS statement to enable ingestion."
    
    if st.button("🚀 Ingest Verified Statements & Run Portfolio Audit", type="primary", use_container_width=True, disabled=not can_ingest, help=button_help):
        with st.spinner("Processing verified statement records..."):
            suffix = Path(uploaded_cas.name).suffix.lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_cas:
                tmp_cas.write(uploaded_cas.getvalue())
                tmp_cas_path = Path(tmp_cas.name)

            try:
                holdings, txns, folios = cas_p.parse_cas_file(tmp_cas_path, password=cas_password)
                st.success(f"🎉 Successfully ingested {len(holdings)} holdings totaling ₹{cas_validation.total_portfolio_value_inr:,.0f}!")

                df = pd.DataFrame([
                    {
                        "Folio": h.get("folio_no", "-"),
                        "Scheme Name": h.get("scheme", "-"),
                        "Plan": "Direct" if "direct" in h.get("scheme", "").lower() else "Regular",
                        "Units": round(float(h.get("units", 0) or 0), 3),
                        "Invested (₹)": f"₹{float(h.get('invested', 0) or 0):,.0f}",
                        "Current Value (₹)": f"₹{float(h.get('current_value', 0) or 0):,.0f}",
                        "Unrealized Gain (₹)": f"₹{float(h.get('returns', 0) or 0):+,.0f}"
                    }
                    for h in holdings
                ])
                st.subheader(f"📊 Verified Statement Preview ({len(holdings)} Funds)")
                st.dataframe(df, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"Ingestion processing error: {e}")
            finally:
                tmp_cas_path.unlink(missing_ok=True)


if __name__ == "__main__":
    render_upload_page()
