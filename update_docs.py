import pathlib
from pathlib import Path

# Read all three documents
with open('docs/OPTION_B_ROADMAP.md', 'r', encoding='utf-8') as f:
    roadmap = f.read()

with open('docs/OPTION_B_HLD_LLD.md', 'r', encoding='utf-8') as f:
    hld_lld = f.read()

with open('docs/logical_flow.md', 'r', encoding='utf-8') as f:
    logical_flow = f.read()

print("Documents loaded")
print(f"Roadmap length: {len(roadmap)}")
print(f"HLD/LLD length: {len(hld_lld)}")
print(f"Logical flow length: {len(logical_flow)}")