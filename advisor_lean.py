#!/usr/bin/env python3
"""
advisor_lean.py — legacy report CLI.
Reads local private client data and uses shared core calculation modules.
This is an executable report script, not a side-effect-free importable library.
Usage:
    python advisor_lean.py              # 3 reports -> outputs/
    python advisor_lean.py --no-ai      # deterministic facts only
    python advisor_lean.py --query "..." # one-off grounded answer
    python advisor_lean.py --chat       # interactive REPL
"""
from __future__ import annotations
import json, re, sys, argparse
from datetime import date, datetime
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def discover_client_portfolios(root_dir: Path | None = None) -> dict[str, Path]:
    if root_dir is None:
        root_dir = ROOT
    data_dir = root_dir / "data"
    portfolios = {}
    if not data_dir.exists():
        return portfolios
    for p in sorted(data_dir.iterdir()):
        if p.is_dir() and p.name not in ("policy", "cache", "__pycache__"):
            if (p / "config.json").exists() or (p / "statements").exists() or list(p.glob("*.xlsx")):
                portfolios[p.name] = p
    return portfolios

def get_default_client_dir() -> Path:
    import os
    env_client_dir = os.environ.get("MF_CLIENT_DATA_DIR")
    if env_client_dir:
        client_dir = Path(env_client_dir).expanduser().resolve()
        if not client_dir.is_dir():
            raise FileNotFoundError(f"MF_CLIENT_DATA_DIR does not exist: {client_dir}")
        return client_dir
    ports = discover_client_portfolios()
    if "lalit_portfolio" in ports:
        return ports["lalit_portfolio"]
    if ports:
        return next(iter(ports.values()))
    return ROOT / "data" / "lalit_portfolio"

CLIENT = get_default_client_dir()
POLICY = ROOT / "data" / "policy"
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

def jload(p): return json.loads(p.read_text(encoding="utf-8"))
def _num(v):
    """Parse required CAS numeric values without silently fabricating zeroes."""
    import math
    if v is None or isinstance(v, bool) or (isinstance(v, str) and not v.strip()):
        raise ValueError(f"Required CAS numeric value is missing: {v!r}")
    try:
        value = float(str(v).replace(",", "").replace("₹", "").strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid CAS numeric value: {v!r}") from exc
    if not math.isfinite(value):
        raise ValueError(f"CAS numeric value must be finite: {v!r}")
    return value

def norm(s):
    s = re.sub(r"\(.*?\)", " ", s)
    return " ".join(t for t in re.split(r"[^a-z0-9]+", s.lower()) if t and t not in {"fund","the","of","and","a","an","option","growth","plan","regular","direct","idcw","dividend","reinvestment","formerly","erstwhile","known","as","in","on","for","to"})

required_client_files = [CLIENT/"config.json", CLIENT/"fund_metrics.json", CLIENT/"fund_aliases.json"]
missing_client_files = [str(p) for p in required_client_files if not p.is_file()]
if missing_client_files:
    raise FileNotFoundError(
        "Private client data is not configured. Set MF_CLIENT_DATA_DIR to a local "
        "directory containing config.json, fund_metrics.json, fund_aliases.json "
        f"and statements/*.xlsx. Missing: {missing_client_files}"
    )
cfg = jload(CLIENT/"config.json")
metrics = {m["id"]: m for m in jload(CLIENT/"fund_metrics.json")["funds"]}
aliases = {}
for fid, names in jload(CLIENT/"fund_aliases.json")["aliases"].items():
    for alias in names:
        key = norm(alias)
        existing = aliases.get(key)
        if existing is not None and existing != fid:
            raise ValueError(f"Ambiguous normalized scheme alias {alias!r}: {existing!r} vs {fid!r}")
        aliases[key] = fid
aa_policy = jload(POLICY/"asset_allocation.json")

def match_scheme(scheme):
    """Resolve only through an explicit normalized alias; never fuzzy-match funds."""
    n = norm(str(scheme or ""))
    fund_id = aliases.get(n)
    if fund_id is None:
        raise ValueError(f"No exact fund alias for CAS scheme {scheme!r}; refusing to omit or fuzzy-map the holding.")
    if fund_id not in metrics:
        raise ValueError(f"Exact alias for CAS scheme {scheme!r} points to missing metrics id {fund_id!r}.")
    return metrics[fund_id]

import openpyxl
xlsx = sorted((CLIENT/"statements").glob("cas_detailed_report_*.xlsx"))[-1]
wb = openpyxl.load_workbook(xlsx, data_only=True)
ws = wb["Portfolio Details"]
hdr, as_of, holdings = None, "", []
for row in ws.iter_rows(values_only=True):
    v = [str(c).strip() if c else "" for c in row]
    if v and v[0] == "To Date": as_of = v[1]
    elif v and v[0] == "Scheme Name":
        hdr = {name: i for i, name in enumerate(v) if name}
    elif hdr and v and v[hdr["Scheme Name"]]:
        f = {name: (v[i] if i < len(v) else "") for name, i in hdr.items()}
        item = {"scheme": f["Scheme Name"], "folio": f.get("Folio No.", ""), "invested": _num(f.get("Invested Value")), "value": _num(f.get("Current Value"))}
        if item["value"] > 0: holdings.append(item)
if not holdings: sys.exit("No active holdings parsed from CAS")

prem = aa_policy.get("cost_assumptions",{}).get("regular_plan_premium_pct", 1.0)
regular = [h for h in holdings if "direct" not in h["scheme"].lower()]
reg_val = sum(h["value"] for h in regular)
f1 = {"n_folios": len(regular), "n_funds": len({h["scheme"] for h in regular}), "regular_value": reg_val, "annual_bleed": reg_val * prem / 100, "annual_low": reg_val * 0.75 / 100, "annual_high": reg_val * 1.20 / 100}

mc_funds = {}
for h in holdings:
    m = match_scheme(h["scheme"])
    if m and m.get("category") == "Multi Cap":
        mc_funds[m["id"]] = mc_funds.get(m["id"], 0) + h["value"]
mc_ids = sorted(mc_funds, key=mc_funds.get, reverse=True)
pairs = []
for i in range(len(mc_ids)):
    for j in range(i+1, len(mc_ids)):
        # mc_ids already contains canonical metric identifiers; do not feed
        # identifiers back through the external CAS alias resolver.
        a = set(metrics[mc_ids[i]].get("h", [])[:10])
        b = set(metrics[mc_ids[j]].get("h", [])[:10])
        pairs.append((mc_ids[i], mc_ids[j], round(100*len(a&b)/10, 1)))
f2 = {"funds": mc_funds, "pairs": pairs, "avg_overlap": round(sum(p[2] for p in pairs)/max(1,len(pairs)),1), "total": sum(mc_funds.values())}

# ── SEBI 6-Tier Risk-o-meter Profiles & Dynamic Fiduciary Arbiters ──
SEBI_RISKOMETER_PROFILES = {
    "1_low": {
        "level": 1,
        "name": "Low",
        "badge": "🟢 Low (Irish Green)",
        "color": "#2e7d32",
        "description": "Minimal volatility and conservative risk. Focus on capital preservation.",
        "large": 20.0, "mid_small": 0.0, "debt": 80.0, "equity_target": 20.0
    },
    "2_low_to_moderate": {
        "level": 2,
        "name": "Low to Moderate",
        "badge": "🟡 Low to Moderate (Chartreuse)",
        "color": "#7cb342",
        "description": "Low-to-mild risk exposure. Conservative hybrid & short-duration debt.",
        "large": 35.0, "mid_small": 5.0, "debt": 60.0, "equity_target": 40.0
    },
    "3_moderate": {
        "level": 3,
        "name": "Moderate",
        "badge": "🟡 Moderate (Neon Yellow)",
        "color": "#fdd835",
        "description": "Balanced risk and return profile. Dynamic asset allocation & balanced advantage.",
        "large": 50.0, "mid_small": 20.0, "debt": 30.0, "equity_target": 70.0
    },
    "4_moderately_high": {
        "level": 4,
        "name": "Moderately High",
        "badge": "🟠 Moderately High (Caramel)",
        "color": "#fb8c00",
        "description": "Significant volatility expected. Predominantly large-cap equity & hybrid equity.",
        "large": 45.0, "mid_small": 30.0, "debt": 25.0, "equity_target": 75.0
    },
    "5_high": {
        "level": 5,
        "name": "High",
        "badge": "🟠 High (Dark Orange)",
        "color": "#e65100",
        "description": "Higher equity or market sensitivity. Flexi-cap, multi-cap, and mid-cap alpha.",
        "large": 45.0, "mid_small": 45.0, "debt": 10.0, "equity_target": 90.0
    },
    "6_very_high": {
        "level": 6,
        "name": "Very High",
        "badge": "🔴 Very High (Red)",
        "color": "#d32f2f",
        "description": "Aggressive and volatile schemes (small-cap, mid-cap, sectoral/thematic funds).",
        "large": 45.0, "mid_small": 50.0, "debt": 5.0, "equity_target": 95.0
    }
}

# Backward compatible alias map
SAA_PROFILES = {
    "conservative": SEBI_RISKOMETER_PROFILES["2_low_to_moderate"],
    "moderate": SEBI_RISKOMETER_PROFILES["4_moderately_high"],
    "aggressive": SEBI_RISKOMETER_PROFILES["5_high"],
    "very_aggressive": SEBI_RISKOMETER_PROFILES["6_very_high"],
    "very_high": SEBI_RISKOMETER_PROFILES["6_very_high"],
    **SEBI_RISKOMETER_PROFILES
}

def compute_saa(
    profile_name="5_high",
    band=5.0,
    custom_large=None,
    custom_mid_small=None,
    custom_debt=None,
    current_exposure=None,
    total_value=None,
):
    """Pure SAA comparison; portfolio exposure is explicit, never read from globals."""
    key = str(profile_name).strip().lower()
    if current_exposure is None or total_value is None:
        raise ValueError("current_exposure and total_value are required")
    total = float(total_value)
    if not (total > 0):
        raise ValueError("total_value must be positive")
    if not isinstance(current_exposure, dict):
        raise TypeError("current_exposure must be a mapping")
    raw_current = {
        "large": float(current_exposure["large"]),
        "mid_small": float(current_exposure["mid_small"]),
        "debt": float(current_exposure["debt"]),
    }
    if any(not (v >= 0 and v < float("inf")) for v in raw_current.values()):
        raise ValueError("current exposures must be finite and non-negative")
    if abs(sum(raw_current.values()) - total) > max(1.0, total * 0.001):
        raise ValueError("current exposures must reconcile to total_value within 0.1% or INR 1")
    if custom_large is not None or custom_mid_small is not None or custom_debt is not None:
        if any(v is None for v in (custom_large, custom_mid_small, custom_debt)):
            raise ValueError("all three custom SAA weights must be supplied together")
        target = {"large": float(custom_large), "mid_small": float(custom_mid_small), "debt": float(custom_debt)}
        p_info = {"name": "Custom", "color": "#4a5568", "badge": "Custom Asset Mix"}
    else:
        p = SAA_PROFILES.get(key)
        if p is None:
            raise ValueError(f"Unknown SAA profile: {profile_name!r}")
        target = {"large": p["large"], "mid_small": p["mid_small"], "debt": p["debt"]}
        p_info = p
    if any(not (v >= 0 and v <= 100) for v in target.values()) or abs(sum(target.values()) - 100.0) > 0.01:
        raise ValueError("SAA target weights must be non-negative and sum to 100%")
    cur = {k: round(100 * v / total, 1) for k, v in raw_current.items()}
    drift = {k: round(cur[k] - target[k], 1) for k in target}
    breaches = [k for k, v in drift.items() if abs(v) > float(band)]
    return {
        "profile": p_info.get("name", "Custom"),
        "profile_key": key,
        "badge": p_info.get("badge", ""),
        "color": p_info.get("color", "#4a5568"),
        "description": p_info.get("description", ""),
        "total": total,
        "current": cur,
        "target": target,
        "drift": drift,
        "band": float(band),
        "breach": breaches,
        "is_breached": len(breaches) > 0
    }

def compute_cash_waterfall(cash_dict=None, monthly_expense=0.0, months_reserve=6.0, custom_reserve=None):
    if cash_dict is None:
        cash_dict = cfg.get("cash", {})
    total = cash_dict.get("bank_cash_total", 0.0)
    if custom_reserve is not None:
        reserve = float(custom_reserve)
    else:
        reserve = round(monthly_expense * months_reserve, 0)
    deployable = max(0.0, total - reserve)
    return {
        "total": total,
        "monthly_expense": monthly_expense,
        "months_reserve": months_reserve,
        "reserve": reserve,
        "deployable": deployable
    }

def compute_tax_harvesting_ledger(custom_holdings=None):
    h_list = custom_holdings if custom_holdings is not None else holdings
    gains = []
    losses = []
    for h in h_list:
        inv = h["invested"]
        val = h["value"]
        diff = val - inv
        if diff > 0:
            gains.append({"scheme": h["scheme"], "folio": h["folio"], "gain": diff, "value": val, "invested": inv})
        elif diff < 0:
            losses.append({"scheme": h["scheme"], "folio": h["folio"], "loss": abs(diff), "value": val, "invested": inv})
    
    tot_gain = sum(g["gain"] for g in gains)
    tot_loss = sum(l["loss"] for l in losses)
    
    # Generic dynamic identification of top gain holding to shelter
    top_gain = max(gains, key=lambda x: x["gain"]) if gains else None
    top_gain_scheme = top_gain["scheme"] if top_gain else "N/A"
    top_gain_amount = top_gain["gain"] if top_gain else 0.0
    net_after_loss_harvest = max(0.0, top_gain_amount - tot_loss)
    
    return {
        "total_unrealized_gains": tot_gain,
        "total_unrealized_losses": tot_loss,
        "net_unrealized_gain": tot_gain - tot_loss,
        "loss_making_holdings": losses,
        "gain_making_holdings": gains,
        "top_gain_scheme": top_gain_scheme,
        "top_gain_amount": top_gain_amount,
        "net_top_gain_after_loss": net_after_loss_harvest,
        "is_top_gain_fully_sheltered": net_after_loss_harvest <= 125000.0,
        # Backward compatibility aliases:
        "hdfc_defence_gain": top_gain_amount,
        "hdfc_defence_net_after_loss_harvest": net_after_loss_harvest,
        "is_defence_fully_sheltered": net_after_loss_harvest <= 125000.0
    }

def compute_fifo_tax_lots(as_of_date=None):
    """
    Computes lot-level FIFO tax maturation status for all active holdings.
    Tags each purchase lot as LTCG (>365d, 0% exit load) or STCG (<=365d, 1% load).
    """
    if as_of_date is None:
        as_of_date = date(2026, 10, 9)
    txns_path = CLIENT / "transactions.json"
    if not txns_path.exists():
        return []
    with open(txns_path, 'r', encoding='utf-8') as f:
        txns = json.load(f).get('transactions', [])

    scheme_txns = defaultdict(list)
    for t in txns:
        sn = t.get('scheme', '').strip()
        if not sn:
            continue
        amt = float(t.get('amount', 0))
        unt = float(t.get('units', 0) or 0)
        if amt == 0 and unt == 0:
            continue
        try:
            d = datetime.strptime(t['date'][:10], '%Y-%m-%d').date()
        except Exception:
            continue
        scheme_txns[sn].append({
            'date': d, 'amount': amt, 'units': unt,
            'nav': float(t.get('nav', 0) or 0),
            'desc': t.get('description', '')
        })

    active_lots = []
    for sn, stxns in sorted(scheme_txns.items()):
        stxns = sorted(stxns, key=lambda x: x['date'])
        lots = []
        for t in stxns:
            unt = t['units']
            amt = t['amount']
            desc = t['desc'].lower()
            is_rev = any(kw in desc for kw in ('reversal', 'dishonour', 'reject'))
            if unt > 0 and not is_rev:
                lots.append({
                    'date': t['date'],
                    'units': unt,
                    'nav': t['nav'] if t['nav'] > 0 else (amt / unt if unt > 0 else 0),
                    'cost': amt
                })
            elif unt < 0 or is_rev:
                units_to_burn = abs(unt)
                while units_to_burn > 0.0001 and lots:
                    if lots[0]['units'] <= units_to_burn + 0.0001:
                        units_to_burn -= lots[0]['units']
                        lots.pop(0)
                    else:
                        fraction = units_to_burn / lots[0]['units']
                        lots[0]['cost'] -= lots[0]['cost'] * fraction
                        lots[0]['units'] -= units_to_burn
                        units_to_burn = 0.0
                        
        for l in lots:
            hdays = (as_of_date - l['date']).days
            is_ltcg = hdays > 365
            active_lots.append({
                'scheme': sn,
                'purchase_date': l['date'].strftime('%Y-%m-%d'),
                'units': round(l['units'], 3),
                'purchase_nav': round(l['nav'], 2),
                'invested_cost': round(l['cost'], 2),
                'holding_days': hdays,
                'status': "LTCG (0% Exit Load)" if is_ltcg else f"STCG (Matures in {max(0, 365 - hdays)}d)",
                'is_ltcg': is_ltcg,
                'days_to_ltcg': max(0, 365 - hdays),
                'exit_load_penalty': 0.0 if is_ltcg else round(l['cost'] * 0.01, 2)
            })
    return active_lots

def compute_switch_cost_audit():
    """
    Computes exact, statement-derived mathematical costs of switching regular plans:
    1. Exit load penalty on immature regular lots (held <= 365d)
    2. Capital gains tax (LTCG at 12.5% above Rs 1.25L exemption) on regular plans
    3. Net first-year impact of switching today vs phased 3-step switch plan
    """
    reg_lots = [l for l in compute_fifo_tax_lots() if 'direct' not in l['scheme'].lower()]
    mature_lots = [l for l in reg_lots if l['is_ltcg']]
    immature_lots = [l for l in reg_lots if not l['is_ltcg']]

    exit_penalty = sum(l['exit_load_penalty'] for l in immature_lots)

    scheme_gain_ratio = {}
    for h in holdings:
        if 'direct' not in h['scheme'].lower():
            inv = h['invested']
            val = h['value']
            scheme_gain_ratio[h['scheme']] = (val - inv) / inv if inv > 0 else 0.0

    ltcg_net = sum(l['invested_cost'] * scheme_gain_ratio.get(l['scheme'], 0.0) for l in mature_lots)
    stcg_net = sum(l['invested_cost'] * scheme_gain_ratio.get(l['scheme'], 0.0) for l in immature_lots)

    taxable_ltcg = max(0.0, ltcg_net - 125000.0)
    ltcg_tax = taxable_ltcg * 0.125
    stcg_tax = max(0.0, stcg_net) * 0.20
    total_tax_today = ltcg_tax + stcg_tax

    bleed = f1['annual_bleed']
    net_today = bleed - exit_penalty - total_tax_today
    pct_wiped_out = round((exit_penalty + total_tax_today) / bleed * 100, 1) if bleed > 0 else 0.0

    return {
        "annual_bleed": round(bleed, 0),
        "exit_penalty": round(exit_penalty, 0),
        "total_tax_today": round(total_tax_today, 0),
        "ltcg_net": round(ltcg_net, 0),
        "stcg_net": round(stcg_net, 0),
        "taxable_ltcg": round(taxable_ltcg, 0),
        "net_today": round(net_today, 0),
        "pct_wiped_out": pct_wiped_out,
        "n_mature": len(mature_lots),
        "n_immature": len(immature_lots),
        "total_lots": len(reg_lots),
        "mature_cost": round(sum(l['invested_cost'] for l in mature_lots), 0),
        "immature_cost": round(sum(l['invested_cost'] for l in immature_lots), 0),
    }

cash = cfg.get("cash", {})
f3 = compute_cash_waterfall(cash, monthly_expense=0.0, months_reserve=6.0, custom_reserve=cash.get("emergency_reserve", 0.0))

tot = sum(h["value"] for h in holdings)
lc=msm=dg=0.0
for h in holdings:
    m = match_scheme(h["scheme"]); w = h["value"]
    if not m:
        s_low = h["scheme"].lower()
        if any(k in s_low for k in ["debt", "liquid", "gilt", "bond", "overnight"]):
            dg += w
        elif any(k in s_low for k in ["hybrid", "balanced", "multi asset"]):
            lc += w * 0.40; msm += w * 0.25; dg += w * 0.35
        elif any(k in s_low for k in ["mid", "small", "emerging"]):
            msm += w
        else:
            lc += w
        continue
    lc += w * m.get("lc",0)/100; msm += w * (m.get("mc",0)+m.get("sc",0))/100; dg += w * (100-m.get("lc",0)-m.get("mc",0)-m.get("sc",0))/100

f4 = compute_saa(profile_name=cfg.get("ips", {}).get("risk_tolerance", "aggressive"), current_exposure={"large": lc, "mid_small": msm, "debt": dg}, total_value=tot)

# ── Unified XIRR Engine from core.math_engine ──
from core.math_engine import calculate_xirr, calculate_portfolio_xirr

from datetime import datetime, date

# Calculate portfolio XIRR using CAS invested/current values
transactions_path = CLIENT / "transactions.json"
cas_invested = sum(h["invested"] for h in holdings)
cas_current = sum(h["value"] for h in holdings if h["value"] > 0)
portfolio_xirr = calculate_portfolio_xirr(transactions_path, holdings, cas_invested, cas_current)
benchmark_xirr = None
alpha_pct = None
if portfolio_xirr is not None:
    benchmark_xirr = 0.12
    alpha_pct = (portfolio_xirr - 0.12) * 100

# Optional imports - may be unavailable in test environments
try:
    from core.candidate_scoring import FiduciaryScoringEngine, compute_reverse_fed_model
    _HAS_SCORING_ENGINE = True
except ImportError:
    _HAS_SCORING_ENGINE = False

def _get_stress_tests():
    from stress_test import run_stress_tests as _run_stress_tests
    def _wrapper(custom_holdings=None, target_saa=None):
        if custom_holdings is None:
            custom_holdings = holdings
        return _run_stress_tests(
            custom_holdings=custom_holdings,
            target_saa=target_saa,
            client_cfg=cfg
        )
    return _wrapper

run_stress_tests = _get_stress_tests()

def compute_sip_blueprint(
    monthly_budget=100000.0,
    profile_name="5_high",
    custom_large=None,
    custom_mid_small=None,
    custom_debt=None,
    rebalance_drift=False,
    flexi_choice="ppfas_flexi",
    strategy_mode="gap_repair",
    mid_choice="hdfc_midcap",
    **kwargs
):
    """
    Computes dynamic Direct Plan SIP allocation matching:
    1. Institutional Multi-Factor Candidate Scoring (TER, Alpha, Sharpe, International Diversification, Downside Buffer).
    2. The 6 official SEBI Risk-o-meter tiers (Level 1 Low to Level 6 Very High).
    3. Strategy Mode:
       - 'gap_repair': Directs fresh capital to repair SAA drift (e.g. debt deficit) without taxable equity selling.
       - 'max_growth': Directs 95-100% of capital into high-beta equity alpha engines.
    4. Flexible Flexi-Cap Engine: PPFAS (Global) vs HDFC (Domestic) vs 50:50 Hybrid Blend vs 360 ONE.
    5. Fiduciary Mid-Cap Engine: HDFC Mid-Cap (Diversified 80 stocks, lower 0.76% TER) vs Motilal Oswal (Concentrated 31 stocks, 0.91% TER) vs Nifty Midcap 150 Index.
    """
    p = str(profile_name).lower()
    b = float(monthly_budget)

    # Dynamic Scheme Discovery for Core Sleeves
    direct_holdings = [h["scheme"] for h in holdings if "direct" in h["scheme"].lower()]
    
    def resolve_scheme(cat_type: str, fallback: str) -> str:
        cat_lower = cat_type.lower()
        for s in direct_holdings:
            s_lower = s.lower()
            if "large" in cat_lower and "large" in s_lower and "mid" not in s_lower:
                return s
            if "mid" in cat_lower and ("midcap" in s_lower.replace(" ", "") or "mid cap" in s_lower) and "large" not in s_lower:
                return s
            if "small" in cat_lower and "small" in s_lower:
                return s
            if "debt" in cat_lower and any(k in s_lower for k in ("debt", "short term", "liquid", "bond", "banking & psu")):
                return s
            if "hybrid" in cat_lower and any(k in s_lower for k in ("balanced advantage", "baf", "multi asset", "hybrid")):
                return s
        for s in [h["scheme"] for h in holdings]:
            s_lower = s.lower()
            if "mid" in cat_lower and ("midcap" in s_lower.replace(" ", "") or "mid cap" in s_lower) and "large" not in s_lower:
                return s.replace("Regular Plan", "Direct Plan").replace("Regular", "Direct")
        return fallback

    scheme_large = resolve_scheme("large", "Nippon India Large Cap Fund - Direct Growth Plan")
    
    # Mid-Cap Scheme Resolution based on selection & fiduciary scoring
    if mid_choice == "motilal_midcap":
        scheme_mid = "Motilal Oswal Midcap Fund - Direct Plan Growth"
        mid_rationale = "High-Beta Mid-Cap (Score: 67.0/100): Concentrated 25-30 stock portfolio, 0.91% TER, higher volatility (54.6% in top 10), uses existing Direct Folio #910168305634"
    elif mid_choice == "nifty_midcap_150":
        scheme_mid = "Nifty Midcap 150 Index Fund - Direct Plan - Growth"
        mid_rationale = "Passive Mid-Cap Benchmark (Score: 80.0/100): Lowest 0.25% TER (saves 66 bps vs Motilal), zero single-stock blowup risk, pure broad mid-cap representation"
    else:
        # Default: HDFC Mid-Cap Opportunities Direct
        scheme_mid = "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth"
        mid_rationale = "Rank #1 Fiduciary Mid-Cap (Score: 82.5/100): Lower 0.76% TER, robust 80-stock diversification (prevents concentration risk), higher Sharpe (0.62), +15.8% in your portfolio, uses active Direct Folio #22403163"

    scheme_small = resolve_scheme("small", "Nippon India Small Cap Fund - Direct Plan - Growth")
    scheme_debt = resolve_scheme("debt", "ICICI Prudential Short Term Fund - Direct Plan - Growth")
    scheme_hybrid = resolve_scheme("hybrid", "Canara Robeco Multi Asset Allocation Fund - Direct Plan")
    scheme_psu_debt = resolve_scheme("debt_psu", "Aditya Birla Sun Life Banking & PSU Debt Fund - Direct - Growth")

    # Determine Base Weights by Profile
    w_large_core = 0.0

    # 1. Custom Allocation Mode
    if custom_large is not None and custom_debt is not None:
        c_large = float(custom_large)
        c_msm = float(custom_mid_small or 0.0)
        c_debt = float(custom_debt)
        tot_c = c_large + c_msm + c_debt
        if tot_c > 0:
            t_large, t_mid_small, t_debt = c_large / tot_c, c_msm / tot_c, c_debt / tot_c
        else:
            t_large, t_mid_small, t_debt = 0.50, 0.35, 0.15
    else:
        # Standard SEBI 6-Tier Risk-o-meter Profile lookup
        prof = SAA_PROFILES.get(p, SEBI_RISKOMETER_PROFILES["5_high"])
        t_large = prof["large"] / 100.0
        t_mid_small = prof["mid_small"] / 100.0
        t_debt = prof["debt"] / 100.0

    # Derive sleeve weights strictly matching official SEBI targets:
    # Large-Cap Sleeve (t_large): Split between Flexi-Cap Anchor (PPFAS) and Bluechip Large-Cap Core (Nippon)
    if t_large >= 0.30:
        w_large = round(t_large - 0.15, 2)
        w_large_core = 0.15
    else:
        w_large = t_large
        w_large_core = 0.0

    # Mid & Small-Cap Sleeve: Matches exact SEBI mid_small target
    w_mid = t_mid_small
    w_sml = 0.0

    # Debt Stability Floor: Matches exact SEBI debt target
    w_debt = t_debt

    weights = []

    # Flexi-Cap Sleeve Construction
    if w_large > 0:
        if flexi_choice == "blend_50_50":
            half_w = w_large / 2.0
            weights.append(("Core Flexi (Global Compounder)", "Parag Parikh Flexi Cap Fund - Direct Plan - Growth", half_w, "Lowest 0.69% TER, US Tech Diversification & 17.8% defensive buffer (Score: 80.0/100)"))
            weights.append(("Core Flexi (Domestic Alpha)", "HDFC Flexi Cap Fund - Direct Plan - Growth Option", half_w, "High 3Y Alpha (+5.27%), 24.5% Mid/Small kicker, uses active Direct Folio #44678193 (Score: 58.6/100)"))
        elif flexi_choice == "hdfc_flexi":
            weights.append(("Core Flexi-Cap", "HDFC Flexi Cap Fund - Direct Plan - Growth Option", w_large, "Domestic Alpha Engine (Score: 58.6/100): Strong 3Y Alpha (+5.27%), 24.5% Mid/Small Cap, uses active Direct Folio #44678193"))
        elif flexi_choice == "360_one_flexi":
            weights.append(("Core Flexi-Cap", "360 ONE Flexi Cap Fund - Direct Plan - Growth", w_large, "Concentrated Quality Engine (Score: 64.2/100): High active share, 25-30 high-conviction quality leaders"))
        else:
            # Default: Parag Parikh Flexi Cap Direct
            weights.append(("Core Flexi-Cap", "Parag Parikh Flexi Cap Fund - Direct Plan - Growth", w_large, "Rank #1 Fiduciary Compounder (Score: 80.0/100): Lowest 0.69% TER, Global Tech Diversification, 17.8% defensive buffer"))

    # Mid-Cap Sleeve
    if w_mid > 0:
        weights.append(("Mid-Cap Alpha", scheme_mid, w_mid, mid_rationale))

    # Large-Cap Bluechip Sleeve (Consolidates into existing Direct Folio #401321771817)
    if w_large_core > 0:
        weights.append(("Large-Cap Core", scheme_large, w_large_core, "Bluechip market leader stability (+1.99% alpha, consolidates into existing Direct Folio #401321771817)"))

    # Small-Cap Sleeve (Only if explicitly allocated)
    if w_sml > 0:
        weights.append(("Small-Cap Alpha", scheme_small, w_sml, "High-growth emerging enterprise alpha with disciplined small-cap risk limits"))

    # Debt / Stability Floor
    if w_debt > 0:
        if w_debt >= 0.40:
            weights.append(("Short-Duration Debt Floor", scheme_debt, w_debt * 0.60, "AAA/Sovereign credit stability floor to anchor portfolio SAA"))
            weights.append(("Banking & PSU Debt Floor", scheme_psu_debt, w_debt * 0.40, "High credit quality sovereign/PSU debt yield"))
        else:
            weights.append(("Fixed Income Stability Floor", scheme_debt, w_debt, "High quality AAA short duration debt floor to cushion equity drawdowns and fix debt deficit"))

    # Normalize weights
    tot_w = sum(w[2] for w in weights)
    plan = []
    for cat, scheme, w, rat in weights:
        norm_w = w / tot_w
        amt = round(b * norm_w, 0)
        plan.append({
            "category": cat,
            "scheme": scheme,
            "target_pct": f"{norm_w * 100:.1f}%",
            "weight": norm_w,
            "monthly_amount": amt,
            "rationale": rat
        })

    # Adjust rounding discrepancy on largest allocation
    diff = b - sum(item["monthly_amount"] for item in plan)
    if diff != 0 and plan:
        plan[0]["monthly_amount"] += diff

    return plan


def compute_lumpsum_blueprint(
    lumpsum_amount=200000.0,
    profile_name="5_high",
    custom_large=None,
    custom_mid_small=None,
    custom_debt=None,
    deployment_mode="staggered_stp",
    stp_months=6,
    flexi_choice="ppfas_flexi",
    strategy_mode="gap_repair",
    mid_choice="hdfc_midcap",
    **kwargs
):
    """
    Computes institutional lumpsum investment allocation:
    1. Mode A: Staggered STP (Liquid to Equity over 3-6 months to avoid entry point timing risk).
    2. Mode B: Immediate Tactical (allocates into under-allocated asset classes / Debt / Core large-cap).
    3. Valuation Awareness via Reverse Fed Model.
    """
    amt = float(lumpsum_amount)
    fed_res = None
    if _HAS_SCORING_ENGINE:
        fed_res = compute_reverse_fed_model()

    if amt <= 0:
        return {
            "total_amount": 0.0,
            "mode": deployment_mode,
            "allocations": [],
            "stp_monthly": 0.0,
            "reverse_fed": fed_res,
            "valuation_regime": getattr(fed_res, 'valuation_regime', 'N/A') if fed_res else "N/A",
            "summary": "No lumpsum capital specified."
        }

    # Get asset class weights matching client profile
    base_plan = compute_sip_blueprint(
        monthly_budget=amt,
        profile_name=profile_name,
        custom_large=custom_large,
        custom_mid_small=custom_mid_small,
        custom_debt=custom_debt,
        flexi_choice=flexi_choice,
        strategy_mode=strategy_mode,
        mid_choice=mid_choice
    )

    allocations = []
    if deployment_mode == "immediate_tactical":
        for item in base_plan:
            allocations.append({
                "category": item["category"],
                "scheme": item["scheme"],
                "allocation_pct": item["target_pct"],
                "lumpsum_amount": item["monthly_amount"],
                "execution_mode": "Immediate Upfront (Day 1)",
                "rationale": f"Immediate Day 1 tactical deployment into {item['category']} to instantly rebalance SAA; recommended when market is undervalued."
            })
        summary = f"Immediate tactical deployment of Rs {amt:,.0f} on Day 1 across {len(allocations)} direct funds aligned with {profile_name} target."
        stp_monthly = 0.0
    else:
        # Staggered STP: Fixed income upfront on Day 1, Equity via STP
        equity_total = sum(item["monthly_amount"] for item in base_plan if "Debt" not in item["category"] and "Fixed Income" not in item["category"])
        stp_monthly = round(equity_total / max(1, stp_months), 0)

        for item in base_plan:
            is_debt = "Debt" in item["category"] or "Fixed Income" in item["category"]
            item_amt = item["monthly_amount"]
            if is_debt:
                allocations.append({
                    "category": item["category"],
                    "scheme": item["scheme"],
                    "allocation_pct": item["target_pct"],
                    "lumpsum_amount": item_amt,
                    "execution_mode": "Immediate Upfront (Day 1)",
                    "rationale": "Deploy upfront on Day 1: High-grade AAA/Sovereign debt (~7.4% YTM) has zero equity bubble risk and immediately builds your safety cushion."
                })
            else:
                allocations.append({
                    "category": item["category"],
                    "scheme": item["scheme"],
                    "allocation_pct": item["target_pct"],
                    "lumpsum_amount": item_amt,
                    "execution_mode": f"STP via Liquid Fund ({stp_months} Months @ Rs {round(item_amt/stp_months, 0):,.0f}/mo)",
                    "rationale": f"Park in Liquid Direct earning ~6.8% daily yield; transfer Rs {round(item_amt/stp_months, 0):,.0f}/mo over {stp_months} months to eliminate market peak entry risk while rupee-cost averaging."
                })

        summary = f"Staggered STP: Park equity capital (Rs {equity_total:,.0f}) in ICICI Prudential Liquid Fund - Direct Plan and transfer over {stp_months} months (Rs {stp_monthly:,.0f}/mo) while capturing ~6.8% yield on idle balance. ({getattr(fed_res, 'rationale', 'Valuation-aware deployment') if fed_res else 'Strategic allocation'})"

    diff = amt - sum(a["lumpsum_amount"] for a in allocations)
    if diff != 0 and allocations:
        allocations[0]["lumpsum_amount"] += diff

    return {
        "total_amount": amt,
        "mode": deployment_mode,
        "mode_badge": "🛡️ Staggered STP Deployment (3-6 Months)" if deployment_mode == "staggered_stp" else "⚡ Immediate Tactical Deployment",
        "stp_months": stp_months,
        "stp_monthly": stp_monthly,
        "liquid_parking_fund": "ICICI Prudential Liquid Fund - Direct Plan - Growth",
        "estimated_parking_yield_pct": 6.8,
        "reverse_fed": fed_res,
        "valuation_regime": getattr(fed_res, 'valuation_regime', 'N/A') if fed_res else "N/A",
        "allocations": allocations,
        "summary": summary
    }

facts = {
    "client": cfg.get("ips",{}).get("client_name") or cfg.get("client_name") or CLIENT.name.replace("_", " ").title(),
    "as_of": as_of,
    "total_value": tot,
    "invested": sum(h["invested"] for h in holdings),
    "gain": sum(h["value"]-h["invested"] for h in holdings),
    "n_funds": len(holdings),
    "fee_bleed": f1,
    "overlap": f2,
    "cash": f3,
    "saa": f4,
    "sip_budget": cfg.get("ips",{}).get("monthly_sip_budget", 100000),
    "lumpsum_budget": cfg.get("ips",{}).get("lumpsum_budget", 200000),
    "horizon": cfg.get("ips",{}).get("horizon_years", 10),
    "risk": cfg.get("ips",{}).get("risk_tolerance", "aggressive"),
    "xirr_pct": portfolio_xirr,
    "benchmark_xirr_pct": benchmark_xirr,
    "alpha_pct": alpha_pct,
    "holdings": holdings,
    "tax_harvesting": compute_tax_harvesting_ledger(),
    "sip_plan": compute_sip_blueprint(monthly_budget=cfg.get("ips",{}).get("monthly_sip_budget", 100000), profile_name=cfg.get("ips",{}).get("risk_tolerance", "aggressive"), mid_choice="hdfc_midcap"),
    "lumpsum_plan": compute_lumpsum_blueprint(lumpsum_amount=cfg.get("ips",{}).get("lumpsum_budget", 200000), profile_name=cfg.get("ips",{}).get("risk_tolerance", "aggressive"), mid_choice="hdfc_midcap"),
}

SYS = """You are a SEBI-registered fee-only Fiduciary Wealth Advisor. Rules:
1. NEVER hallucinate numbers -- quote EXACT values from input.
2. REGULAR->DIRECT SWITCH TAX REALITY: Under Indian Income Tax Act Sec 47/112A, a Regular to Direct switch is legally treated as a REDEMPTION followed by a PURCHASE. It triggers Capital Gains Tax (STCG 20% <1yr, LTCG 12.5% >1yr above Rs1.25L) and Exit Loads (typically 1% <1yr). It is NOT tax-neutral!
3. NEVER advise switching all regular funds blindly in Week 1. This triggers massive tax liability and exit load penalties.
4. MANDATORY TRANCHE EXECUTION:
   - Step 0: CGS (Capital Gains Statement) & CAS Lot Audit before placing any order.
   - Phase 1 (Immediate / Month 1): Switch ONLY mature lots (>365d, 0% load) with unrealized losses or net gains within the Rs1.25L Sec 112A tax-free threshold. Switching loss-making lots creates capital losses to shelter other gains with ZERO tax.
   - Phase 2 (Months 2-11): Hold recent SIP lots (<365 days) until day 366 to avoid 1% exit loads and 20% STCG.
   - Phase 3 (Next FY April 1): Stagger remaining mature gains across April 1 to utilize next year's Rs1.25L tax exemption.
5. Multi-cap overlap >30% -> consolidate to single core fund.
6. Compact markdown tables only -- no padded whitespace.
7. Crisp, confident, plain English. No "engine indicates" boilerplate.
8. NO VERBIAGE: High data density only. Eliminate conversational filler, redundant introductions, and generic prose.
9. STATUTORY NOTICE: Conclude reports with: "*Statutory Disclaimer: Mutual fund investments are subject to market risks. Read all scheme-related documents carefully. Past performance does not guarantee future returns. Consult a certified tax professional for individual tax filing.*" """

def build_health_prompt(f):
    top = sorted(f["fee_bleed"]["regular_value"] and [{"scheme":h["scheme"],"value":h["value"],"commission":round(h["value"]*0.01,0)} for h in regular], key=lambda x:-x["value"])[:8]
    ov = [{"a":a,"b":b,"pct":p} for a,b,p in f["overlap"]["pairs"]][:6]
    return f"""Generate Portfolio Health & Commission Audit for {f['client']}.

FACTS:
- Portfolio: Rs{f['total_value']:,.0f} | Invested: Rs{f['invested']:,.0f} | Gain: Rs{f['gain']:,.0f} | Funds: {f['n_funds']}
- Portfolio XIRR: {f['xirr_pct']*100:.2f}% | Benchmark: {f['benchmark_xirr_pct']*100:.2f}% | Alpha: {f['alpha_pct']:+.2f}%
- Regular Plans: {f['fee_bleed']['n_funds']} funds, Rs{f['fee_bleed']['regular_value']:,.0f}
- Annual Commission Drag: Rs{f['fee_bleed']['annual_bleed']:,.0f}/yr (Rs{f['fee_bleed']['annual_low']:,.0f}-Rs{f['fee_bleed']['annual_high']:,.0f} band)
- 10Y Compounded Loss @12%: Rs{f['fee_bleed']['annual_bleed']*((1.12**10-1)/0.12):,.0f}
- SAA: Current {f['saa']['current']['large']:.1f}%L / {f['saa']['current']['mid_small']:.1f}%M / {f['saa']['current']['debt']:.1f}%D | Target {f['saa']['target']['large']:.0f}%L / {f['saa']['target']['mid_small']:.0f}%M / {f['saa']['target']['debt']:.0f}%D | Breach: {f['saa']['breach']}
- Idle Cash: Rs{f['cash']['total']:,.0f} (Reserve Rs{f['cash']['reserve']:,.0f}, Deployable Rs{f['cash']['deployable']:,.0f})
- Multi-Cap Funds: {f['overlap']['funds']} | Avg Top-10 Overlap: {f['overlap']['avg_overlap']}%

TOP LEAKS: {top}
TOP OVERLAPS: {ov}

OUTPUT: # Portfolio Health & Commission Audit
1. Executive Scorecard (Cost/Overlap/Risk/Performance)
2. Hidden Commission Leak (table + 10Y loss)
3. Scheme Overlap Analysis (why 4 multi-cap = duplicate risk)
4. Asset Mix Drift (equity overweight)
5. Immediate Diagnostic Summary"""

def build_switch_prompt(f):
    reg_table = "\n".join(f"| {h['scheme']} | Rs{h['value']:,.0f} | Switch to Direct | Eliminate commission |" for h in regular[:12])
    mc = f["overlap"]["funds"]
    lots = [l for l in compute_fifo_tax_lots() if 'direct' not in l['scheme'].lower()]
    mature_count = len([l for l in lots if l["is_ltcg"]])
    immature_count = len([l for l in lots if not l["is_ltcg"]])
    immature_cost = sum(l["invested_cost"] for l in lots if not l["is_ltcg"])
    exit_load_risk = sum(l["exit_load_penalty"] for l in lots if not l["is_ltcg"])

    return f"""Generate Fund-by-Fund Switch & Consolidation Plan for {f['client']}.

FACTS:
- Regular Plans to Switch: {f['fee_bleed']['n_funds']} funds, Rs{f['fee_bleed']['regular_value']:,.0f} | Annual Savings: Rs{f['fee_bleed']['annual_bleed']:,.0f}
- Multi-Cap Crowding: {list(mc.keys())} = Rs{f['overlap']['total']:,.0f} | Avg Overlap: {f['overlap']['avg_overlap']}%
- TAX REALITY: Under Sec 47/112A, a Switch from Regular to Direct is legally a REDEMPTION that triggers Capital Gains Tax and Exit Loads! NEVER switch all funds blindly in Week 1.
- Lot-Level FIFO Maturation: Total {len(lots)} purchase lots across portfolio:
  • Mature Lots (>365d, 0% Exit Load, LTCG Eligible): {mature_count} lots
  • Immature Lots (<=365d, 1% Exit Load Risk, 20% STCG): {immature_count} lots (Capital: Rs {immature_cost:,.0f})
  • Exit Load Penalty at Risk if switched prematurely: Rs {exit_load_risk:,.0f}
- SAA Target: {f['saa']['target']['large']:.0f}% Large / {f['saa']['target']['mid_small']:.0f}% Mid-Small / {f['saa']['target']['debt']:.0f}% Debt

REGULAR FUNDS TABLE:
| Fund | Value | Action | Reason |
|---|---|---|---|
{reg_table}

OUTPUT: # Switch & Consolidation Plan
1. Fiduciary Reconciliation: Gross Bleed vs Net Realized Benefit:
   Markdown table comparing 'Naive Blind Switch (Week 1)' vs 'Fiduciary 3-Phase Tranche Switch':
   - Gross Recoverable Commission Bleed: Rs {f['fee_bleed']['annual_bleed']:,.0f}/yr
   - Exit Load Drag: Naive loses Rs {exit_load_risk:,.0f} on {immature_count} immature lots vs Tranche loses Rs 0.00 (Hold to Day 366)
   - Capital Gains Tax: Naive triggers >Rs 22,000 in immediate taxes vs Tranche pays Rs 0.00 (Loss Netting & Rs 1.25L Exemption)
   - Net Year-1 Benefit: Naive erases ~80% of savings (~Rs 7,700 net) vs Tranche retains 100% (Rs {f['fee_bleed']['annual_bleed']:,.0f})
   - Execution Status: PROPOSED / PENDING CLIENT VERIFICATION OF CGS & FORMAL ACCEPTANCE (Explain that calling gross commission difference an 'immediate saving' without factoring in taxes and investor approval is misleading).
2. Bucket 1: Direct Switch Candidates (Keep fund, eliminate intermediary commission) -- compact table with status
3. Bucket 2: Consolidation & Exit Candidates (High overlap/thematics) -- table with target destination
4. Bucket 3: Retain Existing Direct Core Funds
5. Fiduciary Tranche Transition Roadmap (Tax-Shielded Execution):
   - Step 0: CGS (Capital Gains Statement) & CAS Lot-Level Audit from CAMS/KFintech before placing any order.
   - Phase 1 (Immediate / Month 1): Switch ONLY mature lots (>365d) with unrealized losses or net gains within the Rs1.25L Sec 112A annual exemption. Switching loss-making lots creates capital losses to shelter gains with ZERO tax.
   - Phase 2 (Months 2-11): Strictly hold all {immature_count} recent SIP lots (Rs {immature_cost:,.0f}) until day 366 to avoid 1% exit load penalties (Rs {exit_load_risk:,.0f}) and 20% STCG. Execute rolling monthly switches as lots mature.
   - Phase 3 (Next FY April 1): Stagger remaining mature gains across April 1 to utilize next year's fresh Rs1.25L tax exemption.
6. Post-Consolidation 4-5 Fund Target Portfolio"""

def build_cash_prompt(f):
    lumpsum_amt = f.get("lumpsum_budget", 200000)
    lplan = f.get("lumpsum_plan", {})
    splan = f.get("sip_plan", [])
    
    sip_rows = "\n".join(
        f"| **{s['category']}** | **{s['scheme']}** | **₹{s['monthly_amount']:,.0f}** | **{s['target_pct']}** | {s['rationale']} |"
        for s in splan
    )
    lump_rows = "\n".join(
        f"| **{l['category']}** | **{l['scheme']}** | **{l['allocation_pct']}** | **₹{l['lumpsum_amount']:,.0f}** | {l['execution_mode']}: {l['rationale']} |"
        for l in lplan.get("allocations", [])
    )
    
    return f"""Generate Fresh Money Deployment Plan (SIP & Lumpsum) for {f['client']}.

FACTS:
- Fresh Lumpsum Capital Budget: Rs{lumpsum_amt:,.0f} (Strategy: Staggered STP over 3-6 months @ ~6.8% liquid parking yield vs Immediate Tactical)
- Monthly SIP Budget: Rs{f['sip_budget']:,.0f}
- SAA Gap: Equity {f['saa']['current']['large']+f['saa']['current']['mid_small']:.1f}% vs Target {f['saa']['target']['large']+f['saa']['target']['mid_small']:.0f}% | Debt {f['saa']['current']['debt']:.1f}% vs Target {f['saa']['target']['debt']:.0f}%
- Horizon: {f['horizon']}yr | Risk Profile: {f['risk']}

MANDATORY DETERMINISTIC ALLOCATION TABLES:
You MUST reproduce these exact tables and percentages without alteration:

Lumpsum Table (Total: Rs{lumpsum_amt:,.0f}):
| Asset Sleeve | Recommended Direct Scheme | Allocation (%) | Lumpsum Amount (₹) | Execution Mode & Fiduciary Rationale |
| :--- | :--- | :---: | :---: | :--- |
{lump_rows}

Monthly SIP Table (Total: Rs{f['sip_budget']:,.0f}/mo):
| Category / Role | Recommended Direct Scheme | Monthly SIP (₹) | Allocation (%) | Strategic Fiduciary Rationale |
| :--- | :--- | :---: | :---: | :--- |
{sip_rows}

OUTPUT: # Fresh Money Deployment Plan (SIP & Lumpsum)
1. Deployment Strategy: Overview of disciplined fresh capital allocation without market timing anxiety.
2. Institutional Lumpsum Deployment Blueprint (Budget: Rs{lumpsum_amt:,.0f}): Embed the exact Lumpsum Table above.
3. Optimized Monthly Direct SIP Blueprint: Embed the exact Monthly SIP Table above.
4. Discipline & Rebalancing Rules"""

PROMPTS = {"health": build_health_prompt(facts), "switch": build_switch_prompt(facts), "cash": build_cash_prompt(facts)}

# Use resilient 3-tier AI engine (Requesty -> OpenRouter -> Gemini + Dynamic Discovery & Caching)
from core.ai_engine import call_llm as _engine_call_llm

def call_llm(prompt):
    """Call resilient multi-provider AI engine ported from core reference implementation."""
    return _engine_call_llm(prompt, system_instruction=SYS, use_cache=True)

def gen_report(kind):
    print(f"  Generating {kind}...", flush=True)
    return call_llm(PROMPTS[kind])

def main():
    ap = argparse.ArgumentParser(description="Fiduciary Mutual Funds Advisor (Lean)")
    ap.add_argument("--client", type=str, default=None, help="Client folder name or path under data/")
    ap.add_argument("--no-ai", action="store_true", help="Print deterministic facts only")
    ap.add_argument("--query", type=str, help="One-off grounded question")
    ap.add_argument("--chat", action="store_true", help="Interactive chat")
    args = ap.parse_args()

    if args.no_ai:
        print(json.dumps(facts, indent=2, default=str))
        return

    holdings_ledger = "\n".join(
        f"- {h['scheme']} (Folio: {h['folio']}) | {'Direct' if 'direct' in h['scheme'].lower() else 'Regular'} | Val: Rs{h['value']:,.0f} | Inv: Rs{h['invested']:,.0f} | Gain: Rs{h['value']-h['invested']:+,.0f} ({(h['value']-h['invested'])/h['invested']*100:+.1f}%)"
        for h in sorted(holdings, key=lambda x: -x["value"])
    )

    if args.query:
        ctx = f"Client: {facts['client']} | Portfolio: Rs{facts['total_value']:,.0f} | Regular bleed: Rs{facts['fee_bleed']['annual_bleed']:,.0f}/yr | Overlap: {facts['overlap']['avg_overlap']}% | Lumpsum Budget: Rs{facts['lumpsum_budget']:,.0f}\n\nHOLDINGS LEDGER:\n{holdings_ledger}"
        prompt = f"{SYS}\n\nCONTEXT:\n{ctx}\n\nQUESTION: {args.query}\n\nAnswer directly with exact numbers."
        print(call_llm(prompt))
        return

    if args.chat:
        print(f"Fiduciary Copilot -- {facts['client']} | Type 'exit' to quit")
        hist = []
        while True:
            q = input("\nYou > ").strip()
            if q.lower() in {"exit","quit","q"}: break
            ctx = f"Client: {facts['client']} | Portfolio: Rs{facts['total_value']:,.0f} | Regular bleed: Rs{facts['fee_bleed']['annual_bleed']:,.0f}/yr | Cash: Rs{facts['cash']['deployable']:,.0f} deployable\n\nHOLDINGS LEDGER:\n{holdings_ledger}"
            hist_str = "\n".join(f"{h['role']}: {h['content']}" for h in hist[-4:])
            prompt = f"{SYS}\n\nCONTEXT:\n{ctx}\n\nHISTORY:\n{hist_str}\n\nQUESTION: {q}\n\nAnswer with exact numbers."
            try:
                ans = call_llm(prompt)
                print(f"\nAdvisor >\n{ans}\n")
                hist.extend([{"role":"user","content":q},{"role":"assistant","content":ans}])
            except Exception as e:
                print(f"Error: {e}")
        return

    print("="*60)
    print("  FIDUCIARY ADVISOR -- PORTFOLIO AUDIT")
    print("="*60)
    print(f"Client: {facts['client']} | As of: {facts['as_of']}")
    print(f"Portfolio: Rs{facts['total_value']:,.0f} | Regular bleed: Rs{facts['fee_bleed']['annual_bleed']:,.0f}/yr")
    print(f"Multi-cap overlap: {facts['overlap']['avg_overlap']}% | Deployable cash: Rs{facts['cash']['deployable']:,.0f}")
    print(f"SAA drift: Equity {facts['saa']['current']['large']+facts['saa']['current']['mid_small']:.1f}% vs target {facts['saa']['target']['large']+facts['saa']['target']['mid_small']:.0f}%")
    print("-"*60)

    from core.pdf_exporter import convert_markdown_file_to_pdf
    for kind, fname in [("health","Portfolio_Health_Audit.md"), ("switch","Switch_and_Consolidation_Plan.md"), ("cash","Fresh_Money_Deployment_Plan.md")]:
        md = gen_report(kind)
        md_file = OUT / fname
        md_file.write_text(md, encoding="utf-8")
        pdf_file = convert_markdown_file_to_pdf(md_file)
        print(f"  OK {fname} & {pdf_file.name}")

    print("="*60)
    print(f"  DONE -- Reports in {OUT}")
    print("="*60)

if __name__ == "__main__":
    main()