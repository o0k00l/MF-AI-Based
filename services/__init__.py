"""Services package — CAS parsing, data ingestion, and runtime configuration."""
import os


def sync_streamlit_secrets() -> None:
    """Propagate Streamlit secrets (from Streamlit Cloud) into os.environ.

    Safely transfers known API keys from st.secrets to os.environ so backend
    libraries (e.g. OpenAI, Google GenAI, Requesty) can access them.
    """
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            for key, val in st.secrets.items():
                if isinstance(val, (str, int, float, bool)) and key not in os.environ:
                    os.environ[str(key)] = str(val)
    except Exception:
        pass


sync_streamlit_secrets()

