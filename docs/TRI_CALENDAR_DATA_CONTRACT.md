# TRI and NSE Trading Calendar Data Contract

The release gate also requires the complete approved benchmark universe, not merely any non-empty subset:

- `NIFTY 500 TRI` — broad-market/flexi-cap comparison (including the approved HDFC Flexi Cap mapping).
- `NIFTY 500 MULTICAP 50:25:25 TRI` — multi-cap comparison (including the approved Nippon India Multi Cap mapping).
- `NIFTY MIDCAP 150 TRI` — mid-cap comparison (including the approved Motilal Oswal Midcap mapping).

Benchmark names are matched case-insensitively after trimming whitespace. Additional series may be supplied, but cannot replace any required series. If any required benchmark is missing, alpha release is blocked.

The cash-flow-matched TRI calculation requires two distinct inputs:

1. A daily historical TRI series with a SHA256 checksum over its normalized `levels` mapping.
2. A separately maintained NSE trading-session calendar at `data/policy/nse_trading_calendar.json`.

The engine does **not** generate expected sessions by counting weekdays. NSE holidays and special sessions make weekday arithmetic insufficient.

## Calendar file schema

```json
{
  "exchange": "NSE",
  "status": "VERIFIED",
  "sessions": ["2026-01-01", "2026-01-02"],
  "provenance": {
    "source_url": "https://www.nseindia.com/...",
    "source_document_sha256": "<64 hexadecimal characters>",
    "sessions_sha256": "<SHA256 of compact JSON sessions array>"
  }
}
```

Requirements:

- `sessions` must contain unique, ascending ISO `YYYY-MM-DD` dates.
- The session list must be reconciled against official NSE trading-session/holiday records before `status` is set to `VERIFIED`.
- `source_document_sha256` records the source document digest.
- `sessions_sha256` is SHA256 of `json.dumps(sessions, separators=(",", ":"), ensure_ascii=False)` encoded as UTF-8.
- The calendar must cover the entire investor cash-flow window through the requested terminal date.
- A generated weekday list, benchmark series dates, or editable `expected_trading_days` metadata is not an acceptable substitute.

## Fail-closed behaviour

If the calendar file is absent, malformed, checksum-invalid, or does not cover the investor cash-flow window, TRI XIRR/alpha is unavailable. The benchmark JSON's `expected_trading_days` and `coverage_pct` fields are descriptive only and are not used as the coverage denominator.

Daily TRI observations are required. Cash flows on non-trading dates use the preceding session's TRI close; values are not linearly interpolated or extrapolated.

The engine verifies the supplied series/calendar checksums and validates the provenance metadata shape. It does not cryptographically authenticate the source publisher; the returned audit therefore explicitly leaves source authenticity as unverified. Human source review remains a release prerequisite.
