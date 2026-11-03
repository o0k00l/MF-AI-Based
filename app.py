#!/usr/bin/env python3
"""
app.py — Launch the retired dashboard notice only.
The legacy portfolio dashboard is disabled pending a validated rebuild.
"""
import subprocess
import sys

if __name__ == "__main__":
    subprocess.run([sys.executable, "-m", "streamlit", "run", "ui/app.py", "--server.port", "8501"])