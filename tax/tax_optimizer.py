"""
engine/tax_optimizer.py
Tax‑efficiency helpers:
- tax_drag_per_fund: computes STCG/LTCG split, exemption utilisation, carry‑forward loss.
- specific_lot_designation: orders lots for FIFO or specific‑lot method.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Dict, Literal, Optional

from .compliance import load_policy
from . import transition_planner
from decimal import Decimal
import logging
logger = logging.getLogger(__name__)


@dataclass
class TaxDragResult:
    fund_id: str
    stcg_gain: float
    ltcg_gain: float
    exemption_used: float
    carryforward_loss: float
    tax_payable: float


def _determine_asset_class(category: str, acquisition_date=None) -> str:
    """Determine tax asset class based on fund category and acquisition date."""
    cat_lower = str(category).lower() if category else ""
    
    equity_categories = [
        "large cap", "mid cap", "small cap", "flexi cap", "multi cap",
        "large and mid cap", "elss", "index / etf equity", "equity",
        "large & mid cap", "large & mid", "value", "contra", "dividend yield",
        "focused", "sectoral", "thematic",
        # GAP-145 FIX: Hybrid funds maintaining >= 65% equity exposure qualify for Section 112A equity tax
        "balanced advantage", "dynamic asset allocation", "multi asset", "equity savings", "arbitrage"
    ]
    
    debt_categories = [
        "debt", "short duration", "corporate bond", "banking and psu debt",
        "government securities", "money market", "liquid", "short term debt",
        "ultra short duration", "low duration", "medium duration",
        "medium to long duration", "long duration", "dynamic bond",
        "corporate bond fund", "gilt", "floater"
    ]
    
    gold_categories = ["gold", "gold etf"]
    
    international_categories = ["international", "fof", "fund of fund", "overseas"]
    
    if any(kw in cat_lower for kw in equity_categories):
        return "equity_oriented"
    elif any(kw in cat_lower for kw in debt_categories):
        return "debt"
    elif any(kw in cat_lower for kw in gold_categories):
        return "gold_etf"
    elif any(kw in cat_lower for kw in international_categories):
        return "international_and_non_equity_fof"
    
    return "unknown"


def tax_drag_per_fund(
    lots: List[Dict],
    tax_rules: Dict,
    exemption_limit: float = 125_000,
    as_of: Optional[_date] = None,
) -> List[TaxDragResult]:
    """
    Calculate tax drag for each fund given its tax lots.

    Implements statutory 4-stage loss set-off hierarchy under Sections 70 & 71
    and Section 112A of the Indian Income Tax Act (GAP-114, GAP-139, GAP-166):
      - Stage 1: STCL sets off against STCG (Sec 70(1))
      - Stage 2: LTCL sets off ONLY against LTCG (Sec 70(3) - LTCL cannot offset STCG)
      - Stage 3: Residual STCL sets off against remaining LTCG (Sec 70(2))
      - Stage 4: Single statutory ₹1.25L Section 112A exemption applies to remaining net LTCG
    
    Eliminates intra-fund double-deduction where losses were previously subtracted
    both from gross gains and again during intra-head offset.
    """
    from datetime import date as _date
    results: List[TaxDragResult] = []
    classes = tax_rules.get("classes", {})
    cess = tax_rules.get("cess", {}).get("health_education_cess_pct", 4.0) / 100
    
    equity_rules = classes.get("equity_oriented", {})
    equity_stcg_rate = equity_rules.get("short_term", {}).get("rate_pct", 20.0) / 100
    equity_ltcg_rate = equity_rules.get("long_term", {}).get("rate_pct", 12.5) / 100
    
    debt_rules = classes.get("debt_purchased_on_or_after_2023_04_01", {})
    debt_slab_rate = debt_rules.get("default_marginal_tax_rate_pct", 30.0) / 100

    # Group lots by fund
    by_fund: Dict[str, List[Dict]] = {}
    for lot in lots:
        by_fund.setdefault(lot["fund_id"], []).append(lot)

    # 1. First pass: Aggregate gross gains and losses per fund cleanly without double-counting
    fund_data: Dict[str, Dict[str, any]] = {}
    total_stcg = 0.0
    total_ltcg = 0.0
    total_stcl = 0.0
    total_ltcl = 0.0

    for fund_id, fund_lots in by_fund.items():
        first_lot = fund_lots[0] if fund_lots else {}
        category = first_lot.get("category", "")
        asset_class = _determine_asset_class(category)
        
        st_rate = equity_stcg_rate if asset_class != "debt" else debt_slab_rate
        lt_rate = equity_ltcg_rate if asset_class != "debt" else debt_slab_rate
        has_ltcg_exemption = (asset_class != "debt")
        
        f_stcg = 0.0
        f_ltcg = 0.0
        f_stcl = 0.0
        f_ltcl = 0.0

        for lot in fund_lots:
            gain = float(lot.get("gain", 0.0) or 0.0)
            months = lot.get("holding_period_months", 0)
            acq_date = lot.get("acquisition_date")
            is_lt = False
            
            # GAP-214 FIX: Historical holding period evaluated against redemption date, not _date.today()
            redemp_raw = lot.get("redemption_date") or lot.get("disposal_date") or lot.get("sale_date")
            if redemp_raw:
                try:
                    eval_date = _date.fromisoformat(str(redemp_raw).split("T")[0]) if isinstance(redemp_raw, str) else redemp_raw
                except Exception as e:
                    logger.warning(r"Redemption date parse failed: {e}")
                    eval_date = as_of or _date.today()
            else:
                eval_date = as_of or _date.today()

            if acq_date:
                try:
                    if isinstance(acq_date, str):
                        acq = _date.fromisoformat(acq_date.split("T")[0])
                    else:
                        acq = acq_date

                    # GAP-144 FIX: Section 112A grandfathering for equity lots acquired on or before 31-Jan-2018
                    # Deemed Cost = max(Actual Cost, min(FMV on 31-Jan-2018, Sale Consideration))
                    # GAP-246 FIX: Check both "equity" and "equity_oriented" (matching _determine_asset_class output)
                    if asset_class in ("equity", "equity_oriented") and acq <= _date(2018, 1, 31):
                        fmv_2018 = lot.get("fmv_2018") or lot.get("nav_2018_01_31")
                        sale_price = lot.get("sale_price") or lot.get("redemption_nav") or lot.get("current_nav")
                        cost_price = lot.get("purchase_price") or lot.get("cost_nav")
                        units = float(lot.get("units", 1.0) or 1.0)
                        if fmv_2018 is not None and sale_price is not None and cost_price is not None:
                            deemed_cost = max(float(cost_price), min(float(fmv_2018), float(sale_price)))
                            gain = (float(sale_price) - deemed_cost) * units

                    try:
                        anniversary = _date(acq.year + 1, acq.month, acq.day)
                    except ValueError:
                        anniversary = _date(acq.year + 1, 2, 28)
                    is_lt = (eval_date > anniversary)
                except Exception:
                    is_lt = (months > 12)
            else:
                is_lt = (months > 12)
                
            if is_lt:
                if gain > 0:
                    f_ltcg += gain
                elif gain < 0:
                    f_ltcl += abs(gain)
            else:
                if gain > 0:
                    f_stcg += gain
                elif gain < 0:
                    f_stcl += abs(gain)

        fund_data[fund_id] = {
            "asset_class": asset_class,
            "st_rate": st_rate,
            "lt_rate": lt_rate,
            "has_ltcg_exemption": has_ltcg_exemption,
            "gross_stcg": f_stcg,
            "gross_ltcg": f_ltcg,
            "gross_stcl": f_stcl,
            "gross_ltcl": f_ltcl,
        }
        total_stcg += f_stcg
        total_ltcg += f_ltcg
        total_stcl += f_stcl
        total_ltcl += f_ltcl

    # 2. Statutory 4-Stage Portfolio-Wide Netting under Section 70 / 71
    # Stage 1: STCL against STCG
    stcl_absorbed_by_stcg = min(total_stcl, total_stcg)
    net_portfolio_stcg = total_stcg - stcl_absorbed_by_stcg
    residual_stcl = total_stcl - stcl_absorbed_by_stcg

    # Stage 2: LTCL against LTCG ONLY (Sec 70(3))
    ltcl_absorbed_by_ltcg = min(total_ltcl, total_ltcg)
    net_portfolio_ltcg = total_ltcg - ltcl_absorbed_by_ltcg
    unabsorbed_ltcl = total_ltcl - ltcl_absorbed_by_ltcg  # Carries forward

    # Stage 3: Residual STCL against Net LTCG (Sec 70(2))
    stcl_absorbed_by_ltcg = min(residual_stcl, net_portfolio_ltcg)
    net_portfolio_ltcg = net_portfolio_ltcg - stcl_absorbed_by_ltcg
    unabsorbed_stcl = residual_stcl - stcl_absorbed_by_ltcg  # Carries forward

    # Stage 4: Statutory Rs 1.25L Section 112A exemption on remaining net LTCG
    portfolio_exemption_used = min(net_portfolio_ltcg, float(exemption_limit))
    remaining_exemption = float(exemption_limit)

    # 3. Pro-rata / Sequential allocation to individual funds for transparent reporting
    # Sort funds so LTCG exemption is utilized where it provides maximum tax relief
    fund_order = sorted(
        fund_data.keys(),
        key=lambda fid: -fund_data[fid]["gross_ltcg"]
    )

    for fund_id in fund_order:
        fd = fund_data[fund_id]
        f_stcg = fd["gross_stcg"]
        f_ltcg = fd["gross_ltcg"]
        f_stcl = fd["gross_stcl"]
        f_ltcl = fd["gross_ltcl"]

        # Fund-level net gains after proportionate absorption
        stcg_ratio = (f_stcg / total_stcg) if total_stcg > 0 else 0.0
        ltcg_ratio = (f_ltcg / total_ltcg) if total_ltcg > 0 else 0.0

        fund_net_stcg = f_stcg - (stcl_absorbed_by_stcg * stcg_ratio)
        fund_ltcg_after_ltcl = f_ltcg - (ltcl_absorbed_by_ltcg * ltcg_ratio)
        fund_net_ltcg = max(0.0, fund_ltcg_after_ltcl - (stcl_absorbed_by_ltcg * ltcg_ratio))

        # Apply remaining exemption
        if fd["has_ltcg_exemption"]:
            exemption_for_fund = min(fund_net_ltcg, remaining_exemption)
            remaining_exemption -= exemption_for_fund
            taxable_ltcg = fund_net_ltcg - exemption_for_fund
        else:
            exemption_for_fund = 0.0
            taxable_ltcg = fund_net_ltcg

        # Unabsorbed losses for carryforward
        stcl_ratio = (f_stcl / total_stcl) if total_stcl > 0 else 0.0
        ltcl_ratio = (f_ltcl / total_ltcl) if total_ltcl > 0 else 0.0
        fund_carryforward = (unabsorbed_stcl * stcl_ratio) + (unabsorbed_ltcl * ltcl_ratio)

        tax_stcg = fund_net_stcg * fd["st_rate"]
        tax_ltcg = taxable_ltcg * fd["lt_rate"]
        tax_payable = (tax_stcg + tax_ltcg) * (1.0 + cess)

        results.append(
            TaxDragResult(
                fund_id=fund_id,
                stcg_gain=fund_net_stcg,
                ltcg_gain=fund_net_ltcg,
                exemption_used=exemption_for_fund,
                carryforward_loss=fund_carryforward,
                tax_payable=tax_payable,
            )
        )
    return results


def specific_lot_designation(
    lots: List[Dict],
    method: Literal["FIFO", "SPECIFIC"] = "FIFO",
) -> List[Dict]:
    """
    Return lots ordered for disposal.

    - FIFO: oldest acquisition_date first.
    - SPECIFIC: expects each lot to have a 'priority' key; higher first.
    """
    if method == "FIFO":
        return sorted(lots, key=lambda x: x.get("acquisition_date", ""))
    # Specific‑lot: sort by priority descending
    return sorted(lots, key=lambda x: x.get("priority", 0), reverse=True)


# Canonical alias for statutory 4-stage capital gains set-off (GAP-114 & GAP-166)
optimize_capital_gains_set_off = tax_drag_per_fund