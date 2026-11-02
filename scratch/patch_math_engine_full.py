import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

with open("core/math_engine.py", "r", encoding="utf-8") as f:
    text = f.read()

# 1. Patch Lumpsum flexi blend
old_lump_flexi = """        flexi_s, flexi_f, flexi_r = _resolve_flexi_details(flexi_choice, holdings, direct_flexi_folio)
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

new_lump_flexi = """        is_blend = "blend" in str(flexi_choice).lower()
        flexi_s, flexi_f, flexi_r = _resolve_flexi_details(flexi_choice, holdings, direct_flexi_folio)
        ppfas_s, ppfas_f, ppfas_r = _resolve_flexi_details("ppfas_flexi", holdings, direct_flexi_folio)
        hdfc_s, hdfc_f, hdfc_r = _resolve_flexi_details("hdfc_flexi", holdings, direct_flexi_folio)

        if not is_big:
            # Single destination STP
            stp_pct = round((stp_total / L) * 100.0, 1)
            if is_blend:
                f1_amt = round(stp_total * 0.50, 2)
                f2_amt = round(stp_total - f1_amt, 2)
                f1_pct = round(stp_pct * 0.50, 1)
                f2_pct = round(stp_pct - f1_pct, 1)
                m1_stp = round(monthly_stp_total * 0.50, 2)
                m2_stp = round(monthly_stp_total - m1_stp, 2)
                tranches.append(
                    LumpsumTrancheItem(
                        role="Core Flexi-Cap (Global Anchor Leg 1a)",
                        scheme_name=ppfas_s,
                        folio_target=ppfas_f,
                        amount_inr=f1_amt,
                        monthly_inr=m1_stp,
                        allocation_pct=f1_pct,
                        timing=f"{stp_months}-Month STP (INR {m1_stp:,.0f}/mo)",
                        source_vehicle=parking_vehicle,
                        fiduciary_rationale="Global tech moat (Alphabet, Meta, Microsoft) + defensive cash buffer; lowest category 0.69% TER."
                    )
                )
                tranches.append(
                    LumpsumTrancheItem(
                        role="Core Flexi-Cap (Domestic Alpha Leg 1b)",
                        scheme_name=hdfc_s,
                        folio_target=hdfc_f,
                        amount_inr=f2_amt,
                        monthly_inr=m2_stp,
                        allocation_pct=f2_pct,
                        timing=f"{stp_months}-Month STP (INR {m2_stp:,.0f}/mo)",
                        source_vehicle=parking_vehicle,
                        fiduciary_rationale="High-conviction domestic cyclical alpha (+5.27% 3Y alpha, Roshi Jain); overcomes PPFAS foreign remit cap."
                    )
                )
            else:
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

            if is_blend:
                f1_amt = round(flexi_stp * 0.50, 2)
                f2_amt = round(flexi_stp - f1_amt, 2)
                f1_pct = round((f1_amt / L) * 100.0, 1)
                f2_pct = round((f2_amt / L) * 100.0, 1)
                m1_stp = round(f1_amt / stp_months, 2)
                m2_stp = round(f2_amt / stp_months, 2)
                tranches.append(
                    LumpsumTrancheItem(
                        role="Core Flexi-Cap (Global Anchor Leg 1a)",
                        scheme_name=ppfas_s,
                        folio_target=ppfas_f,
                        amount_inr=f1_amt,
                        monthly_inr=m1_stp,
                        allocation_pct=f1_pct,
                        timing=f"{stp_months}-Month STP (INR {m1_stp:,.0f}/mo)",
                        source_vehicle=parking_vehicle,
                        fiduciary_rationale="Global tech ballast + defensive cash buffer; mitigates domestic market volatility."
                    )
                )
                tranches.append(
                    LumpsumTrancheItem(
                        role="Core Flexi-Cap (Domestic Alpha Leg 1b)",
                        scheme_name=hdfc_s,
                        folio_target=hdfc_f,
                        amount_inr=f2_amt,
                        monthly_inr=m2_stp,
                        allocation_pct=f2_pct,
                        timing=f"{stp_months}-Month STP (INR {m2_stp:,.0f}/mo)",
                        source_vehicle=parking_vehicle,
                        fiduciary_rationale="High-conviction domestic alpha (+5.27% 3Y alpha, Roshi Jain); eliminates PPFAS size drag and foreign remit ceilings."
                    )
                )
            else:
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

assert old_lump_flexi in text, "old_lump_flexi not found!"
text = text.replace(old_lump_flexi, new_lump_flexi, 1)

with open("core/math_engine.py", "w", encoding="utf-8") as f:
    f.write(text)

print("SUCCESS: Lumpsum flexi blend patched!")

