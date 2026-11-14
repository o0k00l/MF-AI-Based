"""Retired legacy dashboard entry point.

The legacy portfolio dashboard is intentionally unavailable. The supported
application entry point is the repository-root app.py, which currently exposes
only the readiness notice until the canonical SIP workflow passes acceptance.
This module must never import portfolio parsers, recommendation services,
financial engines, or legacy planning pages.
"""
from __future__ import annotations

import streamlit as st


st.set_page_config(
    page_title="MF Engine — retired dashboard",
    page_icon="🔒",
    layout="centered",
)
st.title("Legacy dashboard retired")
st.warning(
    "This entry point is disabled. It does not accept portfolio uploads or "
    "produce investment recommendations."
)
st.markdown(
    "Use the documented root application command: python app.py. "
    "The canonical investor-facing SIP workflow is not yet approved for use."
)
st.info(
    "No portfolio, SIP, lumpsum, tax, switch, redemption, or execution "
    "functionality is available from this retired entry point."
)
st.stop()
