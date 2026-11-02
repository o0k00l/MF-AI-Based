with open("core/eligibility.py", "r", encoding="utf-8") as f:
    text = f.read()

# Replace Gate 2 AUM logic
gate2_old = '''    category = fund_data.get("category", fund_data.get("cat", ""))
    cat_cap = CATEGORY_AUM_CAPS.get(category)
    aum_cap_ok = True
    if cat_cap and aum > cat_cap:
        aum_cap_ok = False
        failed.append(f"Gate 2 [AUM Size Drag]: AUM ₹{aum:,.0f} Cr exceeds {category} ceiling ₹{cat_cap:,.0f} Cr")'''

gate2_new = '''    category = fund_data.get("category", fund_data.get("cat", ""))
    cat_cap = CATEGORY_AUM_CAPS.get(category)
    # Dynamic Flexi-Cap AUM Scaling: If fund maintains >= 65% in large caps & cash,
    # its capacity mirrors large-cap bluechip liquidity (ceiling ₹175,000 Cr). Stricter ₹90,000 Cr applies if mid/small > 35%.
    if "flexi" in category.lower():
        lc_pct = float(fund_data.get("portfolio_large_cap_pct", fund_data.get("lc", 70.0)) or 70.0)
        cat_cap = 175000.0 if lc_pct >= 65.0 else 90000.0

    aum_cap_ok = True
    if cat_cap and aum > cat_cap:
        aum_cap_ok = False
        failed.append(f"Gate 2 [AUM Size Drag]: AUM ₹{aum:,.0f} Cr exceeds {category} ceiling ₹{cat_cap:,.0f} Cr")'''

# Replace Gate 3 Sector Concentration logic
gate3_old = '''    # Sector concentration check
    sector_conc = float(fund_data.get("single_sector_weight_pct", fund_data.get("max_sector_concentration_pct", fund_data.get("fin", 0.0))) or 0.0)
    # Broad diversified equity funds must not exceed single-sector concentration cap (35%).
    # Dedicated thematic/sectoral funds are governed by Gate 9 (15% portfolio allocation cap) rather than an internal sector cap.
    is_thematic = any(kw in category.lower() or kw in fund_name.lower() for kw in ("thematic", "sectoral", "defence", "energy", "pharma", "health", "tech"))
    if not is_thematic and sector_conc > max_sector_concentration_pct:
        failed.append(f"Gate 3 [Sector Concentration]: Sector weight {sector_conc:.1f}% > {max_sector_concentration_pct:.1f}%")
    details["sector_concentration_pct"] = sector_conc'''

gate3_new = '''    # Sector concentration check
    sector_conc = float(fund_data.get("single_sector_weight_pct", fund_data.get("max_sector_concentration_pct", fund_data.get("fin", 0.0))) or 0.0)
    # Broad diversified equity funds must not exceed single-sector concentration cap (35%).
    # Dedicated thematic/sectoral funds are governed by Gate 9 (15% portfolio allocation cap) rather than an internal sector cap.
    # High-grade debt and arbitrage vehicles hold sovereign/AAA financials per SEBI credit guidelines and are exempt.
    is_thematic = any(kw in category.lower() or kw in fund_name.lower() for kw in ("thematic", "sectoral", "defence", "energy", "pharma", "health", "tech"))
    is_debt_or_arb = any(kw in category.lower() or kw in fund_name.lower() for kw in ("debt", "liquid", "short term", "short duration", "bond", "overnight", "arbitrage", "hybrid: arbitrage"))
    if not is_thematic and not is_debt_or_arb and sector_conc > max_sector_concentration_pct:
        failed.append(f"Gate 3 [Sector Concentration]: Sector weight {sector_conc:.1f}% > {max_sector_concentration_pct:.1f}%")
    details["sector_concentration_pct"] = sector_conc'''

# Replace Gate 4 logic
gate4_old = '''    # --- Gate 4: Risk-Adjusted Sharpe & Alpha Gate ---
    sharpe = fund_data.get("sharpe_3y", fund_data.get("sharpe", None))
    alpha = fund_data.get("alpha_3y", fund_data.get("alpha", None))
    sharpe_ok = True
    if sharpe is not None and float(sharpe) < min_sharpe:
        sharpe_ok = False
        failed.append(f"Gate 4 [Sharpe Ratio]: 3Y Sharpe {float(sharpe):.2f} < {min_sharpe:.2f}")

    alpha_ok = True
    if alpha is not None and float(alpha) < 0.0:
        alpha_ok = False
        failed.append(f"Gate 4 [Alpha Drag]: Negative 3Y Jensen's Alpha {float(alpha):.2f}% vs TRI Benchmark")'''

gate4_new = '''    # --- Gate 4: Risk-Adjusted Sharpe & Alpha Gate ---
    sharpe = fund_data.get("sharpe_3y", fund_data.get("sharpe", None))
    alpha = fund_data.get("alpha_3y", fund_data.get("alpha", None))
    is_passive = bool(fund_data.get("is_passive", False) or "index" in category.lower() or "index" in fund_name.lower())
    is_debt = any(kw in category.lower() or kw in fund_name.lower() for kw in ("debt", "liquid", "short term", "short duration", "bond", "overnight", "arbitrage"))
    sharpe_ok = True
    if not is_debt and sharpe is not None and float(sharpe) < min_sharpe:
        sharpe_ok = False
        failed.append(f"Gate 4 [Sharpe Ratio]: 3Y Sharpe {float(sharpe):.2f} < {min_sharpe:.2f}")

    alpha_ok = True
    if not is_passive and not is_debt and alpha is not None and float(alpha) < 0.0:
        alpha_ok = False
        failed.append(f"Gate 4 [Alpha Drag]: Negative 3Y Jensen's Alpha {float(alpha):.2f}% vs TRI Benchmark")'''

for old_str, new_str, label in [(gate2_old, gate2_new, "Gate 2"), (gate3_old, gate3_new, "Gate 3"), (gate4_old, gate4_new, "Gate 4")]:
    if old_str in text:
        text = text.replace(old_str, new_str)
        print(f"{label} replaced (LF)")
    elif old_str.replace("\n", "\r\n") in text:
        text = text.replace(old_str.replace("\n", "\r\n"), new_str.replace("\n", "\r\n"))
        print(f"{label} replaced (CRLF)")
    else:
        print(f"ERROR: {label} not found")

with open("core/eligibility.py", "w", encoding="utf-8") as f:
    f.write(text)

print("Updated core/eligibility.py successfully!")

