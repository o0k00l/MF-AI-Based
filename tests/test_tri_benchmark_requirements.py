from pathlib import Path

from verify_tri_provenance import REQUIRED_BENCHMARKS, alpha_release_blockers


def test_release_gate_requires_every_approved_benchmark_series():
    fixture = Path("data/policy/benchmark_tri_series_high_coverage.json")

    blockers = alpha_release_blockers(fixture)

    assert REQUIRED_BENCHMARKS == {
        "NIFTY 500 TRI",
        "NIFTY 500 MULTICAP 50:25:25 TRI",
        "NIFTY MIDCAP 150 TRI",
    }
    assert any(
        blocker.startswith("required benchmark series missing:")
        and "NIFTY 500 MULTICAP 50:25:25 TRI" in blocker
        and "NIFTY MIDCAP 150 TRI" in blocker
        for blocker in blockers
    )


def test_benchmark_name_matching_is_case_and_whitespace_insensitive():
    names = {"  nifty 500 tri  ", "Nifty 500 Multicap 50:25:25 TRI", "nifty midcap 150 tri"}

    normalized = {name.strip().upper() for name in names}

    assert normalized == REQUIRED_BENCHMARKS


def test_release_gate_requires_nonempty_series_for_all_required_benchmarks():
    from verify_tri_provenance import REQUIRED_BENCHMARKS

    assert REQUIRED_BENCHMARKS == {
        "NIFTY 500 TRI",
        "NIFTY 500 MULTICAP 50:25:25 TRI",
        "NIFTY MIDCAP 150 TRI",
    }


def test_provenance_urls_reject_lookalike_hosts_and_nonstandard_ports():
    from verify_tri_provenance import _is_approved_official_url

    assert _is_approved_official_url("https://www.nseindia.com/archive/tri.csv")
    assert not _is_approved_official_url("https://nseindia.com.attacker.example/tri.csv")
    assert not _is_approved_official_url("https://nseindia.com:444/tri.csv")
    assert not _is_approved_official_url("https://user@nseindia.com/tri.csv")



def test_fixture_integrity_checks_every_present_benchmark_series(tmp_path):
    import hashlib
    import json

    from verify_tri_provenance import _canonical_sha256, verify_fixture

    names = (
        "NIFTY 500 TRI",
        "NIFTY 50 TRI",
        "NIFTY 500 MULTICAP 50:25:25 TRI",
    )
    benchmarks = {}
    provenance = {}
    coverage = {}
    for index, name in enumerate(names):
        levels = {"2026-01-01": 100.0 + index, "2026-01-02": 101.0 + index}
        slug = name.lower().replace(":", " ").replace(" ", "_")
        benchmarks[name] = {"levels": levels}
        provenance[f"checksum_sha256_{slug}"] = _canonical_sha256(levels)
        coverage[slug] = {"provided_data_points": len(levels)}
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({
        "provenance": provenance, "coverage": coverage, "benchmarks": benchmarks,
    }), encoding="utf-8")

    assert verify_fixture(path) == []


def test_fixture_integrity_rejects_missing_checksum_for_any_benchmark(tmp_path):
    import json

    from verify_tri_provenance import verify_fixture

    path = tmp_path / "fixture.json"
    path.write_text(json.dumps({
        "provenance": {}, "coverage": {},
        "benchmarks": {"NIFTY MIDCAP 150 TRI": {"levels": {"2026-01-01": 100.0}}},
    }), encoding="utf-8")

    failures = verify_fixture(path)
    assert any("NIFTY MIDCAP 150 TRI: checksum missing/mismatched" in item for item in failures)


def test_malformed_calendar_session_objects_fail_closed_without_crashing(tmp_path, monkeypatch):
    import hashlib
    import json
    import verify_tri_provenance as verifier

    root = tmp_path
    monkeypatch.setattr(verifier, "ROOT", root)
    policy = root / "data/policy"
    policy.mkdir(parents=True)
    source = policy / "source.csv"
    source.write_text("official source placeholder", encoding="utf-8")
    calendar_source = policy / "calendar.csv"
    calendar_source.write_text("official calendar placeholder", encoding="utf-8")
    calendar = {
        "exchange": "NSE", "status": "VERIFIED", "sessions": [{"unexpected": "object"}],
        "provenance": {
            "sessions_sha256": verifier._canonical_sha256([]),
            "source_url": "https://www.nseindia.com/calendar.csv",
            "source_document_file": "data/policy/calendar.csv",
            "source_document_sha256": hashlib.sha256(calendar_source.read_bytes()).hexdigest(),
        },
    }
    (policy / "nse_trading_calendar.json").write_text(json.dumps(calendar), encoding="utf-8")
    fixture = policy / "fixture.json"
    levels = {"2026-01-01": 100.0}
    benchmarks = {name: {"levels": levels} for name in verifier.REQUIRED_BENCHMARKS}
    benchmarks["nifty 500 tri"] = {"levels": levels}
    fixture.write_text(json.dumps({
        "provenance": {
            "frequency": "Daily", "interpolation_used": False,
            "source_authenticity": "VERIFIED", "release_eligibility": "ELIGIBLE",
            "historical_source_url": "https://www.nseindia.com/tri.csv",
            "historical_source_file": "data/policy/source.csv",
            "source_document_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "independent_reviewer_id": "reviewer",
        },
        "benchmarks": benchmarks,
    }), encoding="utf-8")

    blockers = verifier.alpha_release_blockers(fixture, approval_verified=True)
    assert any("only ISO date strings" in item for item in blockers)
    assert any("duplicate benchmark identifier after normalization" in item for item in blockers)
