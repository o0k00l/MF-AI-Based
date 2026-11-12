"""
core/math_engine.py - Deterministic Fiduciary Financial Mathematics Engine.

Calculates:
1. Regular-to-Direct commission leakage (Annual ₹ & 10-Year Compounded Loss)
2. Pairwise stock overlap matrix (Minimum-Weight Overlap Arbiter)
3. Strategic Asset Allocation (SAA) current vs target drift
4. Idle cash deployment waterfall (Emergency reserve vs Deployable surplus)
"""

import json
import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from collections import defaultdict
import openpyxl
from datetime import datetime, date, timedelta
from dataclasses import dataclass
import math

# Import various model classes for type annotations
import decimal
from decimal import Decimal, ROUND_HALF_UP
from core.models import (
    TriProvenanceError, HoldingItem, FeeBleedAnalysis, PlanType, AssetClass,
    quantize_inr, _is_finite_numeric
)

# ─────────────────────────────────────────────────────────────────────────────
# DATE-AWARE STATUTORY TAX LAYER (1961 Act vs 2025 Act)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StatutoryTaxCitation:
    governing_act: str
    transfer_statute: str
    ltcg_statute: str
    stcg_statute: str
    debt_fund_statute: str
    loss_netting_statute: str
    loss_carryforward_statute: str


def get_statutory_tax_citation(as_of: Optional[date] = None) -> StatutoryTaxCitation:
    """
    Determines governing tax legislation based on transaction execution date:
    - Pre-1 April 2026: Governed by Income-tax Act, 1961 (as amended by Finance Act 2024).
    - Post-1 April 2026: Governed by Income-tax Act, 2025 (effective 1 April 2026).
    """
    if as_of is None:
        as_of = date.today()

    if as_of < date(2026, 4, 1):
        return StatutoryTaxCitation(
            governing_act="Income-tax Act, 1961 (amended by Finance Act 2024)",
            transfer_statute="Section 45 read with Section 2(47) (Switch treated as taxable transfer)",
            ltcg_statute="Section 112A (12.5% LTCG above statutory ₹1,25,000 aggregate annual exemption)",
            stcg_statute="Section 111A (20.0% STCG on equity units held <= 365 days)",
            debt_fund_statute="Section 50AA (Deemed short-term capital gain taxed at investor marginal slab rate)",
            loss_netting_statute="Section 70 (Intra-head capital loss set-off) & Section 71 (Inter-head restrictions)",
            loss_carryforward_statute="Section 74 (Carry forward and set-off of capital losses up to 8 assessment years)"
        )
    else:
        return StatutoryTaxCitation(
            governing_act="Income-tax Act, 2025 (effective 1 April 2026)",
            transfer_statute="Section 45 equivalent / Transfer Definition (Mutual fund unit switch treated as taxable transfer)",
            ltcg_statute="Section 198 (Special provision for long-term capital gains on qualifying equity-oriented mutual funds; distinct from Section 197 general LTCG)",
            stcg_statute="Section 196 (Short-term capital gains on qualifying equity assets)",
            debt_fund_statute="Section 76 (from 1 April 2026: specified mutual fund units acquired on/after 1 April 2023 where >65% of total proceeds are invested in debt and money-market instruments, or a fund of funds investing >=65% in units of such funds; also includes market-linked debentures; apply statutory annual-average-of-daily-closing test)",
            loss_netting_statute="Section 108 (Current-year intra-head capital loss set-off) & Section 109 (Inter-head restrictions)",
            loss_carryforward_statute="Section 111 (Carry forward and set-off of capital losses up to 8 assessment years)"
        )


def calculate_xirr(cashflows: List[Tuple[date, float]]) -> Optional[float]:
    """Calculate XIRR using the canonical solver; strict domain and convergence verification."""
    from core.math.xirr import calculate_xirr as canonical_xirr
    return canonical_xirr(cashflows)


# ─────────────────────────────────────────────────────────────────────────────
# CASH FLOW CLASSIFICATION FOR BENCHMARK XIRR
# ─────────────────────────────────────────────────────────────────────────────

def classify_cashflow(txn_type: str, txn_subtype: str = "") -> str:
    """
    Classify a transaction for Benchmark XIRR cashflow filtering.

    EXTERNAL FLOWS (investor-level, affect portfolio value):
    - PURCHASE: Investor puts new money in
    - SIP: Systematic Investment Plan (external recurring investment)
    - REDEMPTION: Investor takes money out (full redemption)
    - DIVIDEND: Cash dividend payout (money leaves fund to investor)

    INTERNAL FLOWS (net-zero at portfolio level, do NOT affect benchmark XIRR):
    - SWITCH_IN / SWITCH_OUT: Fund-to-fund transfer within portfolio
    - STP_IN / STP_OUT: Systematic Transfer Plan within portfolio
    - DIVIDEND_REINVEST: Dividend automatically reinvested (no cash leaves)

    Args:
        txn_type: Transaction type from transactions.json (e.g., "PURCHASE", "SWITCH_IN")
        txn_subtype: Optional subtype for more granular classification

    Returns:
        "external" or "internal"
    """
    txn_type = txn_type.upper()
    txn_subtype = txn_subtype.upper() if txn_subtype else ""

    # External flows - investor puts in or takes out cash
    if txn_type == "DIVIDEND" and any(marker in txn_subtype for marker in ("REINVEST", "REINVESTMENT", "DRP")):
        return "internal"

    if txn_type in ("PURCHASE", "SIP", "REDEMPTION", "SWP", "DIVIDEND"):
        return "external"

    # Internal flows - net zero at portfolio level
    if txn_type in ("SWITCH_IN", "SWITCH_OUT", "STP_IN", "STP_OUT", "DIVIDEND_REINVEST"):
        return "internal"

    raise ValueError(f"Unsupported transaction type for cash-flow classification: {txn_type!r}")


def filter_external_cashflows(transactions: list[dict]) -> list[dict]:
    """
    Filter transactions to only include external cash flows for Benchmark XIRR.

    This ensures SWITCH/STP and reinvested dividends are excluded
    since they net to zero at the portfolio level.

    Args:
        transactions: List of transaction dicts from transactions.json

    Returns:
        Filtered list with only external cash flows
    """
    return [
        txn for txn in transactions
        if classify_cashflow(txn.get("type", ""), txn.get("subtype", "")) == "external"
    ]


def calculate_tri_calendar_coverage(
    observed_dates: List[date],
    calendar_sessions: List[date],
    coverage_start: date,
    coverage_end: date,
    minimum_coverage_pct: float = 95.0,
    benchmark_key: str = "TRI",
) -> Dict[str, Any]:
    """
    Calculate TRI observation coverage against an independently supplied
    exchange-session calendar. This helper validates arithmetic only; the
    caller remains responsible for authenticating calendar and TRI sources.
    """
    from core.models import TriProvenanceError

    if not isinstance(coverage_start, date) or not isinstance(coverage_end, date) or coverage_start > coverage_end:
        raise ValueError("TRI coverage window must contain ordered date values")
    if isinstance(minimum_coverage_pct, bool):
        raise ValueError("minimum_coverage_pct must be numeric")
    try:
        minimum = float(minimum_coverage_pct)
    except (TypeError, ValueError) as exc:
        raise ValueError("minimum_coverage_pct must be numeric") from exc
    if not math.isfinite(minimum) or not 0.0 < minimum <= 100.0:
        raise ValueError("minimum_coverage_pct must be finite and in (0, 100]")

    if not calendar_sessions:
        raise TriProvenanceError(
            "Independent exchange-session calendar is empty.",
            benchmark=benchmark_key,
            validation_stage="trading_calendar_range_insufficient",
        )
    if calendar_sessions != sorted(set(calendar_sessions)):
        raise TriProvenanceError(
            "Exchange-session calendar must be unique and strictly ascending.",
            benchmark=benchmark_key,
            validation_stage="trading_calendar_order_invalid",
        )
    if coverage_start < calendar_sessions[0] or coverage_end > calendar_sessions[-1]:
        raise TriProvenanceError(
            "Independent exchange calendar does not cover the full investor cash-flow window.",
            benchmark=benchmark_key,
            validation_stage="trading_calendar_range_insufficient",
        )

    expected_sessions = [d for d in calendar_sessions if coverage_start <= d <= coverage_end]
    expected_set = set(expected_sessions)
    observed_set = set(observed_dates)
    non_session_points = sorted(observed_set - set(calendar_sessions))
    if non_session_points:
        raise TriProvenanceError(
            f"TRI data contains dates that are not exchange sessions: {non_session_points[:5]}",
            benchmark=benchmark_key,
            validation_stage="tri_dates_not_exchange_sessions",
        )

    expected_count = len(expected_sessions)
    provided_count = len(observed_set & expected_set)
    coverage_pct = provided_count / expected_count * 100.0 if expected_count else 0.0
    if expected_count == 0 or coverage_pct < minimum:
        raise TriProvenanceError(
            f"TRI coverage {coverage_pct:.2f}% below minimum {minimum:.1f}% "
            f"for {benchmark_key}. Independent calendar expects {expected_count} sessions "
            f"between {coverage_start} and {coverage_end}; observed {provided_count}.",
            benchmark=benchmark_key,
            validation_stage="coverage_insufficient",
        )
    return {
        "expected_trading_days": expected_count,
        "provided_data_points": provided_count,
        "coverage_pct": coverage_pct,
    }


def calculate_cashflow_matched_benchmark_xirr(
    transactions_path: Path,
    as_of_date: Optional[date] = None,
    benchmark_key: str = "NIFTY 500 TRI",
    benchmark_series_path: Optional[Path] = None,
    cas_current: Optional[float] = None,
    trading_calendar_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Cash-flow-matched Total Return Index (TRI) benchmark performance calculation.
    Replaces static benchmark approximations with an institutional unit-acquisition model:
    - Every transaction date in transactions.json purchases/redeems hypothetical units in the benchmark TRI.
    - Non-trading-day cash flows use the preceding available NSE session close; no synthetic interpolation.
    - Terminal valuation of accumulated benchmark units is evaluated as of as_of_date.
    - Benchmark XIRR and True Portfolio Alpha are deterministically solved.

    PROVENANCE VALIDATION (Zero Hardcoding & Zero Fabrication Mandate):
    - Validates SHA256 checksums of benchmark levels against provenance metadata
    - Enforces minimum trading day coverage threshold (95%)
    - Audits missing-date forward-fill policy
    - Raises TriProvenanceError on any validation failure — NO SILENT FALLBACKS
    """
    from core.models import TriProvenanceError
    import hashlib

    if benchmark_series_path is None:
        benchmark_series_path = Path("data/policy/benchmark_tri_series.json")
    if trading_calendar_path is None:
        trading_calendar_path = Path("data/policy/nse_trading_calendar.json")

    if not trading_calendar_path.exists():
        raise TriProvenanceError(
            f"Independent NSE trading calendar not found: {trading_calendar_path}",
            benchmark=benchmark_key,
            validation_stage="trading_calendar_missing"
        )
    if not benchmark_series_path.exists():
        raise TriProvenanceError(
            f"Benchmark TRI series file not found: {benchmark_series_path}",
            benchmark=benchmark_key,
            validation_stage="file_existence"
        )
    if not transactions_path.exists():
        raise TriProvenanceError(
            f"Transactions file not found: {transactions_path}",
            benchmark=benchmark_key,
            validation_stage="file_existence"
        )

    try:
        with open(transactions_path, "r", encoding="utf-8") as f:
            tx_data = json.load(f)
        with open(benchmark_series_path, "r", encoding="utf-8") as f:
            tri_data = json.load(f)
        with open(trading_calendar_path, "r", encoding="utf-8") as f:
            calendar_data = json.load(f)
    except Exception as e:
        raise TriProvenanceError(
            f"Failed to read benchmark series or transactions: {e}",
            benchmark=benchmark_key,
            validation_stage="read_error"
        )

    # PROVENANCE VALIDATION: Checksum verification
    provenance = tri_data.get("provenance", {})
    benchmarks = tri_data.get("benchmarks", {})
    if not isinstance(provenance, dict) or not isinstance(benchmarks, dict):
        raise TriProvenanceError(
            "TRI provenance and benchmark series must be JSON objects.",
            benchmark=benchmark_key,
            validation_stage="benchmark_structure_invalid"
        )
    b_info = benchmarks.get(benchmark_key)
    if not isinstance(b_info, dict):
        raise TriProvenanceError(
            f"Requested benchmark '{benchmark_key}' is absent; benchmark substitution is prohibited.",
            benchmark=benchmark_key,
            validation_stage="benchmark_missing"
        )
    levels = b_info.get("levels", {})

    if not isinstance(levels, dict) or not levels:
        raise TriProvenanceError(
            f"Benchmark '{benchmark_key}' has empty or malformed levels — cannot compute TRI XIRR",
            benchmark=benchmark_key,
            validation_stage="empty_levels"
        )

    # Verify checksum for every supported benchmark. Unknown benchmark names
    # must not bypass provenance validation by omitting a checksum mapping.
    levels_str = json.dumps(levels, sort_keys=True, separators=(",", ":"))
    computed_checksum = hashlib.sha256(levels_str.encode()).hexdigest()
    checksum_field_map = {
        "NIFTY 500 TRI": "checksum_sha256_nifty_500_tri",
        "NIFTY 500 MULTICAP 50:25:25 TRI": "checksum_sha256_nifty_500_multicap_50_25_25_tri",
        "NIFTY MIDCAP 150 TRI": "checksum_sha256_nifty_midcap_150_tri",
        "NIFTY 50 TRI": "checksum_sha256_nifty_50_tri",
    }
    expected_checksum_field = checksum_field_map.get(benchmark_key)
    if expected_checksum_field is None:
        raise TriProvenanceError(
            f"No approved provenance checksum contract exists for benchmark '{benchmark_key}'.",
            benchmark=benchmark_key,
            validation_stage="benchmark_not_approved"
        )
    expected_checksum = provenance.get(expected_checksum_field, "")
    if (
        not isinstance(expected_checksum, str)
        or len(expected_checksum) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in expected_checksum)
    ):
        raise TriProvenanceError(
            f"Missing or invalid checksum for {benchmark_key} in provenance metadata",
            benchmark=benchmark_key,
            validation_stage="checksum_missing"
        )
    if computed_checksum.lower() != expected_checksum.lower():
        raise TriProvenanceError(
            f"Checksum mismatch for {benchmark_key}: expected {expected_checksum[:16]}..., got {computed_checksum[:16]}...",
            benchmark=benchmark_key,
            validation_stage="checksum_mismatch"
        )

    # COVERAGE VALIDATION: use a separately maintained NSE session calendar.
    # The benchmark JSON's expected_trading_days / coverage_pct are descriptive only;
    # they are not trusted as the denominator because the same fixture can edit them.
    try:
        for date_key, raw_level in levels.items():
            parsed_level = float(raw_level)
            datetime.strptime(date_key, "%Y-%m-%d")
            if not math.isfinite(parsed_level) or parsed_level <= 0:
                raise ValueError(f"Invalid TRI level for {date_key}")
    except (TypeError, ValueError) as exc:
        raise TriProvenanceError(
            f"TRI levels contain invalid dates or non-positive/non-finite values: {exc}",
            benchmark=benchmark_key,
            validation_stage="levels_invalid"
        )
    sorted_dates = sorted([datetime.strptime(d, "%Y-%m-%d").date() for d in levels])
    if not sorted_dates:
        raise TriProvenanceError(
            f"No TRI data available for {benchmark_key}",
            benchmark=benchmark_key,
            validation_stage="no_data"
        )

    calendar_provenance = calendar_data.get("provenance", {})
    sessions = calendar_data.get("sessions", [])
    source_url = str(calendar_provenance.get("source_url", ""))
    source_document_sha256 = str(calendar_provenance.get("source_document_sha256", ""))
    sessions_sha256 = str(calendar_provenance.get("sessions_sha256", ""))
    if (
        calendar_data.get("exchange") != "NSE"
        or calendar_data.get("status") != "VERIFIED"
        or not source_url.startswith("https://")
        or len(source_document_sha256) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in source_document_sha256)
        or not isinstance(sessions, list)
        or not sessions
    ):
        raise TriProvenanceError(
            "NSE calendar must include VERIFIED status, HTTPS source URL, source-document SHA256 and a non-empty sessions list.",
            benchmark=benchmark_key,
            validation_stage="trading_calendar_provenance_invalid"
        )
    computed_sessions_sha256 = hashlib.sha256(
        json.dumps(sessions, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if computed_sessions_sha256 != sessions_sha256:
        raise TriProvenanceError(
            "NSE calendar session checksum mismatch.",
            benchmark=benchmark_key,
            validation_stage="trading_calendar_checksum_mismatch"
        )
    try:
        calendar_sessions = [datetime.strptime(str(d), "%Y-%m-%d").date() for d in sessions]
    except ValueError as exc:
        raise TriProvenanceError(
            f"NSE calendar contains an invalid session date: {exc}",
            benchmark=benchmark_key,
            validation_stage="trading_calendar_dates_invalid"
        )
    if calendar_sessions != sorted(set(calendar_sessions)):
        raise TriProvenanceError(
            "NSE calendar sessions must be unique and strictly ascending.",
            benchmark=benchmark_key,
            validation_stage="trading_calendar_order_invalid"
        )

    # Coverage spans the actual investor cash-flow window through the requested
    # terminal date, not merely the observed TRI start/end (which would let a
    # truncated series report 100% coverage).
    required_dates = []
    for row_index, txn in enumerate(tx_data.get("transactions", [])):
        try:
            raw_amount = float(txn.get("amount", 0))
            if raw_amount == 0:
                continue
            raw_date = txn.get("date")
            if not raw_date:
                raise ValueError("transaction date missing")
            required_dates.append(datetime.strptime(str(raw_date)[:10], "%Y-%m-%d").date())
        except (TypeError, ValueError) as exc:
            raise TriProvenanceError(
                f"Transaction row {row_index} cannot define the TRI coverage window: {exc}",
                benchmark=benchmark_key,
                validation_stage="transaction_date_invalid"
            )
    if not required_dates:
        return {
            "benchmark_name": b_info.get("name", benchmark_key),
            "benchmark_matched_xirr_pct": None,
            "alpha_pct": None,
            "cashflows_count": 0,
            "methodology": "Zero cashflows"
        }
    if as_of_date is None:
        raise TriProvenanceError(
            "Explicit as_of_date matching the CAS valuation date is required; the latest transaction date is not a valid terminal-date substitute.",
            benchmark=benchmark_key,
            validation_stage="as_of_date_missing"
        )
    coverage_start = min(required_dates)
    coverage_end = as_of_date
    coverage_result = calculate_tri_calendar_coverage(
        observed_dates=sorted_dates,
        calendar_sessions=calendar_sessions,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        minimum_coverage_pct=95.0,
        benchmark_key=benchmark_key,
    )
    expected_trading_days = coverage_result["expected_trading_days"]
    provided_data_points = coverage_result["provided_data_points"]
    effective_coverage_pct = coverage_result["coverage_pct"]

    # MISSING-DATE AUDIT: Forward-fill tracking
    sorted_dates = sorted([datetime.strptime(d, "%Y-%m-%d").date() for d in levels])
    date_gaps = []
    for i in range(len(sorted_dates) - 1):
        d0, d1 = sorted_dates[i], sorted_dates[i + 1]
        gap_days = (d1 - d0).days
        if gap_days > 35:  # More than ~monthly gap indicates missing data
            date_gaps.append({"from": str(d0), "to": str(d1), "gap_days": gap_days})

    def get_tri(d: date) -> float:
        """Return the exact session close or prior session close for non-trading dates."""
        if d < sorted_dates[0] or d > sorted_dates[-1]:
            raise TriProvenanceError(
                f"Requested TRI date {d} falls outside the observed series.",
                benchmark=benchmark_key,
                validation_stage="tri_date_out_of_range"
            )
        if str(d) in levels:
            return float(levels[str(d)])
        prior_dates = [session for session in sorted_dates if session < d]
        if not prior_dates:
            raise TriProvenanceError(
                f"No preceding NSE session exists for {d}.",
                benchmark=benchmark_key,
                validation_stage="tri_prior_session_missing"
            )
        return float(levels[str(prior_dates[-1])])

    cashflows = []
    txn_dates = []
    # Internal transfers are never investor-level cash flows. CAS may encode
    # the out-leg as REDEMPTION with "Switch Out" in its description.

    for txn_index, txn in enumerate(tx_data.get("transactions", [])):
        d_str = txn.get("date", "")
        if not d_str:
            raise TriProvenanceError(
                f"Transaction row {txn_index} has no date and cannot be silently omitted.",
                benchmark=benchmark_key,
                validation_stage="transaction_date_missing"
            )
        try:
            txn_date = datetime.strptime(d_str[:10], "%Y-%m-%d").date()
            amount = float(txn.get("amount", 0))
            txn_type = str(txn.get("type", "")).upper().strip()
            allowed_types = {
                "PURCHASE", "SIP", "REDEMPTION", "SWP", "DIVIDEND",
                "DIVIDEND_REINVEST", "SWITCH_IN", "SWITCH_OUT", "STP_IN", "STP_OUT",
            }
            if txn_type not in allowed_types:
                raise ValueError(f"unsupported transaction type {txn_type!r}")
            desc = str(txn.get("description", "")).lower()
            folio = txn.get("folio", "") or txn.get("folio_number", "") or ""
            scheme = txn.get("scheme", "") or txn.get("fund", "") or ""
            if amount == 0:
                continue
            txn_dates.append(txn_date)
            is_reversal = any(kw in desc for kw in ("reversal", "dishonour", "reject"))

            # Exclude internal transfers regardless of whether CAS labels the
            # out-leg SWITCH_OUT or REDEMPTION. Pair matching by amount/date is
            # unreliable because switch legs can settle on different dates and
            # include STT/rounding differences.
            transfer_description = any(
                marker in desc
                for marker in ("switch in", "switch-in", "switch out", "switch-out", "stp in", "stp-in", "stp out", "stp-out")
            )
            if txn_type in ("SWITCH_IN", "SWITCH_OUT", "STP_IN", "STP_OUT", "DIVIDEND_REINVEST") or transfer_description:
                continue

            if amount < 0:
                cf = -amount
            else:
                # DIVIDEND: classify as cash vs reinvested
                if txn_type == "DIVIDEND":
                    is_reinvested = any(kw in desc for kw in ("reinvest", "reinvestment", "drp", "dividend reinvest"))
                    if is_reinvested:
                        # Reinvested dividend: not a cash flow, skip
                        continue
                    # Cash dividend: taxable inflow
                    cf = abs(amount)
                elif txn_type in ("REDEMPTION", "SWP") and not is_reversal:
                    cf = abs(amount)
                else:
                    cf = -amount
            cashflows.append((txn_date, cf))
        except Exception as exc:
            raise TriProvenanceError(
                f"Transaction row {txn_index} is malformed and cannot be silently omitted: {exc}",
                benchmark=benchmark_key,
                validation_stage="transaction_row_invalid"
            )

    if txn_dates:
        out_of_range = [d for d in txn_dates if d < sorted_dates[0] or d > sorted_dates[-1]]
        if out_of_range:
            raise TriProvenanceError(
                f"Cash-flow dates fall outside observed TRI range: {out_of_range[:5]}",
                benchmark=benchmark_key,
                validation_stage="cashflow_date_out_of_range"
            )

    if not cashflows:
        return {
            "benchmark_name": b_info.get("name", benchmark_key),
            "benchmark_matched_xirr_pct": None,
            "alpha_pct": None,
            "cashflows_count": 0,
            "methodology": "Zero cashflows"
        }

    if as_of_date is None:
        as_of_date = max(txn_dates) if txn_dates else date.today()

    # Terminal portfolio value is investor-specific evidence, never a fallback constant.
    if cas_current is None or isinstance(cas_current, bool):
        raise TriProvenanceError(
            "Current CAS valuation is missing; portfolio XIRR/alpha cannot be calculated.",
            benchmark=benchmark_key,
            validation_stage="terminal_valuation_missing"
        )
    try:
        port_val = float(cas_current)
    except (TypeError, ValueError) as exc:
        raise TriProvenanceError(
            f"Current CAS valuation is invalid: {exc}",
            benchmark=benchmark_key,
            validation_stage="terminal_valuation_invalid"
        )
    if not math.isfinite(port_val) or port_val <= 0:
        raise TriProvenanceError(
            "Current CAS valuation must be finite and positive.",
            benchmark=benchmark_key,
            validation_stage="terminal_valuation_invalid"
        )
    if as_of_date < max(txn_dates):
        raise TriProvenanceError(
            "As-of date precedes the latest transaction; terminal valuation is temporally invalid.",
            benchmark=benchmark_key,
            validation_stage="terminal_valuation_date"
        )
    if as_of_date < sorted_dates[0] or as_of_date > sorted_dates[-1]:
        raise TriProvenanceError(
            "As-of date falls outside the observed TRI series; extrapolation/forward-fill is prohibited.",
            benchmark=benchmark_key,
            validation_stage="terminal_date_out_of_range"
        )
    # Monthly points cannot support exact daily cash-flow matching through interpolation.
    if str(provenance.get("frequency", "")).strip().lower().startswith(("monthly", "quarterly")):
        raise TriProvenanceError(
            "Benchmark series is not daily; interpolated monthly/quarterly points are not accepted for cash-flow-matched XIRR.",
            benchmark=benchmark_key,
            validation_stage="frequency_insufficient"
        )
    # A live-market page is not historical TRI source provenance.
    historical_source = str(provenance.get("historical_source_url", "") or "")
    source_document_sha256 = str(provenance.get("source_document_sha256", "") or "")
    if (
        not historical_source.startswith("https://")
        or len(source_document_sha256) != 64
        or any(c not in "0123456789abcdefABCDEF" for c in source_document_sha256)
    ):
        raise TriProvenanceError(
            "Historical TRI source must include an HTTPS URL and a 64-character source-document SHA256; a levels checksum alone does not authenticate provenance.",
            benchmark=benchmark_key,
            validation_stage="source_provenance_missing"
        )
    port_xirr = calculate_xirr(cashflows + [(as_of_date, port_val)])

    total_units = 0.0
    for d, cf in cashflows:
        nav = get_tri(d)
        units = -cf / nav
        total_units += units

    bench_terminal_val = total_units * get_tri(as_of_date)
    bench_cf = list(cashflows) + [(as_of_date, bench_terminal_val)]
    bench_xirr = calculate_xirr(bench_cf)
    alpha_pct = ((port_xirr - bench_xirr) * 100.0) if (port_xirr is not None and bench_xirr is not None) else None

    return {
        "benchmark_name": b_info.get("name", benchmark_key),
        "benchmark_symbol": b_info.get("symbol", ""),
        "benchmark_isin": b_info.get("isin", ""),
        "as_of_date": str(as_of_date),
        "cashflows_count": len(cashflows),
        "benchmark_units_accumulated": round(total_units, 4),
        "benchmark_terminal_valuation_inr": round(bench_terminal_val, 2),
        "benchmark_matched_xirr_pct": round(bench_xirr * 100.0, 2) if bench_xirr else None,
        "portfolio_xirr_pct": round(port_xirr * 100.0, 2) if port_xirr else None,
        "alpha_pct": round(alpha_pct, 2) if alpha_pct is not None else None,
        "methodology": "Cash-flow-matched TRI unit acquisition model; benchmark series checksum and separate NSE calendar metadata checked, but source authenticity requires separate human verification",
        "provenance_audit": {
            "series_checksum_verified": True,
            "source_authenticity_verified": False,
            "computed_checksum": computed_checksum,
            "calendar_sessions_checksum_verified": True,
            "calendar_source_url": source_url,
            "calendar_source_authenticity_verified": False,
            "expected_trading_sessions": expected_trading_days,
            "coverage_pct": effective_coverage_pct,
            "date_gaps_detected": len(date_gaps),
            "gap_details": date_gaps[:5] if date_gaps else [],
            "missing_date_policy": provenance.get("missing_date_policy", ""),
        }
    }


def assert_mandate_execution_authorized(facts: Any):
    """
    Enforces runtime invariant: blocks live execution orders if portfolio is on hold.
    """
    from core.models import MandateExecutionState, MandateHoldViolationError
    m_state = getattr(facts, "mandate_state", None)
    state_value = m_state.value if isinstance(m_state, MandateExecutionState) else str(m_state or "")
    is_auth = getattr(facts, "is_execution_authorized", False)
    if state_value != MandateExecutionState.CLIENT_APPROVED.value or is_auth is not True:
        raise MandateHoldViolationError(
            f"MANDATE ENFORCEMENT VIOLATION: execution requires explicit CLIENT_APPROVED_EXECUTION_READY state "
            f"and is_execution_authorized is exactly True; received state={state_value!r}, authorized={is_auth!r}."
        )


from core.eligibility import (
    check_eligibility_gates,
    evaluate_no_action,
    filter_candidates,
    load_candidate_universe
)
from core.models import (
    HoldingItem,
    PlanType,
    AssetClass,
    FeeBleedAnalysis,
    OverlapPair,
    SAADriftAnalysis,
    CashDeploymentPlan,
    FiduciaryFactsPayload,
    WeightedOverlapResult,
    RiskDistribution,
    SwitchCostAnalysis,
    EligibilityGateResult,
    NOActionResult,
    SAA_DriftMinimizer,
    TaxLedger,
    ThematicExposureItem,
    LookThroughStabilityBuffer,
    DeterministicSIPRecommendation,
    DeterministicSIPPlan, DeterministicLumpsumPlan, LumpsumTrancheItem,
)


def _asset_class_to_risk_tier(asset_class: AssetClass) -> Optional[str]:
    """Asset class is not a scheme Riskometer observation; never infer a tier."""
    return None

# Import the new simplified SAA utilities
from core.models import RiskTier, AssetAllocationTarget, SAA_POLICY_MAP

def get_target_allocation(
    tier: RiskTier,
    custom_target: Optional[AssetAllocationTarget] = None,
    policy_path: Optional[Path] = None,
) -> AssetAllocationTarget:
    """
    Returns the exact target allocation based on the 3+1 logic from the authoritative policy.
    Carries authoritative policy_version and policy_digest.
    Fails closed if tier is CUSTOM and custom_target is not explicitly provided.
    """
    if tier == RiskTier.CUSTOM:
        if not custom_target:
            raise ValueError("Custom Tier selected but no custom target provided.")
        return custom_target

    from core.models import load_saa_policy_map
    policy_map = load_saa_policy_map(policy_path=policy_path)
    if tier not in policy_map:
        raise ValueError(f"Unrecognized RiskTier: {tier}")
    return policy_map[tier]


def load_holdings_from_cas_excel(
    xlsx_path: Path,
    fund_metrics_path: Optional[Path] = None,
    fund_aliases_path: Optional[Path] = None,
    scheme_master: Optional[Dict[str, Any]] = None,
    scheme_master_source_bytes: Optional[bytes] = None,
    portfolio_disclosures_by_scheme_id: Optional[Dict[str, Dict[str, Any]]] = None,
    portfolio_disclosure_source_bytes_by_scheme_id: Optional[Dict[str, bytes]] = None,
    disclosure_as_of_date: Optional[date] = None,
    disclosure_max_age_days: int = 45,
    require_exact_metric_identity: bool = True,
) -> List[HoldingItem]:
    """
    Parses active mutual fund holdings directly from CAS detailed report Excel sheet.
    Reconciles with fund_metrics.json for expense ratios, market-cap splits, sector allocations, and top stock holdings.

    When require_exact_metric_identity=True (default), requires exact scheme_id/ISIN binding
    to fund metrics; no name-based fuzzy matching. Fails closed without verified identity.
    """
    if not xlsx_path.exists():
        raise FileNotFoundError(f"CAS statement not found: {xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    # Flexible sheet detection: CAMS uses "Portfolio Details", KFinTech/MFCentral
    # may use "Holdings", "Scheme Details", "Portfolio_Summary", etc.
    _SHEET_KEYWORDS = ("portfolio", "holdings", "scheme details", "consolidated")
    sheet_name = None
    for name in wb.sheetnames:
        if any(kw in name.lower() for kw in _SHEET_KEYWORDS):
            sheet_name = name
            break
    if sheet_name is None:
        raise ValueError(
            "Invalid CAS workbook: no portfolio/holdings sheet found. "
            f"Available sheets: {wb.sheetnames}"
        )

    sheet = wb[sheet_name]

    # Load metrics dictionary if provided
    metrics_map = {}
    metrics_provenance = {"status": "MISSING", "reason": "No metrics path supplied."}
    if fund_metrics_path and fund_metrics_path.exists():
        with open(fund_metrics_path, "r", encoding="utf-8") as f:
            m_data = json.load(f)
            for m in m_data.get("funds", []):
                fid = re.sub(r"[^a-z0-9]", "", m.get("id", "")).strip().casefold()
                metrics_map[fid] = m
            # Issue #84: Validate metrics provenance and exact scheme binding
            metrics_provenance = _validate_metrics_provenance(
                metrics_map,
                scheme_master,
                require_exact_identity=require_exact_metric_identity,
            )

    # Load aliases dictionary if provided
    aliases_map = {}
    if (not require_exact_metric_identity and fund_aliases_path
            and fund_aliases_path.exists()):
        with open(fund_aliases_path, "r", encoding="utf-8") as f:
            raw_aliases = json.load(f)
            if "aliases" in raw_aliases:
                for can, names in raw_aliases["aliases"].items():
                    for n in names:
                        aliases_map[n.strip().lower()] = can.strip().lower()
            else:
                for k, v in raw_aliases.items():
                    aliases_map[k.strip().lower()] = str(v).strip().lower()

    holdings: List[HoldingItem] = []
    raw_items = []

    # Parse only an explicit, complete header contract. Never fall back to
    # positional columns: a different workbook layout could otherwise turn
    # unrelated cells into invested/current values without an obvious error.
    # Flexible header matching with aliases (handles CAMS, KFinTech, MFCentral variants)
    _HEADER_ALIASES = {
        "scheme name": "Scheme Name", "scheme": "Scheme Name", "fund name": "Scheme Name",
        "scheme description": "Scheme Name", "scheme / plan": "Scheme Name", "scheme/plan": "Scheme Name",
        "folio no.": "Folio No.", "folio no": "Folio No.", "folio": "Folio No.", "folio number": "Folio No.",
        "account no.": "Folio No.", "account no": "Folio No.",
        "invested value": "Invested Value", "invested": "Invested Value", "cost value": "Invested Value",
        "invested amount": "Invested Value", "cost basis": "Invested Value", "cost": "Invested Value",
        "current value": "Current Value", "current": "Current Value", "market value": "Current Value",
        "closing value": "Current Value", "valuation": "Current Value",
        "units": "Units", "unit": "Units", "closing units": "Units", "balance units": "Units",
        "amc name": "AMC Name", "amc": "AMC Name",
    }
    required_headers = {"Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"}

    hdr = None
    start_row = None
    for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        vals = [str(c).strip() if c is not None else "" for c in row]
        canon_vals = [_HEADER_ALIASES.get(v.lower(), v) for v in vals if v]
        if "Scheme Name" in canon_vals and any(h in canon_vals for h in ("Current Value", "Units", "Folio No.")):
            non_empty = [name for name in vals if name]
            if len(non_empty) != len(set(non_empty)):
                raise ValueError("Invalid CAS workbook: duplicate column headers in 'Portfolio Details'.")
            hdr = {name: i for i, name in enumerate(vals) if name}
            start_row = row_idx + 1
            break

    if hdr is None:
        raise ValueError("Invalid CAS workbook: no 'Scheme Name' header detected.")

    # Normalize header keys using aliases
    normalized_hdr = {}
    for key, idx in hdr.items():
        canonical = _HEADER_ALIASES.get(key.strip().lower(), key)
        normalized_hdr[canonical] = idx

    missing_headers = sorted(required_headers - set(normalized_hdr))
    if missing_headers:
        raise ValueError(
            "Invalid CAS workbook: missing required 'Portfolio Details' columns: "
            + ", ".join(missing_headers)
        )

    col_scheme = normalized_hdr["Scheme Name"]
    col_folio = normalized_hdr["Folio No."]
    col_inv = normalized_hdr["Invested Value"]
    col_cur = normalized_hdr["Current Value"]
    col_units = normalized_hdr["Units"]
    col_amc = normalized_hdr.get("AMC Name")

    for row in sheet.iter_rows(min_row=start_row, values_only=True):
        if not row or len(row) <= col_scheme or not row[col_scheme]:
            continue
        s_name = row[col_scheme]
        f_no = row[col_folio] if len(row) > col_folio else ""
        i_val = row[col_inv] if len(row) > col_inv else None
        c_val = row[col_cur] if len(row) > col_cur else None
        u_val = row[col_units] if len(row) > col_units else None
        try:
            if i_val is None or c_val is None or u_val is None:
                raise ValueError("blank financial cell")
            c_dec = Decimal(str(c_val).strip())
            i_dec = Decimal(str(i_val).strip())
            u_dec = Decimal(str(u_val).strip())
        except (ValueError, TypeError, decimal.InvalidOperation) as exc:
            raise ValueError(
                f"Invalid CAS workbook: malformed financial values for scheme {str(s_name).strip()!r}."
            ) from exc
        if not c_dec.is_finite() or not i_dec.is_finite() or not u_dec.is_finite():
            raise ValueError(
                f"Invalid CAS workbook: non-finite financial values for scheme {str(s_name).strip()!r}."
            )
        if i_dec < Decimal("0") or c_dec < Decimal("0") or u_dec < Decimal("0"):
            raise ValueError(
                f"Invalid CAS workbook: negative financial values for scheme {str(s_name).strip()!r}."
            )
        if c_dec > Decimal("0"):
            if u_dec <= Decimal("0"):
                raise ValueError(
                    f"Invalid CAS workbook: positive current value requires positive units for scheme {str(s_name).strip()!r}."
                )
            nav_dec = (c_dec / u_dec).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
            amc_value = row[col_amc] if col_amc is not None and len(row) > col_amc else ""
            raw_items.append((
                str(s_name).strip(),
                str(f_no).strip() if f_no else "",
                quantize_inr(i_dec),
                quantize_inr(c_dec),
                u_dec.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP),
                nav_dec,
                str(amc_value or "").strip(),
            ))

    for scheme_str, folio_str, invested, current, units_val, nav_val, amc_name in raw_items:
        # Plan and option are separate instrument attributes. Display-name
        # fragments are never evidence for either one.
        plan = PlanType.UNKNOWN
        is_direct = None
        plan_option_status = "MISSING"
        option_type = None

        # Resolve stable scheme identity and plan/option independently from
        # fund performance metrics. Only exact scheme-master fields can
        # establish Direct/Regular or Growth/IDCW.
        identity = {
            "scheme_id": None, "isin": None, "status": "MISSING",
            "plan_type": None, "option_type": None,
            "plan_option_status": "MISSING", "riskometer_score": None,
            "reason": "No verified scheme master was supplied.",
        }
        if scheme_master is not None and scheme_master_source_bytes is not None and amc_name:
            from ingestion.portfolio_disclosure import resolve_scheme_identity
            identity = resolve_scheme_identity(
                {"scheme": scheme_str, "amc_name": amc_name},
                scheme_master,
                source_bytes=scheme_master_source_bytes,
            )
        plan_option_status = identity.get("plan_option_status", "MISSING")
        option_type = identity.get("option_type")
        if plan_option_status == "VERIFIED":
            if identity.get("plan_type") == "DIRECT":
                plan, is_direct = PlanType.DIRECT, True
            elif identity.get("plan_type") == "REGULAR":
                plan, is_direct = PlanType.REGULAR, False
            else:
                plan_option_status = "CONFLICTING"

        # Exact identity / reviewed-alias metrics match only. Never infer
        # classification or substitute default exposures when metrics are absent.
        if require_exact_metric_identity:
            matched_metric = _find_matching_metric_by_scheme_identity(
                identity.get("scheme_id"), identity.get("isin"), metrics_map, identity=identity
            )
            if matched_metric is not None:
                _validate_sip_metrics_exposures(
                    matched_metric, scheme_id=identity["scheme_id"]
                )
        else:
            matched_metric = _find_matching_metric(scheme_str, metrics_map, aliases_map)
        if matched_metric is None:
            category = None
            er = None
            top_h = []
            eq_pct = debt_pct = lc_pct = mc_pct = sc_pct = 0.0
            asset_class = AssetClass.OTHER
            metrics_status = "MISSING"
            sector_alloc = None
            sub_cat = None
            fund_id = identity.get("scheme_id") or scheme_str[:30]
        else:
            category = matched_metric.get("cat")
            sector_alloc = matched_metric.get("sector")
            sub_cat = matched_metric.get("sub_category")
            raw_ter = matched_metric.get("er")
            ter_plan = str(
                matched_metric.get("ter_plan", matched_metric.get("plan", ""))
            ).strip().casefold()
            expected_plan = (
                "direct" if plan == PlanType.DIRECT
                else "regular" if plan == PlanType.REGULAR
                else None
            )
            # TER is plan-specific. Unknown plan identity cannot be assigned
            # either Direct or Regular TER, and no commission delta is inferred.
            if raw_ter is None or expected_plan is None or ter_plan != expected_plan:
                er = None
            else:
                er = float(raw_ter)
                if not math.isfinite(er) or er < 0:
                    raise ValueError(f"Invalid plan-specific TER evidence for {scheme_str!r}.")
            top_h = matched_metric.get("h", [])
            required_exposure_fields = ("eq", "debt", "lc", "mc", "sc")
            missing_exposure_fields = [
                field for field in required_exposure_fields
                if matched_metric.get(field) is None
            ]
            if missing_exposure_fields:
                raise ValueError(
                    f"Fund metrics for CAS scheme {scheme_str!r} are missing exposure fields: "
                    + ", ".join(missing_exposure_fields)
                    + "; portfolio-aware SIP analysis is withheld."
                )
            eq_pct = float(matched_metric["eq"])
            debt_pct = float(matched_metric["debt"])
            lc_pct = float(matched_metric["lc"])
            mc_pct = float(matched_metric["mc"])
            sc_pct = float(matched_metric["sc"])
            asset_class = _infer_asset_class(category, eq_pct, debt_pct, lc_pct, mc_pct, sc_pct)
            metrics_status = "VERIFIED"
            fund_id = matched_metric.get("id", identity.get("scheme_id") or scheme_str[:30])

        disclosure = {"constituent_weights": None,
                      "constituent_weights_coverage_pct": None,
                      "status": "MISSING",
                      "reason": "No verified portfolio disclosure was supplied."}
        if (identity.get("scheme_id")
                and portfolio_disclosures_by_scheme_id is not None
                and portfolio_disclosure_source_bytes_by_scheme_id is not None
                and disclosure_as_of_date is not None):
            from ingestion.portfolio_disclosure import validate_portfolio_disclosure
            disclosure_record = portfolio_disclosures_by_scheme_id.get(identity["scheme_id"])
            disclosure_bytes = portfolio_disclosure_source_bytes_by_scheme_id.get(identity["scheme_id"])
            if disclosure_record is not None and disclosure_bytes is not None:
                disclosure = validate_portfolio_disclosure(
                    disclosure_record, disclosure_bytes,
                    as_of=disclosure_as_of_date,
                    max_age_days=disclosure_max_age_days,
                )
                if disclosure.get("scheme_id") != identity["scheme_id"]:
                    disclosure = {"constituent_weights": None,
                                  "constituent_weights_coverage_pct": None,
                                  "status": "CONFLICTING",
                                  "reason": "Disclosure scheme identifier does not match resolved CAS identity."}

        holdings.append(
            HoldingItem(
                fund_id=fund_id,
                scheme=scheme_str,
                fund_name=scheme_str,
                folio=folio_str,
                is_direct=is_direct,
                plan=plan,
                plan_option_status=plan_option_status,
                option_type=option_type,
                invested_value_inr=invested,
                current_value_inr=current,
                asset_class=asset_class,
                equity_pct=eq_pct,
                debt_pct=debt_pct,
                hybrid_pct=0.0,
                international_pct=0.0,
                units=units_val,
                nav=nav_val,
                top_holdings=top_h,
                expense_ratio_pct=er,
                scheme_id=identity.get("scheme_id"),
                isin=identity.get("isin"),
                constituent_weights=disclosure.get("constituent_weights"),
                constituent_weights_coverage_pct=disclosure.get("constituent_weights_coverage_pct"),
                lookthrough_status=disclosure["status"],
                lookthrough_reason=disclosure["reason"],
                lookthrough_effective_date=disclosure.get("effective_date"),
                lookthrough_source_url=disclosure.get("source_url"),
                lookthrough_source_document_sha256=disclosure.get("source_document_sha256"),
                amc_name=amc_name or None,
                # Use only the scheme-level Riskometer score returned by
                # exact verified scheme-master identity resolution.
                risk_tier=(
                    f"Tier {identity['riskometer_score']}"
                    if identity.get("riskometer_score") is not None else None
                ),
                riskometer_score=identity.get("riskometer_score"),
                riskometer_as_of_date=identity.get("riskometer_as_of_date"),
                riskometer_source_url=identity.get("riskometer_source_url"),
                riskometer_source_document_sha256=identity.get("riskometer_source_document_sha256"),
                metrics_status=metrics_status,
                sector_allocation=sector_alloc,
                sub_category=sub_cat,
            )
        )

    return holdings


def _validate_sip_metrics_exposures(metric: Dict[str, Any], *, scheme_id: str) -> None:
    """Reject malformed exposure inputs before they influence SIP allocation."""
    required = ("eq", "debt", "lc", "mc", "sc")
    values: dict[str, float] = {}
    for field in required:
        raw = metric.get(field)
        if isinstance(raw, bool):
            raise ValueError(f"Fund metrics {field} exposure is invalid for {scheme_id!r}.")
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"Fund metrics {field} exposure is missing or invalid for {scheme_id!r}.") from exc
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise ValueError(f"Fund metrics {field} exposure is outside 0-100 for {scheme_id!r}.")
        values[field] = value
    if values["eq"] + values["debt"] > 100.0 + 1e-9:
        raise ValueError(f"Fund metrics equity plus debt exposure exceeds 100% for {scheme_id!r}.")


def _validate_metrics_provenance(
    metrics_map: Dict[str, Dict[str, Any]],
    scheme_master: Optional[Dict[str, Any]] = None,
    *,
    require_exact_identity: bool = False,
) -> Dict[str, Any]:
    """
    Issue #84: Validate metrics record provenance and exact scheme binding.

    Checks:
    1. Mixed-snapshot detection: all records must have consistent effective_date/source_ref.
    2. Exact identity tuple: when require_exact_identity=True, each record must have
       scheme_id, isin, amc_name, category, plan_type, option_type.
    3. Scheme master cross-check: identity fields must match the verified scheme master.

    Returns a provenance summary dict. Raises ValueError on tamper/mixed-snapshot/conflict.
    """
    if not metrics_map:
        return {
            "status": "MISSING",
            "reason": "No metrics records supplied.",
            "record_count": 0,
            "effective_dates": set(),
            "source_refs": set(),
        }

    effective_dates = set()
    source_refs = set()
    identity_errors = []
    scheme_master_index = {}

    # Build scheme master index for cross-checking
    if scheme_master and isinstance(scheme_master, dict):
        for scheme in scheme_master.get("schemes", []):
            sid = scheme.get("scheme_id") or scheme.get("id")
            if sid:
                scheme_master_index[str(sid).strip().upper()] = scheme

    required_identity_fields = ("scheme_id", "isin", "amc_name", "category", "plan_type", "option_type")

    for fid, metric in metrics_map.items():
        if not isinstance(metric, dict):
            identity_errors.append(f"Metrics record {fid!r} is not a mapping.")
            continue

        # Collect provenance fields
        eff_date = metric.get("effective_date") or metric.get("as_of_date")
        src_ref = metric.get("source_ref") or metric.get("source_document_sha256")
        if eff_date:
            effective_dates.add(str(eff_date).strip())
        if src_ref:
            source_refs.add(str(src_ref).strip().lower())

        if require_exact_identity:
            missing = [f for f in required_identity_fields if not metric.get(f)]
            if missing:
                identity_errors.append(
                    f"Metrics record {fid!r} is missing required identity fields: {', '.join(missing)}."
                )
                continue

            # Cross-check against scheme master if available
            sid = str(metric.get("scheme_id", "")).strip().upper()
            if sid and scheme_master_index:
                master_scheme = scheme_master_index.get(sid)
                if master_scheme is None:
                    identity_errors.append(
                        f"Metrics record {fid!r} scheme_id {sid!r} not found in verified scheme master."
                    )
                    continue
                # Check ISIN match
                m_isin = str(metric.get("isin", "")).strip().upper()
                s_isin = str(master_scheme.get("isin", "")).strip().upper()
                if m_isin and s_isin and m_isin != s_isin:
                    identity_errors.append(
                        f"Metrics record {fid!r} ISIN {m_isin!r} conflicts with scheme master ISIN {s_isin!r}."
                    )
                # Check AMC match
                m_amc = str(metric.get("amc_name", "")).strip().casefold()
                s_amc = str(master_scheme.get("amc_name", "") or master_scheme.get("amc", "")).strip().casefold()
                if m_amc and s_amc and m_amc != s_amc:
                    identity_errors.append(
                        f"Metrics record {fid!r} AMC {m_amc!r} conflicts with scheme master AMC {s_amc!r}."
                    )

    # Mixed-snapshot detection: more than one distinct effective date or source ref
    mixed_snapshot = len(effective_dates) > 1 or len(source_refs) > 1

    if identity_errors:
        raise ValueError(
            "Metrics provenance validation failed (exact identity): " + "; ".join(identity_errors[:5])
        )

    if mixed_snapshot:
        raise ValueError(
            f"Metrics provenance validation failed (mixed snapshot): "
            f"Found {len(effective_dates)} distinct effective dates and "
            f"{len(source_refs)} distinct source references. All metrics must come from a single reviewed snapshot."
        )

    return {
        "status": "VERIFIED",
        "record_count": len(metrics_map),
        "effective_dates": effective_dates,
        "source_refs": source_refs,
        "mixed_snapshot": False,
        "identity_complete": require_exact_identity,
    }


def _find_matching_metric_by_scheme_identity(
    scheme_id: Any,
    isin: Any,
    metrics: Dict[str, Any],
    identity: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve SIP metrics only by the exact verified scheme ID and ISIN.

    Display names and aliases are intentionally excluded: they cannot bind
    performance/exposure facts to a CAS holding. A conflicting ISIN for an
    otherwise matching scheme ID is an evidence error, not a missing match.
    Enforces exact identity tuple binding (AMC, category, plan, option) when identity is provided.
    """
    if not isinstance(scheme_id, str) or not scheme_id.strip():
        return None
    if not isinstance(isin, str) or not isin.strip():
        return None
    matches = [
        metric for metric in metrics.values()
        if isinstance(metric, dict) and metric.get("scheme_id") == scheme_id
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"Duplicate fund metrics for verified scheme ID {scheme_id!r}.")
    metric = matches[0]
    if metric.get("isin") != isin:
        raise ValueError(
            f"Fund metrics ISIN conflicts with verified scheme identity for {scheme_id!r}."
        )
    if identity:
        tuple_checks = [
            ("AMC", "amc_name", ["amc_name", "amc"]),
            ("Category", "category", ["category", "cat"]),
            ("Plan", "plan_type", ["plan_type", "plan", "ter_plan"]),
            ("Option", "option_type", ["option_type", "option"]),
        ]
        for tuple_name, id_key, metric_keys in tuple_checks:
            expected_val = identity.get(id_key)
            metric_val = next((metric[k] for k in metric_keys if k in metric and metric[k] is not None), None)
            if not expected_val:
                raise ValueError(
                    f"Verified scheme identity for {scheme_id!r} is missing required {tuple_name}."
                )
            if not metric_val:
                raise ValueError(
                    f"Fund metrics for {scheme_id!r} is missing required {tuple_name} identity field."
                )
            if str(expected_val).strip().casefold() != str(metric_val).strip().casefold():
                raise ValueError(
                    f"Fund metrics {tuple_name} '{metric_val}' conflicts with verified scheme {tuple_name} '{expected_val}' for {scheme_id!r}."
                )
    return metric


def _find_matching_metric(scheme: str, metrics: Dict[str, Any], aliases: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve metrics only by exact normalized identity or an explicit reviewed alias."""
    def normalize(value: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    requested = normalize(scheme)
    if not requested:
        return None

    # Aliases are reviewed identity mappings, never fuzzy suggestions.
    alias_target = None
    for alias, canonical in aliases.items():
        if normalize(alias) == requested:
            alias_target = normalize(canonical)
            break
    if alias_target:
        direct = metrics.get(alias_target)
        if direct is not None:
            return direct
        matches = [
            metric for metric_id, metric in metrics.items()
            if isinstance(metric, dict) and normalize(metric_id) == alias_target
        ]
        return matches[0] if len(matches) == 1 else None

    # A name match is accepted only when exactly one metric record declares it.
    matches = []
    for metric_id, metric in metrics.items():
        if not isinstance(metric, dict):
            continue
        identities = (metric_id, metric.get("id"), metric.get("scheme"), metric.get("name"))
        if any(normalize(value) == requested for value in identities if value):
            if metric not in matches:
                matches.append(metric)
    return matches[0] if len(matches) == 1 else None

def _infer_asset_class(cat: str, eq: float, debt: float, lc: float, mc: float, sc: float) -> AssetClass:
    """Classify from explicit scheme category before using allocation heuristics.

    Equity percentage alone cannot distinguish flexi-cap, multi-cap and
    large-cap funds: all can hold more than 80% equity.

    NO HARDCODING RULE: Asset class is determined by SEBI category first.
    Debt-percentage fallbacks only apply when category is empty/unknown,
    to avoid misclassifying equity funds with temporary cash positions.
    """
    cat_lower = str(cat or "").casefold().replace("_", " ").replace("-", " ")

    # Primary: Explicit SEBI category matching (authoritative)
    if any(token in cat_lower for token in ("debt", "liquid", "money market", "gilt", "bond")):
        return AssetClass.DEBT_LIQUID
    if any(token in cat_lower for token in ("balanced", "hybrid", "dynamic asset", "multi asset")):
        return AssetClass.HYBRID_BALANCED
    if "international" in cat_lower or "overseas" in cat_lower or "global equity" in cat_lower:
        return AssetClass.INTERNATIONAL
    if "small cap" in cat_lower:
        return AssetClass.SMALL_CAP
    if "mid cap" in cat_lower:
        return AssetClass.MID_CAP
    if "multi cap" in cat_lower or "multicap" in cat_lower:
        return AssetClass.MULTI_CAP
    if "flexi cap" in cat_lower or "flexicap" in cat_lower:
        return AssetClass.FLEXI_CAP
    if "large cap" in cat_lower or "largecap" in cat_lower or "bluechip" in cat_lower:
        return AssetClass.LARGE_CAP

    # Secondary: Market-cap weight heuristics (only when category is generic/empty)
    if sc >= 50.0:
        return AssetClass.SMALL_CAP
    if mc >= 50.0:
        return AssetClass.MID_CAP
    if lc >= 50.0:
        return AssetClass.LARGE_CAP

    # Tertiary: Debt-percentage fallback ONLY when category provides no signal
    # High debt (>=75%) indicates debt fund; moderate debt (>=35%) indicates hybrid
    # These thresholds are conservative to avoid misclassifying equity funds
    # that temporarily hold cash/debt for defensive positioning.
    if not cat_lower or cat_lower in ("equity", "other", "unknown", ""):
        if debt >= 75.0:
            return AssetClass.DEBT_LIQUID
        if debt >= 35.0:
            return AssetClass.HYBRID_BALANCED

    if eq <= 0.0 and debt > 0.0:
        return AssetClass.DEBT_LIQUID
    return AssetClass.EQUITY


def calculate_fee_bleed(holdings: List[HoldingItem]) -> FeeBleedAnalysis:
    """Return unavailable until source-backed, plan-specific commission evidence exists.

    A generic commission percentage and assumed future return are not client
    facts. The function deliberately does not infer commission from TER.
    """
    regular_count = sum(1 for holding in holdings if holding.plan == PlanType.REGULAR)
    return FeeBleedAnalysis(
        annual_commission_leakage_inr=None,
        ten_year_compounded_loss_inr=None,
        regular_funds_count=regular_count,
        regular_funds=[],
        direct_alternatives={},
        availability_status="UNAVAILABLE",
        unavailable_reason=(
            "No fund-, plan-, distributor- and effective-date-specific commission evidence "
            "or approved investor-specific projection assumptions were supplied."
        ),
    )


# ============================================================
# LOT-LEVEL TAX HARVESTING (FIFO with §112A Staging)
# ============================================================

@dataclass
class TaxLot:
    """A single purchase lot of a fund."""
    fund_id: str
    scheme_name: str
    folio: str
    purchase_date: date
    units: float
    nav: float
    cost: float
    source: str  # "transactions" or "manual"
    equity_pct: Optional[float] = None  # verified scheme-master equity allocation

    def holding_days(self, as_of: date) -> int:
        return (as_of - self.purchase_date).days

    def is_long_term(self, as_of: date, holding_months: int = 12) -> bool:
        """LTCG if holding period > 12 calendar months (strict: > 12 months, not >=).
        Uses the exact anniversary date, NOT a fixed 365-day count.
        Per Income-tax Act: 'more than twelve months from the date of acquisition'.
        Exactly 12 months = SHORT term. Feb-29 lots use Feb-28 anniversary in non-leap years."""
        try:
            anniversary = date(
                self.purchase_date.year + (holding_months // 12),
                self.purchase_date.month + (holding_months % 12) if (self.purchase_date.month + holding_months % 12) <= 12
                else self.purchase_date.month + (holding_months % 12) - 12,
                self.purchase_date.day
            )
        except ValueError:  # Feb-29 in non-leap year
            anniversary = date(
                self.purchase_date.year + (holding_months // 12),
                self.purchase_date.month + (holding_months % 12) if (self.purchase_date.month + holding_months % 12) <= 12
                else self.purchase_date.month + (holding_months % 12) - 12,
                28
            )
        return as_of > anniversary

    def is_short_term(self, as_of: date) -> bool:
        return not self.is_long_term(as_of)


@dataclass
class TaxLotSummary:
    """Aggregated tax lot summary for a fund."""
    fund_id: str
    scheme_name: str
    total_units: float
    total_cost: float
    current_value: float
    unrealized_gain: float
    ltcg_units: float
    ltcg_gain: float
    stcg_units: float
    stcg_gain: float
    ltcg_tax: float
    stcg_tax: float
    ltcg_exemption_used: float
    stcg_exemption_used: float


def build_fifo_tax_lots(
    transactions_path: Path,
    holdings: Any,
    as_of_date: Optional[date] = None,
    cas_current: Optional[float] = None,
    scheme_aliases: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, List[TaxLot]]:
    """Build current FIFO lots from CAS transactions and reconcile to holdings.

    Matching is exact after case/punctuation normalization. No fuzzy scheme
    matching is permitted. Unmatched historical schemes are ignored only when
    they are not part of the supplied current-holdings universe; every current
    holding with units must reconcile to its surviving transaction lots.
    """
    import re
    import math

    if not transactions_path.exists():
        raise FileNotFoundError(f"Tax-lot transaction history is missing: {transactions_path}")
    if as_of_date is None:
        as_of_date = date.today()
    if holdings is None:
        raise ValueError("Current holdings are required to build and reconcile FIFO tax lots")
    holding_items = holdings if isinstance(holdings, (list, tuple)) else getattr(holdings, "holdings", None)
    if not holding_items:
        raise ValueError("Current holdings are empty; FIFO tax-lot reconciliation is unavailable")

    def _field(item, name, default=None):
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    def _key(value):
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    scheme_to_fund: Dict[str, str] = {}
    fund_holdings: Dict[str, Dict[str, Any]] = {}

    def _add_alias(alias: Any, fund_id: str) -> None:
        key = _key(alias)
        if not key:
            return
        existing = scheme_to_fund.get(key)
        if existing is not None and existing != fund_id:
            raise ValueError(f"Ambiguous exact scheme alias {alias!r}: {existing!r} vs {fund_id!r}")
        scheme_to_fund[key] = fund_id

    for holding in holding_items:
        fund_id = str(_field(holding, "fund_id", "") or "").strip()
        if not fund_id:
            raise ValueError("Current holding is missing fund_id")
        fund_holdings[fund_id] = {
            "units": _field(holding, "units", None),
            "equity_pct": _field(holding, "equity_pct", None),
        }
        for alias in (
            _field(holding, "scheme", ""),
            _field(holding, "fund_name", ""),
            _field(holding, "isin", ""),
            fund_id,
        ):
            _add_alias(alias, fund_id)

    for fund_id, aliases in (scheme_aliases or {}).items():
        if fund_id not in fund_holdings:
            continue
        for alias in aliases:
            _add_alias(alias, fund_id)

    try:
        with transactions_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        raise ValueError(f"Unable to read CAS transaction history: {exc}") from exc

    transactions = data.get("transactions")
    if not isinstance(transactions, list) or not transactions:
        raise ValueError("CAS transaction history is missing a non-empty transactions list")

    # Remove matched reversal pairs before the FIFO pass. A reversal without
    # its original row is an integrity failure, not a transaction to ignore.
    consumed = set()
    filtered = []
    for index, txn in enumerate(transactions):
        if not isinstance(txn, dict):
            raise ValueError(f"Transaction row {index} is not an object")
        desc = str(txn.get("description", txn.get("desc", "")) or "").casefold()
        if "reversal" not in desc and "dishonour" not in desc and "reject" not in desc:
            continue
        scheme_key = _key(txn.get("scheme"))
        try:
            txn_date = datetime.strptime(str(txn.get("date", ""))[:10], "%Y-%m-%d").date()
            amount = float(txn.get("amount", 0))
            units = float(txn.get("units", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Malformed reversal row {index}: {exc}") from exc
        match_index = None
        for candidate_index, candidate in enumerate(transactions):
            if candidate_index == index or candidate_index in consumed:
                continue
            candidate_desc = str(candidate.get("description", candidate.get("desc", "")) or "").casefold()
            if "reversal" in candidate_desc or "dishonour" in candidate_desc or "reject" in candidate_desc:
                continue
            try:
                candidate_date = datetime.strptime(str(candidate.get("date", ""))[:10], "%Y-%m-%d").date()
                candidate_amount = float(candidate.get("amount", 0))
                candidate_units = float(candidate.get("units", 0))
            except (TypeError, ValueError):
                continue
            if (
                _key(candidate.get("scheme")) == scheme_key
                and candidate_date == txn_date
                and abs(abs(candidate_amount) - abs(amount)) <= 1.0
                and abs(abs(candidate_units) - abs(units)) <= 0.001
            ):
                match_index = candidate_index
                break
        if match_index is None:
            raise ValueError(f"Orphan reversal transaction at row {index}; original row could not be matched")
        consumed.add(index)
        consumed.add(match_index)

    filtered = [txn for index, txn in enumerate(transactions) if index not in consumed]
    fund_lots: Dict[str, List[TaxLot]] = {fund_id: [] for fund_id in fund_holdings}

    allowed_types = {
        "PURCHASE", "SIP", "SWITCH_IN", "STP_IN", "DIVIDEND_REINVEST",
        "REDEMPTION", "SWITCH_OUT", "STP_OUT", "DIVIDEND", "CHARGES",
    }
    purchase_types = {"PURCHASE", "SIP", "SWITCH_IN", "STP_IN", "DIVIDEND_REINVEST"}
    redemption_types = {"REDEMPTION", "SWITCH_OUT", "STP_OUT"}

    for index, txn in enumerate(filtered):
        try:
            txn_date = datetime.strptime(str(txn.get("date", ""))[:10], "%Y-%m-%d").date()
            amount = float(txn.get("amount", 0))
            units = float(txn.get("units", 0))
            nav = float(txn.get("nav", 0) or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Malformed CAS transaction row {index}: {exc}") from exc
        if not all(math.isfinite(value) for value in (amount, units, nav)):
            raise ValueError(f"Non-finite numeric value in CAS transaction row {index}")
        txn_type = str(txn.get("type", "") or "").strip().upper()
        if txn_type not in allowed_types:
            raise ValueError(f"Unsupported CAS transaction type at row {index}: {txn_type!r}")
        if amount == 0 and units == 0:
            continue
        if txn_type == "CHARGES":
            if units != 0:
                raise ValueError(f"Charge row {index} must not change units")
            continue
        if txn_type == "DIVIDEND":
            description = str(txn.get("description", txn.get("desc", "")) or "").casefold()
            if not any(marker in description for marker in ("reinvest", "reinvestment", "drp")):
                continue
            txn_type = "DIVIDEND_REINVEST"
        scheme = str(txn.get("scheme", "") or "")
        fund_id = scheme_to_fund.get(_key(scheme))
        if fund_id is None:
            # Historical schemes no longer represented in current holdings are
            # outside this lot book. Current holdings are reconciled below.
            continue
        folio = str(txn.get("folio", txn.get("folio_number", "")) or "")

        if txn_type in purchase_types:
            if amount <= 0 or units <= 0:
                raise ValueError(f"Purchase row {index} must have positive amount and units")
            if nav <= 0:
                nav = amount / units
            if not math.isfinite(nav) or nav <= 0:
                raise ValueError(f"Purchase row {index} has invalid NAV")
            equity_pct = fund_holdings[fund_id]["equity_pct"]
            fund_lots[fund_id].append(
                TaxLot(
                    fund_id=fund_id,
                    scheme_name=scheme,
                    folio=folio,
                    purchase_date=txn_date,
                    units=units,
                    nav=nav,
                    cost=amount,
                    source="transactions",
                    equity_pct=equity_pct,
                )
            )
        elif txn_type in redemption_types:
            # Transaction type is the authoritative direction. CAS providers
            # differ in whether redemption units/amount are signed or reported
            # as positive magnitudes; both are normalized here.
            if amount == 0 or units == 0:
                raise ValueError(f"Redemption/switch-out row {index} requires non-zero amount and units")
            units_to_remove = abs(units)
            lots = fund_lots[fund_id]
            remaining = units_to_remove
            updated_lots = []
            for lot in sorted(lots, key=lambda item: (item.purchase_date, item.folio)):
                if remaining <= 1e-8:
                    updated_lots.append(lot)
                    continue
                if lot.units <= remaining + 1e-8:
                    remaining -= lot.units
                    continue
                removed_cost = lot.cost * (remaining / lot.units)
                lot.units -= remaining
                lot.cost -= removed_cost
                updated_lots.append(lot)
                remaining = 0.0
            if remaining > 1e-6:
                raise ValueError(
                    f"FIFO redemption row {index} exceeds available units for {fund_id} by {remaining:.6f}"
                )
            fund_lots[fund_id] = updated_lots

    for fund_id, holding in fund_holdings.items():
        expected_units = holding["units"]
        if expected_units is None:
            raise ValueError(f"Current holding {fund_id} is missing units for FIFO reconciliation")
        expected_units = float(expected_units)
        if not math.isfinite(expected_units) or expected_units < 0:
            raise ValueError(f"Current holding {fund_id} has invalid units")
        actual_units = sum(lot.units for lot in fund_lots[fund_id])
        tolerance = max(0.01, expected_units * 1e-4)
        if abs(actual_units - expected_units) > tolerance:
            raise ValueError(
                f"FIFO lot reconciliation failed for {fund_id}: lots={actual_units:.6f}, "
                f"holding={expected_units:.6f}, tolerance={tolerance:.6f}"
            )
        fund_lots[fund_id].sort(key=lambda lot: (lot.purchase_date, lot.folio))
        if not fund_lots[fund_id] and expected_units > tolerance:
            raise ValueError(f"No surviving FIFO lots for non-zero current holding {fund_id}")

    return {fund_id: lots for fund_id, lots in fund_lots.items() if lots}
def calculate_overlap_matrix(holdings: List[HoldingItem], threshold_pct: float = 25.0) -> List[OverlapPair]:
    """
    Legacy top-holdings count proxy only; not weighted constituent overlap.

    Results are explicitly serialized with evidence_basis=TOP_HOLDINGS_COUNT_PROXY
    and verification_status=HEURISTIC. SIP decisions must use
    calculate_weighted_lookthrough_overlap with complete verified weights.
    """
    # Group unique funds by fund_id
    fund_stocks: Dict[str, set] = {}
    for h in holdings:
        if h.top_holdings and h.fund_id not in fund_stocks:
            fund_stocks[h.fund_id] = set(h.top_holdings)

    fund_ids = list(fund_stocks.keys())
    overlap_pairs: List[OverlapPair] = []

    for i in range(len(fund_ids)):
        for j in range(i + 1, len(fund_ids)):
            fa = fund_ids[i]
            fb = fund_ids[j]
            set_a = fund_stocks[fa]
            set_b = fund_stocks[fb]

            common = set_a.intersection(set_b)
            if not common:
                continue

            # Jaccard / Overlap coefficient over top holdings
            overlap_pct = (len(common) / min(len(set_a), len(set_b))) * 100.0

            if overlap_pct >= threshold_pct:
                verdict = "HIGH_DUPLICATION" if overlap_pct >= 35.0 else "MODERATE"
                overlap_pairs.append(
                    OverlapPair(
                        fund_a=fa,
                        fund_b=fb,
                        overlap_pct=round(overlap_pct, 1),
                        shared_stocks=sorted(list(common)),
                        verdict=verdict,
                    )
                )

    # Sort by overlap percentage descending
    overlap_pairs.sort(key=lambda x: x.overlap_pct, reverse=True)
    return overlap_pairs


def calculate_saa_drift(
    holdings: List[HoldingItem],
    target_saa: Optional[Dict[str, float]] = None,
    tolerance_band_pct: float = 5.0,
) -> SAADriftAnalysis:
    """Calculate current asset allocation vs target Strategic Asset Allocation (SAA).

    Incorporates underlying look-through stability buffer (debt + cash).
    Includes Flexi Multi-Cap scheme-category exposure tracking and drift analysis.

    Note: Flexi tracking measures scheme-category exposure (value of Flexi Cap funds),
    not verified look-through equity exposure. A Flexi Cap fund's equity allocation
    varies over time, so this tracks category membership rather than constituent overlap.
    """
    total_val = sum(h.current_value_inr for h in holdings)
    if total_val <= 0.0:
        return SAADriftAnalysis(
            current_equity_pct=0.0,
            current_debt_pct=0.0,
            current_cash_pct=0.0,
            current_equity_inr=0.0,
            current_debt_inr=0.0,
            target_equity_pct=95.0,
            target_debt_pct=5.0,
            tolerance_band_pct=tolerance_band_pct,
            rebalance_required=False,
            equity_gap_inr=0.0,
            debt_gap_inr=0.0,
            look_through_debt_inr=None,
            look_through_cash_inr=None,
            look_through_stability_buffer_pct=None,
            current_flexi_inr=0.0,
            target_flexi_pct=0.0,
            flexi_drift_pct=0.0,
        )

    # Compute look-through equity, debt, and cash amounts
    equity_val = Decimal("0.00")
    debt_val = Decimal("0.00")
    cash_val = Decimal("0.00")
    flexi_val = Decimal("0.00")

    for h in holdings:
        eq_amt = h.current_value_inr * (Decimal(str(h.equity_pct)) / Decimal("100"))
        db_amt = h.current_value_inr * (Decimal(str(h.debt_pct)) / Decimal("100"))
        c_pct = (Decimal("100") - Decimal(str(h.equity_pct)) - Decimal(str(h.debt_pct))).max(Decimal("0"))
        c_amt = h.current_value_inr * (c_pct / Decimal("100"))
        # Detect Flexi Cap funds for look-through tracking
        # Note: This tracks scheme-category exposure, not verified look-through equity exposure.
        # A Flexi Cap fund's equity allocation varies over time, so this measures category membership.
        cat = str(getattr(h, 'category', '')).lower()
        scheme = str(getattr(h, 'scheme', '')).lower()
        is_flexi = 'flexi' in cat or 'flexi' in scheme or 'multi-cap' in cat or 'multi cap' in cat
        if is_flexi:
            flexi_val += h.current_value_inr
        equity_val += eq_amt
        debt_val += db_amt
        cash_val += c_amt

    curr_eq_pct = float((equity_val / total_val) * Decimal("100.0"))
    curr_db_pct = float((debt_val / total_val) * Decimal("100.0"))
    curr_cash_pct = float((cash_val / total_val) * Decimal("100.0"))
    stability_buffer_pct = curr_db_pct + curr_cash_pct

    # Current Flexi percentage for look-through tracking
    curr_flexi_pct = float((flexi_val / total_val) * Decimal("100.0"))

    # Dynamic target resolution supporting Tier 6 and granular allocations
    tgt_flexi_pct = 0.0
    if target_saa:
        tgt_db = target_saa.get("debt_pct", target_saa.get("debt_liquid_pct", target_saa.get("debt_global_pct", 5.0)))
        if "equity_pct" in target_saa:
            tgt_eq = target_saa["equity_pct"]
        elif any(k in target_saa for k in ["large_cap_pct", "mid_cap_pct", "small_cap_pct", "flexi_multi_cap_pct"]):
            tgt_eq = (
                target_saa.get("large_cap_pct", 0.0)
                + target_saa.get("mid_cap_pct", 0.0)
                + target_saa.get("small_cap_pct", 0.0)
                + target_saa.get("flexi_multi_cap_pct", 0.0)
                + target_saa.get("mid_small_cap_pct", 0.0)
            )
            tgt_flexi_pct = float(target_saa.get("flexi_multi_cap_pct", 0.0))
        else:
            tgt_eq = 100.0 - tgt_db
    else:
        tgt_eq = 95.0
        tgt_db = 5.0

    eq_drift = curr_eq_pct - tgt_eq
    stability_satisfied = stability_buffer_pct >= (tgt_db - 1.0)
    rebalance_required = abs(eq_drift) > tolerance_band_pct and not stability_satisfied

    # Gap in rupees to reach target
    target_eq_inr = total_val * (Decimal(str(tgt_eq)) / Decimal("100"))
    target_db_inr = total_val * (Decimal(str(tgt_db)) / Decimal("100"))
    equity_gap_inr = target_eq_inr - equity_val
    debt_gap_inr = 0.0 if stability_satisfied else (target_db_inr - debt_val)

    # Flexi drift calculation
    flexi_drift_pct = curr_flexi_pct - tgt_flexi_pct
    curr_flexi_inr = float(round(flexi_val, 2))

    return SAADriftAnalysis(
        current_equity_pct=round(curr_eq_pct, 1),
        current_debt_pct=round(curr_db_pct, 1),
        current_cash_pct=round(curr_cash_pct, 1),
        current_equity_inr=float(round(equity_val, 2)),
        current_debt_inr=float(round(debt_val, 2)),
        target_equity_pct=round(tgt_eq, 1),
        target_debt_pct=round(tgt_db, 1),
        tolerance_band_pct=tolerance_band_pct,
        rebalance_required=rebalance_required,
        equity_gap_inr=round(equity_gap_inr, 2),
        debt_gap_inr=round(debt_gap_inr, 2),
        look_through_debt_inr=float(round(debt_val, 2)),
        look_through_cash_inr=float(round(cash_val, 2)),
        look_through_stability_buffer_pct=round(stability_buffer_pct, 2),
        current_flexi_inr=curr_flexi_inr,
        target_flexi_pct=tgt_flexi_pct,
        flexi_drift_pct=round(flexi_drift_pct, 2),
    )


def parse_cas(xlsx_path: Path, scheme_master: Optional[Dict[str, Any]] = None, scheme_master_source_bytes: Optional[bytes] = None) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Parses 'Portfolio Details' sheet from CAS Excel report.
    Hard Guard: Enforces single valuation date across all folios.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    _SHEET_KEYWORDS = ("portfolio", "holdings", "scheme details", "consolidated")
    sheet_name = None
    for name in wb.sheetnames:
        if any(kw in name.lower() for kw in _SHEET_KEYWORDS):
            sheet_name = name
            break
    if sheet_name is None:
        raise ValueError(
            "Invalid CAS workbook: no portfolio/holdings sheet found. "
            f"Available sheets: {wb.sheetnames}"
        )
    ws = wb[sheet_name]

    as_of_date = ""
    dates_found = set()
    hdr = None
    holdings = []

    for row in ws.iter_rows(values_only=True):
        vals = [str(c).strip() if c is not None else "" for c in row]
        if not any(vals):
            continue

        if any(v.lower() == "to date" for v in vals):
            idx = [v.lower() for v in vals].index("to date")
            if idx + 1 < len(vals):
                as_of_date = vals[idx + 1]
                dates_found.add(vals[idx + 1])
        elif any(v.lower() in ("scheme name", "scheme", "fund name", "scheme description") for v in vals):
            hdr = {name: i for i, name in enumerate(vals) if name}
            for name, i in list(hdr.items()):
                nl = name.strip().lower()
                if nl in ("scheme name", "scheme", "fund name", "scheme description"):
                    hdr["Scheme Name"] = i
                elif nl in ("current value", "market value", "valuation", "value"):
                    hdr["Current Value"] = i
                elif nl in ("invested value", "cost value", "invested", "cost"):
                    hdr["Invested Value"] = i
                elif nl in ("folio no.", "folio no", "folio", "folio number"):
                    hdr["Folio No."] = i
        elif hdr and vals and vals[hdr.get("Scheme Name", 0)]:
            scheme_name = vals[hdr["Scheme Name"]]
            if not scheme_name or scheme_name.lower() in ("total", "sub total"):
                continue

            try:
                cur_val = float(vals[hdr["Current Value"]])
                inv_val = float(vals[hdr.get("Invested Value", 0)] or 0.0)
            except (ValueError, TypeError):
                continue

            if cur_val > 0:
                holding = {
                    "scheme": scheme_name,
                    "folio": vals[hdr.get("Folio No.", 0)],
                    "value": cur_val,
                    "invested": inv_val,
                    "is_direct": None,
                    "plan": None,
                    "option_type": None,
                    "plan_option_status": "MISSING",
                    "constituent_weights": None,
                    "constituent_weights_coverage_pct": None,
                    "lookthrough_status": "MISSING",
                    "lookthrough_reason": "CAS scheme holdings do not contain stock-level constituent disclosures.",
                    "scheme_id": None,
                    "isin": None,
                    "scheme_identity_status": "MISSING",
                }
                if scheme_master is not None and scheme_master_source_bytes is not None:
                    from ingestion.portfolio_disclosure import resolve_scheme_identity
                    amc_col = hdr.get("AMC Name")
                    if amc_col is not None:
                        holding["amc_name"] = vals[amc_col]
                    identity = resolve_scheme_identity(
                        holding, scheme_master, source_bytes=scheme_master_source_bytes
                    )
                    holding.update({
                        "scheme_id": identity.get("scheme_id"),
                        "isin": identity.get("isin"),
                        "scheme_identity_status": identity["status"],
                        "scheme_identity_reason": identity["reason"],
                        "plan": identity.get("plan_type"),
                        "option_type": identity.get("option_type"),
                        "plan_option_status": identity.get("plan_option_status", "MISSING"),
                        "is_direct": (
                            identity.get("plan_type") == "DIRECT"
                            if identity.get("plan_option_status") == "VERIFIED"
                            else None
                        ),
                    })
                holdings.append(holding)

    if len(dates_found) > 1:
        raise ValueError(f"Integrity Error: Multiple valuation dates detected in CAS: {dates_found}")

    return as_of_date, holdings


def _aggregate_portfolio_benchmark_unavailable() -> dict:
    """Do not compare a mixed-asset portfolio to one equity index."""
    return {
        "release_status": "UNAVAILABLE",
        "validation_stage": "portfolio_composite_benchmark_not_implemented",
        "error": (
            "Aggregate portfolio alpha requires an IPS-weighted composite benchmark "
            "with cash-flow-matched component TRI series and an explicit rebalancing policy. "
            "A single NIFTY 500 TRI is not a valid benchmark for a mixed-asset portfolio."
        ),
        "benchmark_matched_xirr_pct": None,
        "alpha_pct": None,
    }


def _tri_alpha_release_blockers() -> list[str]:
    """Evaluate TRI release evidence independently of the process working directory."""
    from verify_tri_provenance import alpha_release_blockers

    repository_root = Path(__file__).resolve().parents[1]
    fixture_path = repository_root / "data" / "policy" / "benchmark_tri_series.json"
    return alpha_release_blockers(fixture_path)


def _parse_cas_valuation_date(cas_path: Path) -> date:
    """Return the statement's explicit valuation date; never substitute today."""
    raw_date, _ = parse_cas(cas_path)
    date_text = str(raw_date).strip()
    if not date_text:
        raise ValueError("CAS statement does not contain a valuation date")
    try:
        return datetime.fromisoformat(date_text).date()
    except ValueError:
        for date_format in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(date_text, date_format).date()
            except ValueError:
                continue
    raise ValueError(f"CAS valuation date has an unsupported format: {date_text!r}")


def compute_liquidity_waterfall(bank_balance: float, monthly_expenses: float, months_reserve: float) -> Tuple[float, float]:
    """
    Guards emergency buffer before investment; requires explicit approved months_reserve.
    Deployable_Surplus = max(0, bank_balance - (monthly_expenses * months_reserve))
    """
    if any(not math.isfinite(x) or x < 0 for x in (bank_balance, monthly_expenses, months_reserve)):
        raise ValueError("Bank balance, monthly expenses, and months reserve must be finite non-negative numbers")
    emergency_reserve = round(monthly_expenses * months_reserve, 2)
    deployable_surplus = max(0.0, round(bank_balance - emergency_reserve, 2))
    return emergency_reserve, deployable_surplus


def calculate_cash_deployment(
    bank_cash_inr: Optional[float] = None,
    emergency_buffer_inr: Optional[float] = None,
    stp_months: Optional[int] = None,
    emergency_months: Optional[float] = None,
    as_of_date: Optional[str] = None,
    evidence_source: Optional[str] = None,
) -> CashDeploymentPlan:
    """
    Computes cash deployment waterfall for bank balances.
    Allocates emergency reserve first, then spreads deployable surplus via STP.
    Fails closed when evidence is missing; missing cash or reserve is never coerced to zero.
    """
    if bank_cash_inr is None or emergency_buffer_inr is None or emergency_months is None:
        return CashDeploymentPlan(
            status="EVIDENCE_MISSING",
            total_cash_inr=None if bank_cash_inr is None else round(float(bank_cash_inr), 2),
            emergency_reserve_inr=None if emergency_buffer_inr is None else round(float(emergency_buffer_inr), 2),
            emergency_months=emergency_months,
            deployable_surplus_inr=None,
            stp_monthly_amount_inr=None,
            stp_duration_months=stp_months,
            as_of_date=as_of_date,
            evidence_source=evidence_source,
            unavailable_reason="Missing source-backed bank cash, emergency reserve, or approved reserve months; missing values are not coerced to zero."
        )

    bank_cash = float(bank_cash_inr)
    emergency_buf = float(emergency_buffer_inr)
    em_months = float(emergency_months)
    if any(not math.isfinite(x) or x < 0 for x in (bank_cash, emergency_buf, em_months)):
        raise ValueError("Bank cash, emergency reserve, and emergency months must be finite non-negative numbers")

    deployable = max(0.0, bank_cash - emergency_buf)
    if stp_months is None:
        duration = None
        stp_monthly = None
    else:
        duration = int(stp_months)
        if duration <= 0:
            raise ValueError("stp_months must be positive integer when supplied")
        stp_monthly = round(deployable / duration, 2) if duration > 0 else 0.0

    return CashDeploymentPlan(
        status="AVAILABLE",
        total_cash_inr=round(bank_cash, 2),
        emergency_reserve_inr=round(emergency_buf, 2),
        emergency_months=em_months,
        deployable_surplus_inr=round(deployable, 2),
        stp_recommendation=None,
        stp_monthly_amount_inr=None if stp_monthly is None else round(stp_monthly, 2),
        stp_duration_months=duration,
        stp_source_fund=None,
        stp_target_fund=None,
        as_of_date=as_of_date,
        evidence_source=evidence_source,
    )


def compute_fifo_tax_lots(
    transactions_path: Path,
    as_of_date: Optional[date] = None
) -> Optional[Dict[str, Any]]:
    """
    Computes lot-level FIFO tax maturation status for all active holdings.
    Tags each purchase lot as LTCG (>365d, 0% exit load) or STCG (<=365d, 1% load).
    """
    if not transactions_path.exists():
        return None
    try:
        with open(transactions_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    txns = data.get("transactions", [])
    if not txns:
        return None

    if as_of_date is None:
        # Deterministic fallback: use the latest transaction date in the file
        txn_dates = []
        for t in txns:
            try:
                txn_dates.append(datetime.strptime(t["date"][:10], "%Y-%m-%d").date())
            except Exception:
                pass
        as_of_date = max(txn_dates) if txn_dates else date.today()

    scheme_txns = defaultdict(list)
    for t in txns:
        sn = t.get("scheme", "").strip()
        if not sn:
            continue
        amt = float(t.get("amount", 0))
        unt = float(t.get("units", 0) or 0)
        if amt == 0 and unt == 0:
            continue
        try:
            d = datetime.strptime(t["date"][:10], "%Y-%m-%d").date()
        except Exception:
            continue
        scheme_txns[sn].append({
            "date": d, "amount": amt, "units": unt,
            "nav": float(t.get("nav", 0) or 0),
            "desc": t.get("description", "")
        })

    all_lots = []
    for sn, stxns in sorted(scheme_txns.items()):
        stxns = sorted(stxns, key=lambda x: x["date"])
        lots = []
        for t in stxns:
            unt = t["units"]
            amt = t["amount"]
            desc = t["desc"].lower()
            is_rev = any(kw in desc for kw in ("reversal", "dishonour", "reject"))
            if unt > 0 and not is_rev:
                lots.append({
                    "date": t["date"],
                    "units": unt,
                    "nav": t["nav"] if t["nav"] > 0 else (amt / unt if unt > 0 else 0),
                    "cost": amt
                })
            elif unt < 0:
                # Redemption or Purchase Reversal (e.g. cheque dishonour/rejection)
                units_to_burn = abs(unt)
                while units_to_burn > 0.0001 and lots:
                    if lots[0]["units"] <= units_to_burn + 0.0001:
                        units_to_burn -= lots[0]["units"]
                        lots.pop(0)
                    else:
                        fraction = units_to_burn / lots[0]["units"]
                        lots[0]["cost"] -= lots[0]["cost"] * fraction
                        lots[0]["units"] -= units_to_burn
                        units_to_burn = 0.0
            elif unt > 0 and is_rev:
                # Reversal of redemption (units returned to investor)
                lots.append({
                    "date": t["date"],
                    "units": unt,
                    "nav": t["nav"] if t["nav"] > 0 else (amt / unt if unt > 0 else 0),
                    "cost": abs(amt) if amt != 0 else (unt * (t["nav"] if t["nav"] > 0 else 0))
                })

        for l in lots:
            hdays = (as_of_date - l["date"]).days
            is_ltcg = hdays > 365
            all_lots.append({
                "scheme": sn,
                "purchase_date": l["date"].strftime("%Y-%m-%d"),
                "units": round(l["units"], 3),
                "purchase_nav": round(l["nav"], 2),
                "invested_cost": round(l["cost"], 2),
                "holding_days": hdays,
                "status": "LTCG (0% Exit Load)" if is_ltcg else f"STCG (Matures in {max(0, 365 - hdays)}d)",
                "is_ltcg": is_ltcg,
                "days_to_ltcg": max(0, 365 - hdays),
                "exit_load_penalty": 0.0 if is_ltcg else round(l["cost"] * 0.01, 2)
            })

    mature = [l for l in all_lots if l["is_ltcg"]]
    immature = [l for l in all_lots if not l["is_ltcg"]]
    return {
        "total_lots_count": len(all_lots),
        "mature_lots_count": len(mature),
        "immature_lots_count": len(immature),
        "mature_capital_inr": sum(l["invested_cost"] for l in mature),
        "immature_capital_inr": sum(l["invested_cost"] for l in immature),
        "total_exit_load_risk_inr": sum(l["exit_load_penalty"] for l in immature),
        "lots": all_lots
    }


def _validated_ips_numeric_inputs(ips: Dict[str, Any]) -> Tuple[Decimal, Decimal, float]:
    """Validate investor-entered SIP/lumpsum/reserve inputs without bool coercion or default months."""
    if not isinstance(ips, dict):
        raise ValueError("IPS inputs must be an object")
    if "monthly_sip_budget" not in ips:
        raise ValueError("Explicit ips.monthly_sip_budget is required; no default SIP budget is permitted")
    keys = ("monthly_sip_budget", "lumpsum_budget", "emergency_months")
    if any(isinstance(ips.get(key), bool) for key in keys if key in ips):
        raise ValueError("IPS monetary and emergency-month inputs must not be booleans")
    try:
        monthly_sip = quantize_inr(ips["monthly_sip_budget"])
    except (TypeError, ValueError, decimal.InvalidOperation) as exc:
        raise ValueError("IPS monthly_sip_budget must be numeric") from exc
    if not monthly_sip.is_finite() or monthly_sip <= Decimal("0.00"):
        raise ValueError("IPS monthly_sip_budget must be finite and greater than zero")
    if "emergency_months" not in ips:
        raise ValueError("Explicit ips.emergency_months is required; no hardcoded default reserve horizon (e.g. 6.0 months) is permitted")
    try:
        lumpsum_budget = quantize_inr(ips.get("lumpsum_budget", "0.00"))
        emergency_months = float(ips["emergency_months"])
    except (TypeError, ValueError, decimal.InvalidOperation) as exc:
        raise ValueError("IPS SIP, lumpsum and emergency-month inputs must be numeric") from exc
    if not lumpsum_budget.is_finite() or lumpsum_budget < Decimal("0.00"):
        raise ValueError("IPS lumpsum_budget must be finite and non-negative")
    if not math.isfinite(emergency_months) or emergency_months < 0.0:
        raise ValueError("IPS emergency_months must be finite and non-negative")
    return monthly_sip, lumpsum_budget, emergency_months


def _validated_equity_only_sip_authorization(ips: Dict[str, Any], risk_tier: str) -> bool:
    """Read the explicit IPS authorization for Tier 6 equity-only SIP routing."""
    value = ips.get("equity_only_sip_authorized", False)
    if not isinstance(value, bool):
        raise ValueError("IPS equity_only_sip_authorized must be an explicit boolean")
    if value and _parse_sebi_risk_tier(risk_tier) != 6:
        raise ValueError("Equity-only SIP authorization is valid only for SEBI Tier 6")
    return value


def _build_portfolio_gate_summary(holdings: List[HoldingItem]) -> List[Dict[str, Any]]:
    """Preserve the AMC identity/value fields required by candidate AMC gates."""
    return [
        {
            "scheme": holding.scheme,
            "value": holding.current_value_inr,
            "amc_name": holding.amc_name,
        }
        for holding in holdings
    ]


def aggregate_fiduciary_facts(
    cas_path: Path,
    metrics_path: Path,
    config_path: Path,
    aliases_path: Optional[Path] = None,
    scheme_master: Optional[Dict[str, Any]] = None,
    scheme_master_source_bytes: Optional[bytes] = None,
    portfolio_disclosures_by_scheme_id: Optional[Dict[str, Dict[str, Any]]] = None,
    portfolio_disclosure_source_bytes_by_scheme_id: Optional[Dict[str, bytes]] = None,
    disclosure_as_of_date: Optional[date] = None,
    disclosure_max_age_days: int = 45,
) -> FiduciaryFactsPayload:
    """
    Full pipeline aggregator: runs deterministic math on statements and config.
    Returns complete FiduciaryFactsPayload.
    """
    holdings = load_holdings_from_cas_excel(
        cas_path, metrics_path, aliases_path,
        scheme_master=scheme_master,
        scheme_master_source_bytes=scheme_master_source_bytes,
        portfolio_disclosures_by_scheme_id=portfolio_disclosures_by_scheme_id,
        portfolio_disclosure_source_bytes_by_scheme_id=portfolio_disclosure_source_bytes_by_scheme_id,
        disclosure_as_of_date=disclosure_as_of_date,
        disclosure_max_age_days=disclosure_max_age_days,
    )
    # Empty or zero-value holdings are not evidence of a zero-risk, zero-drift
    # portfolio. Cash-only portfolios require a separately verified cash source.
    if not holdings:
        raise ValueError(
            "Portfolio diagnostics unavailable: CAS contains no verified active holdings; "
            "zero drift and zero risk cannot be inferred from an empty portfolio."
        )
    portfolio_value = math.fsum(float(holding.current_value_inr) for holding in holdings)
    if not math.isfinite(portfolio_value) or portfolio_value <= 0.0:
        raise ValueError(
            "Portfolio diagnostics unavailable: verified active holdings have no positive "
            "finite portfolio value; HOLD until a supported cash-only or invested portfolio "
            "snapshot is independently verified."
        )

    # SIP generation requires an explicit investor mandate. Never manufacture
    # a ₹1 lakh budget or Tier 6 risk profile when client inputs are absent.
    if not config_path.is_file():
        raise ValueError("Client IPS config is required for SIP analysis; no default budget or risk tier is permitted")
    try:
        with open(config_path, "r", encoding="utf-8") as config_handle:
            cfg = json.load(config_handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Client IPS config is unreadable or invalid JSON") from exc
    if not isinstance(cfg, dict) or not isinstance(cfg.get("ips"), dict):
        raise ValueError("Client IPS config must contain an ips object")
    ips = cfg["ips"]
    client_name = cfg.get("client_name") or ips.get("client_name") or "Valued Client"
    client_age_val = ips.get("client_age")
    horizon_yrs_val = ips.get("horizon_years")
    client_risk_tier = cfg.get("risk_tier") or ips.get("risk_tolerance")
    if not isinstance(client_risk_tier, str) or not client_risk_tier.strip():
        raise ValueError("An explicit investor risk_tolerance or risk_tier is required for SIP analysis")
    monthly_sip, lumpsum_budget, emergency_months = _validated_ips_numeric_inputs(ips)
    target_saa = cfg.get("target_allocation", {})

    if not holdings:
        raise ValueError("Portfolio diagnostics unavailable: CAS contains no verified active holdings; no zero-drift report can be produced")
    tot_cur = sum((Decimal(str(h.current_value_inr)) for h in holdings), Decimal("0.00"))
    if not tot_cur.is_finite() or tot_cur <= Decimal("0.00"):
        raise ValueError("Portfolio diagnostics unavailable: total verified holding value must be positive")
    tot_inv = sum((Decimal(str(h.invested_value_inr)) for h in holdings), Decimal("0.00"))
    tot_gain = tot_cur - tot_inv

    # Module 2: Portfolio Diagnostics - with architectural corrections
    fee_bleed = calculate_fee_bleed(holdings)
    overlap = calculate_overlap_matrix(holdings)

    # Architectural Correction 1: Weighted Look-Through Overlap (replaces naive Jaccard)
    weighted_overlap = calculate_weighted_lookthrough_overlap(holdings, metrics_path)

    # Architectural Correction 2: Ordinal Risk Distribution (replaces cardinal 5.84/6.00)
    risk_distribution = calculate_risk_distribution(holdings)

    # Architectural Correction 4: SAA Drift Minimizer (renamed from optimizer)
    saa_minimizer = calculate_saa_drift_minimizer(holdings, target_saa, monthly_sip)

    # Convert SAA Drift Minimizer to SAADriftAnalysis for backward compatibility
    total_equity_val = sum(h.current_value_inr for h in holdings if h.asset_class in (
        AssetClass.EQUITY, AssetClass.LARGE_CAP, AssetClass.MID_CAP, AssetClass.SMALL_CAP,
        AssetClass.FLEXI_CAP, AssetClass.MULTI_CAP, AssetClass.INTERNATIONAL
    ))
    total_debt_val = sum(h.current_value_inr for h in holdings if h.asset_class in (
        AssetClass.DEBT, AssetClass.DEBT_LIQUID,
    ))
    total_cash_val = sum(h.current_value_inr for h in holdings if h.asset_class in (
        AssetClass.CASH,
    ))
    total_hybrid_equity = sum(h.current_value_inr * (h.equity_pct / 100.0) for h in holdings if h.asset_class in (
        AssetClass.HYBRID_BALANCED, AssetClass.HYBRID
    ))
    total_hybrid_debt = sum(h.current_value_inr * (h.debt_pct / 100.0) for h in holdings if h.asset_class in (
        AssetClass.HYBRID_BALANCED, AssetClass.HYBRID
    ))

    total_equity_val = total_equity_val + total_hybrid_equity
    total_debt_val = total_debt_val + total_hybrid_debt
    total_cash_val = total_cash_val

    total_val = sum(h.current_value_inr for h in holdings)

    saa = SAADriftAnalysis(
        current_equity_pct=saa_minimizer.current_allocation.get('Equity', 0),
        current_debt_pct=saa_minimizer.current_allocation.get('Debt', 0),
        current_cash_pct=saa_minimizer.current_allocation.get('Cash', 0),
        current_equity_inr=round(total_equity_val, 2),
        current_debt_inr=round(total_debt_val, 2),
        target_equity_pct=saa_minimizer.target_allocation.get('Equity', 0),
        target_debt_pct=saa_minimizer.target_allocation.get('Debt', 0),
        tolerance_band_pct=5.0,
        rebalance_required=saa_minimizer.total_drift_l2_norm > 5.0,
        equity_gap_inr=round(saa_minimizer.drift_after_sip.get('Equity', 0) * total_val / 100, 2),
        debt_gap_inr=round(saa_minimizer.drift_after_sip.get('Debt', 0) * total_val / 100, 2),
    )

    # Module 3: Investor Suitability & Liquidity - with emergency months & bank cash from config
    bank_cash_cfg = None
    emergency_reserve_cfg = None
    cash_as_of = None
    cash_evidence_src = None
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as cf:
            cdata = json.load(cf).get("cash")
            if isinstance(cdata, dict):
                if "bank_cash_total" in cdata and cdata["bank_cash_total"] is not None:
                    bank_cash_cfg = float(cdata["bank_cash_total"])
                if "emergency_reserve" in cdata and cdata["emergency_reserve"] is not None:
                    emergency_reserve_cfg = float(cdata["emergency_reserve"])
                cash_as_of = cdata.get("as_of_date")
                cash_evidence_src = cdata.get("evidence_source")

    cash = calculate_cash_deployment(
        bank_cash_inr=bank_cash_cfg,
        emergency_buffer_inr=emergency_reserve_cfg,
        emergency_months=emergency_months,
        as_of_date=cash_as_of,
        evidence_source=cash_evidence_src,
    )

    # Look-through stability and thematic exposures
    stability_buf = calculate_lookthrough_stability_buffer(
        holdings=holdings,
        bank_cash_inr=bank_cash_cfg,
        emergency_reserve_inr=emergency_reserve_cfg,
        target_debt_pct=saa.target_debt_pct,
        as_of_date=cash_as_of,
    )
    thematic_exps = calculate_thematic_exposures(holdings, metrics_path, aliases_path)
    # Keep the already validated risk profile from the IPS; do not overwrite it.

    neglected_themes = [th for th in thematic_exps if th.coverage_status == "NEGLECTED"]
    if neglected_themes:
        neglected_themes.sort(key=lambda x: x.dedicated_funds_pct + x.look_through_stocks_pct)
        deficit_theme = neglected_themes[0].theme_name
    else:
        # Unknown thematic taxonomy is not evidence of a Pharma deficit.
        deficit_theme = "UNAVAILABLE"

    equity_only_sip_authorized = _validated_equity_only_sip_authorization(
        ips, client_risk_tier
    )
    det_sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=monthly_sip,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
        holdings=holdings,
        client_aum=tot_cur,
        thematic_deficit_theme=deficit_theme,
        equity_sip_routing_override=equity_only_sip_authorized,
        portfolio_disclosures_by_scheme_id=portfolio_disclosures_by_scheme_id,
        portfolio_disclosure_source_bytes_by_scheme_id=portfolio_disclosure_source_bytes_by_scheme_id,
        disclosure_as_of_date=disclosure_as_of_date,
        disclosure_max_age_days=disclosure_max_age_days,
    )

    det_lumpsum_plan = compute_deterministic_lumpsum_blueprint(
        lumpsum_amount=lumpsum_budget,
        bank_cash_total=bank_cash_cfg,
        emergency_reserve=emergency_reserve_cfg,
        holdings=holdings,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
    )

    # Calculate portfolio XIRR and transaction reconciliation. Tax-lot
    # classification is intentionally not invoked: the legacy classifier is
    # disabled because its generic holding-period and exit-load assumptions
    # are not approved. Missing tax-lot output must not break portfolio
    # diagnostics or be represented as zero tax/cost.
    transactions_path = cas_path.parent / "transactions.json"
    if not transactions_path.exists():
        transactions_path = cas_path.parent.parent / "transactions.json"
    try:
        cas_valuation_date = _parse_cas_valuation_date(cas_path)
    except (OSError, ValueError, TypeError):
        cas_valuation_date = None
    cas_recon = reconcile_cas_holdings_with_transactions(holdings, transactions_path)
    # XIRR is not a standalone property of a parseable transaction list. It is
    # only meaningful when the supplied ledger reconciles to the CAS unit
    # balances; otherwise partial/missing rows can materially distort returns.
    portfolio_xirr = (
        calculate_portfolio_xirr(
            transactions_path,
            holdings,
            cas_current=tot_cur,
            as_of_date=cas_valuation_date,
        )
        if cas_recon.get("status") == "VERIFIED_RECONCILED"
        else None
    )
    tax_lots_summary = None

    # Transaction history is optional for a CAS-only portfolio snapshot. If a
    # supplied history is malformed or does not reconcile, however, it cannot
    # be ignored while issuing a portfolio-aware SIP proposal.
    if transactions_path.exists() and cas_recon.get("status") != "VERIFIED_RECONCILED":
        portfolio_xirr = None
        det_sip_plan.unallocated_budget_inr = det_sip_plan.total_monthly_budget_inr
        for sip_item in det_sip_plan.items:
            sip_item.monthly_inr = Decimal("0.00")
            sip_item.fiduciary_rationale = (
                "NO ACTION — complete SIP budget withheld because supplied transaction "
                "history did not reconcile to CAS holdings. "
                + str(cas_recon.get("status"))
                + ". No redistribution is permitted. "
                + sip_item.fiduciary_rationale
            )
        det_sip_plan.execution_status = "HOLD_CAS_TRANSACTION_RECONCILIATION"
        det_sip_plan.is_execution_authorized = False
        det_sip_plan.is_actionable_order = False
        det_sip_plan.enforcement_notice = (
            "RUNTIME INVARIANT ENFORCED: supplied transaction history failed CAS reconciliation; "
            "the full monthly SIP budget remains unallocated."
        )

    # A single equity index is not a valid comparator for a mixed-asset
    # portfolio. Until an IPS-weighted composite benchmark (with explicit
    # rebalancing policy and cash-flow-matched component TRI series) exists,
    # aggregate portfolio alpha must remain unavailable.
    benchmark_xirr = None
    alpha_pct = None
    bench_audit_record = _aggregate_portfolio_benchmark_unavailable()
    if portfolio_xirr is not None and transactions_path.exists():
        # Persist audit output only beside explicitly configured external client data.
        # Never write client-derived results into the repository working tree.
        client_data_dir = os.environ.get("MF_CLIENT_DATA_DIR")
        if client_data_dir:
            client_root = Path(client_data_dir).expanduser().resolve()
            repository_root = Path(__file__).resolve().parents[1]
            try:
                client_root.relative_to(repository_root)
            except ValueError:
                pass
            else:
                raise ValueError("MF_CLIENT_DATA_DIR must be outside the Git repository")
            bench_out_path = client_root / "outputs" / "benchmark_xirr.json"
            bench_out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(bench_out_path, "w", encoding="utf-8") as f_b:
                json.dump(bench_audit_record, f_b, indent=2)

    # Mandate Authority & Runtime Hold Enforcement
    from core.models import MandateExecutionState
    mandate_cfg = cfg.get("mandate", {}) if isinstance(cfg, dict) else {}
    m_state_str = mandate_cfg.get("mandate_state", "HOLD_PENDING_TRI_VALIDATION")
    try:
        active_mandate_state = MandateExecutionState(m_state_str)
    except ValueError:
        active_mandate_state = MandateExecutionState.HOLD_PENDING_TRI_VALIDATION

    is_exec_auth = bool(mandate_cfg.get("is_execution_authorized", False))
    hold_reasons_list = mandate_cfg.get("hold_reasons", [
        "Existing holdings retained; zero forced redemptions",
        "Redemptions frozen pending scheduled portfolio review",
        "New core SIP deployment on hold pending benchmark TRI and look-through validation"
    ])

    # Enforce runtime non-actionable status on deployment plans under active HOLD mandate
    if active_mandate_state == MandateExecutionState.HOLD_PENDING_TRI_VALIDATION:
        det_sip_plan.mandate_state = active_mandate_state
        det_sip_plan.is_execution_authorized = False
        det_sip_plan.is_actionable_order = False
        det_sip_plan.execution_status = "ON_HOLD_PENDING_TRI_VALIDATION"
        det_sip_plan.enforcement_notice = (
            "RUNTIME INVARIANT ENFORCED: New core SIP deployment is strictly ON HOLD pending "
            "benchmark TRI and constituent look-through validation. Orders are non-actionable conditional scenarios."
        )
        det_lumpsum_plan.mandate_state = active_mandate_state
        det_lumpsum_plan.is_execution_authorized = False
        det_lumpsum_plan.is_actionable_order = False
        det_lumpsum_plan.execution_status = "ON_HOLD_PENDING_TRI_VALIDATION"
        det_lumpsum_plan.enforcement_notice = (
            "RUNTIME INVARIANT ENFORCED: Lumpsum deployment is strictly ON HOLD pending "
            "scheduled portfolio review. Orders are non-actionable conditional scenarios."
        )

    # P0 safety boundary: switch costs are unavailable until exact per-lot and
    # scheme/plan exit-load evidence plus independent tax approval are implemented.
    switch_costs = []
    for holding in holdings:
        if holding.plan == PlanType.REGULAR:
            switch_cost = calculate_switch_cost_analysis(
                source_fund=holding.fund_name,
                target_fund=holding.fund_name + " Direct",
                source_holding=holding,
                target_fund_ter=holding.expense_ratio_pct,
                is_intra_amc=True,
            )
            switch_costs.append({
                "fund_name": holding.fund_name,
                "switch_cost_inr": None,
                "switch_cost_pct": None,
                "exit_load_inr": None,
                "capital_gains_tax_inr": None,
                "available": False,
                "unavailable_reason": switch_cost.unavailable_reason,
                "warning": switch_cost.warning,
            })

    # Architectural Correction 5 & 6: Eligibility Gates & NO ACTION
    # Ingest candidate universe from fund_metrics and run all 10 binary gates
    candidate_universe = load_candidate_universe(
                metrics_path,
                portfolio_disclosures_by_scheme_id=portfolio_disclosures_by_scheme_id,
                portfolio_disclosure_source_bytes_by_scheme_id=portfolio_disclosure_source_bytes_by_scheme_id,
                disclosure_as_of_date=disclosure_as_of_date,
                disclosure_max_age_days=disclosure_max_age_days,
            )
    current_portfolio_summary = _build_portfolio_gate_summary(holdings)
    tier_num = _parse_sebi_risk_tier(client_risk_tier)

    from core.eligibility import load_fund_screening_policy
    screening_policy = load_fund_screening_policy()

    eligible_candidates = []
    for cand in candidate_universe:
        gate_result = check_eligibility_gates(
            fund_data=cand,
            portfolio_holdings=current_portfolio_summary,
            client_risk_tier_num=tier_num,
            is_starter=(tot_cur > 0 and tot_cur < Decimal("500000.00")),
            policy=screening_policy,
        )
        cand["eligibility"] = {
            "passed": gate_result.passed,
            "failed_gates": gate_result.failed_gates,
            "details": gate_result.details,
            "policy_version": gate_result.policy_version,
            "policy_digest": gate_result.policy_digest,
        }
        if gate_result.passed:
            eligible_candidates.append(cand)

    # Mandatory NO ACTION Fiduciary Branch receives the same validated
    # investor suitability profile used by the candidate eligibility gates.
    no_action_decision = evaluate_no_action(
        holdings, eligible_candidates, client_risk_tier_num=tier_num, policy=screening_policy
    )

    # Identify weak or redundant funds
    weak_funds = []
    for h in holdings:
        # Flag regular plans with high commission and overlap
        if h.plan == PlanType.REGULAR and ("multi cap" in h.fund_name.lower() or "multicap" in h.fund_name.lower()):
            weak_funds.append({
                "fund_name": h.fund_name,
                "current_value_inr": h.current_value_inr,
                "issue": "Multi-Cap Crowding (Regular Plan Commission Bleed + High Stock Overlap)"
            })

    return FiduciaryFactsPayload(
        client_name=client_name,
        client_age=client_age_val,
        horizon_years=horizon_yrs_val,
        risk_tier_name=client_risk_tier,
        total_portfolio_value_inr=round(tot_cur, 2),
        total_invested_value_inr=round(tot_inv, 2),
        total_unrealized_gain_inr=round(tot_gain, 2),
        holdings_count=len(holdings),
        fee_bleed=fee_bleed,
        overlap_matrix=overlap,
        weighted_overlap=weighted_overlap,
        weighted_overlap_status=weighted_lookthrough_overlap_status(holdings),
        risk_distribution=risk_distribution,
        saa_drift=saa,
        cash_plan=cash,
        switch_costs=switch_costs,
        eligibility_results=[{"fund_id": c["fund_id"], "fund_name": c["fund_name"], "passed": c["eligibility"]["passed"], "failed_gates": c["eligibility"]["failed_gates"]} for c in candidate_universe],
        no_action=no_action_decision,
        monthly_sip_budget_inr=monthly_sip,
        lumpsum_budget_inr=lumpsum_budget,
        xirr_pct=portfolio_xirr,
        benchmark_xirr_pct=benchmark_xirr,
        alpha_pct=alpha_pct,
        tax_lots_summary=tax_lots_summary,
        weak_funds_flagged=weak_funds,
        holdings=holdings,
        stability_buffer=stability_buf,
        thematic_exposures=thematic_exps,
        deterministic_sip_plan=det_sip_plan,
        deterministic_lumpsum_plan=det_lumpsum_plan,
        cas_reconciliation=cas_recon,
        mandate_state=active_mandate_state,
        is_execution_authorized=is_exec_auth,
    )


# ============================================================
# ARCHITECTURAL CORRECTIONS - NEW FUNCTIONS
# ============================================================

def weighted_lookthrough_overlap_status(holdings: List[HoldingItem]) -> str:
    """Return VERIFIED only when every active holding has complete weighted disclosure."""
    if not holdings:
        return "UNAVAILABLE"
    seen: Dict[str, Dict[str, float]] = {}
    for holding in holdings:
        try:
            value = float(holding.current_value_inr)
            equity_pct = float(getattr(holding, "equity_pct", 100.0))
        except (TypeError, ValueError, AttributeError):
            return "UNAVAILABLE"
        if not math.isfinite(value) or value <= 0.0 or not math.isfinite(equity_pct) or not 0.0 <= equity_pct <= 100.0:
            return "UNAVAILABLE"
        # Pure debt/cash holdings do not contribute to stock overlap and do
        # not require equity constituent disclosures.
        if equity_pct == 0.0:
            continue
        try:
            coverage = float(holding.constituent_weights_coverage_pct)
            raw = holding.constituent_weights
        except (TypeError, ValueError, AttributeError):
            return "UNAVAILABLE"
        if (
            getattr(holding, "lookthrough_status", "MISSING") != "VERIFIED"
            or not math.isfinite(coverage) or not 99.5 <= coverage <= 100.0
            or not isinstance(raw, dict) or not raw
        ):
            return "UNAVAILABLE"
        try:
            weights = {
                re.sub(r"[^a-z0-9]", "", str(stock).casefold()): float(weight)
                for stock, weight in raw.items()
            }
        except (TypeError, ValueError):
            return "UNAVAILABLE"
        if (
            any(not stock or not math.isfinite(weight) or not 0.0 <= weight <= 100.0
                for stock, weight in weights.items())
            or not 99.5 <= sum(weights.values()) <= 100.5
        ):
            return "UNAVAILABLE"
        scheme_id = getattr(holding, "scheme_id", None)
        source_url = getattr(holding, "lookthrough_source_url", None)
        source_digest = getattr(holding, "lookthrough_source_document_sha256", None)
        effective_date = getattr(holding, "lookthrough_effective_date", None)
        if (
            not isinstance(scheme_id, str) or not scheme_id.strip()
            or not isinstance(source_url, str) or not source_url.startswith("https://")
            or not isinstance(source_digest, str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", source_digest)
            or not isinstance(effective_date, str)
        ):
            return "UNAVAILABLE"
        try:
            date.fromisoformat(effective_date)
        except ValueError:
            return "UNAVAILABLE"
        prior = seen.get(scheme_id)
        if prior is not None and prior != weights:
            return "UNAVAILABLE"
        seen[scheme_id] = weights
    return "VERIFIED"


def calculate_weighted_lookthrough_overlap(
    holdings: List[HoldingItem],
    metrics_path: Optional[Path] = None,
    threshold_pct: float = 10.0
) -> List[WeightedOverlapResult]:
    """Calculate pairwise overlap from complete verified constituent weights only.

    The metrics_path parameter is retained for compatibility but is never read.
    Top-holdings lists and equal-weight approximations are not portfolio evidence.
    An empty result means callers must consult weighted_lookthrough_overlap_status;
    it must not be interpreted as verified zero overlap.
    """
    if weighted_lookthrough_overlap_status(holdings) != "VERIFIED":
        return []
    if isinstance(threshold_pct, bool) or not isinstance(threshold_pct, (int, float)):
        raise ValueError("threshold_pct must be a finite number from 0 to 100")
    if not math.isfinite(float(threshold_pct)) or not 0.0 <= float(threshold_pct) <= 100.0:
        raise ValueError("threshold_pct must be a finite number from 0 to 100")

    by_fund: Dict[str, Dict[str, float]] = {}
    source_by_fund: Dict[str, Dict[str, Any]] = {}
    for holding in holdings:
        equity_pct = float(getattr(holding, "equity_pct", 100.0))
        if equity_pct == 0.0:
            continue
        fund_id = str(holding.scheme_id)
        weights = {
            re.sub(r"[^a-z0-9]", "", str(stock).casefold()): float(weight)
            for stock, weight in holding.constituent_weights.items()
        }
        source_ref = {
            "scheme_id": fund_id,
            "source_url": holding.lookthrough_source_url,
            "source_document_sha256": holding.lookthrough_source_document_sha256,
            "effective_date": holding.lookthrough_effective_date,
            "coverage_pct": float(holding.constituent_weights_coverage_pct),
        }
        if fund_id in by_fund and (
            by_fund[fund_id] != weights or source_by_fund[fund_id] != source_ref
        ):
            return []
        by_fund[fund_id] = weights
        source_by_fund[fund_id] = source_ref

    results = []
    fund_ids = sorted(by_fund)
    for index, fund_a in enumerate(fund_ids):
        for fund_b in fund_ids[index + 1:]:
            weights_a, weights_b = by_fund[fund_a], by_fund[fund_b]
            shared = sorted(set(weights_a) & set(weights_b))
            if not shared:
                continue
            weighted_overlap = sum(min(weights_a[stock], weights_b[stock]) for stock in shared)
            union = set(weights_a) | set(weights_b)
            jaccard = len(shared) / len(union) if union else 0.0
            if weighted_overlap >= 20.0:
                verdict = "HIGH_CONCENTRATION"
            elif weighted_overlap >= 10.0:
                verdict = "MODERATE"
            else:
                verdict = "ACCEPTABLE"
            if weighted_overlap >= float(threshold_pct):
                results.append(WeightedOverlapResult(
                    fund_a=fund_a,
                    fund_b=fund_b,
                    weighted_overlap_pct=round(weighted_overlap, 2),
                    jaccard_similarity=round(jaccard * 100.0, 2),
                    shared_stocks=[
                        {
                            "stock": stock,
                            "weight_a_pct": round(weights_a[stock], 2),
                            "weight_b_pct": round(weights_b[stock], 2),
                            "combined_weight_pct": round(weights_a[stock] + weights_b[stock], 2),
                        }
                        for stock in shared
                    ],
                    sector_concentration={},
                    verdict=verdict,
                    status="VERIFIED",
                    source="EXACT_SCHEME_PORTFOLIO_DISCLOSURES",
                    source_refs=[source_by_fund[fund_a], source_by_fund[fund_b]],
                    effective_date=min(
                        source_by_fund[fund_a]["effective_date"],
                        source_by_fund[fund_b]["effective_date"],
                    ),
                    coverage_status="VERIFIED",
                    coverage_pct=round(min(
                        source_by_fund[fund_a]["coverage_pct"],
                        source_by_fund[fund_b]["coverage_pct"],
                    ), 2),
                    reason="Calculated from verified, exact-scheme constituent weights and source digests.",
                ))
    results.sort(key=lambda item: item.weighted_overlap_pct, reverse=True)
    return results


def calculate_risk_distribution(
    holdings: List[HoldingItem]
) -> RiskDistribution:
    if not holdings:
        return RiskDistribution(
            availability_status="UNAVAILABLE",
            verified_coverage_pct=0.0,
            unknown_value_inr=None,
        )
    total_value = sum(float(h.current_value_inr) for h in holdings)
    if not math.isfinite(total_value) or total_value <= 0.0:
        return RiskDistribution(
            availability_status="UNAVAILABLE",
            verified_coverage_pct=0.0,
            unknown_value_inr=total_value if math.isfinite(total_value) else None,
        )

    tier_counts: Dict[str, int] = {}
    tier_values: Dict[str, float] = {}
    verified_value = 0.0
    unknown_value = 0.0
    for holding in holdings:
        tier = getattr(holding, "risk_tier", None)
        if not isinstance(tier, str) or not tier.strip():
            tier = "Unknown"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        tier_values[tier] = tier_values.get(tier, 0.0) + float(holding.current_value_inr)
        if tier == "Unknown":
            unknown_value += float(holding.current_value_inr)
        else:
            verified_value += float(holding.current_value_inr)

    tier_pct = {tier: round(value / total_value * 100.0, 2) for tier, value in tier_values.items()}
    coverage_pct = verified_value / total_value * 100.0
    status = "COMPLETE" if coverage_pct >= 99.999 else ("PARTIAL" if coverage_pct > 0.0 else "UNAVAILABLE")
    return RiskDistribution(
        risk_tier_distribution=tier_counts,
        risk_tier_values=tier_pct,
        availability_status=status,
        verified_coverage_pct=round(coverage_pct, 2),
        unknown_value_inr=round(unknown_value, 2),
        portfolio_beta=None,
        max_drawdown_pct=None,
        downside_capture_ratio=None,
        volatility_annualized_pct=None,
    )


def _load_tax_rules(tax_rules_path: Optional[Path] = None) -> dict:
    """Load only independently approved tax rules; never supply fallback rates."""
    from core.models import InsufficientDataError

    if tax_rules_path is None:
        tax_rules_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "tax_rules.json"
    if not tax_rules_path.is_file():
        raise InsufficientDataError(
            "Tax rules are unavailable; tax-dependent calculations are NO ACTION.",
            missing_data="versioned tax_rules.json",
            required_source="independently reviewed statutory policy",
        )
    try:
        with open(tax_rules_path, "r", encoding="utf-8") as handle:
            rules = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise InsufficientDataError(
            f"Tax rules could not be loaded safely: {exc}",
            missing_data="valid tax_rules.json",
            required_source="versioned statutory policy",
        ) from exc

    review = rules.get("independent_review")
    if rules.get("status") != "approved" or not isinstance(review, dict) or review.get("status") != "approved":
        raise InsufficientDataError(
            "Tax rules are provisional or lack independent legal/adviser approval; tax-dependent calculations are NO ACTION.",
            missing_data="independent tax-policy approval",
            required_source="qualified independent reviewer sign-off and evidence digest",
        )
    return rules


def _classify_fund_for_tax(source_holding: HoldingItem, tax_rules: dict) -> str:
    """Classify equity-oriented units only; fail closed for missing/non-equity inputs.

    This legacy helper is intentionally not a complete tax classifier. It must
    never turn a missing or non-equity percentage into an equity-oriented result.
    """
    import math

    equity_pct = getattr(source_holding, "equity_pct", None)
    if equity_pct is None or isinstance(equity_pct, bool):
        raise ValueError("Verified annual-average equity allocation is required for tax classification")
    try:
        equity_pct = float(equity_pct)
    except (TypeError, ValueError) as exc:
        raise ValueError("Equity allocation must be numeric") from exc
    if not math.isfinite(equity_pct) or not 0.0 <= equity_pct <= 100.0:
        raise ValueError("Equity allocation must be finite and between 0 and 100")

    equity_threshold = float(tax_rules.get("classification_test", {}).get("equity_oriented_threshold_pct", 65.0))
    if not math.isfinite(equity_threshold) or equity_threshold != 65.0:
        raise ValueError("Section 198 statutory equity-oriented threshold must be 65%")
    if equity_pct >= equity_threshold:
        return "equity_oriented"
    raise NotImplementedError(
        "Non-equity tax classification is not implemented in this legacy helper; refusing to infer a tax category."
    )


def calculate_switch_cost_analysis(
    source_fund: str,
    target_fund: str,
    source_holding: HoldingItem,
    target_fund_ter: float,
    is_intra_amc: bool = False,
    holding_period_days: Optional[int] = None,
    current_nav: float = 0.0,
    purchase_nav: float = 0.0,
    tax_rules_path: Optional[Path] = None
) -> SwitchCostAnalysis:
    """Return unavailable until a per-lot tax and scheme-exit-load engine is approved.

    The previous implementation applied one average holding period to mixed lots,
    generic exit-load defaults and a portfolio-wide exemption to a single holding.
    Those calculations are not suitable for investor-specific switching decisions.
    """
    reason = (
        "NO ACTION: switch-cost calculation is disabled. It requires exact transaction "
        "lots, date-specific tax classification, independently approved tax rules, and "
        "current scheme/plan/lot-specific exit-load evidence. A missing cost is not zero."
    )
    return SwitchCostAnalysis(
        source_fund=source_fund,
        target_fund=target_fund,
        exit_load_pct=None,
        exit_load_inr=None,
        capital_gains_tax_inr=None,
        stcg_tax_inr=None,
        ltcg_tax_inr=None,
        net_switch_cost_inr=None,
        net_switch_cost_pct=None,
        is_intra_amc=is_intra_amc,
        is_available=False,
        unavailable_reason=reason,
        warning=reason,
    )


def calculate_saa_drift_minimizer(
    holdings: List[HoldingItem],
    target_allocation: Dict[str, float],
    sip_budget_inr: float,
    policy_path: Optional[Path] = None,
) -> SAA_DriftMinimizer:
    if not holdings:
        raise ValueError("SAA diagnostics are unavailable: no verified active holdings were supplied")
    total_val = sum(float(h.current_value_inr) for h in holdings)
    if not math.isfinite(total_val) or total_val <= 0:
        raise ValueError("SAA diagnostics are unavailable: portfolio value denominator must be positive")

    current_alloc = {}
    for h in holdings:
        asset = h.asset_class.value if hasattr(h.asset_class, 'value') else str(h.asset_class)
        # Map AssetClass to allocation categories
        if h.asset_class in (
            AssetClass.EQUITY, AssetClass.LARGE_CAP, AssetClass.MID_CAP,
            AssetClass.SMALL_CAP, AssetClass.FLEXI_CAP, AssetClass.MULTI_CAP,
            AssetClass.INTERNATIONAL,
        ):
            # International equity is still equity for total-portfolio SAA.
            alloc_category = "Equity"
        elif h.asset_class in (AssetClass.DEBT, AssetClass.DEBT_LIQUID):
            alloc_category = "Debt"
        elif h.asset_class in (AssetClass.CASH,):
            alloc_category = "Cash"
        elif h.asset_class in (AssetClass.HYBRID_BALANCED, AssetClass.HYBRID):
            # Split hybrid based on equity/debt ratio
            equity_val = float(h.current_value_inr) * (h.equity_pct / 100.0)
            debt_val = float(h.current_value_inr) * (h.debt_pct / 100.0)
            if "Equity" not in current_alloc:
                current_alloc["Equity"] = 0.0
            if "Debt" not in current_alloc:
                current_alloc["Debt"] = 0.0
            current_alloc["Equity"] += equity_val
            current_alloc["Debt"] += debt_val
            continue
        else:
            alloc_category = "Other"

        if alloc_category not in current_alloc:
            current_alloc[alloc_category] = 0.0
        current_alloc[alloc_category] += float(h.current_value_inr)

    current_pct = {k: (v / total_val) * 100 for k, v in current_alloc.items()}

    # Do not invent a 95/5 aggressive target when the client's SAA is absent.
    # An explicit zero-equity target is valid and must not be replaced by a fallback.
    if not isinstance(target_allocation, dict):
        raise ValueError("Explicit client SAA target allocation is required")
    equity_keys = (
        "large_cap_pct", "mid_small_cap_pct", "mid_cap_pct",
        "small_cap_pct", "flexi_multi_cap_pct",
    )
    has_equity_target = "equity_pct" in target_allocation or any(
        key in target_allocation for key in equity_keys
    )
    if not has_equity_target:
        raise ValueError("Client SAA is missing an explicit equity allocation; no default target is permitted")
    try:
        if "equity_pct" in target_allocation:
            tgt_eq = float(target_allocation["equity_pct"])
        else:
            tgt_eq = sum(float(target_allocation.get(key, 0.0)) for key in equity_keys)
        debt_key = "debt_liquid_pct" if "debt_liquid_pct" in target_allocation else (
            "debt_global_pct" if "debt_global_pct" in target_allocation else "debt_pct"
        )
        if debt_key not in target_allocation:
            raise ValueError("Client SAA is missing an explicit debt allocation")
        tgt_db = float(target_allocation[debt_key])
        tgt_cash = float(target_allocation.get("cash_pct", 0.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("Client SAA equity/debt/cash targets must be numeric") from exc
    target_values = (tgt_eq, tgt_db, tgt_cash)
    if any(not math.isfinite(value) or not 0.0 <= value <= 100.0 for value in target_values):
        raise ValueError("Client SAA equity/debt/cash targets must be finite and between 0 and 100")
    if abs(sum(target_values) - 100.0) > 0.01:
        raise ValueError("Client SAA equity, debt and cash targets must sum to 100%")

    target_pct = {
        "Equity": tgt_eq,
        "Debt": tgt_db,
        "Cash": tgt_cash
    }

    gaps = {k: target_pct.get(k, 0) - current_pct.get(k, 0) for k in set(current_pct) | set(target_pct)}

    if isinstance(sip_budget_inr, bool):
        raise ValueError("SIP budget must be numeric")
    try:
        budget = float(sip_budget_inr)
    except (TypeError, ValueError) as exc:
        raise ValueError("SIP budget must be numeric") from exc
    if not math.isfinite(budget) or budget < 0.0:
        raise ValueError("SIP budget must be finite and non-negative")

    # Minimize squared post-contribution weight error using the post-SIP
    # denominator. The unconstrained ideal contribution for sleeve i is
    # target_i * (portfolio_value + SIP) - current_value_i. Project that
    # vector onto the non-negative simplex whose sum is exactly the SIP budget.
    # This correctly allows contributions to currently overweight sleeves
    # when they are still below their desired post-SIP value, and naturally
    # preserves zero-target sleeves at zero.
    assets = list(target_pct)
    new_total = total_val + budget
    desired = [
        (target_pct[asset] / 100.0) * new_total - current_alloc.get(asset, 0.0)
        for asset in assets
    ]
    if budget == 0.0:
        projected_contributions = [0.0 for _ in assets]
    else:
        ordered = sorted(desired, reverse=True)
        cumulative = 0.0
        theta = None
        for index, value in enumerate(ordered, start=1):
            cumulative += value
            candidate_theta = (cumulative - budget) / index
            next_value = ordered[index] if index < len(ordered) else float("-inf")
            if value > candidate_theta and next_value <= candidate_theta:
                theta = candidate_theta
                break
        if theta is None:
            raise ValueError("Unable to solve constrained post-SIP SAA allocation")
        projected_contributions = [max(value - theta, 0.0) for value in desired]
        # Correct floating-point residue deterministically without changing
        # the active set or allowing a negative sleeve allocation.
        residue = budget - sum(projected_contributions)
        if abs(residue) > 1e-9:
            active = [i for i, value in enumerate(projected_contributions) if value > 0.0]
            if not active:
                raise ValueError("SAA projection produced no eligible contribution sleeve")
            projected_contributions[active[0]] += residue
    sip_alloc = {asset: projected_contributions[i] for i, asset in enumerate(assets)}

    projected_alloc = {}
    for asset in set(current_pct) | set(target_pct):
        current_val = current_alloc.get(asset, 0)
        sip_val = sip_alloc.get(asset, 0)
        projected_alloc[asset] = ((current_val + sip_val) / new_total) * 100

    drift = {k: projected_alloc.get(k, 0) - target_pct.get(k, 0) for k in target_pct}
    l2_norm = math.sqrt(sum(d * d for d in drift.values()))

    policy_meta = {}
    try:
        from core.models import get_saa_policy_metadata
        policy_meta = get_saa_policy_metadata(policy_path=policy_path)
    except Exception:
        pass

    return SAA_DriftMinimizer(
        current_allocation=current_pct,
        target_allocation=target_pct,
        sip_budget_inr=sip_budget_inr,
        recommended_sip_allocation=sip_alloc,
        drift_after_sip=drift,
        total_drift_l2_norm=round(l2_norm, 2),
        policy_version=policy_meta.get("policy_version"),
        policy_digest=policy_meta.get("policy_digest"),
    )


# check_eligibility_gates and evaluate_no_action are imported directly from core.eligibility
# (Module 4: Hard Binary Selection Gates & NO ACTION Engine)

def calculate_lookthrough_stability_buffer(
    holdings: List[HoldingItem],
    bank_cash_inr: Optional[float] = None,
    emergency_reserve_inr: Optional[float] = None,
    target_debt_pct: float = 5.0,
    as_of_date: Optional[str] = None,
) -> LookThroughStabilityBuffer:
    """Calculates look-through debt, cash, and total stability buffer across portfolio."""
    total_val = sum(h.current_value_inr for h in holdings)
    if total_val <= 0:
        return LookThroughStabilityBuffer()

    embedded_debt = sum(h.current_value_inr * (Decimal(str(h.debt_pct)) / Decimal("100")) for h in holdings)
    embedded_cash = sum(
        h.current_value_inr * (Decimal("100") - Decimal(str(h.equity_pct)) - Decimal(str(h.debt_pct))).max(Decimal("0")) / Decimal("100")
        for h in holdings
    )

    if bank_cash_inr is not None and emergency_reserve_inr is not None:
        deployable_cash = max(0.0, float(bank_cash_inr) - float(emergency_reserve_inr))
        bank_deployable = round(deployable_cash, 2)
        em_reserve = round(float(emergency_reserve_inr), 2)
        total_stability = embedded_debt + embedded_cash + deployable_cash
        cash_status = "AVAILABLE"
    else:
        deployable_cash = 0.0
        bank_deployable = None
        em_reserve = None
        total_stability = embedded_debt + embedded_cash
        cash_status = "EVIDENCE_MISSING"

    total_stability_pct = (total_stability / total_val) * Decimal("100")
    meets_target = total_stability_pct >= Decimal(str(target_debt_pct)) - Decimal("1")

    return LookThroughStabilityBuffer(
        embedded_debt_inr=round(embedded_debt, 2),
        embedded_debt_pct=round((embedded_debt / total_val) * Decimal("100"), 2),
        embedded_cash_inr=round(embedded_cash, 2),
        embedded_cash_pct=round((embedded_cash / total_val) * Decimal("100"), 2),
        bank_deployable_cash_inr=bank_deployable,
        emergency_reserve_inr=em_reserve,
        total_stability_buffer_inr=round(total_stability, 2),
        total_stability_buffer_pct=round(total_stability_pct, 2),
        meets_tier_target=meets_target,
        cash_evidence_status=cash_status,
        cash_as_of_date=as_of_date,
    )


def calculate_thematic_exposures(
    holdings: List[HoldingItem],
    metrics_path: Optional[Path] = None,
    aliases_path: Optional[Path] = None,
) -> List[ThematicExposureItem]:
    """Return unavailable until an independently approved issuer taxonomy exists.

    Verified constituent weights alone do not establish issuer-to-theme
    classification or policy thresholds. The former hardcoded issuer lists,
    name-based dedicated-fund matching and fixed 2/3/4 percent thresholds
    must not produce client-facing thematic amounts or deficit labels.
    """
    _ = (holdings, metrics_path, aliases_path)
    themes = (
        "Defence Thematic",
        "Commodities / Metals",
        "PSU & CPSE Themes",
        "Pharma & Healthcare",
        "Power & Infrastructure",
    )
    return [
        ThematicExposureItem(
            theme_name=name,
            dedicated_funds_inr=None,
            dedicated_funds_pct=None,
            look_through_stocks_inr=None,
            look_through_stocks_pct=None,
            coverage_status="UNAVAILABLE",
            key_underlying_holdings=[],
        )
        for name in themes
    ]


def _parse_sebi_risk_tier(risk_tier: str) -> int:
    """Parse an explicit SEBI riskometer tier; reject ambiguous/unknown labels."""
    import re

    tier_str = str(risk_tier or "").strip().casefold()
    if not tier_str:
        raise ValueError("Risk tier is required")
    match = re.search(r"\btier\s*([1-6])\b", tier_str)
    if match:
        return int(match.group(1))
    if "capital preservation" in tier_str or "very low" in tier_str or tier_str == "preservation":
        return 1
    if "low to moderate" in tier_str or tier_str == "low moderate":
        return 2
    if "moderately high" in tier_str:
        return 4
    if "very high" in tier_str or "aggressive" in tier_str:
        return 6
    if tier_str in {"low", "very low"}:
        return 1
    if "conservative" in tier_str:
        return 2
    # The investor-facing 3-tier profile "Moderate" maps to the
    # approved middle profile (SEBI Tier 4). Explicit SEBI labels such as
    # "Tier 3 (Moderate)" have already been resolved by the Tier N parser
    # above and retain their literal Riskometer meaning.
    if tier_str in {"moderate", "risk_tier.moderate", "moderate risk"}:
        # Plain investor-facing Moderate is Tier 4. Literal SEBI Tier 3
        # remains available only through an explicit "Tier 3" label.
        return 4
    if tier_str == "high" or tier_str.startswith("high "):
        return 5
    raise ValueError(f"Unrecognized SEBI risk tier: {risk_tier!r}")



def find_client_direct_folio(holdings: Optional[List[HoldingItem]], category_keyword: str) -> Tuple[Optional[str], Optional[str]]:
    """
    DETERMINISTIC 4-POINT SCHEME-LEVEL FOLIO ROUTER:
    Discovers if the client ALREADY holds an active Direct Growth folio in this category.
    Enforces strict 4-point verification:
    1. Scheme / Category alignment (eliminates cross-category bleed)
    2. Direct Plan verification (is_direct == True)
    3. Growth Option enforcement (strictly rejects IDCW / Dividend payout folios)
    4. Non-empty, verified CAS ledger folio number
    Returns: (scheme_name, folio_number)
    """
    if not holdings:
        return None, None

    cat_kw = category_keyword.lower().strip()
    for h in holdings:
        # Point 2 & 4: Direct and non-empty folio
        if not h.is_direct or not h.folio:
            continue
        s_lower = h.scheme.lower()
        # Point 3: Growth Option enforcement (strictly reject IDCW / Dividend)
        if "idcw" in s_lower or "dividend" in s_lower:
            continue

        # Point 1: Clean category identity matching
        if cat_kw in ("large", "large cap", "large_cap"):
            if "large" in s_lower and "mid" not in s_lower and "multi" not in s_lower:
                return h.scheme, h.folio
        elif cat_kw in ("mid", "mid cap", "midcap"):
            if ("mid" in s_lower or "midcap" in s_lower) and "large" not in s_lower and "multi" not in s_lower:
                return h.scheme, h.folio
        elif cat_kw in ("flexi", "flexi cap", "flexi_cap"):
            if "flexi" in s_lower:
                return h.scheme, h.folio
        elif cat_kw in ("pharma", "healthcare", "thematic"):
            if "pharma" in s_lower or "health" in s_lower:
                return h.scheme, h.folio
        elif cat_kw in ("small", "small cap", "small_cap", "smallcap"):
            if "small" in s_lower and "mid" not in s_lower:
                return h.scheme, h.folio
        elif cat_kw in ("multi", "multi cap", "multi_cap", "multicap"):
            if "multi cap" in s_lower or "multicap" in s_lower:
                return h.scheme, h.folio
        elif cat_kw in ("elss", "tax saver", "tax saving"):
            if "elss" in s_lower or "tax" in s_lower:
                return h.scheme, h.folio
        elif cat_kw in ("value", "contra"):
            if "value" in s_lower or "contra" in s_lower:
                return h.scheme, h.folio
        elif cat_kw in ("debt", "short term", "liquid", "bond", "arbitrage"):
            if any(k in s_lower for k in ("arbitrage", "liquid", "short term", "debt")) and "balanced advantage" not in s_lower:
                return h.scheme, h.folio
        elif any(th in cat_kw for th in ("pharma", "healthcare", "defence", "defense", "tech", "technology", "energy", "power", "psu", "infra", "thematic", "sectoral")):
            keywords = [w for w in ("pharma", "health", "defence", "defense", "tech", "energy", "power", "psu", "infra") if w in cat_kw]
            if keywords and any(kw in s_lower for kw in keywords):
                return h.scheme, h.folio
    return None, None


def compute_candidate_portfolio_overlap(
    cand: Dict[str, Any],
    holdings: Optional[List[HoldingItem]] = None,
    candidate_universe: Optional[List[Dict[str, Any]]] = None,
    security_master: Optional[Dict[str, Any]] = None,
    strict: bool = True,
) -> Optional[float]:
    """
    Calculate candidate-to-portfolio overlap from explicit constituent weights.

    Each constituent_weights map expresses stock weights as percentages of the
    fund's equity sleeve and must be complete (>=99.5% coverage and weights
    summing to 99.5..100.5%). Portfolio weights are value-weighted across the
    supplied holdings. None means evidence is missing/incomplete; zero is
    returned only for a verified empty portfolio or genuinely disjoint holdings.
    """
    if holdings is None:
        return None
    if not holdings:
        return 0.0

    if security_master is None:
        try:
            from core.security_master import load_security_master
            security_master = load_security_master()
        except Exception:
            security_master = None
    if strict and security_master is None:
        return None

    def validated_weights(raw: Any, coverage_raw: Any, label: str) -> Optional[Dict[str, float]]:
        if not isinstance(raw, dict) or not raw:
            return None
        if isinstance(coverage_raw, bool):
            return None
        try:
            coverage = float(coverage_raw)
            from core.security_master import normalize_constituent_weights
            weights, _ = normalize_constituent_weights(raw, security_master=security_master, strict=strict)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(coverage) or coverage < 99.5 or coverage > 100.0:
            return None
        if any(not k or not math.isfinite(v) or v < 0.0 or v > 100.0 for k, v in weights.items()):
            return None
        total = sum(weights.values())
        if not 99.5 <= total <= 100.5:
            return None
        return weights

    candidate_weights = validated_weights(
        cand.get("constituent_weights"),
        cand.get("constituent_weights_coverage_pct"),
        "candidate",
    )
    if candidate_weights is None:
        return None

    total_equity_value = 0.0
    portfolio_stock_weights: Dict[str, float] = {}
    for holding in holdings:
        try:
            value = float(holding.current_value_inr)
            equity_pct = float(holding.equity_pct)
        except (TypeError, ValueError, AttributeError):
            return None
        if not math.isfinite(value) or value <= 0.0 or not math.isfinite(equity_pct) or not 0.0 <= equity_pct <= 100.0:
            return None
        if equity_pct == 0.0:
            continue
        holding_weights = validated_weights(
            getattr(holding, "constituent_weights", None),
            getattr(holding, "constituent_weights_coverage_pct", None),
            f"holding {getattr(holding, 'fund_id', 'unknown')}",
        )
        if holding_weights is None:
            return None
        equity_value = value * equity_pct / 100.0
        total_equity_value += equity_value
        for security_id, stock_weight_pct in holding_weights.items():
            portfolio_stock_weights[security_id] = (
                portfolio_stock_weights.get(security_id, 0.0)
                + equity_value * stock_weight_pct / 100.0
            )

    # Compare equity sleeves with equity sleeves. Including debt/cash in this
    # denominator artificially dilutes overlap and can make a duplicate fund
    # look diversified merely because the investor also holds debt.
    if not math.isfinite(total_equity_value) or total_equity_value <= 0.0:
        return 0.0
    portfolio_stock_weights = {
        security_id: value / total_equity_value * 100.0
        for security_id, value in portfolio_stock_weights.items()
    }
    overlap = sum(
        min(candidate_weight, portfolio_stock_weights.get(security_id, 0.0))
        for security_id, candidate_weight in candidate_weights.items()
    )
    return round(overlap, 2)


def evaluate_candidate_portfolio_concentration_controls(
    candidate: Dict[str, Any],
    holdings: Optional[List[HoldingItem]] = None,
    *,
    security_master: Optional[Dict[str, Any]] = None,
    classifications: Optional[Dict[str, Any]] = None,
    max_overlap_pct: float = 30.0,
    max_issuer_pct: float = 10.0,
    max_sector_pct: float = 35.0,
    max_theme_pct: float = 15.0,
    max_market_cap_pct: float = 50.0,
    max_scheme_pct: float = 25.0,
    is_starter: bool = False,
    as_of_date: Optional[str] = None,
    require_security_master: bool = False,
) -> Dict[str, Any]:
    """
    Issue #26: Comprehensive multi-dimensional concentration and overlap controls.
    Measures:
    1. Look-through completeness (>=99.5% required; missing returns HOLD)
    2. Pairwise candidate overlap ceiling (<= max_overlap_pct, default 30%)
    3. Total-portfolio issuer concentration cap (<= max_issuer_pct, default 10%)
    4. Total-portfolio sector concentration cap (<= max_sector_pct, default 35%)
    5. Thematic satellite cap (<= 15% for established, 0% for starter)
    6. Market-cap concentration cap (<= max_market_cap_pct, default 50%)
    7. Single-scheme concentration cap (<= max_scheme_pct, default 25%)
    """
    if holdings is None:
        return {"status": "HOLD", "passed": False, "reason": "HOLDINGS_DATA_MISSING", "overlap_pct": None}

    if require_security_master and security_master is None:
        return {"status": "HOLD", "passed": False, "reason": "SECURITY_MASTER_REQUIRED", "overlap_pct": None}

    overlap = compute_candidate_portfolio_overlap(
        candidate, holdings=holdings, security_master=security_master, strict=(security_master is not None)
    )
    if overlap is None:
        return {
            "status": "HOLD",
            "passed": False,
            "reason": "LOOKTHROUGH_INCOMPLETE_OR_UNRESOLVED",
            "overlap_pct": None,
        }

    if overlap > max_overlap_pct:
        return {
            "status": "REJECT",
            "passed": False,
            "reason": f"CANDIDATE_OVERLAP_BREACH: {overlap:.2f}% exceeds policy ceiling of {max_overlap_pct:.2f}%",
            "overlap_pct": overlap,
        }

    if is_starter:
        cat = str(candidate.get("category", candidate.get("cat", "")) or "").casefold()
        if "thematic" in cat or "sectoral" in cat or candidate.get("is_thematic"):
            return {
                "status": "REJECT",
                "passed": False,
                "reason": "STARTER_PORTFOLIO_THEMATIC_PROHIBITED",
                "overlap_pct": overlap,
            }

    # Multi-dimensional concentration check across issuer, sector, theme, market-cap and scheme
    if classifications is not None and security_master is not None and holdings:
        from core.security_master import normalize_security_identifier
        total_equity_value = 0.0
        issuer_totals: Dict[str, float] = {}
        sector_totals: Dict[str, float] = {}
        theme_totals: Dict[str, float] = {}
        mcap_totals: Dict[str, float] = {}

        for h in holdings:
            val = float(getattr(h, "current_value_inr", 0.0) or 0.0)
            eq_pct = float(getattr(h, "equity_pct", 0.0) or 0.0)
            eq_val = val * eq_pct / 100.0
            total_equity_value += eq_val
            c_weights = getattr(h, "constituent_weights", {}) or {}
            for issuer, w in c_weights.items():
                try:
                    c_id, _ = normalize_security_identifier(issuer, security_master=security_master)
                    c_val = eq_val * float(w) / 100.0
                    issuer_totals[c_id] = issuer_totals.get(c_id, 0.0) + c_val

                    facts = classifications.get(c_id, {})
                    if isinstance(facts, dict):
                        sec = facts.get("sector")
                        if sec:
                            sector_totals[sec] = sector_totals.get(sec, 0.0) + c_val
                        mcap = facts.get("market_cap_bucket")
                        if mcap:
                            mcap_totals[mcap] = mcap_totals.get(mcap, 0.0) + c_val
                        themes = facts.get("themes") or []
                        for th in themes:
                            theme_totals[th] = theme_totals.get(th, 0.0) + c_val
                except ValueError:
                    return {
                        "status": "HOLD",
                        "passed": False,
                        "reason": f"LOOKTHROUGH_INCOMPLETE_OR_UNRESOLVED: Unresolved constituent '{issuer}' in holdings",
                        "overlap_pct": overlap,
                    }

        cand_weights = candidate.get("constituent_weights") or {}
        # Candidate nominal weight in post-contribution equity (defaulting to standard ticket exposure)
        cand_allocation = float(candidate.get("allocation_inr", 0.0) or 0.0)
        cand_eq_val = cand_allocation if cand_allocation > 0 else (total_equity_value * 0.10 if total_equity_value > 0 else 10000.0)
        post_equity_total = total_equity_value + cand_eq_val

        if post_equity_total > 0:
            for issuer, w in cand_weights.items():
                try:
                    c_id, _ = normalize_security_identifier(issuer, security_master=security_master)
                    add_val = cand_eq_val * float(w) / 100.0
                    comb_val = issuer_totals.get(c_id, 0.0) + add_val
                    issuer_pct = (comb_val / post_equity_total) * 100.0
                    if issuer_pct > max_issuer_pct:
                        return {
                            "status": "REJECT",
                            "passed": False,
                            "reason": f"ISSUER_CONCENTRATION_BREACH: Issuer '{c_id}' at {issuer_pct:.2f}% exceeds cap of {max_issuer_pct:.2f}%",
                            "overlap_pct": overlap,
                            "breached_issuer": c_id,
                            "issuer_pct": issuer_pct,
                        }

                    facts = classifications.get(c_id, {})
                    if isinstance(facts, dict):
                        sec = facts.get("sector")
                        if sec:
                            s_comb = sector_totals.get(sec, 0.0) + add_val
                            s_pct = (s_comb / post_equity_total) * 100.0
                            if s_pct > max_sector_pct:
                                return {
                                    "status": "REJECT",
                                    "passed": False,
                                    "reason": f"SECTOR_CONCENTRATION_BREACH: Sector '{sec}' at {s_pct:.2f}% exceeds cap of {max_sector_pct:.2f}%",
                                    "overlap_pct": overlap,
                                    "breached_sector": sec,
                                    "sector_pct": s_pct,
                                }
                        themes = facts.get("themes") or []
                        for th in themes:
                            th_comb = theme_totals.get(th, 0.0) + add_val
                            th_pct = (th_comb / post_equity_total) * 100.0
                            if th_pct > max_theme_pct:
                                return {
                                    "status": "REJECT",
                                    "passed": False,
                                    "reason": f"THEME_CONCENTRATION_BREACH: Theme '{th}' at {th_pct:.2f}% exceeds cap of {max_theme_pct:.2f}%",
                                    "overlap_pct": overlap,
                                    "breached_theme": th,
                                    "theme_pct": th_pct,
                                }
                        mcap = facts.get("market_cap_bucket")
                        if mcap and max_market_cap_pct > 0:
                            m_comb = mcap_totals.get(mcap, 0.0) + add_val
                            m_pct = (m_comb / post_equity_total) * 100.0
                            if m_pct > max_market_cap_pct:
                                return {
                                    "status": "REJECT",
                                    "passed": False,
                                    "reason": f"MARKET_CAP_CONCENTRATION_BREACH: Bucket '{mcap}' at {m_pct:.2f}% exceeds cap of {max_market_cap_pct:.2f}%",
                                    "overlap_pct": overlap,
                                    "breached_market_cap": mcap,
                                    "market_cap_pct": m_pct,
                                }
                except ValueError:
                    return {
                        "status": "HOLD",
                        "passed": False,
                        "reason": f"LOOKTHROUGH_INCOMPLETE_OR_UNRESOLVED: Unresolved constituent '{issuer}' in candidate",
                        "overlap_pct": overlap,
                    }

    return {
        "status": "PASSED",
        "passed": True,
        "overlap_pct": overlap,
        "concentration_status": "COMPLIANT",
    }



def compute_multi_horizon_fiduciary_score(
    c: Dict[str, Any],
    category_key: str,
    portfolio_overlap_pct: Optional[float] = None,
    *,
    scoring_weights: Any,
) -> float:
    """
    Standardized 6-Pillar Fiduciary Normalized Scoring Engine (0 - 100 Scale):
    Uses Category-Relative Min-Max Normalization with regulatory anchor clamping.
    Caps momentum at 25% of total score, preventing short-term return hijacking.
    Incorporates actual candidate-to-portfolio weighted stock look-through overlap.
    Issue #25: Prohibits scoring candidates before mandatory eligibility gates pass.
    """
    # Issue #25: Mandatory eligibility gates must pass before scoring (strictly fail-closed)
    elig_status = c.get("eligibility_status")
    is_eligible = c.get("is_eligible")
    if elig_status not in ("PASS", "ELIGIBLE", "PASSED"):
        raise ValueError(f"Candidate '{c.get('fund_id', 'unknown')}' has invalid, missing, or unvetted eligibility status ({elig_status!r}); scoring before positive eligibility is prohibited.")
    if is_eligible is not True:
        raise ValueError(f"Candidate '{c.get('fund_id', 'unknown')}' does not have verified positive eligibility (is_eligible={is_eligible!r}); scoring before eligibility is prohibited.")
    from core.candidate_scoring import calculate_candidate_6_pillar_score
    score, _ = calculate_candidate_6_pillar_score(
        c, category_key, portfolio_overlap_pct, weights=scoring_weights
    )
    return score


# ─────────────────────────────────────────────────────────────────────────────
# THREE-REGIME SPECIFIED MUTUAL FUND CLASSIFIER (Section 198 / 50AA / 76)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ClassificationResult:
    """Result of specified mutual fund classification under applicable provision."""
    qualifies: bool
    provision: str                     # "Section 198" | "Section 50AA" | "Section 76" | "Section 48 (Grandfathered)"
    effective_date: date
    threshold: float
    calculation_method: str            # "annual_average_monthly" | "annual_average_daily"
    source_data_status: str            # "complete" | "partial" | "missing"
    reason: str
    equity_pct: float = 0.0
    debt_and_money_market_pct: float = 0.0
    acquisition_date: Optional[date] = None
    transfer_date: Optional[date] = None
    is_fund_of_funds: bool = False
    fof_debt_investing_pct: Optional[float] = None
    is_mld: bool = False


@dataclass
class MonthlyPortfolioSnapshot:
    """Monthly opening/closing portfolio composition for Section 198 annual-average tests."""
    month: date
    opening_equity_pct: Optional[float] = None
    closing_equity_pct: Optional[float] = None
    opening_fof_units_pct: Optional[float] = None
    closing_fof_units_pct: Optional[float] = None
    opening_underlying_equity_pct: Optional[float] = None
    closing_underlying_equity_pct: Optional[float] = None


@dataclass(frozen=True)
class MonthlySnapshotCoverageEvidence:
    expected_months: Tuple[date, ...]
    source_url: str
    source_document_sha256: str
    reviewer_attested: bool


def validate_monthly_snapshot_coverage(
    snapshots: List[MonthlyPortfolioSnapshot],
    fy_start: date,
    fy_end: date,
    evidence: Optional[MonthlySnapshotCoverageEvidence],
) -> None:
    import re
    from core.models import InsufficientDataError

    if not isinstance(evidence, MonthlySnapshotCoverageEvidence):
        raise InsufficientDataError(
            "Section 198 requires provenance-backed monthly coverage evidence, not only 12 supplied records.",
            missing_data="MonthlySnapshotCoverageEvidence",
            required_source="Verified monthly disclosure calendar with source URL and SHA-256",
        )
    if evidence.reviewer_attested is not True:
        raise InsufficientDataError(
            "Section 198 monthly disclosure calendar lacks an explicit reviewer attestation.",
            missing_data="reviewer attestation for monthly coverage",
            required_source="Monthly disclosure calendar with source URL and document digest, reviewed by an adviser",
        )
    if not isinstance(evidence.source_url, str) or not evidence.source_url.startswith("https://"):
        raise ValueError("Monthly snapshot source_url must be an HTTPS URL")
    if not isinstance(evidence.source_document_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", evidence.source_document_sha256):
        raise ValueError("Monthly snapshot source_document_sha256 must be a 64-character SHA-256 hex digest")
    expected = list(evidence.expected_months)
    if not expected or expected != sorted(set(expected)):
        raise ValueError("Expected monthly snapshot dates must be non-empty, sorted and unique")
    if any(d.day != 1 for d in expected):
        raise ValueError("Expected monthly snapshot dates must be first day of each month")
    observed = [s.month for s in snapshots or []]
    if len(observed) != len(set(observed)):
        raise ValueError("Observed monthly portfolio snapshots contain duplicate months")
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        unexpected = sorted(set(observed) - set(expected))
        raise InsufficientDataError(
            "Section 198 monthly snapshot dates do not match the reviewer-attested monthly disclosure calendar.",
            missing_data=f"missing_months={missing}, unexpected_months={unexpected}",
            required_source="Complete monthly opening and closing portfolio disclosures",
        )


@dataclass
class DailyPortfolioSnapshot:
    """Daily portfolio composition for annual-average-of-daily-closing calculation."""
    date: date
    equity_pct: float
    debt_pct: float
    money_market_pct: float
    fof_specified_mf_pct: Optional[float] = None


def compute_annual_average_monthly_opening_closing(
    snapshots: List[MonthlyPortfolioSnapshot],
    fy_start: date,
    fy_end: date,
    metric: str = "equity_pct",
) -> float:
    """Average the 12 monthly means of opening and closing figures required by Section 198."""
    import math

    if metric not in {"equity_pct", "fof_units_pct", "underlying_equity_pct"}:
        raise ValueError(f"Unsupported monthly portfolio-composition metric: {metric!r}")
    if fy_start.day != 1 or fy_start.month != 4 or fy_end != date(fy_start.year + 1, 3, 31):
        raise ValueError("Section 198 requires exact financial-year boundaries (1 April to 31 March)")
    expected_months = [date(fy_start.year + (3 + i) // 12, ((3 + i) % 12) + 1, 1) for i in range(12)]
    by_month = {}
    for snapshot in snapshots or []:
        if not isinstance(snapshot, MonthlyPortfolioSnapshot):
            raise TypeError("Section 198 requires MonthlyPortfolioSnapshot records")
        if snapshot.month in by_month:
            raise ValueError(f"Duplicate monthly portfolio snapshot for {snapshot.month}")
        by_month[snapshot.month] = snapshot
    if set(by_month) != set(expected_months):
        missing = sorted(set(expected_months) - set(by_month))
        unexpected = sorted(set(by_month) - set(expected_months))
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Section 198 monthly opening/closing observations must cover all 12 financial-year months.",
            missing_data=f"missing_months={missing}, unexpected_months={unexpected}",
            required_source="Verified monthly opening and closing portfolio-composition disclosures",
        )
    monthly_means = []
    for month in expected_months:
        record = by_month[month]
        opening = getattr(record, f"opening_{metric}")
        closing = getattr(record, f"closing_{metric}")
        values = []
        for label, raw in (("opening", opening), ("closing", closing)):
            if raw is None or isinstance(raw, bool):
                raise ValueError(f"Section 198 {metric} {label} value is required for {month}")
            value = float(raw)
            if not math.isfinite(value) or not 0.0 <= value <= 100.0:
                raise ValueError(f"Section 198 {metric} {label} value must be finite and between 0 and 100 for {month}")
            values.append(value)
        monthly_means.append((values[0] + values[1]) / 2.0)
    return sum(monthly_means) / 12.0


@dataclass(frozen=True)
class DailySnapshotCoverageEvidence:
    """Auditable expected-date coverage evidence for a statutory daily series."""
    expected_dates: Tuple[date, ...]
    source_url: str
    source_document_sha256: str
    reviewer_attested: bool


def validate_daily_snapshot_coverage(
    snapshots: List[DailyPortfolioSnapshot],
    fy_start: date,
    fy_end: date,
    evidence: Optional[DailySnapshotCoverageEvidence],
) -> None:
    """Require exact equality between observed dates and a provenance-backed expected-date calendar."""
    import re
    from core.models import InsufficientDataError

    if not isinstance(evidence, DailySnapshotCoverageEvidence):
        raise InsufficientDataError(
            "Section 76 requires explicit expected-date coverage evidence, not a caller-supplied boolean.",
            missing_data="DailySnapshotCoverageEvidence",
            required_source="Verified expected observation calendar with source URL and SHA-256",
        )
    if evidence.reviewer_attested is not True:
        raise InsufficientDataError(
            "Daily snapshot calendar evidence lacks an explicit reviewer attestation.",
            missing_data="reviewer attestation for daily coverage",
            required_source="Independently verified expected observation calendar",
        )
    if not isinstance(evidence.source_url, str) or not evidence.source_url.startswith("https://"):
        raise ValueError("Daily snapshot calendar source_url must be an HTTPS URL")
    if not isinstance(evidence.source_document_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", evidence.source_document_sha256):
        raise ValueError("Daily snapshot calendar source_document_sha256 must be a 64-character SHA-256 hex digest")
    expected = list(evidence.expected_dates)
    if not expected or any(not isinstance(d, date) for d in expected):
        raise ValueError("Expected snapshot dates must be a non-empty sequence of dates")
    if expected != sorted(set(expected)):
        raise ValueError("Expected snapshot dates must be sorted and unique")
    if any(d < fy_start or d > fy_end for d in expected):
        raise ValueError("Expected snapshot dates must all fall within the relevant financial year")
    observed = [s.date for s in snapshots if fy_start <= s.date <= fy_end]
    if len(observed) != len(set(observed)):
        raise ValueError("Observed daily portfolio snapshots contain duplicate dates")
    if set(observed) != set(expected):
        missing = sorted(set(expected) - set(observed))
        unexpected = sorted(set(observed) - set(expected))
        raise InsufficientDataError(
            "Section 76 daily snapshot dates do not exactly match the verified expected-date calendar.",
            missing_data=f"missing_dates={missing[:10]}, unexpected_dates={unexpected[:10]}",
            required_source="Complete daily closing portfolio series aligned to a source-documented, reviewer-attested expected-date calendar",
        )


def compute_annual_average_daily_closing(
    snapshots: List[DailyPortfolioSnapshot],
    fy_start: date,
    fy_end: date,
    metric: str = "equity_pct"
) -> Optional[float]:
    """
    Compute the arithmetic average of the supplied daily closing observations.

    This function validates the observations it receives, but does not itself
    prove that every required day is present. Statutory callers must separately
    establish and pass verified coverage before relying on the result.
    """
    allowed_metrics = {"equity_pct", "debt_pct", "money_market_pct", "fof_specified_mf_pct"}
    if metric not in allowed_metrics:
        raise ValueError(f"Unsupported portfolio-composition metric: {metric!r}")
    if fy_start > fy_end:
        raise ValueError("Financial-year start date must not be after its end date")
    if not snapshots:
        return None

    fy_snapshots = [s for s in snapshots if fy_start <= s.date <= fy_end]
    if not fy_snapshots:
        return None

    seen_dates = set()
    values = []
    for snapshot in fy_snapshots:
        if snapshot.date in seen_dates:
            raise ValueError(f"Duplicate daily portfolio snapshot for {snapshot.date}")
        seen_dates.add(snapshot.date)
        raw_value = getattr(snapshot, metric)
        if isinstance(raw_value, bool):
            raise ValueError(f"{metric} must be a finite percentage, not a boolean")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{metric} must be numeric for {snapshot.date}") from exc
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise ValueError(f"{metric} must be finite and between 0 and 100 for {snapshot.date}")
        values.append(value)

    return sum(values) / len(values)

def qualifies_as_equity_oriented_under_section_198(
    equity_pct: float,
    calculation_method: str = "annual_average_monthly_opening_closing",
    monthly_snapshots: Optional[List[MonthlyPortfolioSnapshot]] = None,
    monthly_coverage_evidence: Optional[MonthlySnapshotCoverageEvidence] = None,
    fof_underlying_traded_on_recognised_exchange: Optional[bool] = None,
    fy_start: Optional[date] = None,
    fy_end: Optional[date] = None,
    is_fund_of_funds: bool = False,
) -> ClassificationResult:
    """
    Section 198(8): equity-oriented fund qualification.

    Direct fund: at least 65% in domestic listed equity.
    Qualifying fund-of-funds: at least 90% in units of another qualifying
    exchange-traded fund, whose own allocation is at least 90% domestic equity.
    Both tests use the annual average of monthly averages of opening and closing
    figures. A point-in-time percentage is not a statutory substitute.
    """
    from core.models import InsufficientDataError

    if not monthly_snapshots or fy_start is None or fy_end is None:
        raise InsufficientDataError(
            "Section 198 classification requires 12 monthly opening/closing observations for the relevant financial year.",
            missing_data="monthly opening and closing portfolio-composition snapshots",
            required_source="Verified monthly portfolio disclosures for all 12 financial-year months",
        )

    validate_monthly_snapshot_coverage(monthly_snapshots, fy_start, fy_end, monthly_coverage_evidence)

    if is_fund_of_funds:
        if not isinstance(fof_underlying_traded_on_recognised_exchange, bool):
            raise InsufficientDataError(
                "Section 198 fund-of-funds classification requires verified evidence whether the underlying fund is exchange-traded.",
                missing_data="fof_underlying_traded_on_recognised_exchange",
                required_source="Verified exchange-listing status of the underlying fund",
            )
        if not fof_underlying_traded_on_recognised_exchange:
            return ClassificationResult(
                qualifies=False,
                provision="Section 198(8)",
                effective_date=fy_end,
                threshold=65.0,
                calculation_method="not_qualifying_non_exchange_traded_fof",
                source_data_status="PROVISIONAL_STRUCTURE_REVIEW",
                reason="The 90%/90% fund-of-funds limb requires the underlying fund to be traded on a recognised stock exchange",
                equity_pct=0.0,
                is_fund_of_funds=True,
            )
        fund_units_pct = compute_annual_average_monthly_opening_closing(
            monthly_snapshots, fy_start, fy_end, "fof_units_pct"
        )
        underlying_equity_pct = compute_annual_average_monthly_opening_closing(
            monthly_snapshots, fy_start, fy_end, "underlying_equity_pct"
        )
        qualifies = fund_units_pct >= 90.0 and underlying_equity_pct >= 90.0
        effective_pct = underlying_equity_pct
        threshold = 90.0
        method = "annual_average_monthly_opening_closing_fof_90_90"
        reason = (
            f"FoF allocation to qualifying exchange-traded fund units is {fund_units_pct:.2f}% "
            f"and underlying domestic equity is {underlying_equity_pct:.2f}%; both must be >= 90%"
        )
    else:
        effective_pct = compute_annual_average_monthly_opening_closing(
            monthly_snapshots, fy_start, fy_end, "equity_pct"
        )
        qualifies = effective_pct >= 65.0
        threshold = 65.0
        method = "annual_average_monthly_opening_closing"
        reason = f"Annual-average monthly opening/closing domestic equity is {effective_pct:.2f}% {'meets' if qualifies else 'below'} 65%"

    return ClassificationResult(
        qualifies=qualifies,
        provision="Section 198(8)",
        effective_date=fy_end,
        threshold=threshold,
        calculation_method=method,
        source_data_status="PROVISIONAL_MONTHLY_COVERAGE_RECONCILED",
        reason=reason,
        equity_pct=effective_pct,
    )



def qualifies_as_specified_mutual_fund_under_section_50AA(
    equity_pct: float,
    debt_and_money_market_pct: float,
    is_fund_of_funds: bool,
    fof_debt_investing_pct: float | None,
    acquisition_date: date | None,
    transfer_date: date,
    snapshots: list | None = None,
    fy_start: date | None = None,
    fy_end: date | None = None,
    is_mld: bool = False,
    snapshot_coverage_evidence: Optional[DailySnapshotCoverageEvidence] = None,
) -> ClassificationResult:
    """
    Section 50AA (Income-tax Act, 1961), applicable to transfers from
    1 April 2024 through 31 March 2026.

    For ordinary mutual-fund units, the original definition uses the
    not-more-than-35% domestic-equity test for units acquired on/after
    1 April 2023. Market-linked debentures are separately included,
    irrespective of their acquisition date. The amended debt/MM and
    fund-of-funds definition takes effect only from 1 April 2026 under
    the successor Section 76 regime.
    """
    effective_from = date(2024, 4, 1)
    successor_from = date(2026, 4, 1)

    if transfer_date < effective_from:
        return ClassificationResult(
            qualifies=False,
            provision="Section 50AA (Not Applicable)",
            effective_date=transfer_date,
            threshold=35.0,
            calculation_method="N/A",
            source_data_status="complete",
            reason="Section 50AA applies to transfers on or after 1 April 2024",
            equity_pct=equity_pct,
            debt_and_money_market_pct=debt_and_money_market_pct,
            acquisition_date=acquisition_date,
            transfer_date=transfer_date,
            is_fund_of_funds=is_fund_of_funds,
            fof_debt_investing_pct=fof_debt_investing_pct,
            is_mld=is_mld,
        )

    if transfer_date >= successor_from:
        return ClassificationResult(
            qualifies=False,
            provision="Section 50AA (Not Applicable - Section 76 governs)",
            effective_date=transfer_date,
            threshold=0.0,
            calculation_method="N/A",
            source_data_status="complete",
            reason="Transfers on or after 1 April 2026 are governed by Section 76 of the Income-tax Act, 2025",
            equity_pct=equity_pct,
            debt_and_money_market_pct=debt_and_money_market_pct,
            acquisition_date=acquisition_date,
            transfer_date=transfer_date,
            is_fund_of_funds=is_fund_of_funds,
            fof_debt_investing_pct=fof_debt_investing_pct,
            is_mld=is_mld,
        )

    if is_mld:
        return ClassificationResult(
            qualifies=True,
            provision="Section 50AA (Market-Linked Debenture)",
            effective_date=transfer_date,
            threshold=0.0,
            calculation_method="statutory_inclusion",
            source_data_status="complete",
            reason="Market-linked debentures are included independently of the mutual-fund unit acquisition-date test",
            equity_pct=equity_pct,
            debt_and_money_market_pct=debt_and_money_market_pct,
            acquisition_date=acquisition_date,
            transfer_date=transfer_date,
            is_fund_of_funds=False,
            fof_debt_investing_pct=fof_debt_investing_pct,
            is_mld=True,
        )

    if acquisition_date is None:
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Section 50AA classification requires the unit acquisition date.",
            missing_data="acquisition_date",
            required_source="CAS transaction ledger or verified registrar transaction statement",
        )

    if acquisition_date < date(2023, 4, 1):
        return ClassificationResult(
            qualifies=False,
            provision="Section 48 (Grandfathered)",
            effective_date=transfer_date,
            threshold=0.0,
            calculation_method="N/A",
            source_data_status="complete",
            reason=f"Units acquired {acquisition_date} before 1 April 2023 are outside Section 50AA unit scope",
            equity_pct=equity_pct,
            debt_and_money_market_pct=debt_and_money_market_pct,
            acquisition_date=acquisition_date,
            transfer_date=transfer_date,
            is_fund_of_funds=is_fund_of_funds,
            fof_debt_investing_pct=fof_debt_investing_pct,
            is_mld=False,
        )

    if not (snapshots and fy_start and fy_end):
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Original Section 50AA classification requires annual-average daily closing equity observations.",
            missing_data="daily domestic-equity portfolio-composition snapshots and financial-year boundaries",
            required_source="Verified daily closing portfolio disclosures and complete expected-date coverage",
        )
    if fy_start != date(transfer_date.year if transfer_date.month >= 4 else transfer_date.year - 1, 4, 1):
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Section 50AA snapshots must cover the financial year in which the transfer occurs.",
            missing_data="financial-year-aligned daily snapshots",
            required_source="Verified daily closing portfolio-composition series",
        )
    expected_fy_end = date(fy_start.year + 1, 3, 31)
    if fy_end != expected_fy_end:
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Section 50AA snapshots must end on 31 March of the transfer financial year.",
            missing_data="complete financial-year daily snapshots",
            required_source="Verified daily closing portfolio-composition series",
        )
    validate_daily_snapshot_coverage(snapshots, fy_start, fy_end, snapshot_coverage_evidence)
    annual_average_equity = compute_annual_average_daily_closing(
        snapshots, fy_start, fy_end, "equity_pct"
    )
    if annual_average_equity is None:
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Section 50AA annual-average daily closing equity could not be computed.",
            missing_data="valid daily domestic-equity observations",
            required_source="Verified daily closing portfolio-composition series",
        )
    effective_equity = annual_average_equity

    qualifies = effective_equity <= 35.0
    return ClassificationResult(
        qualifies=qualifies,
        provision="Section 50AA",
        effective_date=transfer_date,
        threshold=35.0,
        calculation_method="annual_average_daily_closing_domestic_equity",
        source_data_status="PROVISIONAL_DAILY_COVERAGE_RECONCILED",
        reason=(
            f"Annual-average daily closing domestic equity {effective_equity:.2f}% "
            f"{'<= 35% (specified mutual fund)' if qualifies else '> 35% (not specified)'} "
            "under the original Section 50AA definition applicable through 31 March 2026"
        ),
        equity_pct=effective_equity,
        debt_and_money_market_pct=debt_and_money_market_pct,
        acquisition_date=acquisition_date,
        transfer_date=transfer_date,
        is_fund_of_funds=is_fund_of_funds,
        fof_debt_investing_pct=fof_debt_investing_pct,
        is_mld=False,
    )

def compute_multi_horizon_fiduciary_score(
    c: Dict[str, Any],
    category_key: str,
    portfolio_overlap_pct: Optional[float] = None,
    *,
    scoring_weights: Any,
) -> float:
    """
    Standardized 6-Pillar Fiduciary Normalized Scoring Engine (0 - 100 Scale):
    Uses Category-Relative Min-Max Normalization with regulatory anchor clamping.
    Caps momentum at 25% of total score, preventing short-term return hijacking.
    Incorporates actual candidate-to-portfolio weighted stock look-through overlap.
    Issue #25: Prohibits scoring candidates before mandatory eligibility gates pass.
    """
    # Issue #25: Mandatory eligibility gates must pass before scoring (strictly fail-closed)
    elig_status = c.get("eligibility_status")
    is_eligible = c.get("is_eligible")
    if elig_status not in ("PASS", "ELIGIBLE", "PASSED"):
        raise ValueError(f"Candidate '{c.get('fund_id', 'unknown')}' has invalid, missing, or unvetted eligibility status ({elig_status!r}); scoring before positive eligibility is prohibited.")
    if is_eligible is not True:
        raise ValueError(f"Candidate '{c.get('fund_id', 'unknown')}' does not have verified positive eligibility (is_eligible={is_eligible!r}); scoring before eligibility is prohibited.")
    from core.candidate_scoring import calculate_candidate_6_pillar_score
    score, _ = calculate_candidate_6_pillar_score(
        c, category_key, portfolio_overlap_pct, weights=scoring_weights
    )
    return score


def qualifies_as_specified_mutual_fund_under_section_76(
    debt_and_money_market_pct: float,
    is_fund_of_funds: bool,
    fof_debt_investing_pct: Optional[float],
    acquisition_date: Optional[date],
    transfer_date: date,
    is_mld: bool = False,
    snapshots: Optional[List[DailyPortfolioSnapshot]] = None,
    fy_start: Optional[date] = None,
    fy_end: Optional[date] = None,
    snapshot_coverage_evidence: Optional[DailySnapshotCoverageEvidence] = None,
) -> ClassificationResult:
    """
    Section 76 (Income-tax Act, 2025), applicable from 1 April 2026.

    MLDs are independently included. For mutual-fund units acquired on/after
    1 April 2023, the statutory test is >65% of total proceeds invested in
    debt and money-market instruments, or (for a fund of funds) >=65% in
    units of such specified mutual funds. The portfolio-composition limb
    uses annual-average daily closing figures; a point-in-time percentage
    is not an acceptable substitute.
    """
    if transfer_date < date(2026, 4, 1):
        return ClassificationResult(
            qualifies=False,
            provision="Section 76 (Not Applicable)",
            effective_date=transfer_date,
            threshold=65.0,
            calculation_method="N/A",
            source_data_status="complete",
            reason=f"Transfer date {transfer_date} is before Section 76 commencement on 1 April 2026",
            debt_and_money_market_pct=debt_and_money_market_pct,
            acquisition_date=acquisition_date,
            transfer_date=transfer_date,
            is_fund_of_funds=is_fund_of_funds,
            fof_debt_investing_pct=fof_debt_investing_pct,
            is_mld=is_mld,
        )

    if is_mld:
        return ClassificationResult(
            qualifies=True,
            provision="Section 76 (Market-Linked Debenture)",
            effective_date=transfer_date,
            threshold=0.0,
            calculation_method="statutory_inclusion",
            source_data_status="complete",
            reason="Market-linked debentures are included independently of the mutual-fund unit acquisition-date test",
            debt_and_money_market_pct=debt_and_money_market_pct,
            acquisition_date=acquisition_date,
            transfer_date=transfer_date,
            is_fund_of_funds=False,
            fof_debt_investing_pct=fof_debt_investing_pct,
            is_mld=True,
        )

    if acquisition_date is None:
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Section 76 classification requires the mutual-fund unit acquisition date.",
            missing_data="acquisition_date",
            required_source="CAS transaction ledger or verified registrar transaction statement",
        )

    if acquisition_date < date(2023, 4, 1):
        return ClassificationResult(
            qualifies=False,
            provision="Section 48 (Grandfathered)",
            effective_date=transfer_date,
            threshold=0.0,
            calculation_method="N/A",
            source_data_status="complete",
            reason=f"Units acquired {acquisition_date} before 1 April 2023 are outside Section 76 unit scope",
            debt_and_money_market_pct=debt_and_money_market_pct,
            acquisition_date=acquisition_date,
            transfer_date=transfer_date,
            is_fund_of_funds=is_fund_of_funds,
            fof_debt_investing_pct=fof_debt_investing_pct,
            is_mld=False,
        )

    if is_fund_of_funds:
        if not (snapshots and fy_start and fy_end):
            from core.models import InsufficientDataError
            raise InsufficientDataError(
                "Section 76 fund-of-funds classification requires annual-average daily closing allocation observations.",
                missing_data="daily fof_specified_mf_pct observations and financial-year boundaries",
                required_source="Verified daily closing fund-of-funds allocation disclosures",
            )
        financial_year_start = date(transfer_date.year if transfer_date.month >= 4 else transfer_date.year - 1, 4, 1)
        financial_year_end = date(financial_year_start.year + 1, 3, 31)
        if fy_start != financial_year_start or fy_end != financial_year_end:
            from core.models import InsufficientDataError
            raise InsufficientDataError(
                "Section 76 FoF snapshots must cover the financial year in which the transfer occurs.",
                missing_data=f"expected {financial_year_start} through {financial_year_end}",
                required_source="Verified financial-year daily closing FoF allocation series",
            )
        validate_daily_snapshot_coverage(snapshots, fy_start, fy_end, snapshot_coverage_evidence)
        fof_pct = compute_annual_average_daily_closing(
            snapshots, fy_start, fy_end, "fof_specified_mf_pct"
        )
        if fof_pct is None:
            from core.models import InsufficientDataError
            raise InsufficientDataError(
                "Section 76 FoF annual-average daily closing allocation could not be computed.",
                missing_data="daily allocation to units of specified mutual funds",
                required_source="Verified daily closing fund-of-funds allocation disclosures",
            )
        qualifies = fof_pct >= 65.0
        return ClassificationResult(
            qualifies=qualifies,
            provision="Section 76",
            effective_date=transfer_date,
            threshold=65.0,
            calculation_method="annual_average_daily_closing_fof_allocation",
            source_data_status="PROVISIONAL_DAILY_COVERAGE_RECONCILED",
            reason=f"Annual-average daily closing FoF allocation to specified mutual funds is {fof_pct:.2f}% {'>= 65%' if qualifies else '< 65%'}",
            debt_and_money_market_pct=debt_and_money_market_pct,
            acquisition_date=acquisition_date,
            transfer_date=transfer_date,
            is_fund_of_funds=True,
            fof_debt_investing_pct=fof_pct,
            is_mld=False,
        )

    if not (snapshots and fy_start and fy_end):
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Section 76 requires annual-average daily closing portfolio-composition snapshots; point-in-time debt percentages are not sufficient.",
            missing_data="daily portfolio-composition snapshots and financial-year boundaries",
            required_source="Verified daily closing portfolio disclosures with documented coverage for the transfer financial year",
        )

    financial_year_start = date(transfer_date.year if transfer_date.month >= 4 else transfer_date.year - 1, 4, 1)
    financial_year_end = date(financial_year_start.year + 1, 3, 31)
    if fy_start != financial_year_start or fy_end != financial_year_end:
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Section 76 snapshots must cover the financial year in which the transfer occurs.",
            missing_data=f"expected {financial_year_start} through {financial_year_end}",
            required_source="Verified financial-year daily closing portfolio-composition series",
        )
    validate_daily_snapshot_coverage(snapshots, fy_start, fy_end, snapshot_coverage_evidence)

    avg_debt = compute_annual_average_daily_closing(snapshots, fy_start, fy_end, "debt_pct")
    avg_mm = compute_annual_average_daily_closing(snapshots, fy_start, fy_end, "money_market_pct")
    if avg_debt is None or avg_mm is None:
        from core.models import InsufficientDataError
        raise InsufficientDataError(
            "Section 76 annual-average daily closing percentages could not be computed from the supplied snapshots.",
            missing_data="valid daily debt and money-market percentages",
            required_source="Verified daily closing portfolio-composition series",
        )
    effective_debt = avg_debt + avg_mm
    qualifies = effective_debt > 65.0
    return ClassificationResult(
        qualifies=qualifies,
        provision="Section 76",
        effective_date=transfer_date,
        threshold=65.0,
        calculation_method="annual_average_daily_closing",
        source_data_status="PROVISIONAL_DAILY_COVERAGE_RECONCILED",
        reason=(
            f"Annual-average daily closing debt plus money-market allocation is {effective_debt:.2f}% "
            f"{'> 65%' if qualifies else '<= 65%'} under Section 76"
        ),
        debt_and_money_market_pct=effective_debt,
        acquisition_date=acquisition_date,
        transfer_date=transfer_date,
        is_fund_of_funds=False,
        fof_debt_investing_pct=fof_debt_investing_pct,
        is_mld=False,
    )


def classify_specified_mutual_fund(
    asset_class: str,
    equity_pct: float,
    debt_and_money_market_pct: Optional[float] = None,
    is_fund_of_funds: bool = False,
    fof_debt_investing_pct: Optional[float] = None,
    acquisition_date: Optional[date] = None,
    transfer_date: Optional[date] = None,
    as_of: Optional[date] = None,
    snapshots: Optional[List[DailyPortfolioSnapshot]] = None,
    monthly_snapshots: Optional[List[MonthlyPortfolioSnapshot]] = None,
    monthly_coverage_evidence: Optional[MonthlySnapshotCoverageEvidence] = None,
    fof_underlying_traded_on_recognised_exchange: Optional[bool] = None,
    fy_start: Optional[date] = None,
    fy_end: Optional[date] = None,
    is_mld: bool = False,
    snapshot_coverage_evidence: Optional[DailySnapshotCoverageEvidence] = None,
    # Aliases for backward-compatibility
    purchase_date: Optional[date] = None,
) -> dict:
    # Handle backward-compatible aliases
    if purchase_date is not None and acquisition_date is None:
        acquisition_date = purchase_date
    if debt_and_money_market_pct is None:
        debt_and_money_market_pct = 0.0
    if transfer_date is None:
        transfer_date = as_of if as_of is not None else date.today()
    if as_of is None:
        as_of = date.today()

    if not is_mld:
        expected_fy_start = date(transfer_date.year if transfer_date.month >= 4 else transfer_date.year - 1, 4, 1)
        expected_fy_end = date(expected_fy_start.year + 1, 3, 31)
        if fy_start != expected_fy_start or fy_end != expected_fy_end:
            from core.models import InsufficientDataError
            raise InsufficientDataError(
                "Tax classification observations must cover the financial year of the transfer.",
                missing_data=f"expected financial year {expected_fy_start} through {expected_fy_end}",
                required_source="Verified monthly and daily portfolio-composition series for the transfer financial year",
            )

    if is_mld:
        equity_result = ClassificationResult(
            qualifies=False,
            provision="Market-Linked Debenture (not an equity-oriented fund)",
            effective_date=transfer_date,
            threshold=65.0,
            calculation_method="not_applicable",
            source_data_status="not_applicable",
            reason="Market-linked debenture is classified under its separate statutory inclusion, not as an equity-oriented mutual fund",
            is_mld=True,
        )
    else:
        equity_result = qualifies_as_equity_oriented_under_section_198(
            equity_pct=equity_pct,
            monthly_snapshots=monthly_snapshots,
            fy_start=fy_start,
            fy_end=fy_end,
            is_fund_of_funds=is_fund_of_funds,
            monthly_coverage_evidence=monthly_coverage_evidence,
            fof_underlying_traded_on_recognised_exchange=fof_underlying_traded_on_recognised_exchange,
        )

    section_50aa_result = qualifies_as_specified_mutual_fund_under_section_50AA(
        equity_pct=equity_pct,
        debt_and_money_market_pct=debt_and_money_market_pct,
        is_fund_of_funds=is_fund_of_funds,
        fof_debt_investing_pct=fof_debt_investing_pct,
        acquisition_date=acquisition_date,
        transfer_date=transfer_date,
        snapshots=snapshots,
        fy_start=fy_start,
        fy_end=fy_end,
        is_mld=is_mld,
        snapshot_coverage_evidence=snapshot_coverage_evidence,
    )

    section_76_result = qualifies_as_specified_mutual_fund_under_section_76(
        debt_and_money_market_pct=debt_and_money_market_pct,
        is_fund_of_funds=is_fund_of_funds,
        fof_debt_investing_pct=fof_debt_investing_pct,
        acquisition_date=acquisition_date,
        transfer_date=transfer_date,
        is_mld=is_mld,
        snapshots=snapshots,
        fy_start=fy_start,
        fy_end=fy_end,
        snapshot_coverage_evidence=snapshot_coverage_evidence,
    )

    is_equity_oriented = equity_result.qualifies
    is_specified_50aa = section_50aa_result.qualifies
    is_specified_76 = section_76_result.qualifies

    if is_specified_50aa:
        overall_classification = "SPECIFIED_MUTUAL_FUND_OR_MLD"
        tax_treatment = "SECTION_50AA_DEEMED_STCG"
    elif is_specified_76:
        overall_classification = "SPECIFIED_MUTUAL_FUND_OR_MLD"
        tax_treatment = "SECTION_76_DEEMED_STCG"
    elif is_equity_oriented:
        overall_classification = "EQUITY_ORIENTED"
        tax_treatment = "EQUITY_ORIENTED_CONCESSIONAL"
    else:
        overall_classification = "HYBRID_OR_DEBT_NON_SPECIFIED"
        tax_treatment = "HYBRID_UNLISTED_OR_NORMAL"

    return {
        "overall_classification": overall_classification,
        "tax_treatment": tax_treatment,
        "equity_oriented": {
            "qualifies": equity_result.qualifies,
            "provision": equity_result.provision,
            "threshold": equity_result.threshold,
            "effective_equity_pct": equity_result.equity_pct,
            "calculation_method": equity_result.calculation_method,
            "source_data_status": equity_result.source_data_status,
            "reason": equity_result.reason
        },
        "specified_50AA": {
            "qualifies": section_50aa_result.qualifies,
            "provision": section_50aa_result.provision,
            "threshold": section_50aa_result.threshold,
            "effective_equity_pct": section_50aa_result.equity_pct,
            "effective_debt_pct": section_50aa_result.debt_and_money_market_pct,
            "calculation_method": section_50aa_result.calculation_method,
            "source_data_status": section_50aa_result.source_data_status,
            "reason": section_50aa_result.reason
        },
        "specified_76": {
            "qualifies": section_76_result.qualifies,
            "provision": section_76_result.provision,
            "threshold": section_76_result.threshold,
            "effective_debt_pct": section_76_result.debt_and_money_market_pct,
            "calculation_method": section_76_result.calculation_method,
            "source_data_status": section_76_result.source_data_status,
            "reason": section_76_result.reason,
            "is_mld": section_76_result.is_mld
        },
        "overall_classification": overall_classification,
        "tax_treatment": tax_treatment,
        "equity_pct": equity_pct,
        "debt_and_money_market_pct": debt_and_money_market_pct,
        "is_fund_of_funds": is_fund_of_funds,
        "fof_debt_investing_pct": fof_debt_investing_pct,
        "acquisition_date": acquisition_date.isoformat() if acquisition_date else None,
        "transfer_date": transfer_date.isoformat(),
        "is_mld": is_mld,
        "source_data_status": "complete" if snapshots else "partial",
        "calculation_method": "annual_average_daily" if snapshots else "annual_average_monthly",
        # ---- Flat key aliases for backward compatibility and test assertions ----
        "is_equity_oriented": is_equity_oriented,
        "is_specified_mutual_fund": is_specified_50aa or is_specified_76,
        "governing_statute": (
            "Section 48 (Grandfathered - pre April 2023 acquisition)"
            if (not is_mld and acquisition_date is not None and acquisition_date < date(2023, 4, 1))
            else (
                "Section 76 (Income-tax Act 2025)"
                if is_specified_76
                else (
                    "Section 50AA (Income-tax Act 1961)"
                    if is_specified_50aa
                    else (
                        "Section 198 / Section 197 (Income-tax Act 2025) - Equity Oriented"
                        if is_equity_oriented
                        else "Not specified fund"
                    )
                )
            )
        ),
    }

def select_autonomous_blueprint_funds(
    holdings: Optional[List[HoldingItem]] = None,
    candidate_universe: Optional[List[Dict[str, Any]]] = None,
    client_risk_tier: Any = 6,
    thematic_deficit_theme: str = "",
    thematic_satellite_authorized: bool = False,
    thematic_satellite_pct_of_equity: float = 0.0,
    portfolio_disclosures_by_scheme_id: Optional[Dict[str, Dict[str, Any]]] = None,
    portfolio_disclosure_source_bytes_by_scheme_id: Optional[Dict[str, bytes]] = None,
    disclosure_as_of_date: Optional[date] = None,
    disclosure_max_age_days: int = 45,
    custom_saa_target: Optional[Any] = None,
    risk_ceiling: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Select candidates only from the supplied, source-backed universe.

    Every selected candidate must:
      - have a stable fund identifier and name;
      - be explicitly marked as a Direct plan;
      - pass every eligibility gate;
      - be scored only after it passes those gates.

    No AUM/riskometer exception, passive shortcut, inferred folio or hardcoded
    scheme fallback is permitted. A missing qualifying candidate returns an
    explicit NO_ACTION slot with its full target shown as unallocated.
    """
    from core.eligibility import (
        check_eligibility_gates,
        load_candidate_universe,
        _reviewed_direct_plan_evidence_status,
    )
    from core.fund_classifier import classify_fund_category, detect_fund_theme

    import json
    import math
    import os
    from pathlib import Path

    if hasattr(client_risk_tier, "value"):
        tier_map = {"Conservative": 2, "Moderate": 4, "Aggressive": 6}
        risk_label = str(client_risk_tier.value)
        if risk_label == "Custom":
            if custom_saa_target is None:
                raise ValueError(
                    "Custom risk profile requires an explicitly approved custom SAA; "
                    "it must not inherit the Aggressive/SEBI Tier 6 allocation."
                )
            tier_int = 0
        else:
            tier_int = tier_map.get(risk_label)
            if tier_int is None:
                raise ValueError(f"Unsupported investor risk profile: {risk_label!r}")
    elif str(client_risk_tier).strip() == "Custom":
        if custom_saa_target is None:
            raise ValueError(
                "Custom risk profile requires an explicitly approved custom SAA; "
                "it must not inherit the Aggressive/SEBI Tier 6 allocation."
            )
        tier_int = 0
    elif isinstance(client_risk_tier, bool):
        raise ValueError("client_risk_tier must be an integer from 1 through 6")
    else:
        try:
            tier_int = int(client_risk_tier)
        except (TypeError, ValueError) as exc:
            raise ValueError("client_risk_tier must be an integer from 1 through 6") from exc
        if tier_int not in range(1, 7) and not (tier_int == 0 and custom_saa_target is not None):
            raise ValueError("client_risk_tier must be an integer from 1 through 6")

    effective_risk_ceiling = risk_ceiling
    if effective_risk_ceiling is None and custom_saa_target is not None:
        effective_risk_ceiling = getattr(custom_saa_target, "risk_ceiling", None)

    if not isinstance(thematic_satellite_authorized, bool):
        raise ValueError("thematic_satellite_authorized must be a boolean")
    try:
        satellite_pct = float(thematic_satellite_pct_of_equity)
    except (TypeError, ValueError) as exc:
        raise ValueError("thematic_satellite_pct_of_equity must be numeric") from exc
    if not math.isfinite(satellite_pct) or not 0.0 <= satellite_pct <= 100.0:
        raise ValueError("thematic satellite percentage must be finite and between 0 and 100")
    if satellite_pct > 0.0 and not thematic_satellite_authorized:
        raise ValueError("A positive thematic satellite allocation requires explicit IPS authorization")
    if not thematic_satellite_authorized:
        satellite_pct = 0.0

    if candidate_universe is None:
        client_data_dir = os.environ.get("MF_CLIENT_DATA_DIR")
        if client_data_dir:
            client_root = Path(client_data_dir).expanduser().resolve()
            repository_root = Path(__file__).resolve().parents[1]
            try:
                client_root.relative_to(repository_root)
            except ValueError:
                pass
            else:
                raise ValueError("MF_CLIENT_DATA_DIR must be outside the Git repository")
            metrics_path = client_root / "fund_metrics.json"
            if not metrics_path.is_file():
                raise FileNotFoundError(f"MF_CLIENT_DATA_DIR is set but fund_metrics.json is missing: {metrics_path}")
            candidate_universe = load_candidate_universe(metrics_path)
        else:
            candidate_universe = []
    if not isinstance(candidate_universe, list):
        raise TypeError("candidate_universe must be a list of candidate records")

    if portfolio_disclosures_by_scheme_id is not None:
        from ingestion.portfolio_disclosure import validate_portfolio_disclosure
        source_map = portfolio_disclosure_source_bytes_by_scheme_id or {}
        enriched_candidates = []
        for candidate in candidate_universe:
            if not isinstance(candidate, dict):
                enriched_candidates.append(candidate)
                continue
            scheme_id = candidate.get("scheme_id")
            disclosure = portfolio_disclosures_by_scheme_id.get(scheme_id) if scheme_id else None
            source_bytes = source_map.get(scheme_id) if scheme_id else None
            if disclosure is None or source_bytes is None or disclosure_as_of_date is None:
                result = {"constituent_weights": None,
                          "constituent_weights_coverage_pct": None,
                          "status": "MISSING",
                          "reason": "No exact-ID disclosure and source evidence available at SIP decision time."}
            else:
                result = validate_portfolio_disclosure(
                    disclosure, source_bytes,
                    as_of=disclosure_as_of_date,
                    max_age_days=disclosure_max_age_days,
                )
                if result.get("scheme_id") != scheme_id:
                    result = {"constituent_weights": None,
                              "constituent_weights_coverage_pct": None,
                              "status": "CONFLICTING",
                              "reason": "Disclosure scheme identifier does not match candidate."}
            enriched = dict(candidate)
            enriched.update({
                "constituent_weights": result.get("constituent_weights"),
                "constituent_weights_coverage_pct": result.get("constituent_weights_coverage_pct"),
                "lookthrough_status": result["status"],
                "lookthrough_reason": result["reason"],
            })
            enriched_candidates.append(enriched)
        candidate_universe = enriched_candidates

    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    if not policy_path.is_file():
        raise FileNotFoundError(f"Required allocation policy is missing: {policy_path}")
    try:
        allocation_policy = json.loads(policy_path.read_text(encoding="utf-8"))
        profile_keys = {
            1: "low", 2: "low_to_moderate", 3: "moderate",
            4: "moderately_high", 5: "high", 6: "very_high",
        }
        if tier_int == 0 or custom_saa_target is not None:
            from core.models import AssetAllocationTarget
            if not isinstance(custom_saa_target, AssetAllocationTarget):
                raise ValueError("custom_saa_target must be a validated AssetAllocationTarget instance")
            equity_total = float(custom_saa_target.equity_pct)
            debt_target_pct = float(custom_saa_target.debt_pct)
            if custom_saa_target.large_cap_pct is not None:
                equity_parts = {
                    "flexi": float(custom_saa_target.flexi_cap_pct),
                    "mid": float(custom_saa_target.mid_cap_pct),
                    "small": float(custom_saa_target.small_cap_pct),
                    "large": float(custom_saa_target.large_cap_pct),
                }
            elif equity_total > 0:
                custom_policy = allocation_policy.get("custom_saa_policy", {})
                dist = custom_policy.get("default_equity_distribution_pct", {
                    "large_cap_pct": 35.0, "flexi_multi_cap_pct": 25.0, "mid_cap_pct": 20.0, "small_cap_pct": 20.0,
                })
                scale = equity_total / 100.0
                equity_parts = {
                    "large": round(float(dist.get("large_cap_pct", 35.0)) * scale, 2),
                    "flexi": round(float(dist.get("flexi_multi_cap_pct", 25.0)) * scale, 2),
                    "mid": round(float(dist.get("mid_cap_pct", 20.0)) * scale, 2),
                    "small": round(float(dist.get("small_cap_pct", 20.0)) * scale, 2),
                }
                diff = equity_total - sum(equity_parts.values())
                equity_parts["large"] = round(equity_parts["large"] + diff, 2)
            else:
                equity_parts = {"large": 0.0, "flexi": 0.0, "mid": 0.0, "small": 0.0}
        else:
            profile = allocation_policy["behavioral_risk_profiles"][profile_keys[tier_int]]
            saa = profile["saa_targets"]
            equity_parts = {
                "flexi": float(saa["flexi_multi_cap_pct"]),
                "mid": float(saa["mid_cap_pct"]),
                "small": float(saa["small_cap_pct"]),
                "large": float(saa["large_cap_pct"]),
            }
            equity_total = sum(equity_parts.values())
            debt_target_pct = float(saa["debt_liquid_pct"])
        satellite_policy = allocation_policy["thematic_satellite_policy"]
        satellite_cap = float(satellite_policy["max_pct_of_equity"])
        universe_policy = allocation_policy["fund_universe_requirements"]
        raw_minimum_universe = universe_policy["min_candidate_universe_size"]
        if isinstance(raw_minimum_universe, bool):
            raise ValueError("min_candidate_universe_size must be a positive integer")
        minimum_candidate_universe = int(raw_minimum_universe)
        if minimum_candidate_universe < 1 or float(raw_minimum_universe) != minimum_candidate_universe:
            raise ValueError("min_candidate_universe_size must be a positive integer")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid allocation policy for risk tier {tier_int}") from exc
    if any(not math.isfinite(v) or v < 0.0 for v in equity_parts.values()):
        raise ValueError("SAA equity sleeve weights must be finite and non-negative")
    if not math.isfinite(debt_target_pct) or debt_target_pct < 0.0:
        raise ValueError("SAA debt target must be finite and non-negative")
    if abs(equity_total + debt_target_pct - 100.0) > 0.01:
        raise ValueError("SAA equity and debt targets must sum to 100%")
    if satellite_pct > satellite_cap:
        raise ValueError(f"Thematic satellite percentage exceeds the central policy cap of {satellite_cap:g}%")
    if satellite_policy.get("enabled_by_default") is not False:
        raise ValueError("Thematic satellite must remain disabled by default in central policy")
    if satellite_pct > 0.0 and satellite_policy.get("requires_explicit_ips_authorization") is not True:
        raise ValueError("Central policy does not authorize a thematic satellite override")

    core_budget_pct = 100.0 - satellite_pct
    slot_targets = {
        "Slot 1: Core Flexi-Cap Compounder": round(core_budget_pct * equity_parts["flexi"] / equity_total, 1) if equity_total else 0.0,
        "Slot 2: Mid-Cap Alpha Engine": round(core_budget_pct * equity_parts["mid"] / equity_total, 1) if equity_total else 0.0,
        "Slot 3: Small-Cap Growth Engine": round(core_budget_pct * equity_parts["small"] / equity_total, 1) if equity_total else 0.0,
        "Slot 4: Large-Cap Bluechip Anchor": 0.0,
    }
    slot_targets["Slot 4: Large-Cap Bluechip Anchor"] = round(
        core_budget_pct
        - slot_targets["Slot 1: Core Flexi-Cap Compounder"]
        - slot_targets["Slot 2: Mid-Cap Alpha Engine"]
        - slot_targets["Slot 3: Small-Cap Growth Engine"],
        1,
    )

    # Validate candidate identity before evaluating. Ambiguous IDs must not
    # silently overwrite one another in the selected-candidate audit trail.
    normalized_candidates = []
    seen_ids = set()
    for row_index, candidate in enumerate(candidate_universe):
        if not isinstance(candidate, dict):
            raise ValueError(f"Candidate row {row_index} must be an object")
        fund_id = candidate.get("fund_id") or candidate.get("id")
        fund_name = candidate.get("fund_name") or candidate.get("name") or candidate.get("scheme_name")
        if not isinstance(fund_id, str) or not fund_id.strip():
            raise ValueError(f"Candidate row {row_index} is missing a stable fund_id")
        if fund_id in seen_ids:
            raise ValueError(f"Duplicate candidate fund_id: {fund_id!r}")
        if not isinstance(fund_name, str) or not fund_name.strip():
            raise ValueError(f"Candidate {fund_id!r} is missing a scheme name")
        seen_ids.add(fund_id)
        normalized_candidates.append(candidate)

    # Starter status is determined by client AUM threshold, which is not passed to this function.
    # For autonomous blueprint selection, default to non-starter (full eligibility).
    is_starter = False

    universe_insufficient = len(normalized_candidates) < minimum_candidate_universe
    universe_insufficient_reason = (
        f"candidate universe insufficient ({len(normalized_candidates)} < "
        f"{minimum_candidate_universe}); all SIP slots remain unallocated"
    )

    theme_aliases = {
        "Pharma": "Healthcare",
        "Pharmaceutical": "Healthcare",
        "Health": "Healthcare",
        "Pharma & Healthcare": "Healthcare",
        "Defence": "Defence",
        "Defense": "Defence",
        "Energy": "Power/Energy",
        "Power": "Power/Energy",
    }
    canonical_theme = theme_aliases.get(thematic_deficit_theme, thematic_deficit_theme)

    def no_action(slot_name: str, target_pct: float, reason: str, basis: str) -> Dict[str, Any]:
        return {
            "fund_name": f"NO_ACTION: {reason}",
            "scheme": f"NO_ACTION: {reason}",
            "fund_id": None,
            "category": None,
            "score": None,
            "gate_passed": False,
            "is_direct": None,
            "folio": None,
            "allocation_pct": 0.0,
            "unallocated_pct": target_pct,
            "allocation_basis": basis,
            "rationale": f"NO_ACTION: {reason}",
        }

    from core.eligibility import load_fund_screening_policy
    screening_policy = load_fund_screening_policy()
    try:
        from core.security_master import load_security_master
        security_master = load_security_master()
    except Exception:
        security_master = None

    def choose_candidate(
        slot_name: str,
        target_pct: float,
        category_predicate,
        reason: str,
        basis: str,
    ) -> Dict[str, Any]:
        if target_pct <= 0.0:
            return no_action(slot_name, 0.0, "no allocation is authorized for this slot", basis)
        if universe_insufficient:
            return no_action(slot_name, target_pct, universe_insufficient_reason, basis)
        evaluated = []
        for candidate in normalized_candidates:
            name = candidate.get("fund_name") or candidate.get("name") or ""
            category = candidate.get("category", "")
            if not category_predicate(candidate, name, category):
                continue
            # Explicit Direct-plan identity and its local source file must
            # both be reviewer-attested and hash-matched. A caller cannot bypass
            # this by supplying is_direct=True or copying the status string.
            if (
                candidate.get("is_direct") is not True
                or _reviewed_direct_plan_evidence_status(
                    candidate,
                    as_of_date=disclosure_as_of_date,
                ) != "REVIEWER_ATTESTED_HASH_MATCH"
            ):
                continue
            cand_sch_status = str(candidate.get("scheme_status", "ACTIVE") or "ACTIVE").strip().upper()
            if cand_sch_status not in ("ACTIVE", "OPEN"):
                continue
            cand_sub_status = str(candidate.get("subscription_status", "OPEN") or "OPEN").strip().upper()
            if cand_sub_status in ("CLOSED", "CLOSED_FOR_SUBSCRIPTION", "CLOSED_FOR_FRESH_SIP", "SUSPENDED", "RESTRICTED", "PAUSED"):
                continue
            gate_result = check_eligibility_gates(
                candidate,
                holdings or [],
                client_risk_tier_num=tier_int,
                as_of_date=disclosure_as_of_date,
                policy=screening_policy,
                risk_ceiling=effective_risk_ceiling,
            )
            if getattr(gate_result, "passed", False) is not True:
                continue
            # Use the candidate's actual investment category. Never let an
            # unsupported category silently inherit Healthcare scoring anchors.
            classified_category = classify_fund_category(name, category, candidate)
            scoring_categories = {
                "Flexi Cap Equity": "Flexi Cap",
                "Mid Cap Equity": "Mid Cap",
                "Large Cap Equity": "Large Cap",
                "Small Cap Equity": "Small Cap",
            }
            score_category_key = scoring_categories.get(classified_category)
            if score_category_key is None and detect_fund_theme(name, category) == "Healthcare":
                score_category_key = "Healthcare"
            if score_category_key is None:
                # No approved scoring model exists for this category (notably
                # debt and unsupported thematic categories). Keep it unselected.
                continue
            # Existing holdings must influence marginal portfolio fit. A confirmed
            # empty portfolio has zero overlap; missing/incomplete constituent
            # evidence is unknown and therefore cannot enter the ranking.
            if holdings:
                if candidate.get("lookthrough_status") != "VERIFIED":
                    continue
                if any(
                    float(getattr(holding, "equity_pct", 0.0) or 0.0) > 0.0
                    and getattr(holding, "lookthrough_status", "MISSING") != "VERIFIED"
                    for holding in holdings
                ):
                    continue
            overlap_eval = evaluate_candidate_portfolio_concentration_controls(
                candidate,
                holdings=holdings,
                security_master=security_master,
                max_overlap_pct=40.0,
                is_starter=is_starter,
                as_of_date=str(disclosure_as_of_date) if disclosure_as_of_date else None,
            )
            if not overlap_eval.get("passed", False):
                continue
            portfolio_overlap = overlap_eval.get("overlap_pct")
            if portfolio_overlap is None:
                continue
            try:
                score = compute_multi_horizon_fiduciary_score(
                    candidate,
                    category_key=score_category_key,
                    portfolio_overlap_pct=portfolio_overlap,
                )
            except ValueError:
                # An unscorable candidate is not a zero-score candidate and
                # must not be allowed to enter the ranking.
                continue
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
                raise ValueError(f"Candidate {candidate.get('fund_id')!r} returned an invalid composite score")
            evaluated.append((float(score), candidate))
        evaluated.sort(key=lambda item: (item[0], str(item[1].get("fund_id") or item[1].get("id"))), reverse=True)
        if not evaluated:
            return no_action(slot_name, target_pct, reason, basis)
        score, selected = evaluated[0]
        return {
            "fund_name": selected.get("fund_name") or selected.get("name"),
            "scheme": selected.get("fund_name") or selected.get("name"),
            "fund_id": selected.get("fund_id") or selected.get("id"),
            "isin": selected.get("isin"),
            "category": selected.get("category"),
            "score": score,
            "gate_passed": True,
            "is_direct": True,
            "scheme_status": selected.get("scheme_status", "ACTIVE"),
            "subscription_status": selected.get("subscription_status", "OPEN"),
            "scheme_min_sip_inr": selected.get("min_sip_amount") or selected.get("scheme_min_sip_inr"),
            "lock_in_days": selected.get("lock_in_days", 0),
            # A fund identifier is not a folio number. Only reuse an explicit
            # verified existing folio; the custodian may create a new one later.
            "folio": selected.get("folio") or selected.get("direct_folio"),
            "allocation_pct": target_pct,
            "unallocated_pct": 0.0,
            "allocation_basis": basis,
            "rationale": selected.get(
                "rationale",
                "Selected from the source-backed candidate universe after all eligibility gates passed.",
            ),
        }

    blueprint = {}
    blueprint["Slot 1: Core Flexi-Cap Compounder"] = choose_candidate(
        "Slot 1: Core Flexi-Cap Compounder",
        slot_targets["Slot 1: Core Flexi-Cap Compounder"],
        lambda candidate, name, category: classify_fund_category(name, category, candidate) == "Flexi Cap Equity",
        "no Direct Flexi Cap candidate passed all eligibility gates",
        "percent_of_equity_budget",
    )
    blueprint["Slot 2: Mid-Cap Alpha Engine"] = choose_candidate(
        "Slot 2: Mid-Cap Alpha Engine",
        slot_targets["Slot 2: Mid-Cap Alpha Engine"],
        lambda candidate, name, category: classify_fund_category(name, category, candidate) == "Mid Cap Equity",
        "no Direct Mid Cap candidate passed all eligibility gates",
        "percent_of_equity_budget",
    )
    blueprint["Slot 3: Small-Cap Growth Engine"] = choose_candidate(
        "Slot 3: Small-Cap Growth Engine",
        slot_targets["Slot 3: Small-Cap Growth Engine"],
        lambda candidate, name, category: classify_fund_category(name, category, candidate) == "Small Cap Equity",
        "no Direct Small Cap candidate passed all eligibility gates",
        "percent_of_equity_budget",
    )
    blueprint["Slot 4: Large-Cap Bluechip Anchor"] = choose_candidate(
        "Slot 4: Large-Cap Bluechip Anchor",
        slot_targets["Slot 4: Large-Cap Bluechip Anchor"],
        lambda candidate, name, category: classify_fund_category(name, category, candidate) == "Large Cap Equity",
        "no Direct Large Cap candidate passed all eligibility gates",
        "percent_of_equity_budget",
    )

    thematic_target = satellite_pct
    if not thematic_satellite_authorized or thematic_target <= 0.0:
        blueprint["Slot 5: Tactical Thematic Satellite"] = no_action(
            "Slot 5: Tactical Thematic Satellite",
            0.0,
            "thematic satellite is disabled or not explicitly authorized by the IPS",
            "percent_of_equity_budget",
        )
    else:
        blueprint["Slot 5: Tactical Thematic Satellite"] = choose_candidate(
            "Slot 5: Tactical Thematic Satellite",
            thematic_target,
            lambda candidate, name, category: detect_fund_theme(name, category) == canonical_theme,
            f"no Direct {thematic_deficit_theme} candidate passed all eligibility gates",
            "percent_of_equity_budget",
        )
    blueprint["High-Grade Debt Anchor"] = choose_candidate(
        "High-Grade Debt Anchor",
        debt_target_pct,
        lambda candidate, name, category: classify_fund_category(name, category, candidate) in (
            "Debt", "Debt Funds", "Liquid", "Liquid Fund", "Overnight Fund",
            "Money Market", "Money Market Fund", "Debt: Short Duration", "Short Duration",
            "Ultra Short Duration", "Low Duration", "Arbitrage Fund", "Corporate Bond", "Banking & PSU",
        ),
        "no supported debt-specific ranking model and verified Direct candidate are available",
        "percent_of_total_portfolio",
    )
    return blueprint

def calculate_universal_tier_split(
    tier_num: int,
    stability_buffer_pct: Optional[float] = None,
    equity_sip_routing_override: bool = False,
    custom_saa_target: Optional[Any] = None,
) -> Tuple[float, float]:
    """
    Return the policy-defined new-SIP equity/debt split for a risk tier.

    The policy's explicit new_sip_allocation is authoritative for tiers 1–5.
    A current stability-buffer percentage cannot override the post-contribution
    SAA or the investor's approved SIP split. Tier 6 equity-only routing remains
    separately gated by explicit IPS authorization. Missing or malformed policy
    is a hard failure.
    """
    import json
    import math
    from pathlib import Path

    if custom_saa_target is not None or tier_num == 0:
        from core.models import AssetAllocationTarget
        if not isinstance(custom_saa_target, AssetAllocationTarget):
            raise ValueError("custom_saa_target must be an AssetAllocationTarget instance")
        return float(custom_saa_target.equity_pct), float(custom_saa_target.debt_pct)
    if isinstance(tier_num, bool) or tier_num not in range(1, 7):
        raise ValueError("tier_num must be an integer from 1 through 6")
    if stability_buffer_pct is not None:
        try:
            stability = float(stability_buffer_pct)
        except (TypeError, ValueError) as exc:
            raise ValueError("stability_buffer_pct must be numeric") from exc
        if not math.isfinite(stability) or not 0.0 <= stability <= 100.0:
            raise ValueError("stability_buffer_pct must be finite and between 0 and 100")
    else:
        stability = None

    profile_keys = {
        1: "low", 2: "low_to_moderate", 3: "moderate",
        4: "moderately_high", 5: "high", 6: "very_high",
    }
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    if not policy_path.is_file():
        raise ValueError(f"Required allocation policy file is missing: {policy_path}")
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        profile = policy["behavioral_risk_profiles"][profile_keys[tier_num]]
        saa = profile["saa_targets"]
        sip = profile["new_sip_allocation"]
        debt_target = float(saa["debt_liquid_pct"])
        tolerance = float(profile["tolerance_band_pct"])
        equity_sip = float(sip["equity_pct"])
        debt_sip = float(sip["debt_pct"])
        authorization_flag = sip.get("requires_explicit_ips_authorization")
        if not isinstance(authorization_flag, bool):
            raise ValueError(
                "requires_explicit_ips_authorization must be a required literal boolean in every risk profile"
            )
        requires_ips_authorization = authorization_flag
        if tier_num == 6:
            if not requires_ips_authorization:
                raise ValueError("Tier 6 equity-only routing requires explicit IPS authorization policy")
            if abs(equity_sip - 100.0) > 0.01 or abs(debt_sip) > 0.01:
                raise ValueError("Tier 6 policy must preserve the approved 100/0 equity-only route")
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid allocation policy for SEBI risk tier {tier_num}") from exc

    values = (debt_target, tolerance, equity_sip, debt_sip)
    if any(not math.isfinite(v) for v in values):
        raise ValueError("Allocation policy values must be finite")
    if not (0.0 <= debt_target <= 100.0 and 0.0 <= tolerance <= 100.0):
        raise ValueError("SAA debt target and tolerance must be between 0 and 100")
    if any(not 0.0 <= v <= 100.0 for v in (equity_sip, debt_sip)):
        raise ValueError("New-SIP equity and debt percentages must be between 0 and 100")
    if abs(equity_sip + debt_sip - 100.0) > 0.01:
        raise ValueError("Policy new-SIP equity and debt percentages must sum to 100%")

    if not isinstance(equity_sip_routing_override, bool):
        raise ValueError("equity_sip_routing_override must be a boolean")

    if requires_ips_authorization and not equity_sip_routing_override:
        # Strategic allocation is the default until the IPS authorizes the
        # higher-risk new-SIP routing.
        return 100.0 - debt_target, debt_target
    if requires_ips_authorization and equity_sip_routing_override:
        return equity_sip, debt_sip

    # Do not infer permission to route new contributions 100% to equity
    # from the current portfolio's stability buffer. A contribution changes
    # the portfolio denominator and can create SAA drift; only the explicit
    # policy split (or separately authorized Tier 6 override) may route it.
    return equity_sip, debt_sip


def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: Optional[str] = None,
    stability_buffer_pct: Optional[float] = None,
    thematic_deficit_theme: str = "",
    thematic_satellite_authorized: bool = False,
    thematic_satellite_pct_of_equity: float = 0.0,
    candidate_universe: Optional[List[Dict[str, Any]]] = None,
    bank_cash_verified: bool = False,
    staging_policy: Optional[Dict[str, Any]] = None,
    parking_candidate: Optional[Dict[str, Any]] = None,
    equity_sip_routing_override: bool = False,
) -> DeterministicLumpsumPlan:
    """
    Fail-closed lumpsum planning.

    No tranche, parking vehicle or tax-saving estimate is created until the
    inputs and staging methodology have source-backed validation. This prevents
    defaulting to named funds, assumed yields, universal 20/80 deployment or
    a hardcoded multi-slot STP split.
    """
    import math
    import re

    if risk_tier is None or (isinstance(risk_tier, str) and not risk_tier.strip()):
        raise ValueError("An explicit validated investor risk profile is required; Tier 6 is never inferred")
    try:
        amount = float(lumpsum_amount)
        cash_total = float(bank_cash_total)
        reserve = float(emergency_reserve)
        satellite_pct = float(thematic_satellite_pct_of_equity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Lumpsum, bank-cash, reserve and thematic inputs must be numeric") from exc
    if not math.isfinite(amount) or amount < 0:
        raise ValueError("Lumpsum amount must be finite and non-negative")
    if not math.isfinite(cash_total) or cash_total < 0:
        raise ValueError("Bank cash must be finite and non-negative")
    if not math.isfinite(reserve) or reserve < 0 or reserve > cash_total:
        raise ValueError("Emergency reserve must be finite, non-negative and no greater than bank cash")
    if not isinstance(bank_cash_verified, bool):
        raise ValueError("bank_cash_verified must be a boolean")
    if not isinstance(thematic_satellite_authorized, bool):
        raise ValueError("thematic_satellite_authorized must be a boolean")
    if not math.isfinite(satellite_pct) or not 0.0 <= satellite_pct <= 15.0:
        raise ValueError("Thematic satellite percentage must be finite and between 0 and 15")
    if satellite_pct > 0 and not thematic_satellite_authorized:
        raise ValueError("A positive thematic satellite allocation requires explicit IPS authorization")

    deployable = cash_total - reserve
    reasons: List[str] = []
    if not bank_cash_verified:
        reasons.append("bank cash and emergency reserve are not independently verified")
    if deployable < amount:
        reasons.append("verified deployable surplus does not cover the requested lumpsum")

    tier_num = _parse_sebi_risk_tier(risk_tier)
    slots = select_autonomous_blueprint_funds(
        holdings=holdings,
        candidate_universe=candidate_universe,
        client_risk_tier=tier_num,
        thematic_deficit_theme=thematic_deficit_theme,
        thematic_satellite_authorized=thematic_satellite_authorized,
        thematic_satellite_pct_of_equity=satellite_pct,
    )
    equity_pct, debt_pct = calculate_universal_tier_split(
        tier_num, stability_buffer_pct, equity_sip_routing_override=equity_sip_routing_override
    )
    # Require only sleeves with a positive policy target. A zero-weight
    # sleeve must not turn an otherwise valid low-risk plan into NO_ACTION.
    required_slots = [
        name for name in (
            "Slot 1: Core Flexi-Cap Compounder",
            "Slot 2: Mid-Cap Alpha Engine",
            "Slot 3: Small-Cap Growth Engine",
            "Slot 4: Large-Cap Bluechip Anchor",
        )
        if (
            float((slots.get(name) or {}).get("allocation_pct", 0.0))
            + float((slots.get(name) or {}).get("unallocated_pct", 0.0))
        ) > 0.0
    ]
    if thematic_satellite_authorized and satellite_pct > 0:
        required_slots.append("Slot 5: Tactical Thematic Satellite")
    if debt_pct > 0:
        required_slots.append("High-Grade Debt Anchor")

    for slot_name in required_slots:
        slot = slots.get(slot_name) or {}
        scheme = slot.get("scheme") or slot.get("fund_name")
        if (
            not isinstance(scheme, str)
            or not scheme.strip()
            or scheme.strip().upper().startswith("NO_ACTION")
            or slot.get("is_direct") is not True
            or slot.get("gate_passed") is not True
        ):
            reasons.append(f"{slot_name} lacks a verified Direct-plan candidate passing every eligibility gate")

    # A parking vehicle must be a candidate in the supplied universe, not a
    # hardcoded brand or an inferred tax category.
    parking = parking_candidate if isinstance(parking_candidate, dict) else {}
    parking_id = parking.get("fund_id")
    candidates_by_id = {
        str(item.get("fund_id")): item
        for item in (candidate_universe or [])
        if isinstance(item, dict) and item.get("fund_id") is not None
    }
    parking_source = candidates_by_id.get(str(parking_id)) if parking_id is not None else None
    provenance = parking.get("_provenance") or (parking_source or {}).get("_provenance") or {}
    source_hash = provenance.get("source_document_sha256")
    source_url = provenance.get("source_url")
    if equity_pct > 0 and not (
        parking_source is not None
        and isinstance(parking.get("scheme_name") or parking_source.get("fund_name"), str)
        and parking.get("is_direct") is True
        and parking.get("category") == "Arbitrage"
        and parking.get("classification_status") == "VERIFIED"
        and isinstance(source_url, str) and source_url.startswith("https://")
        and isinstance(source_hash, str) and re.fullmatch(r"[0-9a-fA-F]{64}", source_hash)
    ):
        reasons.append("A source-backed Direct arbitrage parking candidate with verified tax classification is missing")

    if not isinstance(staging_policy, dict):
        reasons.append("an investor-authorized staging policy is missing")
    else:
        try:
            immediate_pct = float(staging_policy["immediate_equity_pct"])
            stp_months = int(staging_policy["stp_months"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Staging policy requires immediate_equity_pct and stp_months") from exc
        if not math.isfinite(immediate_pct) or not 0.0 <= immediate_pct <= 100.0:
            raise ValueError("immediate_equity_pct must be finite and between 0 and 100")
        if stp_months < 1 or stp_months > 36:
            raise ValueError("stp_months must be between 1 and 36")

    if not reasons:
        reasons.append(
            "tranche construction is not release-verified; retain the entire amount as unallocated pending independent review"
        )
    return DeterministicLumpsumPlan(
        total_lumpsum_inr=amount,
        unallocated_amount_inr=amount,
        is_big_ticket=amount >= 500000.0,
        stp_duration_months=0,
        immediate_amount_inr=0.0,
        stp_total_amount_inr=0.0,
        monthly_stp_total_inr=0.0,
        parking_vehicle="NO_ACTION",
        tax_savings_vs_debt_fund_inr=None,
        cash_validation_passed=bank_cash_verified and deployable >= amount,
        cash_validation_message="NO ACTION: " + "; ".join(reasons),
        tranches=[],
    )


def _sip_operational_constraint_violations(
    items,
    sip_policy,
    portfolio_introduction_history: Optional[Dict[str, Any]] = None,
    existing_schemes: Optional[List[Any]] = None,
    is_starter: bool = False,
):
    """Return fail-closed operational constraint violations for positive SIP lines."""
    import math
    from decimal import Decimal

    try:
        max_fund_pct = float(sip_policy["max_fund_allocation_pct"])
        min_ticket = Decimal(str(sip_policy["min_sip_per_fund_inr"]))
        increment = Decimal(str(sip_policy["sip_increment_inr"]))
        max_core_count = int(sip_policy["max_core_fund_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("SIP operational constraint policy is missing or invalid") from exc
    if (
        not math.isfinite(max_fund_pct) or not 0.0 < max_fund_pct <= 100.0
        or not math.isfinite(float(min_ticket)) or float(min_ticket) <= 0.0
        or not math.isfinite(float(increment)) or float(increment) <= 0.0
        or max_core_count < 1
    ):
        raise ValueError("SIP operational constraint policy values must be finite and positive")

    starter_exception = sip_policy.get("starter_flexi_sleeve_cap_exception")
    starter_cap_permitted = (
        is_starter
        and isinstance(starter_exception, dict)
        and starter_exception.get("permitted") is True
    )
    starter_max_sleeve_pct = (
        float(starter_exception.get("max_sleeve_pct", 60.0))
        if starter_cap_permitted else max_fund_pct
    )

    established_exception = sip_policy.get("established_sleeve_cap_exception")
    established_cap_permitted = (
        (not is_starter)
        and isinstance(established_exception, dict)
        and established_exception.get("permitted") is True
    )
    established_max_sleeve_pct = (
        float(established_exception.get("max_sleeve_pct", 35.0))
        if established_cap_permitted else max_fund_pct
    )

    # Convert monthly_inr to Decimal for safe arithmetic with all input types
    def _to_decimal(val):
        if isinstance(val, Decimal):
            return val
        return Decimal(str(val))

    active = [item for item in items if _to_decimal(item.monthly_inr) > Decimal("0")]
    violations = []
    for item in active:
        monthly_inr = _to_decimal(item.monthly_inr)
        is_starter_flexi = is_starter and "flexi" in item.category_role.lower()
        if is_starter_flexi:
            effective_cap = starter_max_sleeve_pct
        elif not is_starter and established_cap_permitted:
            effective_cap = established_max_sleeve_pct
        else:
            effective_cap = max_fund_pct
        if item.allocation_pct > effective_cap + 1e-9:
            violations.append(
                f"{item.category_role} allocation {item.allocation_pct:.2f}% exceeds "
                f"the {effective_cap:.2f}% per-fund cap"
            )
        if monthly_inr < min_ticket - Decimal("1e-9"):
            violations.append(
                f"{item.category_role} SIP ₹{monthly_inr:.2f} is below "
                f"the ₹{min_ticket:.2f} minimum ticket"
            )
        units = monthly_inr / increment
        if abs(units - round(units)) > Decimal("1e-8"):
            violations.append(
                f"{item.category_role} SIP ₹{monthly_inr:.2f} is not a "
                f"multiple of the ₹{increment:.2f} SIP increment"
            )
        # Operational feasibility and scheme status constraints
        sch_status = str(getattr(item, "scheme_status", "ACTIVE") or "ACTIVE").strip().upper()
        if sch_status not in ("ACTIVE", "OPEN"):
            violations.append(
                f"{item.scheme_name} is not confirmed active (scheme status: {sch_status})"
            )
        sub_status = str(getattr(item, "subscription_status", "OPEN") or "OPEN").strip().upper()
        if sub_status in ("CLOSED", "CLOSED_FOR_SUBSCRIPTION", "CLOSED_FOR_FRESH_SIP", "SUSPENDED", "RESTRICTED", "PAUSED"):
            violations.append(
                f"{item.scheme_name} subscription is restricted or closed (status: {sub_status})"
            )
        scheme_ticket = getattr(item, "scheme_min_sip_inr", None)
        if scheme_ticket is not None:
            try:
                ticket_val = Decimal(str(scheme_ticket))
                if ticket_val > Decimal("0") and monthly_inr < ticket_val - Decimal("1e-9"):
                    violations.append(
                        f"{item.scheme_name} SIP ₹{monthly_inr:.2f} is below "
                        f"scheme-specific minimum ticket ₹{ticket_val:.2f}"
                    )
            except (TypeError, ValueError):
                pass
    core_items = [
        item for item in active
        if "thematic" not in item.category_role.lower()
        and "debt" not in item.category_role.lower()
    ]
    if len(core_items) > max_core_count:
        violations.append(
            f"{len(core_items)} active core funds exceed the maximum of {max_core_count}"
        )

    # Enforce 12-month new-fund limit when portfolio introduction history is supplied or checked
    if "max_new_funds_per_12_months" in sip_policy:
        max_new_funds = int(sip_policy["max_new_funds_per_12_months"])
        if portfolio_introduction_history is not None:
            if not isinstance(portfolio_introduction_history, dict):
                violations.append("Portfolio introduction history must be an object")
            else:
                prior_new_funds = portfolio_introduction_history.get("new_funds_last_12_months")
                if prior_new_funds is None or not isinstance(prior_new_funds, (int, float)):
                    violations.append(
                        "Missing 12-month scheme introduction history; missing history is not treated as zero new funds"
                    )
                else:
                    existing_names = set()
                    if existing_schemes:
                        for s in existing_schemes:
                            name = s.get("scheme_name", s.get("scheme", "")) if isinstance(s, dict) else getattr(s, "scheme_name", getattr(s, "scheme", str(s)))
                            existing_names.add(name.lower().strip())

                    newly_introduced = 0
                    for item in active:
                        sname = item.scheme_name.lower().strip()
                        # Regular to Direct within same scheme is plan migration, NOT new fund
                        is_existing = any(
                            (sname in en or en in sname)
                            or (sname.replace("direct", "").strip() in en.replace("regular", "").strip())
                            for en in existing_names
                        )
                        if not is_existing:
                            newly_introduced += 1

                    if prior_new_funds + newly_introduced > max_new_funds:
                        violations.append(
                            f"{newly_introduced} new fund(s) proposed + {int(prior_new_funds)} prior introductions "
                            f"exceed the 12-month limit of {max_new_funds}"
                        )
    return violations


def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: Optional[str] = None,
    stability_buffer_pct: Optional[float] = None,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: Optional[float] = None,
    thematic_deficit_theme: str = "",
    thematic_satellite_pct_of_equity: float = 0.0,
    thematic_satellite_authorized: bool = False,
    candidate_universe: Optional[List[Dict[str, Any]]] = None,
    equity_sip_routing_override: bool = False,
    portfolio_disclosures_by_scheme_id: Optional[Dict[str, Dict[str, Any]]] = None,
    portfolio_disclosure_source_bytes_by_scheme_id: Optional[Dict[str, bytes]] = None,
    disclosure_as_of_date: Optional[date] = None,
    disclosure_max_age_days: int = 45,
    client_aum_verified: bool = False,
    policy_path: Optional[Path] = None,
    portfolio_introduction_history: Optional[Dict[str, Any]] = None,
    custom_saa_target: Optional[Any] = None,
    risk_ceiling: Optional[int] = None,
) -> DeterministicSIPPlan:
    """
    Computes deterministic SIP blueprint dynamically tailored across all SEBI risk tiers
    (Level 1 Capital Preservation to Level 6 Aggressive Equity).
    Scales across Starter (< INR 5L AUM) vs Established (> INR 25L AUM) portfolios.
    Reuses existing client Direct folios dynamically; NEVER hardcodes folios.
    """
    import math
    import json
    from pathlib import Path
    if risk_tier is None or (isinstance(risk_tier, str) and not risk_tier.strip()):
        raise ValueError("An explicit validated investor risk profile is required; Tier 6 is never inferred")
    if client_aum is None:
        raise ValueError("Verified reconciled client AUM is required; missing AUM is not zero")
    if not isinstance(client_aum_verified, bool):
        raise ValueError("client_aum_verified must be an explicit boolean")
    try:
        b = quantize_inr(monthly_budget)
        aum_value = quantize_inr(client_aum)
        stability_value = None if stability_buffer_pct is None else float(stability_buffer_pct)
    except (TypeError, ValueError, decimal.InvalidOperation) as exc:
        raise ValueError("SIP budget, client AUM and stability buffer must be numeric") from exc
    if not b.is_finite() or b < Decimal("0.00"):
        raise ValueError("Monthly SIP budget must be finite and non-negative")
    if not aum_value.is_finite() or aum_value < Decimal("0.00"):
        raise ValueError("Client AUM must be finite and non-negative")
    if stability_value is not None and (
        not math.isfinite(stability_value) or not 0.0 <= stability_value <= 100.0
    ):
        raise ValueError("Stability buffer percentage must be finite and between 0 and 100")
    stability_buffer_pct = stability_value
    client_aum = aum_value
    if not client_aum_verified:
        return DeterministicSIPPlan(
            total_monthly_budget_inr=b,
            unallocated_budget_inr=b,
            equity_sip_pct=0.0,
            debt_sip_pct=0.0,
            items=[],
            execution_status="HOLD_PORTFOLIO_AUM_UNVERIFIED",
            enforcement_notice=(
                "NO ACTION — complete SIP budget withheld because total portfolio AUM "
                "has not been independently reconciled and attested. CAS-only holdings "
                "are not treated as the complete investor portfolio."
            ),
        )
    policy_file = policy_path or (Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json")
    if not policy_file.is_file():
        raise ValueError(f"Required allocation policy file is missing: {policy_file}")
    try:
        from core.models import get_saa_policy_metadata
        policy_meta = get_saa_policy_metadata(policy_path=policy_file)
        allocation_policy = json.loads(policy_file.read_text(encoding="utf-8"))
        satellite_policy = allocation_policy["thematic_satellite_policy"]
        max_satellite_pct = float(satellite_policy["max_pct_of_equity"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Thematic satellite policy is missing or invalid") from exc
    if not math.isfinite(max_satellite_pct) or not 0.0 <= max_satellite_pct <= 100.0:
        raise ValueError("Thematic satellite policy cap must be finite and between 0 and 100")
    try:
        satellite_pct = float(thematic_satellite_pct_of_equity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Thematic satellite percentage must be numeric") from exc
    if not math.isfinite(satellite_pct) or not 0.0 <= satellite_pct <= max_satellite_pct:
        raise ValueError(f"Thematic satellite percentage of equity must be finite and between 0 and {max_satellite_pct:g}")
    if satellite_pct > 0.0 and thematic_satellite_authorized is not True:
        raise ValueError("A positive thematic satellite allocation requires explicit IPS authorization")
    if not isinstance(thematic_satellite_authorized, bool):
        raise ValueError("thematic_satellite_authorized must be a boolean")
    try:
        starter_policy = allocation_policy["starter_portfolio_routing"]
        starter_aum_threshold = float(starter_policy["aum_threshold_inr"])
        starter_budget_threshold = float(starter_policy["monthly_budget_threshold_inr"])
        starter_weights = starter_policy["equity_sleeves_pct_of_equity_budget"]
        starter_flexi_weight = float(starter_weights["flexi_cap"])
        starter_mid_weight = float(starter_weights["mid_small_cap"])
        starter_large_weight = float(starter_weights["large_cap"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Starter portfolio routing policy is missing or invalid") from exc
    starter_values = (starter_aum_threshold, starter_budget_threshold, starter_flexi_weight, starter_mid_weight, starter_large_weight)
    if any(not math.isfinite(v) or v < 0.0 for v in starter_values):
        raise ValueError("Starter portfolio thresholds and weights must be finite and non-negative")
    if abs(starter_flexi_weight + starter_mid_weight + starter_large_weight - 100.0) > 0.01:
        raise ValueError("Starter portfolio equity sleeve weights must sum to 100%")
    # CAS mutual-fund holdings alone are not total investor AUM. The
    # starter heuristic is permitted only when the caller has independently
    # reconciled and attested the complete portfolio perimeter.
    is_starter = (client_aum < starter_aum_threshold or b < starter_budget_threshold) and custom_saa_target is None

    # Dynamic Folio Discovery
    # Resolved dynamically through select_autonomous_blueprint_funds below

    # 1. Target Asset Allocation by Risk Level
    if str(risk_tier or "").strip().casefold() in {"custom", "risk_tier.custom"}:
        if custom_saa_target is None:
            raise ValueError("Custom risk profile requires an explicitly approved custom SAA target.")
        from core.models import AssetAllocationTarget
        if not isinstance(custom_saa_target, AssetAllocationTarget):
            raise ValueError("custom_saa_target must be an AssetAllocationTarget instance")
        tier_num = 0
        target_eq = float(custom_saa_target.equity_pct)
        target_debt = float(custom_saa_target.debt_pct)
    else:
        tier_num = _parse_sebi_risk_tier(risk_tier)
        target_eq, target_debt = calculate_universal_tier_split(
            tier_num, stability_buffer_pct, equity_sip_routing_override=equity_sip_routing_override
        )

    # Re-validate holding disclosures at the public SIP boundary when evidence
    # bundles are supplied. A missing exact-ID match clears stale weights.
    if holdings is not None and portfolio_disclosures_by_scheme_id is not None:
        from ingestion.portfolio_disclosure import validate_portfolio_disclosure
        enriched_holdings = []
        source_map = portfolio_disclosure_source_bytes_by_scheme_id or {}
        for holding in holdings:
            scheme_id = getattr(holding, "scheme_id", None)
            disclosure = portfolio_disclosures_by_scheme_id.get(scheme_id) if scheme_id else None
            source_bytes = source_map.get(scheme_id) if scheme_id else None
            if disclosure is None or source_bytes is None or disclosure_as_of_date is None:
                result = {"constituent_weights": None,
                          "constituent_weights_coverage_pct": None,
                          "status": "MISSING",
                          "reason": "No exact-ID disclosure and source evidence available at SIP decision time."}
            else:
                result = validate_portfolio_disclosure(
                    disclosure, source_bytes,
                    as_of=disclosure_as_of_date,
                    max_age_days=disclosure_max_age_days,
                )
                if result.get("scheme_id") != scheme_id:
                    result = {"constituent_weights": None,
                              "constituent_weights_coverage_pct": None,
                              "status": "CONFLICTING",
                              "reason": "Disclosure scheme identifier does not match existing holding."}
            enriched_holdings.append(holding.model_copy(update={
                "constituent_weights": result.get("constituent_weights"),
                "constituent_weights_coverage_pct": result.get("constituent_weights_coverage_pct"),
                "lookthrough_status": result["status"],
                "lookthrough_reason": result["reason"],
            }))
        holdings = enriched_holdings

    items = []

    # Autonomous Fiduciary Slot Selection (Zero Hardcoded Brands)
    slots = select_autonomous_blueprint_funds(
        holdings=holdings,
        candidate_universe=candidate_universe,
        client_risk_tier=tier_num,
        thematic_deficit_theme=thematic_deficit_theme,
        thematic_satellite_authorized=thematic_satellite_authorized,
        thematic_satellite_pct_of_equity=satellite_pct,
        portfolio_disclosures_by_scheme_id=portfolio_disclosures_by_scheme_id,
        portfolio_disclosure_source_bytes_by_scheme_id=portfolio_disclosure_source_bytes_by_scheme_id,
        disclosure_as_of_date=disclosure_as_of_date,
        disclosure_max_age_days=disclosure_max_age_days,
        custom_saa_target=custom_saa_target,
        risk_ceiling=risk_ceiling,
    )
    flexi_info = slots["Slot 1: Core Flexi-Cap Compounder"]
    mid_info = slots["Slot 2: Mid-Cap Alpha Engine"]
    small_info = slots["Slot 3: Small-Cap Growth Engine"]
    large_info = slots["Slot 4: Large-Cap Bluechip Anchor"]
    thematic_info = slots["Slot 5: Tactical Thematic Satellite"]
    debt_info = slots.get("High-Grade Debt Anchor", {})

    flexi_scheme = flexi_info.get("scheme") or flexi_info.get("fund_name") or "NO_ACTION: No eligible fund selected"
    flexi_target_folio = flexi_info.get("folio")
    flexi_default_rat = flexi_info.get("rationale", "NO_ACTION: No eligible fund selected for Slot 1.")

    mid_scheme = mid_info.get("scheme") or mid_info.get("fund_name") or "NO_ACTION: No eligible fund selected"
    mid_target_folio = mid_info.get("folio")
    mid_default_rat = mid_info.get("rationale", "NO_ACTION: No eligible fund selected for Slot 2.")

    small_scheme = small_info.get("scheme") or small_info.get("fund_name") or "NO_ACTION: No eligible fund selected"
    small_target_folio = small_info.get("folio")
    small_default_rat = small_info.get("rationale", "NO_ACTION: No eligible fund selected for Slot 3.")

    large_scheme = large_info.get("scheme") or large_info.get("fund_name") or "NO_ACTION: No eligible fund selected"
    large_target_folio = large_info.get("folio")
    large_default_rat = large_info.get("rationale", "NO_ACTION: No eligible fund selected for Slot 4.")

    thematic_scheme = thematic_info.get("scheme") or thematic_info.get("fund_name") or "NO_ACTION: No eligible fund selected"
    direct_thematic_folio = thematic_info.get("folio")
    thematic_rat = thematic_info.get("rationale", "NO_ACTION: No eligible thematic fund selected for Slot 5.")

    debt_scheme = debt_info.get("scheme") or "NO_ACTION: No verified debt candidate selected"
    direct_debt_folio = debt_info.get("folio")
    debt_rat = debt_info.get("rationale", "High-grade AAA short-term debt fulfilling SAA fixed income target.")

    def _append_flexi_sip_items(alloc_pct: float):
        items.append(
            DeterministicSIPRecommendation(
                category_role="Core Flexi-Cap Compounder",
                scheme_name=flexi_scheme,
                folio_target=flexi_target_folio,
                monthly_inr=quantize_inr(b * Decimal(str(alloc_pct)) / Decimal("100.0")),
                allocation_pct=alloc_pct,
                rational_code="CORE_COMPOUNDER",
                fiduciary_rationale=flexi_default_rat,
                is_direct=flexi_info.get("is_direct")
            )
        )

    if is_starter:
        # Starter routing is a provisional research heuristic defined in policy.
        if target_eq > 0:
            thematic_pct = round(target_eq * satellite_pct / 100.0, 1)
            core_equity_pct = target_eq - thematic_pct
            flexi_pct = round(core_equity_pct * starter_flexi_weight / 100.0, 1)
            mid_small_pct = round(core_equity_pct * starter_mid_weight / 100.0, 1)
            # Preserve the starter policy's combined mid/small sleeve while
            # splitting it using the investor's SAA mid/small proportions.
            if custom_saa_target is not None or tier_num == 0:
                if custom_saa_target.large_cap_pct is not None:
                    _starter_large = float(custom_saa_target.large_cap_pct)
                    _starter_mid = float(custom_saa_target.mid_cap_pct)
                    _starter_small = float(custom_saa_target.small_cap_pct)
                    _starter_flexi = float(custom_saa_target.flexi_cap_pct)
                else:
                    _starter_large = round(35.0 * target_eq / 100.0, 2)
                    _starter_flexi = round(25.0 * target_eq / 100.0, 2)
                    _starter_mid = round(20.0 * target_eq / 100.0, 2)
                    _starter_small = round(20.0 * target_eq / 100.0, 2)
            else:
                _tier_profiles = {1: "low", 2: "low_to_moderate", 3: "moderate", 4: "moderately_high", 5: "high", 6: "very_high"}
                _starter_saa = allocation_policy["behavioral_risk_profiles"][_tier_profiles[tier_num]]["saa_targets"]
                _starter_mid = float(_starter_saa["mid_cap_pct"])
                _starter_small = float(_starter_saa["small_cap_pct"])
            _starter_mid_small = _starter_mid + _starter_small
            if _starter_mid_small > 0:
                mid_pct = round(mid_small_pct * _starter_mid / _starter_mid_small, 1)
                small_pct = round(mid_small_pct - mid_pct, 1)
            else:
                mid_pct = 0.0
                small_pct = 0.0
            large_pct = round(core_equity_pct * starter_large_weight / 100.0, 1)
            diff = round(core_equity_pct - flexi_pct - mid_pct - small_pct - large_pct, 1)
            flexi_pct = round(flexi_pct + diff, 1)
            _append_flexi_sip_items(flexi_pct)
            if mid_pct > 0:
                items.append(
                    DeterministicSIPRecommendation(
                        category_role="Mid-Cap Alpha Engine",
                        scheme_name=mid_scheme,
                        folio_target=mid_target_folio,
                        monthly_inr=quantize_inr(b * Decimal(str(mid_pct)) / Decimal("100.0")),
                        allocation_pct=mid_pct,
                        rational_code="ALPHA_ENGINE",
                        fiduciary_rationale=mid_default_rat,
                        is_direct=mid_info.get("is_direct")
                    )
                )
            if small_pct > 0:
                items.append(
                    DeterministicSIPRecommendation(
                        category_role="Small-Cap Growth Engine",
                        scheme_name=small_scheme,
                        folio_target=small_target_folio,
                        monthly_inr=quantize_inr(b * Decimal(str(small_pct)) / Decimal("100.0")),
                        allocation_pct=small_pct,
                        rational_code="SMALL_CAP_GROWTH",
                        fiduciary_rationale=small_default_rat,
                        is_direct=small_info.get("is_direct"),
                    )
                )
            if large_pct > 0:
                items.append(
                    DeterministicSIPRecommendation(
                        category_role="Large-Cap Bluechip Anchor",
                        scheme_name=large_scheme,
                        folio_target=large_target_folio,
                        monthly_inr=quantize_inr(b * Decimal(str(large_pct)) / Decimal("100.0")),
                        allocation_pct=large_pct,
                        rational_code="BLUECHIP_ANCHOR",
                        fiduciary_rationale=large_default_rat,
                        is_direct=large_info.get("is_direct")
                    )
                )
            if thematic_pct > 0:
                items.append(
                    DeterministicSIPRecommendation(
                        category_role="Tactical Thematic Satellite",
                        scheme_name=thematic_scheme,
                        folio_target=direct_thematic_folio,
                        monthly_inr=quantize_inr(b * Decimal(str(thematic_pct)) / Decimal("100.0")),
                        allocation_pct=thematic_pct,
                        rational_code="TACTICAL_SATELLITE",
                        fiduciary_rationale=thematic_rat,
                        is_direct=thematic_info.get("is_direct")
                    )
                )
        if target_debt > 0:
            items.append(
                DeterministicSIPRecommendation(
                    category_role="High-Grade Debt Anchor",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=quantize_inr(b * Decimal(str(target_debt)) / Decimal("100.0")),
                    allocation_pct=target_debt,
                    rational_code="DEBT_ANCHOR",
                    fiduciary_rationale="Preserves capital stability and fulfills SAA fixed income target.",
                    is_direct=debt_info.get("is_direct"),
                )
            )
    else:
        # Established Portfolio (>= INR 5L AUM): Policy-file-driven slot sizing engine
        # Weights from data/policy/asset_allocation.json behavioral_risk_profiles[tier].saa_targets
        if target_eq > 0:
            # --- Policy-file-driven slot weights ---
            # Reads data/policy/asset_allocation.json
            # behavioral_risk_profiles[tier].saa_targets
            # NOT hardcoded literals. Auditor-confirmed defect fix.
            if custom_saa_target is not None or tier_num == 0:
                if custom_saa_target.large_cap_pct is not None:
                    _large = float(custom_saa_target.large_cap_pct)
                    _mid = float(custom_saa_target.mid_cap_pct)
                    _small = float(custom_saa_target.small_cap_pct)
                    _flexi = float(custom_saa_target.flexi_cap_pct)
                else:
                    scale = target_eq / 100.0 if target_eq > 0 else 0.0
                    _large = round(35.0 * scale, 2)
                    _flexi = round(25.0 * scale, 2)
                    _mid = round(20.0 * scale, 2)
                    _small = round(20.0 * scale, 2)
                    diff = target_eq - (_large + _flexi + _mid + _small)
                    _large = round(_large + diff, 2)
            else:
                _tier_to_profile = {
                    1: 'low', 2: 'low_to_moderate', 3: 'moderate',
                    4: 'moderately_high', 5: 'high', 6: 'very_high',
                }
                if tier_num not in _tier_to_profile:
                    raise ValueError(f"Unsupported SEBI risk tier: {tier_num}")
                _profile_key = _tier_to_profile[tier_num]
                try:
                    _saa = allocation_policy["behavioral_risk_profiles"][_profile_key]["saa_targets"]
                except (KeyError, TypeError) as exc:
                    raise ValueError(f"Required SAA policy is invalid for risk profile {_profile_key!r}") from exc
                try:
                    _large = float(_saa["large_cap_pct"])
                    _mid = float(_saa["mid_cap_pct"])
                    _small = float(_saa["small_cap_pct"])
                    _flexi = float(_saa["flexi_multi_cap_pct"])
                except (TypeError, ValueError, KeyError) as exc:
                    raise ValueError("SAA policy must contain numeric large/mid/small/flexi weights") from exc
            _core_weights = (_large, _mid, _small, _flexi)
            if any(not math.isfinite(v) or v < 0.0 for v in _core_weights):
                raise ValueError("SAA core weights must be finite and non-negative")
            _eq_sum = sum(_core_weights)
            if _eq_sum <= 0.0 or _eq_sum > 100.0:
                raise ValueError("SAA core equity weights must sum to a value in (0, 100]")
            # Slot 4 is zero by default. A separately authorized satellite is
            # carved out of the equity budget before core weights are applied.
            thematic_pct = round(target_eq * satellite_pct / 100.0, 1)
            core_equity_pct = target_eq - thematic_pct
            _w_flexi = _flexi / _eq_sum
            _w_mid = _mid / _eq_sum
            _w_small = _small / _eq_sum
            _w_large = _large / _eq_sum
            flexi_pct = round(core_equity_pct * _w_flexi, 1)
            mid_pct = round(core_equity_pct * _w_mid, 1)
            small_pct = round(core_equity_pct * _w_small, 1)
            large_pct = round(core_equity_pct * _w_large, 1)

            # Absorb sub-percent rounding discrepancy into Flexi only; preserve
            # the separate mid- and small-cap strategic sleeve targets.
            eq_diff = round(target_eq - (flexi_pct + mid_pct + small_pct + large_pct + thematic_pct), 1)
            flexi_pct = round(flexi_pct + eq_diff, 1)

            # Slot 1: Core Flexi-Cap Compounder
            _append_flexi_sip_items(flexi_pct)

            # Slot 2: Mid-Cap Alpha Engine
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Mid-Cap Alpha Engine",
                    scheme_name=mid_scheme,
                    folio_target=mid_target_folio,
                    monthly_inr=quantize_inr(b * Decimal(str(mid_pct)) / Decimal("100.0")),
                    allocation_pct=mid_pct,
                    rational_code="ALPHA_ENGINE",
                    fiduciary_rationale=mid_default_rat
                )
            )

            # Slot 3: Small-Cap Growth Engine
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Small-Cap Growth Engine",
                    scheme_name=small_scheme,
                    folio_target=small_target_folio,
                    monthly_inr=quantize_inr(b * Decimal(str(small_pct)) / Decimal("100.0")),
                    allocation_pct=small_pct,
                    rational_code="SMALL_CAP_GROWTH",
                    fiduciary_rationale=small_default_rat,
                    is_direct=small_info.get("is_direct"),
                )
            )

            # Slot 4: Large-Cap Bluechip Anchor
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Large-Cap Bluechip Anchor",
                    scheme_name=large_scheme,
                    folio_target=large_target_folio,
                    monthly_inr=quantize_inr(b * Decimal(str(large_pct)) / Decimal("100.0")),
                    allocation_pct=large_pct,
                    rational_code="CORE_ANCHOR",
                    fiduciary_rationale=large_default_rat,
                    is_direct=large_info.get("is_direct")
                )
            )

            # Slot 5: Tactical Thematic Satellite
            items.append(
                DeterministicSIPRecommendation(
                    category_role="Tactical Thematic Satellite",
                    scheme_name=thematic_scheme,
                    folio_target=direct_thematic_folio,
                    monthly_inr=quantize_inr(b * Decimal(str(thematic_pct)) / Decimal("100.0")),
                    allocation_pct=thematic_pct,
                    rational_code="SATELLITE_THEME",
                    fiduciary_rationale=thematic_rat,
                    is_direct=thematic_info.get("is_direct")
                )
            )

        if target_debt > 0:
            items.append(
                DeterministicSIPRecommendation(
                    category_role="High-Grade Debt Cushion" if target_eq > 0 else "Capital Preservation Debt",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=quantize_inr(b * Decimal(str(target_debt)) / Decimal("100.0")),
                    allocation_pct=target_debt,
                    rational_code="DEBT_CUSHION" if target_eq > 0 else "DEBT_ANCHOR",
                    fiduciary_rationale=f"Fulfills {target_debt:.0f}% high-grade debt target under SAA mandate without credit risk.",
                    is_direct=debt_info.get("is_direct")
                )
            )

    # Fail closed as a whole: if any positive slot lacks an explicitly
    # verified Direct-plan candidate, do not partially deploy or reallocate the
    # investor's budget to another slot. Preserve target allocation percentages
    # for diagnosis, but zero every amount and disclose the full unallocated sum.
    unverified_active_slots = [
        item for item in items
        if item.monthly_inr > 0
        and (item.is_direct is not True or item.scheme_name.upper().startswith("NO_ACTION"))
    ]
    unallocated_budget = Decimal("0.00")
    if unverified_active_slots:
        unallocated_budget = b
        for item in items:
            item.monthly_inr = Decimal("0.00")
            item.fiduciary_rationale = (
                "NO ACTION — entire SIP budget withheld because at least one required "
                "slot lacks verified Direct-plan eligibility. No redistribution is permitted. "
                + item.fiduciary_rationale
            )
    else:
        total_allocated = sum(quantize_inr(item.monthly_inr) for item in items)
        diff = b - total_allocated
        if diff != Decimal("0.00") and items:
            items[0].monthly_inr = quantize_inr(Decimal(str(items[0].monthly_inr)) + diff)

    # Operational policy constraints are hard gates. If any active line
    # breaches a cap/ticket/increment/count rule, withhold the whole budget;
    # never silently redistribute a rejected line to another fund.
    try:
        sip_operational_policy = allocation_policy["sip_allocation_policy"]
    except (KeyError, TypeError) as exc:
        raise ValueError("SIP operational allocation policy is missing") from exc
    operational_violations = _sip_operational_constraint_violations(
        items,
        sip_operational_policy,
        portfolio_introduction_history=portfolio_introduction_history,
        existing_schemes=holdings,
        is_starter=is_starter,
    )
    if operational_violations:
        unallocated_budget = b
        for item in items:
            item.monthly_inr = Decimal("0.00")
            item.fiduciary_rationale = (
                "NO ACTION — entire SIP budget withheld because operational policy "
                "constraints are not satisfied. No redistribution is permitted. "
                + "; ".join(operational_violations)
                + ". " + item.fiduciary_rationale
            )

    plan = DeterministicSIPPlan(
        total_monthly_budget_inr=b,
        unallocated_budget_inr=unallocated_budget,
        equity_sip_pct=target_eq,
        debt_sip_pct=target_debt,
        items=items,
        policy_version=policy_meta.get("policy_version"),
        policy_digest=policy_meta.get("policy_digest"),
    )

    from core.eligibility import validate_thematic_satellite_cap, validate_direct_sip_mandate
    validate_thematic_satellite_cap(plan, client_aum)
    validate_direct_sip_mandate(plan)

    return plan



# Re-export personal redemption engine
from core.redemption_engine import compute_personal_redemption_plan

# P0 SAFETY GATE: legacy FIFO tax classification is not approved. The
# separate build_fifo_tax_lots helper is also not a supported preparation
# interface: its output model/provenance contract is incomplete and it has no
# production callers. Disable both public paths until a tested, reconciled
# lot-evidence contract is implemented.
class TaxClassificationDisabledError(RuntimeError):
    """Raised when provisional legacy tax/exit-load classification is invoked."""


def _tax_classification_disabled(*args, **kwargs):
    raise TaxClassificationDisabledError(
        "Legacy FIFO tax/exit-load classification is disabled: the generic "
        "365-day and 1% exit-load assumptions are not approved. No tax or "
        "redemption classification has been generated."
    )


compute_fifo_tax_lots = _tax_classification_disabled


def _tax_lot_preparation_disabled(*args, **kwargs):
    raise TaxClassificationDisabledError(
        "Legacy FIFO lot preparation is disabled: its output model and "
        "provenance/reconciliation contract are incomplete. No lot evidence "
        "has been generated."
    )


build_fifo_tax_lots = _tax_lot_preparation_disabled


# Do not permit callers to bypass the approved-policy loader by supplying an
# arbitrary dictionary to the legacy, non-provenance-backed classifier.
_classify_fund_for_tax = _tax_classification_disabled

# Statutory section/rate summaries are also withheld until the checked-in
# legal mapping receives independent, current-law review.
get_statutory_tax_citation = _tax_classification_disabled

# Date-/instrument-specific statutory classification remains disabled until
# the successor-Act mapping and source evidence receive independent review.
classify_specified_mutual_fund = _tax_classification_disabled
qualifies_as_equity_oriented_under_section_198 = _tax_classification_disabled
qualifies_as_specified_mutual_fund_under_section_50AA = _tax_classification_disabled
qualifies_as_specified_mutual_fund_under_section_76 = _tax_classification_disabled



def _tax_lot_maturity_classification_disabled(*args, **kwargs):
    raise TaxClassificationDisabledError(
        "Direct tax-lot maturity classification is disabled pending independent "
        "Indian tax/legal approval and exact scheme/plan/lot evidence. No "
        "holding-period, LTCG or STCG classification has been generated."
    )


# =============================================================================
# FAIL-CLOSED XIRR CALCULATION FROM TRANSACTION LEDGER
# =============================================================================

def calculate_portfolio_xirr(
    ledger_path: Path,
    allocations: list,
    cas_current: Optional[float] = None,
    as_of_date: Optional[date] = None,
    require_reviewer_signature: bool = True,
) -> Optional[float]:
    """
    Calculate portfolio XIRR from transaction ledger with fail-closed validation.

    Fail_CLOSED: Returns None instead of raising on any data quality issue.
    - Malformed rows are rejected, not silently dropped
    - Non-finite amounts are rejected
    - Invalid as_of_date is rejected
    - Unverified cash flows (e.g., charges) are rejected

    Args:
        ledger_path: Path to transactions.json file with {"transactions": [...]} structure
        allocations: List of allocation objects (reserved for future use)
        cas_current: Final portfolio value (optional, used for validation)
        as_of_date: Date for portfolio valuation (required)
        require_reviewer_signature: Whether reviewer signature is required

    Returns:
        XIRR as decimal (e.g., 0.12 for 12%), or None if validation fails
    """
    from core.math.xirr import calculate_xirr

    # Fail closed: require valid as_of_date
    if as_of_date is None or not isinstance(as_of_date, date):
        return None

    # Fail closed: ledger file must exist
    if not isinstance(ledger_path, Path) or not ledger_path.exists():
        return None

    # Read and parse transactions
    try:
        data = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Fail closed: transactions must be a list
    transactions = data.get("transactions")
    if not isinstance(transactions, list):
        return None

    valid_types = {"PURCHASE", "SIP", "REDEEM", "SWITCH_IN", "SWITCH_OUT", "DIVIDEND"}
    cashflows = []
    latest_txn_date = None

    for row in transactions:
        # Fail closed: each row must be a dict with required fields
        if not isinstance(row, dict):
            return None

        row_date_str = row.get("date")
        row_type = row.get("type")
        row_amount = row.get("amount")
        row_units = row.get("units")

        # Fail closed: validate date
        try:
            row_date = datetime.strptime(str(row_date_str), "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

        # Track latest transaction date for as_of_date validation
        if latest_txn_date is None or row_date > latest_txn_date:
            latest_txn_date = row_date

        # Fail closed: validate transaction type
        if row_type not in valid_types:
            return None

        # Fail closed: validate amount is finite
        try:
            amount_float = float(row_amount)
            if not math.isfinite(amount_float):
                return None
        except (ValueError, TypeError):
            return None

        # DIVIDEND and CHARGES are positive flows (returns)
        # PURCHASE, SIP, REDEEM, SWITCH are negative flows (investments)
        # We'll use the type to determine sign
        if row_type in {"PURCHASE", "SIP", "REDEEM", "SWITCH_IN"}:
            sign = -1
        elif row_type in {"REDEEM", "SWITCH_OUT", "DIVIDEND"}:
            sign = 1
        else:
            sign = -1  # default to investment

        cashflows.append((row_date, sign * abs(amount_float)))

    # Fail closed: as_of_date must be >= latest transaction date
    if latest_txn_date is not None and as_of_date < latest_txn_date:
        return None

    # Add final portfolio value as positive cashflow on as_of_date
    if cas_current is not None and math.isfinite(cas_current) and cas_current > 0:
        cashflows.append((as_of_date, cas_current))

    # Sort by date
    cashflows.sort(key=lambda x: x[0])

    # Calculate XIRR
    return calculate_xirr(cashflows)


# =============================================================================
# FAIL-CLOSED CAS HOLDINGS AND TRANSACTION RECONCILIATION
# =============================================================================

def reconcile_cas_holdings_with_transactions(
    cas_holdings: list,
    transactions_path: Optional[Path],
) -> dict:
    """
    Reconcile CAS holdings with transaction ledger with fail-closed validation.

    Fail_CLOSED: Returns error status dict instead of raising on data quality issues.

    Args:
        cas_holdings: List of holdings with .scheme, .units, .folio attributes
        transactions_path: Path to transactions.json file

    Returns:
        Dict with 'status' key indicating:
        - 'READ_ERROR' - Transactions file could not be read
        - 'NO_TRANSACTION_FILE' - No transactions file provided
        - 'INVALID_TRANSACTION' - Transactions contain invalid rows
        - 'VERIFIED_RECONCILED' - Holdings match transactions exactly
        - 'PARTIALLY_RECONCILED' - Partially matched
    """
    result: Dict[str, Any] = {"status": "UNKNOWN"}

    # Handle missing file
    if transactions_path is None:
        return {"status": "NO_TRANSACTION_FILE"}

    if not isinstance(transactions_path, Path):
        return {"status": "READ_ERROR"}

    if not transactions_path.exists():
        return {"status": "NO_TRANSACTION_FILE"}

    # Read transactions file
    try:
        data = json.loads(transactions_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"status": "READ_ERROR"}

    transactions = data.get("transactions")
    if not isinstance(transactions, list):
        # READ_ERROR for invalid container type (dict/object instead of list)
        return {"status": "READ_ERROR"}

    # Validate and aggregate transactions
    valid_types = {"PURCHASE", "SIP", "REDEEM", "SWITCH_IN", "SWITCH_OUT", "DIVIDEND"}
    txn_units_by_scheme: Dict[str, float] = defaultdict(float)

    for txn in transactions:
        # Fail closed: each row must be a valid dict
        if not isinstance(txn, dict):
            result["status"] = "INVALID_TRANSACTION"
            result["details"] = "Transaction row is not an object"
            return result

        scheme = txn.get("scheme")
        units = txn.get("units")
        txn_type = txn.get("type")

        if scheme is None or txn_type is None:
            result["status"] = "INVALID_TRANSACTION"
            return result

        # Fail closed: validate units is finite number
        try:
            unit_val = float(units)
            if not math.isfinite(unit_val):
                result["status"] = "INVALID_TRANSACTION"
                return result
        except (ValueError, TypeError):
            result["status"] = "INVALID_TRANSACTION"
            return result

        # Fail closed: units must be positive for PURCHASE/SIP/SWITCH_IN
        if txn_type in {"PURCHASE", "SIP", "SWITCH_IN"} and unit_val < 0:
            result["status"] = "INVALID_TRANSACTION"
            return result

        # Fail closed: validate type
        if txn_type not in valid_types:
            result["status"] = "INVALID_TRANSACTION"
            return result

        # Aggregate units (positive for purchases, negative for redemptions)
        if txn_type in {"PURCHASE", "SIP", "SWITCH_IN", "DIVIDEND"}:
            txn_units_by_scheme[str(scheme)] += unit_val
        else:  # REDEEM, SWITCH_OUT
            txn_units_by_scheme[str(scheme)] -= unit_val

    # Aggregate CAS holdings by scheme
    cas_units_by_scheme: Dict[str, float] = defaultdict(float)
    discrepancies: List[Dict[str, str]] = []

    for holding in cas_holdings:
        scheme = getattr(holding, "scheme", None)
        units = getattr(holding, "units", None)

        if scheme is None or units is None:
            continue

        try:
            unit_val = float(units)
            if math.isfinite(unit_val):
                cas_units_by_scheme[str(scheme)] += unit_val
        except (ValueError, TypeError):
            continue

    # Compare holdings vs transactions
    txn_schemes_set = set(txn_units_by_scheme.keys())
    cas_schemes_set = set(cas_units_by_scheme.keys())

    for scheme in txn_schemes_set:
        cas_units = cas_units_by_scheme.get(scheme, 0.0)
        txn_units = txn_units_by_scheme.get(scheme, 0.0)

        if abs(cas_units - txn_units) > 0.001:  # tolerance for floating point
            # Check if this is an exact scheme match in CAS holdings
            is_exact_match = scheme in cas_schemes_set

            if not is_exact_match:
                discrepancies.append({
                    "scheme": scheme,
                    "cas_units": cas_units,
                    "transaction_units": txn_units,
                    "difference": cas_units - txn_units,
                    "reason": "NO_EXACT_TRANSACTION_SCHEME_MATCH",
                })
            else:
                discrepancies.append({
                    "scheme": scheme,
                    "cas_units": cas_units,
                    "transaction_units": txn_units,
                    "difference": cas_units - txn_units,
                })

    unmatched_txn_schemes = [s for s in txn_schemes_set if s not in cas_schemes_set]

    if discrepancies:
        result["status"] = "PARTIALLY_RECONCILED"
        result["discrepancies"] = discrepancies
        result["unmatched_transaction_schemes"] = [{"scheme": s} for s in unmatched_txn_schemes]
    else:
        result["status"] = "VERIFIED_RECONCILED"
        result["reconciled_schemes"] = len(set(cas_units_by_scheme.keys()) & set(txn_units_by_scheme.keys()))

    return result


# Patch TaxLot class to disable maturity classification methods
# This must happen after TaxClassificationDisabledError is defined
def _tax_lot_maturity_classification_disabled(*args, **kwargs):
    raise TaxClassificationDisabledError(
        "Direct tax-lot maturity classification is disabled pending independent "
        "Indian tax/legal approval and exact scheme/plan/lot evidence. No "
        "holding-period, LTCG or STCG classification has been generated."
    )

TaxLot.is_long_term = _tax_lot_maturity_classification_disabled
TaxLot.is_short_term = _tax_lot_maturity_classification_disabled
