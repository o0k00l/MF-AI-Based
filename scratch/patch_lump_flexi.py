with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

target = """        if not is_big:
            # Single destination STP
            stp_pct = round((stp_total / L) * 100.0, 1)
            tranches.append(
                LumpsumTrancheItem(
                    role="Core Flexi-Cap Compounder",
                    scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                    folio_target=flexi_target_folio,
                    amount_inr=stp_total,
                    monthly_inr=monthly_stp_total,
                    allocation_pct=stp_pct,
                    timing=f"{stp_months}-Month STP (INR {monthly_stp_total:,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale="Dollar-cost averages into all-weather compounder with built-in cash/global buffer."
                )
            )
        else:
            # Multi-slot STP for big-ticket lumpsums
            flexi_stp = round(stp_total * 0.50, 2)
            mid_stp = round(stp_total * 0.35, 2)
            large_stp = round(stp_total * 0.15, 2)

            tranches.append(
                LumpsumTrancheItem(
                    role="Core Flexi-Cap Compounder (STP Leg 1)",
                    scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                    folio_target=flexi_target_folio,
                    amount_inr=flexi_stp,
                    monthly_inr=round(flexi_stp / stp_months, 2),
                    allocation_pct=round((flexi_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(flexi_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale="Primary compounding ballast; avoids single-fund overconcentration on large capital."
                )
            )"""

replacement = """        flexi_s, flexi_f, flexi_r = _resolve_flexi_details(flexi_choice, holdings, direct_flexi_folio)
        if not is_big:
            # Single destination STP
            stp_pct = round((stp_total / L) * 100.0, 1)
            tranches.append(
                LumpsumTrancheItem(
                    role="Core Flexi-Cap Compounder",
                    scheme_name=flexi_s,
                    folio_target=flexi_f,
                    amount_inr=stp_total,
                    monthly_inr=monthly_stp_total,
                    allocation_pct=stp_pct,
                    timing=f"{stp_months}-Month STP (INR {monthly_stp_total:,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale=flexi_r
                )
            )
        else:
            # Multi-slot STP for big-ticket lumpsums
            flexi_stp = round(stp_total * 0.50, 2)
            mid_stp = round(stp_total * 0.35, 2)
            large_stp = round(stp_total * 0.15, 2)

            tranches.append(
                LumpsumTrancheItem(
                    role="Core Flexi-Cap Compounder (STP Leg 1)",
                    scheme_name=flexi_s,
                    folio_target=flexi_f,
                    amount_inr=flexi_stp,
                    monthly_inr=round(flexi_stp / stp_months, 2),
                    allocation_pct=round((flexi_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(flexi_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale=flexi_r
                )
            )"""

if target not in text:
    print("ERROR: Target not found!")
else:
    text = text.replace(target, replacement, 1)
    with open("core/math_engine.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("SUCCESS: Lumpsum flexi resolution patched!")

