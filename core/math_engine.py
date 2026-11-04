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
from core.models import TriProvenanceError, HoldingItem, FeeBleedAnalysis, PlanType, AssetClass

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
    """
    Calculate XIRR (Extended Internal Rate of Return) for irregular cash flows.
    
    Args:
        cashflows: List of (date, amount) tuples where negative = investment, positive = return
        
    Returns:
        Annualized XIRR as decimal (e.g., 0.134 for 13.4%), or None if cannot converge
    """
    if not cashflows or len(cashflows) < 2:
        return None
    
    # Sort by date
    cashflows = sorted(cashflows, key=lambda x: x[0])
    
    # Check if we have both positive and negative flows
    has_negative = any(cf[1] < 0 for cf in cashflows)
    has_positive = any(cf[1] > 0 for cf in cashflows)
    if not (has_negative and has_positive):
        return None
    
    # Use Newton-Raphson method to solve for IRR
    # NPV(rate) = sum(cf / (1+rate)^(days/365)) = 0
    
    def npv(rate: float) -> float:
        total = 0.0
        base_date = cashflows[0][0]
        for cf_date, amount in cashflows:
            days = (cf_date - base_date).days
            total += amount / ((1 + rate) ** (days / 365.0))
        return total
    
    def npv_derivative(rate: float) -> float:
        total = 0.0
        base_date = cashflows[0][0]
        for cf_date, amount in cashflows:
            days = (cf_date - base_date).days
            total += -amount * (days / 365.0) / ((1 + rate) ** (days / 365.0 + 1))
        return total
    
    # Initial guess: simple approximation
    total_invested = sum(abs(cf[1]) for cf in cashflows if cf[1] < 0)
    total_returned = sum(cf[1] for cf in cashflows if cf[1] > 0)
    if total_invested > 0:
        guess = (total_returned - total_invested) / total_invested
        guess = max(-0.99, min(10.0, guess))  # Clamp between -99% and 1000%
    else:
        guess = 0.1
    
    # Newton-Raphson iteration
    rate = guess
    for _ in range(100):
        # Guard against invalid rates that would cause math errors
        if rate <= -1.0:
            # If we get an invalid rate, fallback to bisection method
            break
            
        npv_val = npv(rate)
        if abs(npv_val) < 1e-6:
            return rate
        deriv = npv_derivative(rate)
        if abs(deriv) < 1e-10:
            break
        rate_new = rate - npv_val / deriv
        # Guard against rate_new going below -1
        if rate_new <= -1.0:
            rate_new = -0.99  # Stay in valid range
        if abs(rate_new - rate) < 1e-8:
            return rate_new
        rate = rate_new
    
    # Fallback: secant method
    rate_low, rate_high = -0.99, 10.0
    npv_low, npv_high = npv(rate_low), npv(rate_high)
    if npv_low * npv_high > 0:
        return None
    for _ in range(50):
        rate_mid = (rate_low + rate_high) / 2
        npv_mid = npv(rate_mid)
        if abs(npv_mid) < 1e-6:
            return rate_mid
        if npv_low * npv_mid <= 0:
            rate_high, npv_high = rate_mid, npv_mid
        else:
            rate_low, npv_low = rate_mid, npv_mid
    return (rate_low + rate_high) / 2


def reconcile_cas_holdings_with_transactions(holdings: List[HoldingItem], transactions_path: Path) -> Dict[str, Any]:
    """Reconcile aggregated CAS units to transaction history by exact normalized scheme name.

    Rows across multiple folios are aggregated before comparison. Substring/fuzzy
    matching is deliberately prohibited: unresolved identities are discrepancies.
    """
    import re

    if not transactions_path.exists():
        return {"status": "NO_TRANSACTION_FILE", "reconciled_schemes": 0,
                "total_schemes": len(holdings), "discrepancies": [],
                "unmatched_transaction_schemes": []}
    try:
        with open(transactions_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("transactions"), list):
            raise ValueError("transactions.json must contain a transactions array")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return {"status": "READ_ERROR", "error": str(exc), "reconciled_schemes": 0,
                "total_schemes": len(holdings), "discrepancies": [],
                "unmatched_transaction_schemes": []}

    def key(value: Any) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    cas_units: Dict[str, float] = {}
    cas_names: Dict[str, str] = {}
    for holding in holdings:
        scheme_name = getattr(holding, "scheme", None)
        scheme_key = key(scheme_name)
        try:
            units = float(getattr(holding, "units"))
        except (TypeError, ValueError, AttributeError):
            return {"status": "INVALID_CAS_UNITS", "reconciled_schemes": 0,
                    "total_schemes": len(holdings), "discrepancies": [],
                    "unmatched_transaction_schemes": []}
        if not scheme_key or not math.isfinite(units) or units < 0:
            return {"status": "INVALID_CAS_UNITS", "reconciled_schemes": 0,
                    "total_schemes": len(holdings), "discrepancies": [],
                    "unmatched_transaction_schemes": []}
        cas_units[scheme_key] = cas_units.get(scheme_key, 0.0) + units
        cas_names.setdefault(scheme_key, str(scheme_name))

    transaction_units: Dict[str, float] = {}
    transaction_names: Dict[str, str] = {}
    supported_types = {"PURCHASE", "SIP", "SWITCH_IN", "STP_IN", "DIVIDEND_REINVEST",
                       "DIVIDEND", "REDEMPTION", "SWITCH_OUT", "STP_OUT"}
    for index, transaction in enumerate(data["transactions"]):
        if not isinstance(transaction, dict):
            return {"status": "INVALID_TRANSACTION", "error": f"Transaction row {index} is not an object",
                    "reconciled_schemes": 0, "total_schemes": len(holdings),
                    "discrepancies": [], "unmatched_transaction_schemes": []}
        scheme_name = transaction.get("scheme")
        scheme_key = key(scheme_name)
        txn_type = str(transaction.get("type", "PURCHASE")).upper()
        try:
            units = float(transaction.get("units", 0.0) or 0.0)
        except (TypeError, ValueError):
            units = float("nan")
        if (not scheme_key or txn_type not in supported_types or not math.isfinite(units)
                or units < 0.0):
            return {"status": "INVALID_TRANSACTION", "error": f"Invalid scheme, type or units at transaction row {index}",
                    "reconciled_schemes": 0, "total_schemes": len(holdings),
                    "discrepancies": [], "unmatched_transaction_schemes": []}
        if txn_type == "DIVIDEND":
            sign = 0.0  # Cash payout does not change mutual-fund units.
        else:
            sign = -1.0 if txn_type in {"REDEMPTION", "SWITCH_OUT", "STP_OUT"} else 1.0
        transaction_units[scheme_key] = transaction_units.get(scheme_key, 0.0) + sign * units
        transaction_names.setdefault(scheme_key, str(scheme_name))

    discrepancies = []
    reconciled_count = 0
    for scheme_key, cas_total in cas_units.items():
        if scheme_key not in transaction_units:
            discrepancies.append({"scheme": cas_names[scheme_key], "cas_units": round(cas_total, 3),
                                  "transaction_units": None, "difference": None,
                                  "reason": "NO_EXACT_TRANSACTION_SCHEME_MATCH"})
            continue
        tx_total = transaction_units[scheme_key]
        difference = cas_total - tx_total
        if abs(difference) <= 0.05:
            reconciled_count += 1
        else:
            discrepancies.append({"scheme": cas_names[scheme_key], "cas_units": round(cas_total, 3),
                                  "transaction_units": round(tx_total, 3),
                                  "difference": round(difference, 3), "reason": "UNIT_MISMATCH"})

    unmatched_active = []
    for scheme_key, tx_total in transaction_units.items():
        if scheme_key not in cas_units and abs(tx_total) > 0.05:
            unmatched_active.append({"scheme": transaction_names[scheme_key],
                                     "transaction_units": round(tx_total, 3),
                                     "reason": "ACTIVE_TRANSACTION_SCHEME_NOT_IN_CAS"})
    status = "VERIFIED_RECONCILED" if not discrepancies and not unmatched_active else "PARTIALLY_RECONCILED"
    return {"status": status, "reconciled_schemes": reconciled_count,
            "total_schemes": len(cas_units), "discrepancies": discrepancies,
            "unmatched_transaction_schemes": unmatched_active}


def calculate_portfolio_xirr(
    transactions_path: Path,
    holdings: Any,
    cas_invested: Optional[float] = None,
    cas_current: Optional[float] = None,
    as_of_date: Optional[date] = None
) -> Optional[float]:
    """
    Calculate portfolio-level XIRR from transaction history.
    
    Supports both Pydantic HoldingItem models and raw dictionary holdings.
    Handles all CAS transaction types: PURCHASE, SIP, REDEMPTION, SWITCH_IN, SWITCH_OUT, STP_IN, STP_OUT, DIVIDEND.
    
    Args:
        transactions_path: Path to transactions.json
        holdings: Current holdings (List of HoldingItem or List of dict)
        cas_invested: Optional pre-aggregated invested amount from CAS
        cas_current: Optional pre-aggregated current valuation from CAS
        as_of_date: Valuation date (defaults to max transaction date or today)
        
    Returns:
        Portfolio XIRR as decimal (e.g. 0.1582 for 15.82%), or None if insufficient data
    """
    if not transactions_path.exists():
        return None
    
    try:
        with open(transactions_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return None
    
    transactions = data.get('transactions', [])
    if not transactions:
        return None
    
    cashflows = []
    txn_dates = []
    for txn in transactions:
        try:
            d_str = txn.get('date', '')
            if not d_str:
                continue
            txn_date = datetime.strptime(d_str[:10], '%Y-%m-%d').date()
            amount = float(txn.get('amount', 0))
            txn_type = txn.get('type', '').upper()
            desc = txn.get('description', '').lower()
            
            # Skip zero-amount non-financial transactions (address/nominee updates)
            if amount == 0:
                continue
                
            txn_dates.append(txn_date)
            is_reversal = any(kw in desc for kw in ('reversal', 'dishonour', 'reject'))
            
            # In CAS statements, amounts follow accounting conventions:
            # - Negative amount: money leaving scheme (redemption, switch out, purchase reversal) -> positive cashflow: -amount
            # - Positive amount: money entering scheme (purchase, SIP, switch in, redemption reversal) -> negative cashflow: -amount
            if amount < 0:
                cf = -amount
            else:
                if txn_type in ('REDEMPTION', 'SWITCH_OUT', 'STP_OUT', 'DIVIDEND', 'SWP') and not is_reversal:
                    cf = abs(amount)
                else:
                    cf = -amount
            cashflows.append((txn_date, cf))
        except Exception:
            continue
            
    if not cashflows:
        return None
        
    if as_of_date is None:
        as_of_date = max(txn_dates) if txn_dates else date.today()
    
    # Terminal valuation cashflow (positive = investor's net worth)
    if cas_current is not None and cas_current > 0:
        total_value = float(cas_current)
    else:
        total_value = 0.0
        for h in (holdings or []):
            if isinstance(h, dict):
                v = float(h.get("value", h.get("current_value", 0.0)) or 0.0)
            else:
                v = float(getattr(h, "current_value_inr", 0.0) or 0.0)
            if v > 0:
                total_value += v

    if total_value > 0:
        cashflows.append((as_of_date, total_value))
    
    if len(cashflows) < 2:
        return None
    
    return calculate_xirr(cashflows)




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


def _asset_class_to_risk_tier(asset_class: AssetClass) -> str:
    """Map AssetClass to SEBI risk-o-meter tier."""
    mapping = {
        AssetClass.DEBT: "Tier 1 (Low)",
        AssetClass.CASH: "Tier 1 (Low)",
        AssetClass.HYBRID_BALANCED: "Tier 3 (Moderate)",
        AssetClass.HYBRID: "Tier 3 (Moderate)",
        AssetClass.LARGE_CAP: "Tier 5 (High)",
        AssetClass.FLEXI_CAP: "Tier 5 (High)",
        AssetClass.MULTI_CAP: "Tier 5 (High)",
        AssetClass.INTERNATIONAL: "Tier 5 (High)",
        AssetClass.MID_CAP: "Tier 6 (Very High)",
        AssetClass.SMALL_CAP: "Tier 6 (Very High)",
        AssetClass.OTHER: "Tier 3 (Moderate)",
    }
    return mapping.get(asset_class, "Tier 3 (Moderate)")

# Import the new simplified SAA utilities
from core.models import RiskTier, AssetAllocationTarget, SAA_POLICY_MAP

def get_target_allocation(tier: RiskTier, custom_target: AssetAllocationTarget = None) -> AssetAllocationTarget:
    """
    Returns the exact target allocation based on the 3+1 logic.
    """
    if tier == RiskTier.CUSTOM:
        if not custom_target:
            raise ValueError("Custom Tier selected but no custom target provided.")
        return custom_target
        
    return SAA_POLICY_MAP[tier]


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
) -> List[HoldingItem]:
    """
    Parses active mutual fund holdings directly from CAS detailed report Excel sheet.
    Reconciles with fund_metrics.json for expense ratios, market-cap splits, and top stock holdings.
    """
    if not xlsx_path.exists():
        raise FileNotFoundError(f"CAS statement not found: {xlsx_path}")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    if "Portfolio Details" not in wb.sheetnames:
        raise ValueError("Invalid CAS workbook: missing 'Portfolio Details' sheet.")

    sheet = wb["Portfolio Details"]

    # Load metrics dictionary if provided
    metrics_map = {}
    if fund_metrics_path and fund_metrics_path.exists():
        with open(fund_metrics_path, "r", encoding="utf-8") as f:
            m_data = json.load(f)
            for m in m_data.get("funds", []):
                fid = m.get("id", "").strip().lower()
                metrics_map[fid] = m

    # Load aliases dictionary if provided
    aliases_map = {}
    if fund_aliases_path and fund_aliases_path.exists():
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
    hdr = None
    start_row = None
    for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        vals = [str(c).strip() if c is not None else "" for c in row]
        if "Scheme Name" in vals:
            non_empty = [name for name in vals if name]
            if len(non_empty) != len(set(non_empty)):
                raise ValueError("Invalid CAS workbook: duplicate column headers in 'Portfolio Details'.")
            hdr = {name: i for i, name in enumerate(vals) if name}
            start_row = row_idx + 1
            break

    required_headers = {"Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"}
    if hdr is None:
        raise ValueError("Invalid CAS workbook: no 'Scheme Name' header found in 'Portfolio Details'.")
    missing_headers = sorted(required_headers - set(hdr))
    if missing_headers:
        raise ValueError(
            "Invalid CAS workbook: missing required 'Portfolio Details' columns: "
            + ", ".join(missing_headers)
        )

    col_scheme = hdr["Scheme Name"]
    col_folio = hdr["Folio No."]
    col_inv = hdr["Invested Value"]
    col_cur = hdr["Current Value"]
    col_units = hdr["Units"]
    col_amc = hdr.get("AMC Name")

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
            c_float = float(c_val)
            i_float = float(i_val)
            u_float = float(u_val)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Invalid CAS workbook: malformed financial values for scheme {str(s_name).strip()!r}."
            ) from exc
        if not all(math.isfinite(value) for value in (i_float, c_float, u_float)):
            raise ValueError(
                f"Invalid CAS workbook: non-finite financial values for scheme {str(s_name).strip()!r}."
            )
        if i_float < 0 or c_float < 0 or u_float < 0:
            raise ValueError(
                f"Invalid CAS workbook: negative financial values for scheme {str(s_name).strip()!r}."
            )
        if c_float > 0.0:
            if u_float <= 0.0:
                raise ValueError(
                    f"Invalid CAS workbook: positive current value requires positive units for scheme {str(s_name).strip()!r}."
                )
            nav_float = round(c_float / u_float, 4)
            amc_value = row[col_amc] if col_amc is not None and len(row) > col_amc else ""
            raw_items.append((str(s_name).strip(), str(f_no).strip() if f_no else "", i_float, c_float, u_float, nav_float, str(amc_value or "").strip()))

    for scheme_str, folio_str, invested, current, units_val, nav_val, amc_name in raw_items:
        # Plan detection
        scheme_lower = scheme_str.lower()
        plan = PlanType.DIRECT if "direct" in scheme_lower else PlanType.REGULAR
        is_direct = plan == PlanType.DIRECT

        # Exact identity / reviewed-alias match only. Never invent an equity
        # classification for an unmatched CAS scheme.
        matched_metric = _find_matching_metric(scheme_str, metrics_map, aliases_map)
        if matched_metric is None:
            raise ValueError(
                f"CAS scheme {scheme_str!r} has no unambiguous exact match in fund metrics; "
                "add a reviewed alias or verified scheme identity before SIP analysis."
            )

        category = matched_metric.get("cat")
        er = float(matched_metric.get("er", 0.75)) if matched_metric else (0.85 if plan == PlanType.DIRECT else 1.90)
        
        # If Regular plan and only Direct ER is in dataset, estimate regular fee = direct ER + 1.05%
        if plan == PlanType.REGULAR and matched_metric:
            er = er + 1.05

        top_h = matched_metric.get("h", []) if matched_metric else []
        sharpe = matched_metric.get("sharpe") if matched_metric else None

        # Market-cap split
        required_exposure_fields = ("eq", "debt", "lc", "mc", "sc")
        missing_exposure_fields = [field for field in required_exposure_fields if matched_metric.get(field) is None]
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

        fund_id = matched_metric.get("id", scheme_str[:30]) if matched_metric else scheme_str[:30]
        identity = {"scheme_id": None, "isin": None, "status": "MISSING",
                    "reason": "No verified scheme master was supplied."}
        if scheme_master is not None and scheme_master_source_bytes is not None and amc_name:
            from ingestion.portfolio_disclosure import resolve_scheme_identity
            identity = resolve_scheme_identity(
                {"scheme": scheme_str, "amc_name": amc_name},
                scheme_master,
                source_bytes=scheme_master_source_bytes,
            )

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
                amc_name=amc_name or None,
                risk_tier=_asset_class_to_risk_tier(asset_class),
            )
        )

    return holdings


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
    """
    cat_lower = str(cat or "").casefold().replace("_", " ").replace("-", " ")
    if any(token in cat_lower for token in ("debt", "liquid", "money market", "gilt", "bond")) or debt >= 75.0:
        return AssetClass.DEBT_LIQUID
    if any(token in cat_lower for token in ("balanced", "hybrid", "dynamic asset", "multi asset")) or debt >= 20.0:
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
    # Only use disclosed market-cap weights when the scheme category is absent
    # or genuinely generic. Never infer Flexi Cap from a high equity percentage.
    if sc >= 50.0:
        return AssetClass.SMALL_CAP
    if mc >= 50.0:
        return AssetClass.MID_CAP
    if lc >= 50.0:
        return AssetClass.LARGE_CAP
    if eq <= 0.0 and debt > 0.0:
        return AssetClass.DEBT_LIQUID
    return AssetClass.EQUITY


def calculate_fee_bleed(holdings: List[HoldingItem], default_commission_rate: float = 0.0105) -> FeeBleedAnalysis:
    """
    Computes exact annual commission drag for Regular plan holdings.
    Also calculates 10-year compounded opportunity loss at 12% CAGR.
    """
    regular_holdings = [h for h in holdings if h.plan == PlanType.REGULAR]
    total_regular_val = sum(h.current_value_inr for h in regular_holdings)

    details = []
    annual_bleed = 0.0

    for h in regular_holdings:
        # Typical distributor trail commission delta is ~1.05% per year
        fund_bleed = h.current_value_inr * default_commission_rate
        annual_bleed += fund_bleed
        details.append({
            "fund_name": h.fund_name,
            "folio_no": h.folio,
            "current_value_inr": round(h.current_value_inr, 2),
            "estimated_annual_commission_inr": round(fund_bleed, 2),
            "expense_ratio_pct": round(h.expense_ratio_pct, 2)
        })

    # Sort details by commission bleed descending
    details.sort(key=lambda x: x["estimated_annual_commission_inr"], reverse=True)

    # 10-year compounding lost wealth: annuity factor at 12% CAGR over 10 years
    # Sum_{t=1}^{10} (1.12)^t = 1.12 * ((1.12^10 - 1) / 0.12) = 19.65
    # Future value of annuity due = Annual * [((1+r)^n - 1)/r] * (1+r)
    r = 0.12
    n = 10
    annuity_factor = (((1.0 + r) ** n - 1.0) / r) * (1.0 + r)
    ten_year_compounded_loss = annual_bleed * annuity_factor

    return FeeBleedAnalysis(
        annual_commission_leakage_inr=round(annual_bleed, 2),
        ten_year_compounded_loss_inr=round(ten_year_compounded_loss, 2),
        regular_funds_count=len(regular_holdings),
        regular_funds=details,
        direct_alternatives={}
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
        "REDEMPTION", "SWITCH_OUT", "STP_OUT", "DIVIDEND",
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
            if amount >= 0 or units >= 0:
                raise ValueError(f"Redemption/switch-out row {index} must have negative amount and units")
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
    Computes pairwise stock overlap among equity funds holding stock disclosures.
    Flags pairs with overlap >= threshold_pct (default 25%).
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
    """
    Calculates current asset allocation vs target Strategic Asset Allocation (SAA).
    Incorporates underlying look-through stability buffer (debt + cash).
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
            look_through_debt_inr=0.0,
            look_through_cash_inr=0.0,
            look_through_stability_buffer_pct=0.0,
        )

    # Compute look-through equity, debt, and cash amounts
    equity_val = 0.0
    debt_val = 0.0
    cash_val = 0.0

    for h in holdings:
        eq_amt = h.current_value_inr * (h.equity_pct / 100.0)
        db_amt = h.current_value_inr * (h.debt_pct / 100.0)
        c_pct = max(0.0, 100.0 - h.equity_pct - h.debt_pct)
        c_amt = h.current_value_inr * (c_pct / 100.0)
        equity_val += eq_amt
        debt_val += db_amt
        cash_val += c_amt

    curr_eq_pct = (equity_val / total_val) * 100.0
    curr_db_pct = (debt_val / total_val) * 100.0
    curr_cash_pct = (cash_val / total_val) * 100.0
    stability_buffer_pct = curr_db_pct + curr_cash_pct

    # Dynamic target resolution supporting Tier 6 and granular allocations
    if target_saa:
        tgt_db = target_saa.get("debt_liquid_pct", target_saa.get("debt_global_pct", 5.0))
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
        else:
            tgt_eq = 100.0 - tgt_db
    else:
        tgt_eq = 95.0
        tgt_db = 5.0

    eq_drift = curr_eq_pct - tgt_eq
    stability_satisfied = stability_buffer_pct >= (tgt_db - 1.0)
    rebalance_required = abs(eq_drift) > tolerance_band_pct and not stability_satisfied

    # Gap in rupees to reach target
    target_eq_inr = total_val * (tgt_eq / 100.0)
    target_db_inr = total_val * (tgt_db / 100.0)
    equity_gap_inr = target_eq_inr - equity_val
    debt_gap_inr = 0.0 if stability_satisfied else (target_db_inr - debt_val)

    return SAADriftAnalysis(
        current_equity_pct=round(curr_eq_pct, 1),
        current_debt_pct=round(curr_db_pct, 1),
        current_cash_pct=round(curr_cash_pct, 1),
        current_equity_inr=round(equity_val, 2),
        current_debt_inr=round(debt_val, 2),
        target_equity_pct=round(tgt_eq, 1),
        target_debt_pct=round(tgt_db, 1),
        tolerance_band_pct=tolerance_band_pct,
        rebalance_required=rebalance_required,
        equity_gap_inr=round(equity_gap_inr, 2),
        debt_gap_inr=round(debt_gap_inr, 2),
        look_through_debt_inr=round(debt_val, 2),
        look_through_cash_inr=round(cash_val, 2),
        look_through_stability_buffer_pct=round(stability_buffer_pct, 2),
    )


def parse_cas(xlsx_path: Path, scheme_master: Optional[Dict[str, Any]] = None, scheme_master_source_bytes: Optional[bytes] = None) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Parses 'Portfolio Details' sheet from CAS Excel report.
    Hard Guard: Enforces single valuation date across all folios.
    """
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb["Portfolio Details"]
    
    as_of_date = ""
    dates_found = set()
    hdr = None
    holdings = []

    for row in ws.iter_rows(values_only=True):
        vals = [str(c).strip() if c is not None else "" for c in row]
        if not any(vals):
            continue
            
        if vals[0] == "To Date":
            as_of_date = vals[1]
            dates_found.add(vals[1])
        elif vals[0] == "Scheme Name":
            hdr = {name: i for i, name in enumerate(vals) if name}
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
                    "is_direct": "direct" in scheme_name.lower(),
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


def compute_liquidity_waterfall(bank_balance: float, monthly_expenses: float, months_reserve: float = 6.0) -> Tuple[float, float]:
    """
    Guards emergency buffer before investment.
    Deployable_Surplus = max(0, bank_balance - (monthly_expenses * months_reserve))
    """
    emergency_reserve = round(monthly_expenses * months_reserve, 2)
    deployable_surplus = max(0.0, round(bank_balance - emergency_reserve, 2))
    return emergency_reserve, deployable_surplus


def calculate_cash_deployment(
    bank_cash_inr: float = 0.0,
    emergency_buffer_inr: float = 0.0,
    stp_months: int = 6,
    emergency_months: float = 6.0,
) -> CashDeploymentPlan:
    """
    Computes cash deployment waterfall for bank balances.
    Allocates emergency reserve first, then spreads deployable surplus via STP.
    """
    deployable = max(0.0, bank_cash_inr - emergency_buffer_inr)
    stp_monthly = deployable / stp_months if stp_months > 0 else 0.0

    return CashDeploymentPlan(
        total_cash_inr=round(bank_cash_inr, 2),
        emergency_reserve_inr=round(emergency_buffer_inr, 2),
        emergency_months=emergency_months,
        deployable_surplus_inr=round(deployable, 2),
        stp_recommendation=None,
        stp_monthly_amount_inr=round(stp_monthly, 2),
        stp_duration_months=stp_months,
        stp_source_fund=None,
        stp_target_fund=None,
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


def _validated_ips_numeric_inputs(ips: Dict[str, Any]) -> Tuple[float, float, float]:
    """Validate investor-entered SIP/lumpsum/reserve inputs without bool coercion."""
    if not isinstance(ips, dict):
        raise ValueError("IPS inputs must be an object")
    if "monthly_sip_budget" not in ips:
        raise ValueError("Explicit ips.monthly_sip_budget is required; no default SIP budget is permitted")
    keys = ("monthly_sip_budget", "lumpsum_budget", "emergency_months")
    if any(isinstance(ips.get(key), bool) for key in keys if key in ips):
        raise ValueError("IPS monetary and emergency-month inputs must not be booleans")
    try:
        monthly_sip = float(ips["monthly_sip_budget"])
        lumpsum_budget = float(ips.get("lumpsum_budget", 0.0))
        emergency_months = float(ips.get("emergency_months", 6.0))
    except (TypeError, ValueError) as exc:
        raise ValueError("IPS SIP, lumpsum and emergency-month inputs must be numeric") from exc
    if not math.isfinite(monthly_sip) or monthly_sip <= 0.0:
        raise ValueError("IPS monthly_sip_budget must be finite and greater than zero")
    if not math.isfinite(lumpsum_budget) or lumpsum_budget < 0.0:
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

    tot_cur = sum(h.current_value_inr for h in holdings)
    tot_inv = sum(h.invested_value_inr for h in holdings)
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
    bank_cash_cfg = 0.0
    emergency_reserve_cfg = 0.0
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as cf:
            cdata = json.load(cf).get("cash", {})
            bank_cash_cfg = float(cdata.get("bank_cash_total", 0.0))
            emergency_reserve_cfg = float(cdata.get("emergency_reserve", 0.0))

    cash = calculate_cash_deployment(
        bank_cash_inr=bank_cash_cfg,
        emergency_buffer_inr=emergency_reserve_cfg,
        emergency_months=emergency_months
    )

    # Look-through stability and thematic exposures
    stability_buf = calculate_lookthrough_stability_buffer(
        holdings=holdings,
        bank_cash_inr=bank_cash_cfg,
        emergency_reserve_inr=emergency_reserve_cfg,
        target_debt_pct=saa.target_debt_pct
    )
    thematic_exps = calculate_thematic_exposures(holdings, metrics_path, aliases_path)
    # Keep the already validated risk profile from the IPS; do not overwrite it.

    neglected_themes = [th for th in thematic_exps if th.coverage_status == "NEGLECTED"]
    if neglected_themes:
        neglected_themes.sort(key=lambda x: x.dedicated_funds_pct + x.look_through_stocks_pct)
        deficit_theme = neglected_themes[0].theme_name
    else:
        deficit_theme = "Pharma"

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
    portfolio_xirr = calculate_portfolio_xirr(transactions_path, holdings)
    cas_recon = reconcile_cas_holdings_with_transactions(holdings, transactions_path)
    tax_lots_summary = None

    # Transaction history is optional for a CAS-only portfolio snapshot. If a
    # supplied history is malformed or does not reconcile, however, it cannot
    # be ignored while issuing a portfolio-aware SIP proposal.
    if transactions_path.exists() and cas_recon.get("status") != "VERIFIED_RECONCILED":
        det_sip_plan.unallocated_budget_inr = det_sip_plan.total_monthly_budget_inr
        for sip_item in det_sip_plan.items:
            sip_item.monthly_inr = 0.0
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
        "Redemptions frozen pending April 2027 review",
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
            "April 2027 review. Orders are non-actionable conditional scenarios."
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

    eligible_candidates = []
    for cand in candidate_universe:
        gate_result = check_eligibility_gates(
            fund_data=cand,
            portfolio_holdings=current_portfolio_summary,
            client_risk_tier_num=tier_num,
            is_starter=(tot_cur > 0 and tot_cur < 500000.0)
        )
        cand["eligibility"] = {
            "passed": gate_result.passed,
            "failed_gates": gate_result.failed_gates,
            "details": gate_result.details
        }
        if gate_result.passed:
            eligible_candidates.append(cand)
    
    # Mandatory NO ACTION Fiduciary Branch
    no_action_decision = evaluate_no_action(holdings, eligible_candidates)
    
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

def calculate_weighted_lookthrough_overlap(
    holdings: List[HoldingItem],
    metrics_path: Optional[Path] = None,
    threshold_pct: float = 10.0
) -> List[WeightedOverlapResult]:
    """
    Calculate weighted look-through overlap using actual top-10 holding weights from fund_metrics.json.
    
    The fund_metrics.json contains top-10 holdings and their percentage of portfolio (top10 field).
    We assume equal weight within the top-10 holdings: each stock = top10% / 10.
    """
    # Load fund metrics for actual top-10 weights
    fund_metrics: Dict[str, Dict] = {}
    if metrics_path and metrics_path.exists():
        try:
            with open(metrics_path, "r", encoding="utf-8") as f:
                m_data = json.load(f)
                for m in m_data.get("funds", []):
                    fund_id = m.get("id", "")
                    if fund_id:
                        top10_pct = m.get("top10", 0.0)
                        top_holdings = m.get("h", [])
                        # Weight per stock = top10% / 10 (assuming equal weight within top-10)
                        weight_per_stock = top10_pct / 10.0 if top_holdings else 0.0
                        fund_metrics[fund_id] = {
                            "top10_pct": top10_pct,
                            "top_holdings": top_holdings,
                            "weight_per_stock": weight_per_stock
                        }
        except Exception:
            pass
    
    stock_fund_weights: Dict[str, Dict[str, float]] = {}
    fund_total_value: Dict[str, float] = {}
    
    for h in holdings:
        if not h.top_holdings:
            continue
        fund_total_value[h.fund_id] = h.current_value_inr
        
        # Get actual weight per stock from fund_metrics
        metrics = fund_metrics.get(h.fund_id, {})
        weight_per_stock = metrics.get("weight_per_stock", 0.0)
        top_holdings = metrics.get("top_holdings", h.top_holdings)
        
        for stock in top_holdings:
            if stock not in stock_fund_weights:
                stock_fund_weights[stock] = {}
            stock_fund_weights[stock][h.fund_id] = weight_per_stock
    
    fund_ids = list(fund_total_value.keys())
    results = []
    
    for i in range(len(fund_ids)):
        for j in range(i + 1, len(fund_ids)):
            fa = fund_ids[i]
            fb = fund_ids[j]
            
            shared_stocks = []
            weighted_overlap = 0.0
            sector_weights: Dict[str, float] = {}
            
            for stock, fund_weights in stock_fund_weights.items():
                if fa in fund_weights and fb in fund_weights:
                    weight_a = fund_weights[fa]
                    weight_b = fund_weights[fb]
                    combined = weight_a + weight_b
                    
                    shared_stocks.append({
                        "stock": stock,
                        "weight_a_pct": round(weight_a, 2),
                        "weight_b_pct": round(weight_b, 2),
                        "combined_weight_pct": round(combined, 2)
                    })
                    weighted_overlap += min(weight_a, weight_b)
            
            if not shared_stocks:
                continue
            
            set_a = set(stock for stock in stock_fund_weights if fa in stock_fund_weights[stock])
            set_b = set(stock for stock in stock_fund_weights if fb in stock_fund_weights[stock])
            jaccard = len(set_a & set_b) / len(set_a | set_b) if (set_a | set_b) else 0
            
            if weighted_overlap >= 20.0:
                verdict = "HIGH_CONCENTRATION"
            elif weighted_overlap >= 10.0:
                verdict = "MODERATE"
            else:
                verdict = "ACCEPTABLE"
            
            if weighted_overlap >= threshold_pct:
                results.append(WeightedOverlapResult(
                    fund_a=fa,
                    fund_b=fb,
                    weighted_overlap_pct=round(weighted_overlap, 2),
                    jaccard_similarity=round(jaccard * 100, 2),
                    shared_stocks=shared_stocks,
                    sector_concentration=sector_weights,
                    verdict=verdict
                ))
    
    results.sort(key=lambda x: x.weighted_overlap_pct, reverse=True)
    return results


def calculate_risk_distribution(
    holdings: List[HoldingItem]
) -> RiskDistribution:
    tier_counts: Dict[str, int] = {}
    tier_values: Dict[str, float] = {}
    total_value = sum(h.current_value_inr for h in holdings)
    
    for h in holdings:
        tier = getattr(h, 'risk_tier', None)
        if tier is None:
            tier = 'Unknown'
        if tier not in tier_counts:
            tier_counts[tier] = 0
            tier_values[tier] = 0.0
        tier_counts[tier] += 1
        tier_values[tier] += h.current_value_inr
    
    tier_pct = {t: round((v / total_value) * 100, 2) for t, v in tier_values.items()} if total_value > 0 else {}
    
    return RiskDistribution(
        risk_tier_distribution=tier_counts,
        risk_tier_values=tier_pct,
        portfolio_beta=None,
        max_drawdown_pct=None,
        downside_capture_ratio=None,
        volatility_annualized_pct=None
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
    sip_budget_inr: float
) -> SAA_DriftMinimizer:
    total_val = sum(h.current_value_inr for h in holdings)
    if total_val <= 0:
        return SAA_DriftMinimizer(
            current_allocation={},
            target_allocation=target_allocation,
            sip_budget_inr=sip_budget_inr,
            recommended_sip_allocation={},
            drift_after_sip={},
            total_drift_l2_norm=0.0
        )
    
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
            equity_val = h.current_value_inr * (h.equity_pct / 100.0)
            debt_val = h.current_value_inr * (h.debt_pct / 100.0)
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
        current_alloc[alloc_category] += h.current_value_inr
    
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
    
    positive_gaps = {k: v for k, v in gaps.items() if v > 0}
    total_positive_gap = sum(positive_gaps.values())
    
    sip_alloc = {}
    if total_positive_gap > 0:
        for asset, gap in positive_gaps.items():
            sip_alloc[asset] = sip_budget_inr * (gap / total_positive_gap)
    else:
        for asset in target_pct:
            sip_alloc[asset] = sip_budget_inr / len(target_pct)
    
    new_total = total_val + sip_budget_inr
    projected_alloc = {}
    for asset in set(current_pct) | set(target_pct):
        current_val = current_alloc.get(asset, 0)
        sip_val = sip_alloc.get(asset, 0)
        projected_alloc[asset] = ((current_val + sip_val) / new_total) * 100
    
    drift = {k: projected_alloc.get(k, 0) - target_pct.get(k, 0) for k in target_pct}
    l2_norm = math.sqrt(sum(d * d for d in drift.values()))
    
    return SAA_DriftMinimizer(
        current_allocation=current_pct,
        target_allocation=target_pct,
        sip_budget_inr=sip_budget_inr,
        recommended_sip_allocation=sip_alloc,
        drift_after_sip=drift,
        total_drift_l2_norm=round(l2_norm, 2)
    )


# check_eligibility_gates and evaluate_no_action are imported directly from core.eligibility
# (Module 4: Hard Binary Selection Gates & NO ACTION Engine)

def calculate_lookthrough_stability_buffer(
    holdings: List[HoldingItem],
    bank_cash_inr: float = 0.0,
    emergency_reserve_inr: float = 0.0,
    target_debt_pct: float = 5.0,
) -> LookThroughStabilityBuffer:
    """Calculates look-through debt, cash, and total stability buffer across portfolio."""
    total_val = sum(h.current_value_inr for h in holdings)
    if total_val <= 0:
        return LookThroughStabilityBuffer()

    embedded_debt = sum(h.current_value_inr * (h.debt_pct / 100.0) for h in holdings)
    embedded_cash = sum(
        h.current_value_inr * max(0.0, 100.0 - h.equity_pct - h.debt_pct) / 100.0
        for h in holdings
    )

    deployable_cash = max(0.0, bank_cash_inr - emergency_reserve_inr)
    total_stability = embedded_debt + embedded_cash

    total_stability_pct = (total_stability / total_val) * 100.0
    meets_target = total_stability_pct >= (target_debt_pct - 1.0)

    return LookThroughStabilityBuffer(
        embedded_debt_inr=round(embedded_debt, 2),
        embedded_debt_pct=round((embedded_debt / total_val) * 100.0, 2),
        embedded_cash_inr=round(embedded_cash, 2),
        embedded_cash_pct=round((embedded_cash / total_val) * 100.0, 2),
        bank_deployable_cash_inr=round(deployable_cash, 2),
        emergency_reserve_inr=round(emergency_reserve_inr, 2),
        total_stability_buffer_inr=round(total_stability, 2),
        total_stability_buffer_pct=round(total_stability_pct, 2),
        meets_tier_target=meets_target,
    )


def calculate_thematic_exposures(
    holdings: List[HoldingItem],
    metrics_path: Optional[Path] = None,
    aliases_path: Optional[Path] = None,
) -> List[ThematicExposureItem]:
    """Calculates dedicated fund and look-through stock exposure across 5 core themes."""
    total_val = sum(h.current_value_inr for h in holdings)
    if total_val <= 0:
        return []

    themes_def = {
        "Defence Thematic": {
            "stocks": {
                "Hindustan Aeronautics", "Bharat Electronics", "Bharat Forge",
                "Solar Industries", "Mazagon Dock", "Astra Microwave", "BEML",
                "MTAR Technologies", "Cochin Shipyard", "Bharat Dynamics", "Data Patterns"
            },
            "keywords": ["defence"],
        },
        "Commodities / Metals": {
            "stocks": {
                "Coal India", "Lloyds Metals", "Jindal Steel", "Vedanta",
                "Dalmia Bharat", "Ultratech Cement", "Multi Commodity Exch"
            },
            "keywords": ["commodity", "commodities", "metal", "gold", "silver"],
        },
        "PSU & CPSE Themes": {
            "stocks": {
                "State Bank of India", "NTPC", "Power Grid", "Coal India",
                "ONGC", "GAIL", "Bharat Petroleum", "HPCL", "Indian Bank",
                "Bharat Heavy Electricals", "Petronet LNG", "Gujarat Energy",
                "Hindustan Aeronautics", "Bharat Electronics", "Mazagon Dock"
            },
            "keywords": ["psu", "cpse"],
        },
        "Pharma & Healthcare": {
            "stocks": {
                "Sun Pharma", "Cipla", "Dr. Reddy", "Divi", "Apollo Hospitals",
                "Aurobindo Pharma", "Ipca Laboratories", "Glenmark Pharma",
                "Fortis Healthcare", "Gland Pharma", "Ajanta Pharma", "Torrent Pharma", "Lupin"
            },
            "keywords": ["pharma", "healthcare"],
        },
        "Power & Infrastructure": {
            "stocks": {
                "Larsen & Toubro", "NTPC", "Power Grid", "Adani Power",
                "Adani Green Energy", "Bharat Heavy Electricals", "Thermax",
                "Kalpataru Projects", "Premier Energies", "JSW Infrastructure",
                "IRB Developers", "Kei Industries"
            },
            "keywords": ["infrastructure", "infra", "energy", "power"],
        },
    }

    funds_map = {}
    if metrics_path and metrics_path.exists():
        with open(metrics_path, "r", encoding="utf-8") as mf:
            for m in json.load(mf).get("funds", []):
                funds_map[m.get("id")] = m

    aliases_dict = {}
    if aliases_path and aliases_path.exists():
        with open(aliases_path, "r", encoding="utf-8") as af:
            aliases_dict = json.load(af).get("aliases", {})

    items = []
    for theme_name, tdata in themes_def.items():
        dedicated_inr = 0.0
        look_through_inr = 0.0
        key_stocks_found = set()

        for h in holdings:
            val = h.current_value_inr
            s_lower = h.scheme.lower()

            if any(k in s_lower for k in tdata["keywords"]):
                dedicated_inr += val

            cid = None
            for k, al in aliases_dict.items():
                if any(a.lower() in s_lower or s_lower in a.lower() for a in al):
                    cid = k
                    break
            if not cid:
                for k in funds_map:
                    if k.lower() in s_lower:
                        cid = k
                        break
            m = funds_map.get(cid, {})
            top_stocks = m.get("h", [])
            per_stock_wt = 0.045  # Equal weight proxy within top 10

            for s in top_stocks:
                if any(match in s for match in tdata["stocks"]):
                    look_through_inr += (val * per_stock_wt)
                    key_stocks_found.add(s)

        dedicated_pct = (dedicated_inr / total_val) * 100.0
        look_through_pct = (look_through_inr / total_val) * 100.0

        if dedicated_pct > 3.0 or look_through_pct > 4.0:
            status = "FULL"
        elif look_through_pct < 2.0 and dedicated_pct == 0.0:
            status = "BY_DESIGN_MINIMAL" if theme_name == "Commodities / Metals" else "NEGLECTED"
        else:
            status = "ADEQUATE"

        items.append(
            ThematicExposureItem(
                theme_name=theme_name,
                dedicated_funds_inr=round(dedicated_inr, 2),
                dedicated_funds_pct=round(dedicated_pct, 2),
                look_through_stocks_inr=round(look_through_inr, 2),
                look_through_stocks_pct=round(look_through_pct, 2),
                coverage_status=status,
                key_underlying_holdings=sorted(list(key_stocks_found))[:6],
            )
        )

    return items




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
    if tier_str == "low" or "conservative" in tier_str:
        return 2
    # The investor-facing 3-tier profile "Moderate" maps to the
    # approved middle profile (SEBI Tier 4). Explicit SEBI labels such as
    # "Tier 3 (Moderate)" have already been resolved by the Tier N parser
    # above and retain their literal Riskometer meaning.
    if tier_str == "moderate":
        return 4
    if "moderate" in tier_str and "high" not in tier_str:
        return 3
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
        elif cat_kw in ("debt", "short term", "liquid", "bond", "arbitrage"):
            if any(k in s_lower for k in ("arbitrage", "liquid", "short term", "debt")) and "balanced advantage" not in s_lower:
                return h.scheme, h.folio
    return None, None


def compute_candidate_portfolio_overlap(
    cand: Dict[str, Any],
    holdings: Optional[List[HoldingItem]] = None,
    candidate_universe: Optional[List[Dict[str, Any]]] = None
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

    def validated_weights(raw: Any, coverage_raw: Any, label: str) -> Optional[Dict[str, float]]:
        if not isinstance(raw, dict) or not raw:
            return None
        if isinstance(coverage_raw, bool):
            return None
        try:
            coverage = float(coverage_raw)
            weights = {str(k).strip().casefold(): float(v) for k, v in raw.items()}
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



def compute_multi_horizon_fiduciary_score(
    c: Dict[str, Any],
    category_key: str = "Healthcare",
    portfolio_overlap_pct: Optional[float] = None
) -> float:
    """
    Standardized 6-Pillar Fiduciary Normalized Scoring Engine (0 - 100 Scale):
    Uses Category-Relative Min-Max Normalization with regulatory anchor clamping.
    Caps momentum at 25% of total score, preventing short-term return hijacking.
    Incorporates actual candidate-to-portfolio weighted stock look-through overlap.
    """
    from core.candidate_scoring import calculate_candidate_6_pillar_score
    score, _ = calculate_candidate_6_pillar_score(c, category_key, portfolio_overlap_pct)
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
    category_key: str = "Healthcare",
    portfolio_overlap_pct: Optional[float] = None
) -> float:
    """
    Standardized 6-Pillar Fiduciary Normalized Scoring Engine (0 - 100 Scale):
    Uses Category-Relative Min-Max Normalization with regulatory anchor clamping.
    Caps momentum at 25% of total score, preventing short-term return hijacking.
    Incorporates actual candidate-to-portfolio weighted stock look-through overlap.
    """
    from core.candidate_scoring import calculate_candidate_6_pillar_score
    score, _ = calculate_candidate_6_pillar_score(c, category_key, portfolio_overlap_pct)
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
    client_risk_tier: int = 6,
    thematic_deficit_theme: str = "Pharma",
    thematic_satellite_authorized: bool = False,
    thematic_satellite_pct_of_equity: float = 0.0,
    portfolio_disclosures_by_scheme_id: Optional[Dict[str, Dict[str, Any]]] = None,
    portfolio_disclosure_source_bytes_by_scheme_id: Optional[Dict[str, bytes]] = None,
    disclosure_as_of_date: Optional[date] = None,
    disclosure_max_age_days: int = 45,
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

    if isinstance(client_risk_tier, bool):
        raise ValueError("client_risk_tier must be an integer from 1 through 6")
    if hasattr(client_risk_tier, "value"):
        tier_map = {"Conservative": 2, "Moderate": 4, "Aggressive": 6}
        risk_label = str(client_risk_tier.value)
        if risk_label == "Custom":
            raise ValueError(
                "Custom risk profile requires an explicitly approved custom SAA; "
                "it must not inherit the Aggressive/SEBI Tier 6 allocation."
            )
        tier_int = tier_map.get(risk_label)
        if tier_int is None:
            raise ValueError(f"Unsupported investor risk profile: {risk_label!r}")
    else:
        try:
            tier_int = int(client_risk_tier)
        except (TypeError, ValueError) as exc:
            raise ValueError("client_risk_tier must be an integer from 1 through 6") from exc
    if tier_int not in range(1, 7):
        raise ValueError("client_risk_tier must be an integer from 1 through 6")

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
        fund_name = candidate.get("fund_name") or candidate.get("name")
        if not isinstance(fund_id, str) or not fund_id.strip():
            raise ValueError(f"Candidate row {row_index} is missing a stable fund_id")
        if fund_id in seen_ids:
            raise ValueError(f"Duplicate candidate fund_id: {fund_id!r}")
        if not isinstance(fund_name, str) or not fund_name.strip():
            raise ValueError(f"Candidate {fund_id!r} is missing a scheme name")
        seen_ids.add(fund_id)
        normalized_candidates.append(candidate)

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
                or _reviewed_direct_plan_evidence_status(candidate) != "REVIEWER_ATTESTED_HASH_MATCH"
            ):
                continue
            gate_result = check_eligibility_gates(
                candidate,
                holdings or [],
                client_risk_tier_num=tier_int,
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
            portfolio_overlap = compute_candidate_portfolio_overlap(
                candidate,
                holdings=holdings,
            )
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
            "category": selected.get("category"),
            "score": score,
            "gate_passed": True,
            "is_direct": True,
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
            "Debt", "Liquid", "Money Market", "Debt: Short Duration"
        ),
        "no supported debt-specific ranking model and verified Direct candidate are available",
        "percent_of_total_portfolio",
    )
    return blueprint

def calculate_universal_tier_split(
    tier_num: int,
    stability_buffer_pct: Optional[float] = None,
    equity_sip_routing_override: bool = False,
) -> Tuple[float, float]:
    """
    Return the policy-defined new-SIP equity/debt split for a risk tier.

    The SAA debt target and tolerance determine the stability-buffer threshold.
    If the verified portfolio stability buffer meets that threshold, new SIPs
    may be routed 100% to equity; otherwise use the policy's explicit
    new_sip_allocation. Missing or malformed policy is a hard failure.
    """
    import json
    import math
    from pathlib import Path

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
        requires_ips_authorization = bool(sip.get("requires_explicit_ips_authorization", False))
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

    stability_threshold = max(0.0, debt_target - tolerance)
    if stability_threshold > 0.0 and stability is not None and stability >= stability_threshold:
        return 100.0, 0.0
    return equity_sip, debt_sip


def compute_deterministic_lumpsum_blueprint(
    lumpsum_amount: float,
    bank_cash_total: float = 0.0,
    emergency_reserve: float = 0.0,
    holdings: Optional[List[HoldingItem]] = None,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: Optional[float] = None,
    thematic_deficit_theme: str = "Pharma",
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
        tax_savings_vs_debt_fund_inr=0.0,
        cash_validation_passed=bank_cash_verified and deployable >= amount,
        cash_validation_message="NO ACTION: " + "; ".join(reasons),
        tranches=[],
    )


def _sip_operational_constraint_violations(items, sip_policy):
    """Return fail-closed operational constraint violations for positive SIP lines."""
    import math

    try:
        max_fund_pct = float(sip_policy["max_fund_allocation_pct"])
        min_ticket = float(sip_policy["min_sip_per_fund_inr"])
        increment = float(sip_policy["sip_increment_inr"])
        max_core_count = int(sip_policy["max_core_fund_count"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("SIP operational constraint policy is missing or invalid") from exc
    if (
        not math.isfinite(max_fund_pct) or not 0.0 < max_fund_pct <= 100.0
        or not math.isfinite(min_ticket) or min_ticket <= 0.0
        or not math.isfinite(increment) or increment <= 0.0
        or max_core_count < 1
    ):
        raise ValueError("SIP operational constraint policy values must be finite and positive")

    active = [item for item in items if item.monthly_inr > 0.0]
    violations = []
    for item in active:
        if item.allocation_pct > max_fund_pct + 1e-9:
            violations.append(
                f"{item.category_role} allocation {item.allocation_pct:.2f}% exceeds "
                f"the {max_fund_pct:.2f}% per-fund cap"
            )
        if item.monthly_inr + 1e-9 < min_ticket:
            violations.append(
                f"{item.category_role} SIP ₹{item.monthly_inr:.2f} is below "
                f"the ₹{min_ticket:.2f} minimum ticket"
            )
        units = item.monthly_inr / increment
        if abs(units - round(units)) > 1e-8:
            violations.append(
                f"{item.category_role} SIP ₹{item.monthly_inr:.2f} is not a "
                f"multiple of the ₹{increment:.2f} SIP increment"
            )
    core_items = [
        item for item in active
        if "thematic" not in item.category_role.lower()
        and "debt" not in item.category_role.lower()
    ]
    if len(core_items) > max_core_count:
        violations.append(
            f"{len(core_items)} active core funds exceed the maximum of {max_core_count}"
        )
    return violations


def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: Optional[float] = None,
    holdings: Optional[List[HoldingItem]] = None,
    client_aum: float = 0.0,
    thematic_deficit_theme: str = "Pharma",
    thematic_satellite_pct_of_equity: float = 0.0,
    thematic_satellite_authorized: bool = False,
    candidate_universe: Optional[List[Dict[str, Any]]] = None,
    equity_sip_routing_override: bool = False,
    portfolio_disclosures_by_scheme_id: Optional[Dict[str, Dict[str, Any]]] = None,
    portfolio_disclosure_source_bytes_by_scheme_id: Optional[Dict[str, bytes]] = None,
    disclosure_as_of_date: Optional[date] = None,
    disclosure_max_age_days: int = 45,
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
    try:
        b = float(monthly_budget)
        aum_value = float(client_aum)
        stability_value = None if stability_buffer_pct is None else float(stability_buffer_pct)
    except (TypeError, ValueError) as exc:
        raise ValueError("SIP budget, client AUM and stability buffer must be numeric") from exc
    if not math.isfinite(b) or b < 0:
        raise ValueError("Monthly SIP budget must be finite and non-negative")
    if not math.isfinite(aum_value) or aum_value < 0:
        raise ValueError("Client AUM must be finite and non-negative")
    if stability_value is not None and (
        not math.isfinite(stability_value) or not 0.0 <= stability_value <= 100.0
    ):
        raise ValueError("Stability buffer percentage must be finite and between 0 and 100")
    stability_buffer_pct = stability_value
    client_aum = aum_value
    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "asset_allocation.json"
    if not policy_path.is_file():
        raise ValueError(f"Required allocation policy file is missing: {policy_path}")
    try:
        allocation_policy = json.loads(policy_path.read_text(encoding="utf-8"))
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
    is_starter = client_aum < starter_aum_threshold or b < starter_budget_threshold

    # Dynamic Folio Discovery
    # Resolved dynamically through select_autonomous_blueprint_funds below

    # 1. Target Asset Allocation by Risk Level
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

    pharma_scheme = thematic_info.get("scheme") or thematic_info.get("fund_name") or "NO_ACTION: No eligible fund selected"
    direct_pharma_folio = thematic_info.get("folio")
    pharma_rat = thematic_info.get("rationale", "NO_ACTION: No eligible thematic fund selected for Slot 5.")

    debt_scheme = debt_info.get("scheme") or "NO_ACTION: No verified debt candidate selected"
    direct_debt_folio = debt_info.get("folio")
    debt_rat = debt_info.get("rationale", "High-grade AAA short-term debt fulfilling SAA fixed income target.")

    def _append_flexi_sip_items(alloc_pct: float):
        items.append(
            DeterministicSIPRecommendation(
                category_role="Core Flexi-Cap Compounder",
                scheme_name=flexi_scheme,
                folio_target=flexi_target_folio,
                monthly_inr=round(b * (alloc_pct / 100.0), 2),
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
                        monthly_inr=round(b * (mid_pct / 100.0), 2),
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
                        monthly_inr=round(b * (small_pct / 100.0), 2),
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
                        monthly_inr=round(b * (large_pct / 100.0), 2),
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
                        scheme_name=pharma_scheme,
                        folio_target=direct_pharma_folio,
                        monthly_inr=round(b * (thematic_pct / 100.0), 2),
                        allocation_pct=thematic_pct,
                        rational_code="TACTICAL_SATELLITE",
                        fiduciary_rationale=pharma_rat,
                        is_direct=thematic_info.get("is_direct")
                    )
                )
        if target_debt > 0:
            items.append(
                DeterministicSIPRecommendation(
                    category_role="High-Grade Debt Anchor",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=round(b * (target_debt / 100.0), 2),
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
                    monthly_inr=round(b * (mid_pct / 100.0), 2),
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
                    monthly_inr=round(b * (small_pct / 100.0), 2),
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
                    monthly_inr=round(b * (large_pct / 100.0), 2),
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
                    scheme_name=pharma_scheme,
                    folio_target=direct_pharma_folio,
                    monthly_inr=round(b * (thematic_pct / 100.0), 2),
                    allocation_pct=thematic_pct,
                    rational_code="SATELLITE_THEME",
                    fiduciary_rationale=pharma_rat,
                    is_direct=thematic_info.get("is_direct")
                )
            )

        if target_debt > 0:
            items.append(
                DeterministicSIPRecommendation(
                    category_role="High-Grade Debt Cushion" if target_eq > 0 else "Capital Preservation Debt",
                    scheme_name=debt_scheme,
                    folio_target=direct_debt_folio,
                    monthly_inr=round(b * (target_debt / 100.0), 2),
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
    unallocated_budget = 0.0
    if unverified_active_slots:
        unallocated_budget = b
        for item in items:
            item.monthly_inr = 0.0
            item.fiduciary_rationale = (
                "NO ACTION — entire SIP budget withheld because at least one required "
                "slot lacks verified Direct-plan eligibility. No redistribution is permitted. "
                + item.fiduciary_rationale
            )
    else:
        total_allocated = sum(item.monthly_inr for item in items)
        diff = round(b - total_allocated, 2)
        if abs(diff) > 0.0 and items:
            items[0].monthly_inr = round(items[0].monthly_inr + diff, 2)

    # Operational policy constraints are hard gates. If any active line
    # breaches a cap/ticket/increment/count rule, withhold the whole budget;
    # never silently redistribute a rejected line to another fund.
    try:
        sip_operational_policy = allocation_policy["sip_allocation_policy"]
    except (KeyError, TypeError) as exc:
        raise ValueError("SIP operational allocation policy is missing") from exc
    operational_violations = _sip_operational_constraint_violations(
        items, sip_operational_policy
    )
    if operational_violations:
        unallocated_budget = b
        for item in items:
            item.monthly_inr = 0.0
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
        items=items
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
