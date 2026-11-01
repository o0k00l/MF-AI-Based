import subprocess

# Stage all changes
subprocess.run(['git', 'add', '.'], check=True)

# Commit
message = """Architectural corrections based on institutional review

- Fixed zero-friction switch fallacy (Section 47 & 112A)
- Removed dogmatic multi-cap exit rule
- Implemented weighted look-through overlap calculation
- Fixed cardinal vs ordinal risk score fallacy
- Added Mandatory NO ACTION rule
- Implemented 6-module unified architecture
- Reordered roadmap sprints (AI last)
- Updated all three documents with corrections
- Fixed circular imports and dictionary iterations
- Verified all modules working

Critical fixes applied to core/math_engine.py, advisor_lean.py, ui/app.py
"""

subprocess.run(['git', 'commit', '-m', message], check=True)
print("Committed changes")

# Push
try:
    subprocess.run(['git', 'push'], check=True)
    print("Pushed to GitHub")
except:
    print("Push failed - may need authentication")
