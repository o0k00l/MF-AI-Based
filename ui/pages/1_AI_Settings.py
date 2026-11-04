"""Local configuration page for the three supported AI providers."""
from __future__ import annotations

import streamlit as st

from core.settings import AI_PROVIDER_KEYS, ai_key_status, save_ai_keys

st.set_page_config(
    page_title="AI Provider Settings",
    page_icon="🔐",
    layout="centered",
)

st.title("AI Provider Settings")
st.caption("Configure API keys for the AI narrative/research layer.")

status = ai_key_status()
for provider, configured in status.items():
    st.write(f"**{provider}** — {'Configured' if configured else 'Not configured'}")

st.info(
    "Keys are saved to the local, Git-ignored .env file. Existing keys are "
    "never displayed. On hosted deployments, configure these values as "
    "platform environment secrets instead."
)

with st.form("ai_provider_keys"):
    st.subheader("Add or replace API keys")
    requesty = st.text_input(
        "Requesty API key",
        type="password",
        placeholder="Leave blank to keep the existing key",
        help="REQUESTY_API_KEY",
    )
    openrouter = st.text_input(
        "OpenRouter API key",
        type="password",
        placeholder="Leave blank to keep the existing key",
        help="OPENROUTER_API_KEY",
    )
    gemini = st.text_input(
        "Google Gemini API key",
        type="password",
        placeholder="Leave blank to keep the existing key",
        help="GEMINI_API_KEY",
    )
    st.caption("Only non-empty fields are updated.")
    submitted = st.form_submit_button("Save API keys", type="primary")

if submitted:
    try:
        result = save_ai_keys({
            "REQUESTY_API_KEY": requesty,
            "OPENROUTER_API_KEY": openrouter,
            "GEMINI_API_KEY": gemini,
        })
        st.success("Settings saved locally.")
        for provider, configured in result.items():
            st.write(f"**{provider}:** {'Configured' if configured else 'Not configured'}")
    except (OSError, TypeError, ValueError):
        st.error("Settings could not be saved. Check local file permissions and input values.")

st.divider()
st.subheader("Remove a saved key")
with st.form("clear_ai_provider_keys"):
    removals = []
    for provider, env_name in AI_PROVIDER_KEYS.items():
        if status.get(provider):
            if st.checkbox(f"Remove {provider} key"):
                removals.append(env_name)
    clear_submitted = st.form_submit_button("Remove selected keys")

if clear_submitted:
    try:
        save_ai_keys({}, clear=tuple(removals))
        st.success("Selected keys removed from local settings.")
        st.rerun()
    except (OSError, TypeError, ValueError):
        st.error("Selected keys could not be removed.")
