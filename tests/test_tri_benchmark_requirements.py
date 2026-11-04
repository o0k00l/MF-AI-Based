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
