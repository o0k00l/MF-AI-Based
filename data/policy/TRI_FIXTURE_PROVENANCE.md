# TRI Fixture Status and Provenance Limitations

**Release eligibility: BLOCKED.**  
**Permitted use: checksum and fail-closed algorithm tests only.**

The files `benchmark_tri_series.json` and `benchmark_tri_series_high_coverage.json` are provisional test fixtures. They are not an authenticated record of official historical daily TRI observations.

## What the files establish

- The JSON level mappings are parseable.
- Their stored SHA-256 digests can be recomputed and compared with the corresponding metadata values.
- The calculator can reject a missing independent NSE session calendar.
- The coverage helper can reject sparse observations even when a caller supplies inflated coverage metadata.

A matching checksum proves only that a local file matches its declared digest. It does not establish who published the source data, whether the index is the correct TRI, whether values are genuine observations or whether the series is complete.

## What is not established

- No authenticated historical NSE Indices/AMFI daily TRI CSV is committed.
- The live-market-page URLs in fixture metadata are not historical source-file URLs.
- The high-coverage file includes interpolated/generated date points; these are not historical daily TRI observations.
- No independently verified NSE trading-session calendar file is committed.
- The 985 rows in the high-coverage fixture must not be interpreted as 985 authenticated trading sessions or 100% market-data coverage.
- No cash-flow-matched benchmark XIRR or alpha is approved for investment selection or client reporting.

The coverage fields in the fixture are deliberately non-authoritative. They are descriptive placeholders only and must not be used as a denominator or as proof of completeness.

## Requirements before benchmark release

1. Obtain official historical daily TRI files for each benchmark index from an authoritative publisher endpoint.
2. Preserve each original source document, retrieval timestamp, index identifier, source URL and SHA-256 digest.
3. Parse the published observations without interpolation or extrapolation. Document any source-publisher corrections or non-trading-date conventions.
4. Obtain the independent NSE trading-session/holiday calendar for the complete cash-flow period. Preserve its source document and digest.
5. Validate that every required market session is covered and that all observed TRI dates are actual calendar sessions.
6. Independently reconcile investor external cash flows, dividends, switches/STPs, terminal value and XIRR against a second implementation.
7. Run `verify_tri_provenance.py` and the coverage-gate regression against the exact release commit.

Until these conditions are met, the system must expose benchmark XIRR and alpha as unavailable and must not rank funds using interpolated test data.
