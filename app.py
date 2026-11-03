#!/usr/bin/env python3
"""
app.py — Entry point for Fiduciary Wealth Copilot Streamlit Dashboard.
Run: python -m streamlit run app.py --server.port 8501
"""
import subprocess
import sys

if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "streamlit", "run", "ui/app.py", "--server.port", "8501"])