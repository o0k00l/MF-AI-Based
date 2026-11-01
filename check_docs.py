import os
for f in ['README.md', 'ARCHITECTURE.md', 'OPTION_B_ROADMAP.md', 'OPTION_B_HLD_LLD.md', 'logical_flow.md', 'VERIFICATION_REPORT.md']:
    if os.path.exists(f):
        with open(f, 'r') as fh:
            c = fh.read()
            print(f'{f}: {len(c)} chars, updated: {os.path.getmtime(f)}')
    else:
        print(f'{f}: NOT FOUND')