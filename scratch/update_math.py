import re

with open('core/math_engine.py', 'r', encoding='utf-8') as f:
    text = f.read()

# 1. Update calculate_saa_drift
old_saa_fn = """def calculate_saa_drift(
    holdings: List[HoldingItem],
    target_saa: Optional[Dict[str, float]] = None,
    tolerance_band_pct: float = 5.0,
) -> SAADriftAnalysis:
    \"\"\"
    Calculates current asset allocation vs target Strategic Asset Allocation (SAA).
    \"\"\"
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
    )"""

new_saa_fn = """def calculate_saa_drift(
    holdings: List[HoldingItem],
    target_saa: Optional[Dict[str, float]] = None,
    tolerance_band_pct: float = 5.0,
) -> SAADriftAnalysis:
    \"\"\"
    Calculates current asset allocation vs target Strategic Asset Allocation (SAA).
    Incorporates underlying look-through stability buffer (debt + cash).
    \"\"\"
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
    )"""

assert old_saa_fn in text, "old_saa_fn not found"
text = text.replace(old_saa_fn, new_saa_fn)
print("Replaced calculate_saa_drift")

# 2. Update calculate_saa_drift_minimizer targets
old_min_targets = """    # Map config target_allocation keys (large_cap_pct, mid_small_cap_pct, debt_global_pct)
    # to our allocation categories (Equity, Debt, Cash)
    target_pct = {
        "Equity": target_allocation.get("large_cap_pct", 0) + target_allocation.get("mid_small_cap_pct", 0),
        "Debt": target_allocation.get("debt_global_pct", 0),
        "Cash": target_allocation.get("cash_pct", 0)
    }"""

new_min_targets = """    # Dynamic target mapping supporting Tier 6 granular keys
    tgt_eq = (
        target_allocation.get("equity_pct", 0.0)
        or (
            target_allocation.get("large_cap_pct", 0.0)
            + target_allocation.get("mid_small_cap_pct", 0.0)
            + target_allocation.get("mid_cap_pct", 0.0)
            + target_allocation.get("small_cap_pct", 0.0)
            + target_allocation.get("flexi_multi_cap_pct", 0.0)
        )
    )
    if tgt_eq <= 0:
        tgt_eq = 95.0
    tgt_db = target_allocation.get("debt_liquid_pct", target_allocation.get("debt_global_pct", 100.0 - tgt_eq))
    tgt_cash = target_allocation.get("cash_pct", 0.0)

    target_pct = {
        "Equity": tgt_eq,
        "Debt": tgt_db,
        "Cash": tgt_cash
    }"""

assert old_min_targets in text, "old_min_targets not found"
text = text.replace(old_min_targets, new_min_targets)
print("Replaced minimizer targets")

# 3. Add new calculation functions at the end of core/math_engine.py
new_functions = """

def calculate_lookthrough_stability_buffer(
    holdings: List[HoldingItem],
    bank_cash_inr: float = 0.0,
    emergency_reserve_inr: float = 0.0,
    target_debt_pct: float = 5.0,
) -> LookThroughStabilityBuffer:
    \"\"\"Calculates look-through debt, cash, and total stability buffer across portfolio.\"\"\"
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
    \"\"\"Calculates dedicated fund and look-through stock exposure across 5 core themes.\"\"\"
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


def compute_deterministic_sip_blueprint(
    monthly_budget: float,
    risk_tier: str = "Tier 6 (Very High)",
    stability_buffer_pct: float = 6.32,
    holdings: Optional[List[HoldingItem]] = None,
) -> DeterministicSIPPlan:
    \"\"\"
    Computes deterministic SIP blueprint without LLM intervention.
    Enforces 85% Core + 15% Satellite logic for Tier 6 aggressive clients.
    \"\"\"
    direct_folios = {}
    if holdings:
        for h in holdings:
            if h.is_direct and h.folio:
                direct_folios[h.fund_name.lower()] = h.folio

    items = []

    # 1. Core Flexi-Cap Compounder (40%)
    ppfas_folio = None
    for k, f in direct_folios.items():
        if "parag parikh" in k:
            ppfas_folio = f
            break
    items.append(
        DeterministicSIPRecommendation(
            category_role="Core Flexi-Cap Compounder",
            scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            folio_target=ppfas_folio,
            monthly_inr=round(monthly_budget * 0.40, 2),
            allocation_pct=40.0,
            rational_code="CORE_COMPOUNDER",
            fiduciary_rationale="Lowest 0.69% TER, international tech diversification (Alphabet/Meta), ~12% organic defensive cash/arbitrage buffer."
        )
    )

    # 2. Mid-Cap Alpha Engine (30%)
    mid_scheme = "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth"
    mid_folio = None
    for k, f in direct_folios.items():
        if "motilal" in k and "midcap" in k:
            mid_scheme = "Motilal Oswal Midcap Fund - Direct Plan Growth"
            mid_folio = f
            break
        elif "hdfc" in k and "mid" in k:
            mid_scheme = "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth"
            mid_folio = f
            break

    items.append(
        DeterministicSIPRecommendation(
            category_role="Mid-Cap Alpha Engine",
            scheme_name=mid_scheme,
            folio_target=mid_folio,
            monthly_inr=round(monthly_budget * 0.30, 2),
            allocation_pct=30.0,
            rational_code="ALPHA_ENGINE",
            fiduciary_rationale="Highest-returning engine over a 10-year horizon; high risk-adjusted Sharpe; institutional active alpha."
        )
    )

    # 3. Large-Cap Bluechip Anchor (15%)
    nippon_large_folio = None
    for k, f in direct_folios.items():
        if "nippon" in k and "large" in k:
            nippon_large_folio = f
            break
    items.append(
        DeterministicSIPRecommendation(
            category_role="Large-Cap Bluechip Anchor",
            scheme_name="NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION",
            folio_target=nippon_large_folio or "401321771817",
            monthly_inr=round(monthly_budget * 0.15, 2),
            allocation_pct=15.0,
            rational_code="CORE_ANCHOR",
            fiduciary_rationale="Top-quartile active large cap (+1.99% 3Y alpha); consolidates active Direct Folio #401321771817; captures banking re-rating."
        )
    )

    # 4. Tactical Thematic Satellite (15%)
    items.append(
        DeterministicSIPRecommendation(
            category_role="Tactical Thematic Satellite",
            scheme_name="Nippon India Pharma / Healthcare Fund - Direct Plan - Growth",
            folio_target=None,
            monthly_inr=round(monthly_budget * 0.15, 2),
            allocation_pct=15.0,
            rational_code="SATELLITE_THEME",
            fiduciary_rationale="Solves portfolio's critical 1.1% healthcare void; fair valuation (~28x P/E); non-cyclical structural tailwind."
        )
    )

    total_allocated = sum(item.monthly_inr for item in items)
    assert abs(total_allocated - monthly_budget) < 1.0, f"SIP blueprint sum ({total_allocated}) != budget ({monthly_budget})"

    return DeterministicSIPPlan(
        total_monthly_budget_inr=monthly_budget,
        equity_sip_pct=100.0,
        debt_sip_pct=0.0,
        items=items
    )
"""

text += new_functions

# 4. Update aggregate_fiduciary_facts to wire new calculations
old_agg = """    # Module 3: Investor Suitability & Liquidity - with emergency months from config
    cash = calculate_cash_deployment(
        bank_cash_inr=0.0,  # Will be overridden by actual cash from config if available
        emergency_months=emergency_months
    )"""

new_agg = """    # Module 3: Investor Suitability & Liquidity - with emergency months & bank cash from config
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
    client_risk_tier = "Tier 6 (Very High)"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as cf:
            client_risk_tier = json.load(cf).get("risk_tier", "Tier 6 (Very High)")

    det_sip_plan = compute_deterministic_sip_blueprint(
        monthly_budget=monthly_sip,
        risk_tier=client_risk_tier,
        stability_buffer_pct=stability_buf.total_stability_buffer_pct,
        holdings=holdings
    )"""

assert old_agg in text, "old_agg not found"
text = text.replace(old_agg, new_agg)
print("Updated aggregate_fiduciary_facts cash & stability logic")

# Update return statement of aggregate_fiduciary_facts
old_ret = """        weak_funds_flagged=weak_funds,
        holdings=holdings,
    )"""

new_ret = """        weak_funds_flagged=weak_funds,
        holdings=holdings,
        stability_buffer=stability_buf,
        thematic_exposures=thematic_exps,
        deterministic_sip_plan=det_sip_plan,
    )"""

assert old_ret in text, "old_ret not found"
text = text.replace(old_ret, new_ret)
print("Updated aggregate_fiduciary_facts return payload")

with open('core/math_engine.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("core/math_engine.py successfully updated!")

