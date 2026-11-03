#!/usr/bin/env python3
"""Verify TRI file integrity without conflating checksums with source authenticity."""

import hashlib
import json
import sys
from pathlib import Path


def verify_fixture(path: Path) -> list[str]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    provenance = data.get("provenance", {})
    failures = []
    for index_name, checksum_key in (
        ("NIFTY 500 TRI", "checksum_sha256_nifty_500_tri"),
        ("NIFTY 50 TRI", "checksum_sha256_nifty_50_tri"),
    ):
        levels = data.get("benchmarks", {}).get(index_name, {}).get("levels", {})
        expected = str(provenance.get(checksum_key, ""))
        computed = hashlib.sha256(
            json.dumps(levels, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if not levels or computed != expected:
            failures.append(
                f"{path}: {index_name}: checksum missing/mismatched; "
                f"expected={expected or '<missing>'}; computed={computed}"
            )
        else:
            print(f"{path}: {index_name}: checksum matches ({len(levels)} observations)")
    return failures


def main():
    print("=" * 70)
    print("TRI FIXTURE INTEGRITY / RELEASE-ELIGIBILITY CHECK")
    print("=" * 70)

    fixtures = [
        Path("data/policy/benchmark_tri_series.json"),
        Path("data/policy/benchmark_tri_series_high_coverage.json"),
    ]
    failures = []
    for path in fixtures:
        if not path.exists():
            failures.append(f"{path}: fixture missing")
            continue
        failures.extend(verify_fixture(path))

    if failures:
        print("\nINTEGRITY FAILURE:")
        for failure in failures:
            print(f"- {failure}")
        sys.exit(1)

    print("\nLevels-file integrity: PASS for all TRI fixtures")
    # The high-coverage fixture is still only a provisional series: its declared
    # frequency is monthly/interpolated and the URLs are live-market pages.
    with fixtures[1].open(encoding="utf-8") as handle:
        high = json.load(handle)
    provenance = high.get("provenance", {})
    frequency = str(provenance.get("frequency", "")).strip().lower()
    historical_url = str(provenance.get("historical_source_url", "") or "")
    source_sha256 = str(provenance.get("source_document_sha256", "") or "")
    calendar_path = Path("data/policy/nse_trading_calendar.json")

    blockers = []
    if not frequency.startswith("daily"):
        blockers.append(f"series frequency is declared {provenance.get('frequency')!r}, not Daily")
    if not historical_url.startswith("https://") or len(source_sha256) != 64:
        blockers.append("historical TRI source document URL/SHA256 is not supplied")
    if not calendar_path.exists():
        blockers.append("independent NSE trading calendar file is absent")

    if blockers:
        print("TRI alpha release eligibility: BLOCKED")
        for blocker in blockers:
            print(f"- {blocker}")
        print("A matching levels checksum proves file integrity only; it does not prove source authenticity or exchange-calendar coverage.")
        return

    print("TRI alpha release eligibility: METADATA PRESENT — source authenticity still requires human verification")


if __name__ == "__main__":
    main()
