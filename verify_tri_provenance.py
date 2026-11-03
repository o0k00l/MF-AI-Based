#!/usr/bin/env python3
"""verify_tri_provenance.py - TRI fixture checksum and provenance verification."""

import json
import hashlib
import sys

def main():
    print("=" * 70)
    print("TRI FIXTURE PROVENANCE VERIFICATION")
    print("=" * 70)

    with open('data/policy/benchmark_tri_series_high_coverage.json') as f:
        data = json.load(f)

    # Verify status
    status = data.get('status')
    print(f"\nTRI Fixture Status: {status}")
    if status != 'VALIDATED — coverage above 95% minimum; passes TriProvenanceError coverage gate':
        print("ERROR: TRI fixture status is not VALIDATED")
        sys.exit(1)

    # Verify coverage
    nifty_500_points = data['coverage']['nifty_500_tri']['provided_data_points']
    nifty_50_points = data['coverage']['nifty_50_tri']['provided_data_points']
    nifty_500_coverage = data['coverage']['nifty_500_tri']['coverage_pct']
    nifty_50_coverage = data['coverage']['nifty_50_tri']['coverage_pct']

    print(f"Nifty 500 TRI points: {nifty_500_points}")
    print(f"Nifty 50 TRI points: {nifty_50_points}")
    print(f"Nifty 500 TRI coverage: {nifty_500_coverage}%")
    print(f"Nifty 50 TRI coverage: {nifty_50_coverage}%")

    if nifty_500_coverage < 95 or nifty_50_coverage < 95:
        print("ERROR: Coverage below 95% threshold")
        sys.exit(1)

    # Verify checksums
    print("\nVerifying checksums...")
    for idx in ['NIFTY 500 TRI', 'NIFTY 50 TRI']:
        levels = data['benchmarks'][idx]['levels']
        computed = hashlib.sha256(json.dumps(levels, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        expected = data['provenance']['checksum_sha256_nifty_500_tri' if '500' in idx else 'checksum_sha256_nifty_50_tri']
        if computed == expected:
            print(f"{idx}: checksum VERIFIED")
        else:
            print(f"ERROR: Checksum mismatch for {idx}")
            print(f"  Expected: {expected}")
            print(f"  Computed: {computed}")
            sys.exit(1)

    print("\nAll checksums VERIFIED")
    print("=" * 70)
    print("TRI PROVENANCE VERIFICATION PASSED")
    print("=" * 70)

if __name__ == '__main__':
    main()