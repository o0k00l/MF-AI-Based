"""
core/math_engine.py - Deterministic Fiduciary Financial Mathematics Engine.

Calculates:
1. Regular-to-Direct commission leakage (Annual â‚¹ & 10-Year Compounded Loss)
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
)


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
                fund_name=scheme_str,
                folio_no=folio_str,
                plan=plan,
                invested_value_inr=invested,
                current_value_inr=current,
                expense_ratio_pct=er,
                category=category,
                asset_class=asset_class,
                equity_pct=eq_pct,
                debt_pct=debt_pct,
                large_cap_pct=lc_pct,
                mid_cap_pct=mc_pct,
                small_cap_pct=sc_pct,
                sharpe_ratio=sharpe,
                top_holdings=top_h,
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
            "folio_no": h.folio_no,
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
        annual_bleed_inr=round(annual_bleed, 2),
        ten_year_compounded_loss_inr=round(ten_year_compounded_loss, 2),
        regular_funds_count=len(regular_holdings),
        regular_portfolio_value_inr=round(total_regular_val, 2),
        details=details
    )


# ============================================================
# LOT-LEVEL TAX HARVESTING (FIFO with Â§112A Staging)
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
    source: str
    
    def holding_days(self, as_of: date) -> int:
        return (as_of - self.purchase_date).days
    
    def is_long_term(self, as_of: date, holding_months: int = 12) -> bool:
        return (as_of - self.purchase_date).days > 365
    
    def is_short_term(self, as_of: date) -> bool:
        return not self.is_long_term(as_of)

@dataclass
class TaxLotSummary:
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


def _fifo_redeem(lots: List[TaxLot], units_to_remove: float) -> List[TaxLot]:
    """Remove units from lot pool using FIFO method."""
    remaining = units_to_remove
    new_lots = []
    for lot in lots:
        if remaining <= 0:
            new_lots.append(lot)
            continue
        if lot.units <= remaining:
            remaining -= lot.units
        else:
            remaining_units = lot.units - remaining
            redeemed_units = remaining
            redeemed_lot = TaxLot(
                fund_id=lot.fund_id,
                scheme_name=lot.scheme_name,
                folio=lot.folio,
                purchase_date=lot.purchase_date,
                units=redeemed_units,
                nav=lot.nav,
                cost=lot.cost * (redeemed_units / lot.units),
                source=lot.source
            )
            remaining_lot = TaxLot(
                fund_id=lot.fund_id,
                scheme_name=lot.scheme_name,
                folio=lot.folio,
                purchase_date=lot.purchase_date,
                units=remaining_units,
                nav=lot.nav,
                cost=lot.cost * (remaining_units / lot.units),
                source=lot.source
            )
            new_lots.append(remaining_lot)
            remaining = 0
    return new_lots

def _match_scheme_to_fund(scheme: str) -> Optional[str]:
    """Match a scheme name to a fund_id using fuzzy matching."""
    if not scheme:
        return None
    scheme_lower = scheme.lower()
    for fund_id, metric in fund_metrics.items():
        if metric.get('id', '').lower() in scheme_lower:
            return fund_id
        if metric.get('name', '').lower() in scheme_lower:
            return fund_id
    normalized = re.sub(r'[^a-z0-9]+', '_', scheme_lower).strip('_')
    return normalized if normalized else None

def build_fifo_tax_lots(
    transactions_path: Path,
    holdings: Any,
    as_of_date: Optional[date] = None,
    cas_current: Optional[float] = None
) -> Dict[str, List[TaxLot]]:
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
    fund_lots: Dict[str, List[TaxLot]] = {}
    fund_holdings: Dict[str, float] = {}
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
            fund_id = _match_scheme_to_fund(scheme)
            if not fund_id:
                continue
            if fund_id not in fund_lots:
                fund_lots[fund_id] = []
            if fund_id not in fund_holdings:
                fund_holdings[fund_id] = 0.0
            if txn_type in ('PURCHASE', 'SIP', 'SWITCH_IN', 'STP_IN', 'DIVIDEND_REINVEST'):
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
                units_to_remove = units if units > 0 else (abs(amount) / nav) if nav > 0 else 0
                if units_to_remove > 0:
                    fund_lots[fund_id] = _fifo_redeem(fund_lots[fund_id], units_to_remove)
                    fund_holdings[fund_id] -= units_to_remove
            elif txn_type in ('DIVIDEND',):
                pass
            elif txn_type in ('SWITCH_IN', 'SWITCH_OUT'):
                pass
        except Exception:
            continue
    for fund_id in fund_lots:
        fund_lots[fund_id].sort(key=lambda x: x.purchase_date)
    return fund_lots


def compute_fifo_tax_lots(
    transactions_path: Path,
    holdings: Any,
    as_of_date: Optional[date] = None
) -> Dict[str, TaxLotSummary]:
    if as_of_date is None:
        as_of_date = date.today()
    fund_lots = build_fifo_tax_lots(transactions_path, [], as_of_date)
    summaries: Dict[str, TaxLotSummary] = {}
    for fund_id, lots in fund_lots.items():
        if not lots:
            continue
        scheme_name = lots[0].scheme_name if lots else ""
        current_value_est = sum(l.nav * l.units for l in lots) if lots else 0
        total_cost = sum(l.cost for l in lots)
        ltcg_units = 0.0
        ltcg_gain = 0.0
        stcg_units = 0.0
        stcg_gain = 0.0
        total_units = 0.0
        for lot in lots:
            is_ltcg = lot.is_long_term(as_of_date)
            gain = (lot.nav - lot.cost / lot.units) * lot.units if lot.units > 0 else 0
            if is_ltcg:
                ltcg_units += lot.units
                ltcg_gain += gain
            else:
                stcg_units += lot.units
                stcg_gain += gain
            total_units += lot.units
        unrealized_gain = current_value_est - total_cost
        ltcg_taxable = max(0, ltcg_gain - 125000.0)
        ltcg_tax = ltcg_taxable * 0.13
        stcg_tax = stcg_gain * 0.208
        summaries[fund_id] = TaxLotSummary(
            fund_id=fund_id,
            scheme_name=scheme_name,
            total_units=total_units,
            total_cost=total_cost,
            current_value=current_value_est,
            unrealized_gain=unrealized_gain,
            ltcg_units=ltcg_units,
            ltcg_gain=ltcg_gain,
            stcg_units=stcg_units,
            stcg_gain=stcg_gain,
            ltcg_tax=ltcg_tax,
            stcg_tax=stcg_tax,
            ltcg_exemption_used=min(ltcg_gain, 125000.0),
            stcg_exemption_used=0.0
        )
    return summaries



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



def calculate_cash_deployment(
    bank_cash_inr: float = 0.0,
    emergency_buffer_inr: float = 0.0,
    stp_months: int = 6,
) -> CashDeploymentPlan:
    """
    Computes cash deployment waterfall for bank balances.
    Allocates emergency reserve first, then spreads deployable surplus via STP.
    """
    deployable = max(0.0, bank_cash_inr - emergency_buffer_inr)
    stp_monthly = deployable / stp_months if stp_months > 0 else 0.0

    return CashDeploymentPlan(
        total_bank_cash_inr=round(bank_cash_inr, 2),
        emergency_buffer_inr=round(emergency_buffer_inr, 2),
        deployable_surplus_inr=round(deployable, 2),
        immediate_lump_sum_inr=0.0,
        stp_monthly_amount_inr=round(stp_monthly, 2),
        stp_duration_months=stp_months,
    )



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
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
            client_name = cfg.get("client_name") or cfg.get("ips", {}).get("client_name") or "Valued Client"
            monthly_sip = float(cfg.get("ips", {}).get("monthly_sip_budget", 100000.0))
            lumpsum_budget = float(cfg.get("ips", {}).get("lumpsum_budget", 200000.0))
            target_saa = cfg.get("target_allocation", {})

    tot_cur = sum(h.current_value_inr for h in holdings)
    tot_inv = sum(h.invested_value_inr for h in holdings)
    tot_gain = tot_cur - tot_inv

    fee_bleed = calculate_fee_bleed(holdings)
    overlap = calculate_overlap_matrix(holdings)
    saa = calculate_saa_drift(holdings, target_saa)
    cash = calculate_cash_deployment()

    # Calculate portfolio XIRR and FIFO tax lots from transactions
    transactions_path = cas_path.parent / "transactions.json"
    if not transactions_path.exists():
        transactions_path = cas_path.parent.parent / "transactions.json"
    portfolio_xirr = calculate_portfolio_xirr(transactions_path, holdings)
    tax_lots_summary = compute_fifo_tax_lots(transactions_path)
    
    # Benchmark XIRR (Nifty 50 TRI approximation)
    benchmark_xirr = None
    alpha_pct = None
    if portfolio_xirr is not None:
        # Nifty 50 TRI approximate annualized return ~12% over long term
        benchmark_xirr = 0.12
        alpha_pct = (portfolio_xirr - benchmark_xirr) * 100

    # Identify weak or redundant funds (Multi-cap crowding & poor Sharpe)
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
        saa_drift=saa,
        cash_plan=cash,
        monthly_sip_budget_inr=monthly_sip,
        lumpsum_budget_inr=lumpsum_budget,
        xirr_pct=portfolio_xirr,
        benchmark_xirr_pct=benchmark_xirr,
        alpha_pct=alpha_pct,
        tax_lots_summary=tax_lots_summary,
        weak_funds_flagged=weak_funds,
        holdings=holdings,
    )