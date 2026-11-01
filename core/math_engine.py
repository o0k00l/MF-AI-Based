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
from datetime import datetime, date
from dataclasses import dataclass
import math

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
        npv_val = npv(rate)
        if abs(npv_val) < 1e-6:
            return rate
        deriv = npv_derivative(rate)
        if abs(deriv) < 1e-10:
            break
        rate_new = rate - npv_val / deriv
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
        AssetClass.INTERNATIONAL: "Tier 5 (High)",
        AssetClass.CASH: "Tier 1 (Low)",
        AssetClass.OTHER: "Tier 3 (Moderate)",
    }
    return mapping.get(asset_class, "Tier 3 (Moderate)")


def load_holdings_from_cas_excel(
    xlsx_path: Path,
    fund_metrics_path: Optional[Path] = None,
    fund_aliases_path: Optional[Path] = None,
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

    # Dynamic header lookup
    hdr = None
    start_row = 1
    for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        vals = [str(c).strip() if c else "" for c in row]
        if vals and "Scheme Name" in vals:
            hdr = {name: i for i, name in enumerate(vals) if name}
            start_row = row_idx + 1
            break

    if hdr and "Scheme Name" in hdr:
        col_scheme = hdr["Scheme Name"]
        col_folio = hdr.get("Folio No.", 3)
        col_inv = hdr.get("Invested Value", 4)
        col_cur = hdr.get("Current Value", 5)

        for row in sheet.iter_rows(min_row=start_row, values_only=True):
            if not row or len(row) <= col_scheme or not row[col_scheme]:
                continue
            s_name = row[col_scheme]
            f_no = row[col_folio] if len(row) > col_folio else ""
            i_val = row[col_inv] if len(row) > col_inv else 0.0
            c_val = row[col_cur] if len(row) > col_cur else 0.0
            try:
                c_float = float(c_val) if c_val else 0.0
                i_float = float(i_val) if i_val else 0.0
            except (ValueError, TypeError):
                continue
            if c_float > 0.0:
                raw_items.append((str(s_name).strip(), str(f_no).strip() if f_no else "", i_float, c_float))
    else:
        for r in range(13, sheet.max_row + 1):
            s_name = sheet.cell(row=r, column=1).value
            f_no = sheet.cell(row=r, column=4).value
            i_val = sheet.cell(row=r, column=5).value
            c_val = sheet.cell(row=r, column=6).value
            if not c_val:
                continue
            try:
                c_float = float(c_val)
                i_float = float(i_val) if i_val else 0.0
            except (ValueError, TypeError):
                continue
            if c_float > 0.0:
                raw_items.append((str(s_name).strip(), str(f_no).strip() if f_no else "", i_float, c_float))

    for scheme_str, folio_str, invested, current in raw_items:
        # Plan detection
        scheme_lower = scheme_str.lower()
        plan = PlanType.DIRECT if "direct" in scheme_lower else PlanType.REGULAR
        is_direct = plan == PlanType.DIRECT

        # Fuzzy match to fund metrics
        matched_metric = _find_matching_metric(scheme_str, metrics_map, aliases_map)

        # Default classification
        category = matched_metric.get("cat", "Equity") if matched_metric else "Equity"
        er = float(matched_metric.get("er", 0.75)) if matched_metric else (0.85 if plan == PlanType.DIRECT else 1.90)
        
        # If Regular plan and only Direct ER is in dataset, estimate regular fee = direct ER + 1.05%
        if plan == PlanType.REGULAR and matched_metric:
            er = er + 1.05

        top_h = matched_metric.get("h", []) if matched_metric else []
        sharpe = matched_metric.get("sharpe") if matched_metric else None

        # Market-cap split
        eq_pct = float(matched_metric.get("eq", 100.0)) if matched_metric else 100.0
        debt_pct = float(matched_metric.get("debt", 0.0)) if matched_metric else 0.0
        lc_pct = float(matched_metric.get("lc", 0.0)) if matched_metric else 0.0
        mc_pct = float(matched_metric.get("mc", 0.0)) if matched_metric else 0.0
        sc_pct = float(matched_metric.get("sc", 0.0)) if matched_metric else 0.0

        asset_class = _infer_asset_class(category, eq_pct, debt_pct, lc_pct, mc_pct, sc_pct)

        fund_id = matched_metric.get("id", scheme_str[:30]) if matched_metric else scheme_str[:30]

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
                units=0.0,
                nav=0.0,
                top_holdings=top_h,
                expense_ratio_pct=er,
                risk_tier=_asset_class_to_risk_tier(asset_class),
            )
        )

    return holdings


def _find_matching_metric(scheme: str, metrics: Dict[str, Any], aliases: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Matches a scheme name string to a metrics entry using aliases and dynamic token overlap similarity."""
    s_clean = scheme.lower()
    stop_words = {"fund", "the", "of", "and", "a", "an", "option", "growth", "plan", "regular", "direct", "idcw", "dividend", "reinvestment", "formerly", "erstwhile", "known", "as", "in", "on", "for", "to"}

    # 1. Direct alias match
    if scheme in aliases and aliases[scheme] in metrics:
        return metrics[aliases[scheme]]
    if s_clean in aliases and aliases[s_clean] in metrics:
        return metrics[aliases[s_clean]]

    # 2. Dynamic token overlap similarity across all metrics
    s_tokens = set(re.findall(r"[a-z0-9]+", re.sub(r"\(.*?\)", " ", s_clean))) - stop_words
    if not s_tokens:
        return None

    best_m, best_score = None, 0.0
    for mid, m in metrics.items():
        m_str = (mid + " " + m.get("name", "") + " " + m.get("scheme", "")).lower()
        m_tokens = set(re.findall(r"[a-z0-9]+", re.sub(r"\(.*?\)", " ", m_str))) - stop_words
        if not m_tokens:
            continue
        score = len(s_tokens & m_tokens) / max(1, min(len(s_tokens), len(m_tokens)))
        if score > best_score:
            best_score = score
            best_m = m

    if best_score >= 0.5:
        return best_m

    return None


def _infer_asset_class(cat: str, eq: float, debt: float, lc: float, mc: float, sc: float) -> AssetClass:
    cat_lower = cat.lower()
    if "debt" in cat_lower or "liquid" in cat_lower or debt >= 75.0:
        return AssetClass.DEBT_LIQUID
    if "balanced" in cat_lower or "hybrid" in cat_lower or "daa" in cat_lower or debt >= 20.0:
        return AssetClass.HYBRID_BALANCED
    if "mid cap" in cat_lower or mc >= 50.0:
        return AssetClass.MID_CAP
    if "small cap" in cat_lower or sc >= 50.0:
        return AssetClass.SMALL_CAP
    return AssetClass.LARGE_CAP


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
    
    def holding_days(self, as_of: date) -> int:
        return (as_of - self.purchase_date).days
    
    def is_long_term(self, as_of: date, holding_months: int = 12) -> bool:
        """LTCG if holding period > 12 months (strict: > 12 months, not >=)."""
        return (as_of - self.purchase_date).days > 365
    
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
    cas_current: Optional[float] = None
) -> Dict[str, List[TaxLot]]:
    """
    Build FIFO-ordered tax lots per fund from transaction history.
    Returns dict[fund_id] -> List[TaxLot] sorted by purchase_date (FIFO).
    
    Handles all CAS transaction types: PURCHASE, SIP, SWITCH_IN, STP_IN, 
    REDEMPTION, SWITCH_OUT, STP_OUT, DIVIDEND, STP_IN, STP_OUT.
    
    Rules:
    - PURCHASE, SIP, SWITCH_IN, STP_IN: Add units to lot pool (FIFO)
    - REDEMPTION, SWITCH_OUT, STP_OUT: Remove units from lot pool (FIFO)
    - DIVIDEND: Reinvested = new lot at ex-div NAV; Payout = no unit change
    - SWITCH_IN: Units received into target fund at switch NAV
    - SWITCH_OUT: Units removed from source fund at switch NAV
    """
    if not transactions_path.exists():
        return {}
    
    if as_of_date is None:
        as_of_date = date.today()
    
    try:
        with open(transactions_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return {}
    
    transactions = data.get('transactions', [])
    if not transactions:
        return {}
    
    # Build lots per fund using FIFO
    fund_lots: Dict[str, List[TaxLot]] = {}
    fund_holdings: Dict[str, float] = {}  # current units per fund
    
    for txn in data.get('transactions', []):
        try:
            txn_date = datetime.strptime(txn.get('date', '')[:10], '%Y-%m-%d').date()
            amount = float(txn.get('amount', 0))
            txn_type = txn.get('type', '').upper()
            scheme = txn.get('scheme', '')
            units = float(txn.get('units', 0)) if txn.get('units') else 0
            nav = float(txn.get('nav', 0)) if txn.get('nav') else 0
            
            if amount == 0 or units == 0:
                continue
            
            # Match scheme to fund_id
            fund_id = _match_scheme_to_fund(scheme)
            if not fund_id:
                continue
            
            if fund_id not in fund_lots:
                fund_lots[fund_id] = []
            if fund_id not in fund_holdings:
                fund_holdings[fund_id] = 0.0
            
            if txn_type in ('PURCHASE', 'SIP', 'SWITCH_IN', 'STP_IN', 'DIVIDEND_REINVEST'):
                # Add units to lot pool
                units_to_add = units if units > 0 else (abs(amount) / nav) if nav > 0 else 0
                if units_to_add > 0:
                    cost = units_to_add * nav if nav > 0 else 0
                    lot = TaxLot(
                        fund_id=fund_id,
                        scheme_name=scheme,
                        folio=txn.get('folio', ''),
                        purchase_date=txn_date,
                        units=units_to_add,
                        nav=nav,
                        cost=cost,
                        source='transactions'
                    )
                    fund_lots[fund_id].append(lot)
                    fund_holdings[fund_id] += units_to_add
            
            elif txn_type in ('REDEMPTION', 'SWITCH_OUT', 'STP_OUT'):
                # Remove units from lot pool (FIFO)
                units_to_remove = units if units > 0 else (abs(amount) / nav) if nav > 0 else 0
                if units_to_remove > 0:
                    fund_lots[fund_id] = _fifo_redeem(fund_lots[fund_id], units_to_remove)
                    fund_holdings[fund_id] -= units_to_remove
            
            elif txn_type in ('DIVIDEND',):
                # Dividend payout = no unit change; reinvestment handled separately
                pass
            
            elif txn_type in ('SWITCH_IN', 'SWITCH_OUT'):
                # Handled above via SWITCH_IN/OUT types
                pass
        except Exception:
            continue
        
        # Sort lots by purchase date (FIFO)
        for fund_id in fund_lots:
            fund_lots[fund_id].sort(key=lambda x: x.purchase_date)
        
        return fund_lots
    """
    Build FIFO-ordered tax lots per fund from transaction history.
    Returns dict[fund_id] -> List[TaxLot] sorted by purchase_date (FIFO).
    
    Handles all CAS transaction types: PURCHASE, SIP, SWITCH_IN, STP_IN, 
    REDEMPTION, SWITCH_OUT, STP_OUT, DIVIDEND, STP_IN, STP_OUT.
    
    Rules:
    - PURCHASE, SIP, SWITCH_IN, STP_IN: Add units to lot pool (FIFO)
    - REDEMPTION, SWITCH_OUT, STP_OUT: Remove units from lot pool (FIFO)
    - DIVIDEND: Reinvested = new lot at ex-div NAV; Payout = no unit change
    - SWITCH_IN: Units received into target fund at switch NAV
    - SWITCH_OUT: Units removed from source fund at switch NAV
    """
    if not transactions_path.exists():
        return {}
    
    if as_of_date is None:
        as_of_date = date.today()
    
    try:
        with open(transactions_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception:
        return {}
    
    transactions = data.get('transactions', [])
    if not transactions:
        return {}
    
    # Build lots per fund using FIFO
    fund_lots: Dict[str, List[TaxLot]] = {}
    fund_holdings: Dict[str, float] = {}  # current units per fund
    
    for txn in data.get('transactions', []):
        try:
            txn_date = datetime.strptime(txn.get('date', '')[:10], '%Y-%m-%d').date()
            amount = float(txn.get('amount', 0))
            txn_type = txn.get('type', '').upper()
            scheme = txn.get('scheme', '')
            units = float(txn.get('units', 0)) if txn.get('units') else 0
            nav = float(txn.get('nav', 0)) if txn.get('nav') else 0
            
            if amount == 0 or units == 0:
                continue
            
            # Match scheme to fund_id
            fund_id = _match_scheme_to_fund(scheme)
            if not fund_id:
                continue
            
            if fund_id not in fund_lots:
                fund_lots[fund_id] = []
            if fund_id not in fund_holdings:
                fund_holdings[fund_id] = 0.0
            
            if txn_type in ('PURCHASE', 'SIP', 'SWITCH_IN', 'STP_IN', 'DIVIDEND_REINVEST'):
                # Add units to lot pool
                units_to_add = units if units > 0 else (abs(amount) / nav) if nav > 0 else 0
                if units_to_add > 0:
                    cost = units_to_add * nav if nav > 0 else 0
                    lot = TaxLot(
                        fund_id=fund_id,
                        scheme_name=scheme,
                        folio=txn.get('folio', ''),
                        purchase_date=txn_date,
                        units=units_to_add,
                        nav=nav,
                        cost=cost,
                        source='transactions'
                    )
                    fund_lots[fund_id].append(lot)
                    fund_holdings[fund_id] += units_to_add
            
            elif txn_type in ('REDEMPTION', 'SWITCH_OUT', 'STP_OUT'):
                # Remove units from lot pool (FIFO)
                units_to_remove = units if units > 0 else (abs(amount) / nav) if nav > 0 else 0
                if units_to_remove > 0:
                    fund_lots[fund_id] = _fifo_redeem(fund_lots[fund_id], units_to_remove)
                    fund_holdings[fund_id] -= units_to_remove
            
            elif txn_type in ('DIVIDEND',):
                # Dividend payout = no unit change; reinvestment handled separately
                pass
            
            elif txn_type in ('SWITCH_IN', 'SWITCH_OUT'):
                # Handled above via SWITCH_IN/OUT types
                pass
        except Exception:
            continue
        
        # Sort lots by purchase date (FIFO)
        for fund_id in fund_lots:
            fund_lots[fund_id].sort(key=lambda x: x.purchase_date)
        
        return fund_lots


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
    """
    total_val = sum(h.current_value_inr for h in holdings)
    if total_val <= 0.0:
        return SAADriftAnalysis(
            current_equity_pct=0.0,
            current_debt_pct=0.0,
            current_cash_pct=0.0,
            current_equity_inr=0.0,
            current_debt_inr=0.0,
            target_equity_pct=75.0,
            target_debt_pct=25.0,
        )

    # Compute look-through equity and debt amounts
    equity_val = 0.0
    debt_val = 0.0

    for h in holdings:
        eq_amt = h.current_value_inr * (h.equity_pct / 100.0)
        db_amt = h.current_value_inr * (h.debt_pct / 100.0)
        equity_val += eq_amt
        debt_val += db_amt

    curr_eq_pct = (equity_val / total_val) * 100.0
    curr_db_pct = (debt_val / total_val) * 100.0
    curr_cash_pct = max(0.0, 100.0 - curr_eq_pct - curr_db_pct)

    # Targets (default 75% Equity / 25% Debt/Global)
    if target_saa:
        tgt_eq = target_saa.get("equity_pct", 75.0)
        if "large_cap_pct" in target_saa and "mid_small_cap_pct" in target_saa:
            tgt_eq = target_saa["large_cap_pct"] + target_saa["mid_small_cap_pct"]
        tgt_db = target_saa.get("debt_global_pct", 100.0 - tgt_eq)
    else:
        tgt_eq = 75.0
        tgt_db = 25.0

    eq_drift = curr_eq_pct - tgt_eq
    rebalance_required = abs(eq_drift) > tolerance_band_pct

    # Gap in rupees to reach target
    target_eq_inr = total_val * (tgt_eq / 100.0)
    target_db_inr = total_val * (tgt_db / 100.0)
    equity_gap_inr = target_eq_inr - equity_val
    debt_gap_inr = target_db_inr - debt_val

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
    )


def parse_cas(xlsx_path: Path) -> Tuple[str, List[Dict[str, Any]]]:
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
                holdings.append({
                    "scheme": scheme_name,
                    "folio": vals[hdr.get("Folio No.", 0)],
                    "value": cur_val,
                    "invested": inv_val,
                    "is_direct": "direct" in scheme_name.lower()
                })

    if len(dates_found) > 1:
        raise ValueError(f"Integrity Error: Multiple valuation dates detected in CAS: {dates_found}")
        
    return as_of_date, holdings


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
        as_of_date = date.today()

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
            elif unt < 0 or is_rev:
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


def aggregate_fiduciary_facts(
    cas_path: Path,
    metrics_path: Path,
    config_path: Path,
    aliases_path: Optional[Path] = None,
) -> FiduciaryFactsPayload:
    """
    Full pipeline aggregator: runs deterministic math on statements and config.
    Returns complete FiduciaryFactsPayload.
    """
    holdings = load_holdings_from_cas_excel(cas_path, metrics_path, aliases_path)

    # Load client config
    client_name = "Client"
    monthly_sip = 100000.0
    target_saa = {}
    emergency_months = 6.0
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            client_name = cfg.get("client_name") or cfg.get("ips", {}).get("client_name") or "Valued Client"
            monthly_sip = float(cfg.get("ips", {}).get("monthly_sip_budget", 100000.0))
            lumpsum_budget = float(cfg.get("ips", {}).get("lumpsum_budget", 200000.0))
            target_saa = cfg.get("target_allocation", {})
            emergency_months = float(cfg.get("ips", {}).get("emergency_months", 6.0))

    tot_cur = sum(h.current_value_inr for h in holdings)
    tot_inv = sum(h.invested_value_inr for h in holdings)
    tot_gain = tot_cur - tot_inv

    # Module 2: Portfolio Diagnostics - with architectural corrections
    fee_bleed = calculate_fee_bleed(holdings)
    overlap = calculate_overlap_matrix(holdings)
    
    # Architectural Correction 1: Weighted Look-Through Overlap (replaces naive Jaccard)
    weighted_overlap = calculate_weighted_lookthrough_overlap(holdings)
    
    # Architectural Correction 2: Ordinal Risk Distribution (replaces cardinal 5.84/6.00)
    risk_distribution = calculate_risk_distribution(holdings)
    
    # Architectural Correction 4: SAA Drift Minimizer (renamed from optimizer)
    saa_minimizer = calculate_saa_drift_minimizer(holdings, target_saa, monthly_sip)
    
    # Convert SAA Drift Minimizer to SAADriftAnalysis for backward compatibility
    total_equity_val = sum(h.current_value_inr for h in holdings if h.asset_class in (
        AssetClass.LARGE_CAP, AssetClass.MID_CAP, AssetClass.SMALL_CAP,
        AssetClass.FLEXI_CAP, AssetClass.MULTI_CAP, AssetClass.LARGE_CAP,
        AssetClass.INTERNATIONAL
    ))
    total_debt_val = sum(h.current_value_inr for h in holdings if h.asset_class in (
        AssetClass.DEBT,
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
    
    # Module 3: Investor Suitability & Liquidity - with emergency months from config
    cash = calculate_cash_deployment(
        bank_cash_inr=0.0,  # Will be overridden by actual cash from config if available
        emergency_months=emergency_months
    )

    # Calculate portfolio XIRR and FIFO tax lots from transactions
    transactions_path = cas_path.parent / "transactions.json"
    if not transactions_path.exists():
        transactions_path = cas_path.parent.parent / "transactions.json"
    portfolio_xirr = calculate_portfolio_xirr(transactions_path, holdings)
    tax_lots_raw = compute_fifo_tax_lots(transactions_path)
    tax_lots_summary = None
    if tax_lots_raw:
        immature_val = tax_lots_raw.get("immature_capital_inr", 0.0)
        mature_val = tax_lots_raw.get("mature_capital_inr", 0.0)
        projected_ltcg = sum(l.get("exit_load_penalty", 0) for l in tax_lots_raw.get("lots", []) if l.get("is_ltcg"))
        stagger_required = tax_lots_raw.get("immature_capital_inr", 0) > 0
        tax_lots_summary = TaxLedger(
            immature_locked_value_inr=round(immature_val, 2),
            mature_switchable_value_inr=round(mature_val, 2),
            projected_ltcg_inr=round(projected_ltcg, 2),
            stagger_required=stagger_required
        )
    
    # Benchmark XIRR (Nifty 50 TRI approximation)
    benchmark_xirr = None
    alpha_pct = None
    if portfolio_xirr is not None:
        benchmark_xirr = 0.12
        alpha_pct = (portfolio_xirr - benchmark_xirr) * 100

    # Architectural Correction 3: Switch Cost Analysis (retracts zero-friction myth)
    # Calculate switch costs for regular fund candidates
    switch_costs = []
    for h in holdings:
        if h.plan == PlanType.REGULAR:
            # Estimate switch cost for each regular fund
            # Use fund's own TER as target (switching to direct plan of same fund)
            target_ter = h.expense_ratio_pct / 100.0  # Convert to decimal
            # Estimate holding period from invested vs current value
            gain_pct = (h.current_value_inr - h.invested_value_inr) / h.invested_value_inr if h.invested_value_inr > 0 else 0
            holding_days = 365 * 2  # Rough estimate: 2 years average
            if gain_pct > 0.2:  # If significant gain, likely held > 1 year
                holding_days = 365 * 3
            
            switch_cost = calculate_switch_cost_analysis(
                source_fund=h.fund_name,
                target_fund=h.fund_name + " Direct",
                source_holding=h,
                target_fund_ter=target_ter,
                is_intra_amc=True,
                holding_period_days=holding_days,
                current_nav=h.nav if h.nav > 0 else h.current_value_inr / max(h.units, 1),
                purchase_nav=h.invested_value_inr / max(h.units, 1) if h.units > 0 else h.nav
            )
            switch_costs.append({
                "fund_name": h.fund_name,
                "switch_cost_inr": switch_cost.net_switch_cost_inr,
                "switch_cost_pct": switch_cost.net_switch_cost_pct,
                "exit_load_inr": switch_cost.exit_load_inr,
                "capital_gains_tax_inr": switch_cost.capital_gains_tax_inr,
                "warning": switch_cost.warning
            })

    # Architectural Correction 5 & 6: Eligibility Gates & NO ACTION
    # Load candidate universe from fund_metrics
    candidate_universe = []
    if metrics_path.exists():
        with open(metrics_path, "r", encoding="utf-8") as f:
            m_data = json.load(f)
            for m in m_data.get("funds", []):
                candidate_universe.append({
                    "fund_id": m.get("id", ""),
                    "fund_name": m.get("name", ""),
                    "aum_crore": m.get("aum_crore", 0),
                    "aum_stable": True,
                    "concentration_top10_pct": m.get("concentration_top10", 0),
                    "max_sector_concentration_pct": m.get("max_sector_concentration", 0),
                    "mandate_suitable": True,
                    "data_complete": True,
                    "manager_tenure_years": m.get("manager_tenure_years", 5),
                    "composite_score": m.get("composite_score", 0),
                    "eligibility": {}  # Will be filled by check_eligibility_gates
                })
    
    # Run eligibility gates on candidates
    eligible_candidates = []
    for cand in candidate_universe:
        gate_result = check_eligibility_gates(cand)
        cand["eligibility"] = {
            "passed": gate_result.passed,
            "failed_gates": gate_result.failed_gates,
            "details": gate_result.details
        }
        if gate_result.passed:
            eligible_candidates.append(cand)
    
    # NO ACTION decision
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
    )


# ============================================================
# ARCHITECTURAL CORRECTIONS - NEW FUNCTIONS
# ============================================================

def calculate_weighted_lookthrough_overlap(
    holdings: List[HoldingItem],
    threshold_pct: float = 10.0
) -> List[WeightedOverlapResult]:
    stock_fund_weights: Dict[str, Dict[str, float]] = {}
    fund_total_value: Dict[str, float] = {}
    
    for h in holdings:
        if not h.top_holdings:
            continue
        fund_total_value[h.fund_id] = h.current_value_inr
        weight_per_stock = 100.0 / len(h.top_holdings)
        for stock in h.top_holdings:
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
                    weighted_overlap += combined
            
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


def calculate_switch_cost_analysis(
    source_fund: str,
    target_fund: str,
    source_holding: HoldingItem,
    target_fund_ter: float,
    is_intra_amc: bool = False,
    holding_period_days: int = 365,
    current_nav: float = 0.0,
    purchase_nav: float = 0.0
) -> SwitchCostAnalysis:
    exit_load_pct = 1.0 if holding_period_days < 365 else 0.0
    exit_load_inr = source_holding.current_value_inr * (exit_load_pct / 100.0)
    
    gain_pct = ((current_nav - purchase_nav) / purchase_nav) * 100 if purchase_nav > 0 else 0
    gain_inr = source_holding.current_value_inr * (gain_pct / 100.0)
    
    if holding_period_days > 365:
        ltcg_exemption = 125000.0
        taxable_ltcg = max(0, gain_inr - ltcg_exemption)
        ltcg_tax = taxable_ltcg * 0.125
        stcg_tax = 0.0
    else:
        stcg_tax = gain_inr * 0.20
        ltcg_tax = 0.0
    
    capital_gains_tax = stcg_tax + ltcg_tax
    net_switch_cost = exit_load_inr + capital_gains_tax
    net_switch_cost_pct = (net_switch_cost / source_holding.current_value_inr) * 100 if source_holding.current_value_inr > 0 else 0
    
    return SwitchCostAnalysis(
        source_fund=source_fund,
        target_fund=target_fund,
        exit_load_pct=exit_load_pct,
        exit_load_inr=round(exit_load_inr, 2),
        capital_gains_tax_inr=round(capital_gains_tax, 2),
        stcg_tax_inr=round(stcg_tax, 2),
        ltcg_tax_inr=round(ltcg_tax, 2),
        net_switch_cost_inr=round(net_switch_cost, 2),
        net_switch_cost_pct=round(net_switch_cost_pct, 2),
        is_intra_amc=is_intra_amc,
        warning="Intra-AMC switches trigger capital gains tax and exit loads per Sections 47 & 112A"
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
        if h.asset_class in (AssetClass.LARGE_CAP, AssetClass.MID_CAP, AssetClass.SMALL_CAP, 
                             AssetClass.FLEXI_CAP, AssetClass.MULTI_CAP, AssetClass.LARGE_CAP):
            alloc_category = "Equity"
        elif h.asset_class in (AssetClass.DEBT,):
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
        elif h.asset_class in (AssetClass.INTERNATIONAL,):
            alloc_category = "International"
        else:
            alloc_category = "Other"
        
        if alloc_category not in current_alloc:
            current_alloc[alloc_category] = 0.0
        current_alloc[alloc_category] += h.current_value_inr
    
    current_pct = {k: (v / total_val) * 100 for k, v in current_alloc.items()}
    target_pct = target_allocation
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


def check_eligibility_gates(
    fund_data: Dict[str, Any],
    min_aum_crore: float = 500,
    max_concentration_top10_pct: float = 30.0,
    max_sector_concentration_pct: float = 25.0,
    min_manager_tenure_years: float = 3.0
) -> EligibilityGateResult:
    failed = []
    
    aum = fund_data.get('aum_crore', 0)
    liquidity_ok = aum >= min_aum_crore
    if not liquidity_ok:
        failed.append(f"Liquidity: AUM {aum}Cr < {min_aum_crore}Cr minimum")
    
    aum_stable = fund_data.get('aum_stable', True)
    if not aum_stable:
        failed.append("AUM Stability: Significant outflows detected")
    
    top10 = fund_data.get('concentration_top10_pct', 0)
    concentration_ok = top10 <= max_concentration_top10_pct
    if not concentration_ok:
        failed.append(f"Concentration: Top 10 holdings {top10}% > {max_concentration_top10_pct}%")
    
    sector_conc = fund_data.get('max_sector_concentration_pct', 0)
    sector_ok = sector_conc <= max_sector_concentration_pct
    if not sector_ok:
        failed.append(f"Sector Concentration: {sector_conc}% > {max_sector_concentration_pct}%")
    
    mandate_ok = fund_data.get('mandate_suitable', True)
    if not mandate_ok:
        failed.append("Mandate Suitability: Strategy mismatch with investor profile")
    
    data_ok = fund_data.get('data_complete', True)
    if not data_ok:
        failed.append("Data Integrity: Incomplete or stale data")
    
    tenure = fund_data.get('manager_tenure_years', 0)
    tenure_ok = tenure >= min_manager_tenure_years
    if not tenure_ok:
        failed.append(f"Manager Tenure: {tenure} years < {min_manager_tenure_years} minimum")
    
    passed = len(failed) == 0
    
    return EligibilityGateResult(
        fund_id=fund_data.get('fund_id', ''),
        fund_name=fund_data.get('fund_name', ''),
        passed=passed,
        failed_gates=failed,
        liquidity_gate=liquidity_ok,
        aum_stability_gate=aum_stable,
        concentration_gate=concentration_ok,
        mandate_suitability_gate=mandate_ok,
        data_integrity_gate=data_ok,
        manager_tenure_gate=tenure_ok,
        details={
            'aum_crore': aum,
            'top10_concentration_pct': top10,
            'sector_concentration_pct': sector_conc,
            'manager_tenure_years': tenure
        }
    )


def evaluate_no_action(
    current_portfolio: List[HoldingItem],
    candidate_funds: List[Dict[str, Any]],
    min_improvement_threshold: float = 5.0
) -> NOActionResult:
    best_improvement = 0.0
    best_fund = None
    
    for fund in candidate_funds:
        if not fund.get('eligibility', {}).get('passed', False):
            continue
        improvement = fund.get('composite_score', 0)
        if improvement > best_improvement:
            best_improvement = improvement
            best_fund = fund
    
    no_improvement = best_improvement < min_improvement_threshold
    current_adequate = no_improvement
    
    if no_improvement:
        best_name = best_fund.get('fund_name', 'None') if best_fund else 'None'
        best_score = best_improvement if best_fund else 0.0
        reason = f"No candidate fund offers >{min_improvement_threshold} pts improvement over current portfolio. Best: {best_name} at {best_score:.1f} pts."
        hold_rec = "Retain all current holdings. Pause new SIP deployment. Review quarterly."
    else:
        reason = f"Found improvement candidate: {best_fund.get('fund_name', 'None')} (+{best_improvement:.1f} pts)"
        hold_rec = "Proceed with candidate evaluation."
    
    return NOActionResult(
        action="NO_ACTION" if no_improvement else "PROCEED",
        reason=reason,
        current_portfolio_adequate=current_adequate,
        no_improvement_found=no_improvement,
        hold_recommendation=hold_rec,
        sip_deployment_pause=no_improvement
    )
