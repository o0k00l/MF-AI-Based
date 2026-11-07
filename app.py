#!/usr/bin/env python3
"""
app.py — Root application launcher for UI dashboard and API services.
Compatible with direct CLI (`python app.py`), API (`python app.py --api`),
and Streamlit Community Cloud (`streamlit run app.py`).
"""
import os
import subprocess
import sys

if "streamlit" in sys.modules:
    # Running directly inside Streamlit (e.g. Streamlit Community Cloud)
    _ui_path = os.path.join(os.path.dirname(__file__), "ui", "app.py")
    with open(_ui_path, encoding="utf-8") as _f:
        exec(compile(_f.read(), _ui_path, "exec"), globals())
elif __name__ == "__main__":
    if "--api" in sys.argv:
        port = os.environ.get("API_PORT", "8000")
        subprocess.run([sys.executable, "-m", "uvicorn", "api.sip_production:app", "--port", port, "--host", "0.0.0.0"])
    else:
        port = os.environ.get("STREAMLIT_PORT", "8501")
        subprocess.run([sys.executable, "-m", "streamlit", "run", "ui/app.py", "--server.port", port])
