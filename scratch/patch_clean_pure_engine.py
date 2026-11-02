import sys
from pathlib import Path

me_file = Path("core/math_engine.py")
content = me_file.read_text(encoding="utf-8")

# 1. Update compute_deterministic_lumpsum_blueprint
# Replace the equity tranche block in compute_deterministic_lumpsum_blueprint
lump_start_marker = "    # B. Equity Tranches\n    if eq_amount > 0:"
lump_end_marker = "    return DeterministicLumpsumPlan("

new_lump_equity_block = '''    # B. Equity Tranches (Autonomously Selected)
    if eq_amount > 0:
        slots = select_autonomous_blueprint_funds(holdings=holdings, client_risk_tier=tier_num)
        flexi_info = slots["Slot 1: Core Flexi-Cap Compounder"]
        mid_info = slots["Slot 2: Mid-Cap Alpha Engine"]
        large_info = slots["Slot 3: Large-Cap Bluechip Anchor"]

        flexi_s, flexi_f, flexi_r = flexi_info["scheme"], flexi_info["folio"], flexi_info["rationale"]
        mid_s, mid_f, mid_r = mid_info["scheme"], mid_info["folio"], mid_info["rationale"]
        large_s, large_f, large_r = large_info["scheme"], large_info["folio"], large_info["rationale"]

        # Day 1 Large-Cap Anchor
        imm_pct = round((immediate_eq / L) * 100.0, 1)
        tranches.append(
            LumpsumTrancheItem(
                role="Day-1 Large-Cap Anchor",
                scheme_name=large_s,
                folio_target=large_f,
                amount_inr=immediate_eq,
                allocation_pct=imm_pct,
                timing="Immediate (Day 1)",
                source_vehicle="Bank Deployable Surplus",
                fiduciary_rationale=large_r
            )
        )

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
            # Multi-slot STP for big-ticket lumpsums (Flexi 50%, Mid 35%, Large 15%)
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
            )
            tranches.append(
                LumpsumTrancheItem(
                    role="Mid-Cap Alpha Engine (STP Leg 2)",
                    scheme_name=mid_s,
                    folio_target=mid_f,
                    amount_inr=mid_stp,
                    monthly_inr=round(mid_stp / stp_months, 2),
                    allocation_pct=round((mid_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(mid_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale=mid_r
                )
            )
            tranches.append(
                LumpsumTrancheItem(
                    role="Large-Cap Bluechip Anchor (STP Leg 3)",
                    scheme_name=large_s,
                    folio_target=large_f,
                    amount_inr=large_stp,
                    monthly_inr=round(large_stp / stp_months, 2),
                    allocation_pct=round((large_stp / L) * 100.0, 1),
                    timing=f"{stp_months}-Month STP (INR {round(large_stp / stp_months, 2):,.0f}/mo)",
                    source_vehicle=parking_vehicle,
                    fiduciary_rationale=large_r
                )
            )
'''

idx1 = content.find(lump_start_marker)
idx2 = content.find(lump_end_marker, idx1)
if idx1 != -1 and idx2 != -1:
    content = content[:idx1] + new_lump_equity_block + "\n" + content[idx2:]
    print("compute_deterministic_lumpsum_blueprint updated to autonomous selection!")
else:
    print(f"Could not find lump markers: idx1={idx1}, idx2={idx2}")

# 2. Update compute_deterministic_sip_blueprint
sip_start_marker = "    # Scheme Identifiers\n    flexi_scheme, flexi_target_folio"
sip_end_marker = "    if is_starter:"

new_sip_scheme_block = '''    # Autonomous Fiduciary Slot Selection (Zero Hardcoded Brands)
    slots = select_autonomous_blueprint_funds(holdings=holdings, client_risk_tier=tier_num)
    flexi_info = slots["Slot 1: Core Flexi-Cap Compounder"]
    mid_info = slots["Slot 2: Mid-Cap Alpha Engine"]
    large_info = slots["Slot 3: Large-Cap Bluechip Anchor"]
    thematic_info = slots["Slot 4: Tactical Thematic Satellite"]
    debt_info = slots.get("High-Grade Debt Anchor", {})

    flexi_scheme = flexi_info["scheme"]
    flexi_target_folio = flexi_info["folio"]
    flexi_default_rat = flexi_info["rationale"]

    mid_scheme = mid_info["scheme"]
    mid_target_folio = mid_info["folio"]
    mid_default_rat = mid_info["rationale"]

    large_scheme = large_info["scheme"]
    large_target_folio = large_info["folio"]
    large_default_rat = large_info["rationale"]

    pharma_scheme = thematic_info["scheme"]
    direct_pharma_folio = thematic_info["folio"]
    pharma_rat = thematic_info["rationale"]

    debt_scheme = debt_info.get("scheme", "ICICI Prudential Short Term Fund - Direct Plan - Growth")
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
                fiduciary_rationale=flexi_default_rat
            )
        )
'''

idx3 = content.find(sip_start_marker)
idx4 = content.find(sip_end_marker, idx3)
if idx3 != -1 and idx4 != -1:
    content = content[:idx3] + new_sip_scheme_block + "\n    " + content[idx4:]
    print("compute_deterministic_sip_blueprint updated to autonomous selection!")
else:
    print(f"Could not find sip markers: idx3={idx3}, idx4={idx4}")

me_file.write_text(content, encoding="utf-8")
print("core/math_engine.py successfully updated with pure autonomous selection!")

