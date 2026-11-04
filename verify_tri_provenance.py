#!/usr/bin/env python3
"""Check TRI fixture integrity and enforce an explicit alpha-release gate.

Normal CI checks fixture self-consistency only. It deliberately does not
certify publisher authenticity. Use --require-alpha-release for a tag/release
gate; provisional or incomplete benchmark evidence must then fail closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
FIXTURES = (
    ROOT / "data/policy/benchmark_tri_series.json",
    ROOT / "data/policy/benchmark_tri_series_high_coverage.json",
)
OFFICIAL_HOSTS = {"nseindia.com", "www.nseindia.com", "niftyindices.com", "www.niftyindices.com"}
REQUIRED_BENCHMARKS = frozenset({"NIFTY 500 TRI", "NIFTY 500 MULTICAP 50:25:25 TRI", "NIFTY MIDCAP 150 TRI"})


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_repo_file(relative: object, description: str) -> tuple[Path | None, str | None]:
    if not isinstance(relative, str) or not relative.strip():
        return None, f"{description}: repository-relative file path is missing"
    candidate = Path(relative)
    if candidate.is_absolute():
        return None, f"{description}: absolute paths are not allowed"
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return None, f"{description}: path escapes the repository"
    if not resolved.is_file():
        return None, f"{description}: file does not exist: {relative}"
    return resolved, None


def verify_fixture(path: Path) -> list[str]:
    """Verify fixture structure, observation values, declared counts and checksums."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: unable to read valid JSON: {exc}"]
    label = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    failures: list[str] = []
    if not isinstance(data, dict):
        return [f"{label}: fixture root must be a JSON object"]
    provenance = data.get("provenance", {})
    coverage = data.get("coverage", {})
    benchmarks = data.get("benchmarks", {})
    if not isinstance(provenance, dict):
        failures.append(f"{label}: provenance must be a JSON object")
        provenance = {}
    if not isinstance(coverage, dict):
        failures.append(f"{label}: coverage must be a JSON object")
        coverage = {}
    if not isinstance(benchmarks, dict):
        failures.append(f"{label}: benchmarks must be a JSON object")
        benchmarks = {}
    for index_name, benchmark in benchmarks.items():
        if not isinstance(index_name, str):
            failures.append(f"{label}: benchmark names must be strings")
            continue
        if not isinstance(benchmark, dict):
            failures.append(f"{label}: {index_name}: benchmark entry must be a JSON object")
            continue
        levels = benchmark.get("levels", {})
        if not isinstance(levels, dict) or not levels:
            failures.append(f"{label}: {index_name}: levels must be a non-empty date/value object")
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", index_name.strip().lower()).strip("_")
        checksum_key = f"checksum_sha256_{slug}"
        coverage_key = slug
        expected = str(provenance.get(checksum_key, ""))
        computed = _canonical_sha256(levels)
        if len(expected) != 64 or computed.lower() != expected.lower():
            failures.append(
                f"{label}: {index_name}: checksum missing/mismatched; "
                f"expected={expected or '<missing>'}; computed={computed}"
            )
        for observation_date, raw_value in levels.items():
            try:
                parsed_date = date.fromisoformat(observation_date)
            except (TypeError, ValueError):
                failures.append(f"{label}: {index_name}: invalid ISO date key {observation_date!r}")
                break
            if parsed_date.isoformat() != observation_date:
                failures.append(f"{label}: {index_name}: non-canonical date key {observation_date!r}")
                break
            if isinstance(raw_value, bool):
                failures.append(f"{label}: {index_name}: boolean TRI level at {observation_date}")
                break
            try:
                number = float(raw_value)
            except (TypeError, ValueError):
                failures.append(f"{label}: {index_name}: non-numeric TRI level at {observation_date}")
                break
            if not math.isfinite(number) or number <= 0:
                failures.append(f"{label}: {index_name}: invalid TRI level at {observation_date}")
                break
        dates = list(levels)
        if any(not isinstance(day, str) for day in dates):
            failures.append(f"{label}: {index_name}: date keys must be strings")
        elif dates != sorted(dates) or len(dates) != len(set(dates)):
            failures.append(f"{label}: {index_name}: dates must be sorted and unique")
        coverage_entry = coverage.get(coverage_key, {})
        if not isinstance(coverage_entry, dict):
            failures.append(f"{label}: {index_name}: coverage entry must be a JSON object")
            coverage_entry = {}
        declared_count = coverage_entry.get("provided_data_points")
        if isinstance(declared_count, bool) or declared_count != len(levels):
            failures.append(
                f"{label}: {index_name}: declared point count {declared_count!r} "
                f"does not match observed count {len(levels)}"
            )
        if not failures:
            print(f"{label}: {index_name}: integrity checks passed ({len(levels)} observations)")
    return failures

def _is_approved_official_url(value: object) -> bool:
    parsed = urlparse(value if isinstance(value, str) else "")
    host = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and host in OFFICIAL_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
    )


def alpha_release_blockers(fixture_path: Path, *, approval_verified: bool = False) -> list[str]:
    blockers: list[str] = []
    try:
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"high-coverage TRI fixture cannot be read: {exc}"]

    if not isinstance(data, dict):
        return ["high-coverage TRI fixture root must be a JSON object"]
    provenance = data.get("provenance", {})
    if not isinstance(provenance, dict):
        return ["high-coverage TRI fixture provenance must be a JSON object"]
    if not str(provenance.get("frequency", "")).strip().lower().startswith("daily"):
        blockers.append(f"series frequency is not Daily: {provenance.get('frequency')!r}")
    if provenance.get("interpolation_used") is not False:
        blockers.append("interpolation_used must be explicitly false")
    if str(provenance.get("source_authenticity", "")).upper() != "VERIFIED":
        blockers.append("source_authenticity is not VERIFIED")
    if str(provenance.get("release_eligibility", "")).upper() != "ELIGIBLE":
        blockers.append("fixture release_eligibility is not ELIGIBLE")
    if not _is_approved_official_url(provenance.get("historical_source_url")):
        blockers.append("historical_source_url must be HTTPS on an approved NSE/Nifty Indices domain")

    source_path, path_error = _safe_repo_file(provenance.get("historical_source_file"), "historical TRI source document")
    if path_error:
        blockers.append(path_error)
    else:
        declared = str(provenance.get("source_document_sha256", "")).lower()
        actual = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if len(declared) != 64 or declared != actual:
            blockers.append("historical TRI source document SHA-256 is absent or does not match the stored source file")

    benchmarks = data.get("benchmarks", {})
    if not isinstance(benchmarks, dict) or not benchmarks:
        blockers.append("benchmarks must be a non-empty object")
        benchmarks = {}
    available_benchmarks = {str(name).strip().upper() for name in benchmarks}
    missing_benchmarks = sorted(REQUIRED_BENCHMARKS - available_benchmarks)
    if missing_benchmarks:
        blockers.append("required benchmark series missing: " + ", ".join(missing_benchmarks))

    calendar_path = ROOT / "data/policy/nse_trading_calendar.json"
    if not calendar_path.is_file():
        blockers.append("independently sourced data/policy/nse_trading_calendar.json is absent")
        return blockers
    try:
        calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        blockers.append(f"NSE trading calendar cannot be read: {exc}")
        return blockers

    if not isinstance(calendar, dict):
        blockers.append("NSE calendar root must be a JSON object")
        return blockers
    if calendar.get("exchange") != "NSE" or str(calendar.get("status", "")).upper() != "VERIFIED":
        blockers.append("NSE calendar must identify exchange=NSE and status=VERIFIED")
    sessions = calendar.get("sessions")
    if not isinstance(sessions, list) or not sessions or any(not isinstance(day, str) for day in sessions):
        blockers.append("NSE calendar sessions must be a non-empty list of ISO date strings")
        sessions = []
    if sessions != sorted(set(sessions)):
        blockers.append("NSE calendar sessions must be sorted and unique")
    for day in sessions:
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError("non-canonical ISO date")
        except ValueError:
            blockers.append(f"NSE calendar contains invalid ISO session date {day!r}")
            break
    cal_provenance = calendar.get("provenance", {})
    if not isinstance(cal_provenance, dict):
        blockers.append("NSE calendar provenance must be a JSON object")
        cal_provenance = {}
    if cal_provenance.get("sessions_sha256") != _canonical_sha256(sessions):
        blockers.append("NSE calendar sessions checksum is missing or mismatched")
    if not _is_approved_official_url(cal_provenance.get("source_url")):
        blockers.append("NSE calendar source_url must be HTTPS on an approved NSE/Nifty Indices domain")
    cal_source_path, cal_path_error = _safe_repo_file(
        cal_provenance.get("source_document_file"), "NSE calendar source document"
    )
    if cal_path_error:
        blockers.append(cal_path_error)
    else:
        declared = str(cal_provenance.get("source_document_sha256", "")).lower()
        actual = hashlib.sha256(cal_source_path.read_bytes()).hexdigest()
        if len(declared) != 64 or declared != actual:
            blockers.append("NSE calendar source document SHA-256 is absent or does not match the stored source file")
    # Reviewer attestation is validated only through the detached signature gate below;
    # a boolean embedded in the calendar document is not an identity credential.

    sessions_set = set(sessions)
    for index_name, benchmark in benchmarks.items():
        if not isinstance(benchmark, dict):
            blockers.append(f"{index_name}: benchmark entry must be an object")
            continue
        levels = benchmark.get("levels", {})
        if not isinstance(levels, dict) or not levels:
            blockers.append(f"{index_name}: TRI levels must be a non-empty date-to-value object")
            continue
        if set(levels) != sessions_set:
            blockers.append(
                f"{index_name}: observations do not exactly match the independently sourced NSE session calendar "
                f"(observed={len(levels)}, sessions={len(sessions_set)})"
            )
        for day, value in levels.items():
            try:
                parsed_day = date.fromisoformat(day)
                if parsed_day.isoformat() != day:
                    raise ValueError("non-canonical ISO date")
            except (TypeError, ValueError):
                blockers.append(f"{index_name}: invalid ISO observation date {day!r}")
                break
            if isinstance(value, bool):
                blockers.append(f"{index_name}: boolean TRI value on {day}")
                break
            try:
                number = float(value)
            except (TypeError, ValueError):
                blockers.append(f"{index_name}: non-numeric TRI value on {day}")
                break
            if not math.isfinite(number) or number <= 0:
                blockers.append(f"{index_name}: non-finite or non-positive TRI value on {day}")
                break
    if not benchmarks:
        blockers.append("no benchmark series supplied")
    if not provenance.get("independent_reviewer_id"):
        blockers.append("independent reviewer identity is not recorded in provenance")
    for required_name in sorted(REQUIRED_BENCHMARKS):
        entry = benchmarks.get(required_name)
        if not isinstance(entry, dict) or not isinstance(entry.get("levels"), dict) or not entry.get("levels"):
            blockers.append(f"required benchmark series missing or empty: {required_name}")
    if not approval_verified:
        blockers.append(
            "external release approval is still required: source authenticity and reviewer identity "
            "must be cryptographically authenticated"
        )
    return blockers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-alpha-release", action="store_true",
        help="fail unless daily TRI data, source/calendar evidence and signed reviewer approval pass",
    )
    parser.add_argument("--expected-commit", default=None, help="exact commit SHA the approval must authorize")
    args = parser.parse_args(argv)

    print("=" * 70)
    print("TRI FIXTURE INTEGRITY / RELEASE-ELIGIBILITY CHECK")
    print("=" * 70)
    failures = []
    for fixture in FIXTURES:
        if not fixture.is_file():
            failures.append(f"{fixture.relative_to(ROOT)}: fixture missing")
        else:
            failures.extend(verify_fixture(fixture))
    if failures:
        print("\nINTEGRITY FAILURE:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nLevels-file integrity: PASS for available TRI fixtures")
    approval_verified = False
    approval_errors: list[str] = []
    if args.require_alpha_release:
        from tri_reviewer_approval import verify_approval_from_environment
        approval_result = verify_approval_from_environment(
            repository="o0k00l/MF-AI-Based", expected_commit=args.expected_commit,
            fixture_path=FIXTURES[1], root=ROOT,
        )
        approval_verified = approval_result.ok
        approval_errors.extend(approval_result.errors)
    blockers = alpha_release_blockers(FIXTURES[1], approval_verified=approval_verified)
    blockers.extend(approval_errors)
    if blockers:
        print("TRI alpha release eligibility: BLOCKED")
        for blocker in blockers:
            print(f"- {blocker}")
        print("A fixture checksum proves local file integrity only; it does not by itself establish publisher authenticity.")
        return 2 if args.require_alpha_release else 0

    if args.require_alpha_release:
        print("TRI alpha release eligibility: PASS")
        print("Signed reviewer approval and all source/calendar evidence gates passed.")
        return 0
    print("TRI alpha release eligibility: BLOCKED")
    print("A signed reviewer approval is required before alpha release.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
