#!/usr/bin/env python3
"""Canonical safe application launcher for the SIP decision-support API.

The Streamlit surface remains a retirement/readiness notice until the canonical
investor SIP journey has passed its end-to-end acceptance gates. The retired
legacy dashboard is deliberately not imported or executed here.
"""
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

if "streamlit" in sys.modules:
    import streamlit as st

    st.set_page_config(
        page_title="MF Engine — SIP workflow readiness",
        page_icon="📊",
        layout="centered",
    )
    st.title("Mutual-fund SIP decision support")
    st.warning("The investor-facing SIP workflow is not yet approved for use.")
    st.markdown(
        "The legacy dashboard is retired. No portfolio upload, fund selection, "
        "allocation, recommendation, switch, redemption or execution workflow "
        "is available from this application entry point."
    )
    st.info(
        "The deterministic SIP API remains a separately deployed, read-only "
        "service. Production recommendations remain blocked until the required "
        "source-evidence and independent release approvals are complete."
    )
    st.stop()

elif __name__ == "__main__":
    if "--api" in sys.argv:
        port = os.environ.get("API_PORT", "8000")
        subprocess.run(
            [
                sys.executable, "-m", "uvicorn", "api.sip_production:app",
                "--port", port, "--host", "0.0.0.0",
            ],
            check=True,
        )
    else:
        port = os.environ.get("STREAMLIT_PORT", "8501")
        subprocess.run(
            [
                sys.executable, "-m", "streamlit", "run", os.path.abspath(__file__),
                "--server.port", port,
            ],
            check=True,
        )
