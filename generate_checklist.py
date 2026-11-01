import csv
from pathlib import Path
import advisor_lean as adv

def extract_amc(scheme_name: str) -> str:
    s = scheme_name.upper()
    for amc in ["HDFC", "NIPPON", "MOTILAL", "PARAG PARIKH", "PPFAS", "MIRAE", "CANARA ROBECO", "SBI", "ICICI PRUDENTIAL", "ICICI", "QUANT", "EDELWEISS", "WHITEOAK", "AXIS", "KOTAK", "UTI", "TATA"]:
        if amc in s:
            return amc
    return s.split()[0]

def resolve_clean_direct_name(scheme: str) -> str:
    s_lower = scheme.lower()
    if "parag parikh" in s_lower:
        return "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
    if "hdfc flexi" in s_lower:
        return "HDFC Flexi Cap Fund - Direct Plan - Growth Option"
    if "hdfc mid" in s_lower:
        return "HDFC Mid Cap Fund - Direct Plan - Growth"
    if "nippon" in s_lower and "large" in s_lower:
        return "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"
    if "icici" in s_lower and "large & mid" in s_lower:
        return "ICICI Prudential Large & Mid Cap Fund - Direct Plan - Growth"
    if "canara robeco" in s_lower and "multi asset" in s_lower:
        return "Canara Robeco Multi Asset Allocation Fund Direct Growth"
    t = scheme.replace("Regular Plan", "Direct Plan").replace("Regular Growth", "Direct Growth").replace("Regular", "Direct")
    if "GROWTH PLAN GROWTH OPTION" in t and "DIRECT" not in t:
        t = t.replace("GROWTH PLAN", "DIRECT GROWTH PLAN")
    elif "Direct" not in t:
        t = t + " - Direct Plan - Growth"
    return t.replace("Direct Plan - Direct Plan", "Direct Plan")

def generate_mfcentral_checklist():
    out_dir = Path("outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "MFCentral_Action_Checklist.csv"

    # Pre-calculate portfolio-wide tax loss harvesting capacity and lot maturation
    tax_harvest = adv.compute_tax_harvesting_ledger()
    total_losses_available = tax_harvest["total_unrealized_losses"]

    from collections import defaultdict
    lots = adv.compute_fifo_tax_lots()
    scheme_lot_map = defaultdict(lambda: {'mature': 0, 'immature': 0, 'immature_cost': 0.0})
    for l in lots:
        s = l['scheme']
        if l['is_ltcg']:
            scheme_lot_map[s]['mature'] += 1
        else:
            scheme_lot_map[s]['immature'] += 1
            scheme_lot_map[s]['immature_cost'] += l['invested_cost']

    # Smart AMC Routing Table: Map each AMC to client's existing direct core holding
    direct_by_amc = {}
    for h in adv.holdings:
        if "direct" in h["scheme"].lower():
            amc = extract_amc(h["scheme"])
            if amc not in direct_by_amc:
                direct_by_amc[amc] = h["scheme"]

    rows = []
    for h in adv.holdings:
        scheme = h["scheme"]
        s_lower = scheme.lower()
        folio = h["folio"]
        val = h["value"]
        inv = h["invested"]
        gain = val - inv
        is_direct = "direct" in s_lower
        amc = extract_amc(scheme)

        meta = adv.match_scheme(scheme) or {}
        category = meta.get("category", "")
        cat_lower = category.lower()

        if is_direct:
            action = "RETAIN CORE (Already Direct)"
            target = scheme
            savings = 0.0
            tax_advice = "No action needed (already in zero-commission direct plan)."
        else:
            savings = round(val * 0.0105, 2)

            # Rule D1: Multi-Cap Overlap Pruning (>25% stock overlap)
            if category == "Multi Cap":
                action = "CONSOLIDATE & EXIT (Multi-Cap Overlap)"
                if amc in direct_by_amc and "large" in direct_by_amc[amc].lower():
                    target = direct_by_amc[amc]  # Same-AMC switch on MFCentral (e.g. Nippon Multi Cap -> Nippon Large Cap Direct)
                else:
                    target = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"

            # Rule D2: Flexi-Cap Consolidation into Category Champion (PPFAS Score: 80.5 vs HDFC Score: 58.1)
            elif category == "Flexi Cap":
                if "parag parikh" in s_lower:
                    action = "SWITCH TO DIRECT PLAN (Keep Scheme)"
                    target = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
                else:
                    action = "CONSOLIDATE & EXIT (Flexi-Cap Consolidation into Core Flagship)"
                    target = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"

            # Rule D3: Category Duplication & Competition Arbiter (Mid Cap: HDFC Score 82.5 vs Motilal Score 67.0)
            elif category == "Mid Cap":
                if "hdfc" in s_lower:
                    action = "SWITCH TO DIRECT PLAN (Keep Scheme)"
                    target = "HDFC Mid Cap Fund - Direct Plan - Growth"
                else:
                    action = "CONSOLIDATE & EXIT (Mid-Cap Duplication & High Concentration)"
                    target = "HDFC Mid Cap Fund - Direct Plan - Growth"

            # Rule D4: Sectoral / Thematic De-risking Policy
            elif cat_lower.startswith("thematic") or cat_lower.startswith("sectoral") or any(w in s_lower for w in ["defence", "energy", "special opportunities"]):
                action = "CONSOLIDATE & EXIT (High Thematic Concentration)"
                # Smart AMC Router: Prioritize same-AMC direct switches on MFCentral
                if amc == "HDFC":
                    target = "HDFC Mid Cap Fund - Direct Plan - Growth"  # Same-AMC switch in Folio #22403163 into Category Champion
                elif "whiteoak" in s_lower:
                    target = "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"  # Global Flexi-Cap Anchor
                else:
                    target = "NIPPON INDIA LARGE CAP FUND - DIRECT GROWTH PLAN GROWTH OPTION"  # Direct Large-Cap Core Anchor

            # Rule D4: Multi-Asset & Hybrid Allocation Preservation
            elif category in ("Multi Asset Allocation", "Hybrid: DAA", "Aggressive Hybrid") or "multi asset" in s_lower:
                action = "SWITCH TO DIRECT PLAN (Keep Hybrid Allocation)"
                target = resolve_clean_direct_name(scheme)

            # Rule D5: Core Diversified Equity Direct Switch
            else:
                action = "SWITCH TO DIRECT PLAN (Keep Scheme)"
                target = resolve_clean_direct_name(scheme)

            # Tax Guardrail Calculation with Cross-Folio Loss Harvesting and Lot-Level Exit Load
            lot_info = scheme_lot_map.get(scheme, {'mature': 0, 'immature': 0, 'immature_cost': 0.0})
            if lot_info['immature'] > 0 and lot_info['mature'] > 0:
                load_note = f" TRANCHE SWITCH: {lot_info['mature']} mature lots (held >1yr, 0% load) ready now. Hold {lot_info['immature']} recent SIP lots (INR {lot_info['immature_cost']:,.0f}) to avoid 1% load."
            elif lot_info['immature'] > 0 and lot_info['mature'] == 0:
                load_note = f" HOLD RECENT LOTS: All {lot_info['immature']} lots held <1yr. Hold until maturation to avoid 1% exit load."
            else:
                load_note = " 0% EXIT LOAD: All units held >1 year."

            if gain > 125000:
                net_offset_gain = max(0.0, gain - total_losses_available)
                if net_offset_gain <= 125000:
                    tax_advice = f"TAX-FREE VIA LOSS-HARVESTING: Gain is INR {gain:,.0f}, but netting against portfolio losses (INR {total_losses_available:,.0f}) brings net gain to INR {net_offset_gain:,.0f} (<= INR 1.25L). Switch together with loss-making folios for ZERO tax!{load_note}"
                else:
                    tax_advice = f"SPLIT IN TRANCHES: Gain of INR {gain:,.0f} exceeds INR 1.25L LTCG limit. Split switch across 2 Financial Years to avoid 12.5% tax.{load_note}"
            elif gain > 0:
                tax_advice = f"TAX-FREE LTCG: Gain is INR {gain:,.0f} (within INR 1.25L annual tax-free window for units held >1 yr).{load_note}"
            else:
                tax_advice = f"HARVEST TAX LOSS: Unrealized loss of INR {abs(gain):,.0f}. Switch now to eliminate regular drag AND create capital losses to shelter other gains!{load_note}"

        rows.append({
            "Folio Number": folio,
            "Current Scheme Name": scheme,
            "Current Plan": "Direct" if is_direct else "Regular",
            "Current Value (INR)": f"{val:,.2f}",
            "Invested Value (INR)": f"{inv:,.2f}",
            "Unrealized Gain (INR)": f"{gain:+,.2f}",
            "Recommended Action": action,
            "Target Direct Scheme": target,
            "Annual Commission Saved (INR)": f"{savings:,.2f}" if savings > 0 else "₹0.00",
            "Execution Status": "Pending CGS Verification" if not is_direct else "Active Core (Direct)",
            "Tax Execution Guardrail": tax_advice
        })

    # Sort so regular switches come first, sorted by highest value
    rows.sort(key=lambda r: (r["Current Plan"] == "Direct", -float(r["Current Value (INR)"].replace(",", ""))))

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Checklist generated: {csv_path.name} with {len(rows)} holdings.")

if __name__ == "__main__":
    generate_mfcentral_checklist()
