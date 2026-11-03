#!/usr/bin/env python3
"""Verify TRI fixture integrity and keep performance claims blocked without evidence."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from datetime import date
from pathlib import Path


BENCHMARKS = (
    ("NIFTY 500 TRI", "nifty_500_tri", "checksum_sha256_nifty_500_tri"),
    ("NIFTY 50 TRI", "nifty_50_tri", "checksum_sha256_nifty_50_tri"),
)


def _canonical_json_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def verify_fixture(path: Path) -> list[str]:
    """Check structural integrity, numeric observations and exact metadata counts."""
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: cannot read valid JSON: {exc}"]

    provenance = data.get("provenance", {})
    coverage = data.get("coverage", {})
    fixtures = data.get("benchmarks", {})
    failures: list[str] = []

    for index_name, coverage_key, checksum_key in BENCHMARKS:
        levels = fixtures.get(index_name, {}).get("levels", {})
        expected = str(provenance.get(checksum_key, ""))
        computed = _canonical_json_sha256(levels)
        if not isinstance(levels, dict) or not levels:
            failures.append(f"{path}: {index_name}: levels must be a non-empty date/value object")
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected) or computed.lower() != expected.lower():
            failures.append(
                f"{path}: {index_name}: checksum missing/mismatched; "
                f"expected={expected or '<missing>'}; computed={computed}"
            )

        for observation_date, raw_value in levels.items():
            try:
                parsed_date = date.fromisoformat(observation_date)
            except (TypeError, ValueError):
                failures.append(f"{path}: {index_name}: invalid ISO date key {observation_date!r}")
                break
            if parsed_date.isoformat() != observation_date:
                failures.append(f"{path}: {index_name}: non-canonical date key {observation_date!r}")
                break
            if isinstance(raw_value, bool):
                failures.append(f"{path}: {index_name}: boolean index value at {observation_date}")
                break
            try:
                numeric_value = float(raw_value)
            except (TypeError, ValueError):
                failures.append(f"{path}: {index_name}: non-numeric index value at {observation_date}")
                break
            if not math.isfinite(numeric_value) or numeric_value <= 0:
                failures.append(f"{path}: {index_name}: invalid index level at {observation_date}")
                break

        declared_count = coverage.get(coverage_key, {}).get("provided_data_points")
        if isinstance(declared_count, bool) or declared_count != len(levels):
            failures.append(
                f"{path}: {index_name}: coverage.provided_data_points={declared_count!r} "
                f"does not match observed level count={len(levels)}"
            )

        dates = list(levels)
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            failures.append(f"{path}: {index_name}: dates must be strictly increasing and unique")

        if not failures:
            print(f"{path}: {index_name}: integrity checks passed ({len(levels)} observations)")

    return failures


def _verify_calendar(path: Path) -> tuple[list[str], set[str] | None]:
    """Verify calendar file integrity metadata; source authenticity remains a separate review."""
    if not path.is_file():
        return ["independent NSE trading calendar file is absent"], None
    try:
        calendar = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"NSE calendar is unreadable: {exc}"], None

    sessions = calendar.get("sessions")
    provenance = calendar.get("provenance", {})
    blockers = []
    if calendar.get("exchange") != "NSE" or calendar.get("status") != "VERIFIED":
        blockers.append("NSE calendar must identify exchange=NSE and status=VERIFIED")
    if not isinstance(sessions, list) or not sessions:
        blockers.append("NSE calendar sessions must be a non-empty list")
        return blockers, None
    if any(not isinstance(item, str) for item in sessions):
        blockers.append("NSE calendar contains non-string session dates")
        return blockers, None
    try:
        parsed = [date.fromisoformat(item) for item in sessions]
    except ValueError:
        blockers.append("NSE calendar contains invalid ISO session dates")
        return blockers, None
    if parsed != sorted(set(parsed)):
        blockers.append("NSE calendar sessions must be sorted and unique")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(provenance.get("source_document_sha256", ""))):
        blockers.append("NSE calendar source-document SHA-256 is missing")
    expected_sessions_hash = str(provenance.get("sessions_sha256", ""))
    actual_sessions_hash = hashlib.sha256(
        json.dumps(sessions, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if expected_sessions_hash.lower() != actual_sessions_hash.lower():
        blockers.append("NSE calendar session digest is missing or mismatched")
    if not str(provenance.get("source_url", "")).startswith("https://"):
        blockers.append("NSE calendar source URL is missing")
    return blockers, set(sessions)


def main() -> int:
    print("=" * 72)
    print("TRI FIXTURE INTEGRITY / ALPHA RELEASE-ELIGIBILITY CHECK")
    print("=" * 72)

    fixtures = [
        Path("data/policy/benchmark_tri_series.json"),
        Path("data/policy/benchmark_tri_series_high_coverage.json"),
    ]
    integrity_failures: list[str] = []
    for path in fixtures:
        if not path.exists():
            integrity_failures.append(f"{path}: fixture missing")
        else:
            integrity_failures.extend(verify_fixture(path))

    if integrity_failures:
        print("\nFIXTURE INTEGRITY FAILURE:")
        for failure in integrity_failures:
            print(f"- {failure}")
        return 1

    high_path = fixtures[1]
    try:
        high = json.loads(high_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read high-coverage fixture: {exc}")
        return 1

    provenance = high.get("provenance", {})
    blockers: list[str] = []
    frequency = str(provenance.get("frequency", "")).strip().lower()
    if frequency != "daily":
        blockers.append(f"series frequency is {provenance.get('frequency')!r}, not an authenticated daily series")
    if provenance.get("interpolation_used") is not False:
        blockers.append("interpolation_used must be explicitly false; interpolated values are not historical observations")
    if str(provenance.get("source_authenticity", "")).upper() != "VERIFIED":
        blockers.append("historical TRI publisher/source authenticity is not independently verified")
    if str(provenance.get("release_eligibility", "")).upper() != "ELIGIBLE":
        blockers.append("fixture metadata does not declare release_eligibility=ELIGIBLE")
    if not str(provenance.get("historical_source_url", "")).startswith("https://"):
        blockers.append("official historical TRI source-document URL is missing")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", str(provenance.get("source_document_sha256", ""))):
        blockers.append("original historical TRI source-document SHA-256 is missing")
    if not provenance.get("retrieval_date"):
        blockers.append("historical TRI retrieval date is missing")

    calendar_blockers, sessions = _verify_calendar(Path("data/policy/nse_trading_calendar.json"))
    blockers.extend(calendar_blockers)
    if sessions is not None:
        for index_name, _, _ in BENCHMARKS:
            observed = set(high.get("benchmarks", {}).get(index_name, {}).get("levels", {}))
            if observed != sessions:
                missing = len(sessions - observed)
                extra = len(observed - sessions)
                blockers.append(
                    f"{index_name}: observed dates do not equal verified NSE sessions "
                    f"(missing={missing}, extra={extra})"
                )

    if blockers:
        print("\nTRI ALPHA RELEASE ELIGIBILITY: BLOCKED")
        for blocker in blockers:
            print(f"- {blocker}")
        print(
            "A checksum verifies file integrity only. It does not authenticate the publisher, "
            "prove the index is a TRI, or establish market-session completeness."
        )
        return 0

    print("\nTRI ALPHA RELEASE ELIGIBILITY: EVIDENCE CHECKS PASSED")
    print("Independent human review and cash-flow reconciliation are still required.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
