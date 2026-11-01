import os
for f in ['docs/OPTION_B_ROADMAP.md', 'docs/OPTION_B_HLD_LLD.md', 'docs/logical_flow.md', 'ARCHITECTURE.md', 'README.md', 'VERIFICATION_REPORT.md']:
    if os.path.exists(f):
        with open(f, 'r') as fh:
            c = fh.read()
            print(f'{f}: {len(c)} chars')
            print('--- First 300 chars ---')
            print(c[:300])
            print()
    else:
        print(f'{f}: NOT FOUND')