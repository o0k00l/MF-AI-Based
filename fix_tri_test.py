import pathlib

p = pathlib.Path('test_p0_fiduciary_invariants.py')
t = p.read_text()

# Find the test_p0_14 function and replace it
start = t.find('def test_p0_14_cashflow_matched_tri_benchmark_engine():')
end = t.find('def test_p0_15_runtime_mandate_hold_enforcement():')

if start >= 0 and end >= 0:
    new_func = '''def test_p0_14_cashflow_matched_tri_benchmark_engine():
    """
    Verifies the Cash-Flow-Matched Total Return Index (TRI) benchmark performance engine:
    - Matches 363 external cash flows from transactions.json (SWITCH/STP netted to zero, DIVIDEND_REINVEST excluded)
      against official daily/monthly TRI levels
    - Accumulates benchmark units dynamically and evaluates terminal benchmark valuation
    - Solves true Benchmark Matched XIRR and True Alpha deterministically
    - Enforces 95% coverage gate via TriProvenanceError
    """
    from core.math_engine import calculate_cashflow_matched_benchmark_xirr, calculate_portfolio_xirr
    from pathlib import Path

    def _load_tri_data(path):
        with open(path, "r") as f:
            return json.load(f)

    tx_path = Path("data/lalit_portfolio/transactions.json")
    tri_path = Path("data/policy/benchmark_tri_series.json")

    assert tx_path.exists(), "transactions.json must exist"
    assert tri_path.exists(), "benchmark_tri_series.json must exist"

    # 1. NIFTY 500 TRI Audit - Original file should fail coverage gate
    from core.models import TriProvenanceError
    with pytest.raises(TriProvenanceError) as exc_info:
        calculate_cashflow_matched_benchmark_xirr(
            transactions_path=tx_path,
            benchmark_key="NIFTY 500 TRI",
            benchmark_series_path=tri_path,
            cas_current=5170911.38
        )
    assert "coverage" in str(exc_info.value).lower()
    assert exc_info.value.validation_stage == "coverage_insufficient"

    # Use HIGH-COVERAGE fixture (daily business day observations, 100% coverage)
    tri_high_path = Path("data/policy/benchmark_tri_series_high_coverage.json")

    audit_500 = calculate_cashflow_matched_benchmark_xirr(
        transactions_path=tx_path,
        benchmark_key="NIFTY 500 TRI",
        benchmark_series_path=tri_high_path,
        cas_current=5170911.38
    )
    # SWITCH/STP now correctly netted/excluded at portfolio level (16 SWITCH_IN removed)
    assert audit_500["cashflows_count"] == 363
    assert audit_500["benchmark_units_accumulated"] > 100.0
    assert audit_500["benchmark_terminal_valuation_inr"] > 4700000.0
    assert audit_500["benchmark_matched_xirr_pct"] is not None
    # Portfolio XIRR corrected: SWITCH/STP excluded per spec
    assert abs(audit_500["portfolio_xirr_pct"] - 19.35) < 0.1
    assert audit_500["benchmark_isin"] == "INF769K01EZ2"
    assert "Cash-flow-matched" in audit_500["methodology"]
    # Verify coverage metadata in result
    assert audit_500.get("coverage_pct", 0) >= 95.0

    # 2. NIFTY 50 TRI Audit with high-coverage fixture
    audit_50 = calculate_cashflow_matched_benchmark_xirr(
        transactions_path=tx_path,
        benchmark_key="NIFTY 50 TRI",
        benchmark_series_path=tri_high_path,
        cas_current=5170911.38
    )
    assert audit_50["benchmark_matched_xirr_pct"] is not None
    assert audit_50["benchmark_isin"] == "INF769K01EY5"
    assert audit_50["alpha_pct"] > 2.0, "Portfolio generates > +2.0% alpha against large-cap Nifty 50 TRI"
    assert audit_50.get("coverage_pct", 0) >= 95.0

    print(f"[PASS] P0.14 Cash-Flow Matched TRI Benchmark Engine Verified (Nifty 500 TRI: {audit_500['benchmark_matched_xirr_pct']}%, Nifty 50 TRI: {audit_50['benchmark_matched_xirr_pct']}%)")

def test_p0_15_runtime_mandate_hold_enforcement():'''

if start >= 0 and end >= 0:
    t = t[:start] + new_func + t[end:]
    p.write_text(t)
    print('Done - TRI test updated')
else:
    print('Function not found')
    print('start:', start, 'end:', end)