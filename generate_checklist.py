"""
generate_checklist.py — Generate MFCentral Action Checklist CSV for Switch to Direct tab.
Automatically scans client holdings and generates a fiduciary-compliant checklist
of regular plans to switch to direct plans.
"""
import pandas as pd
from pathlib import Path


def generate_mfcentral_checklist(regular_funds=None, annual_bleed_inr=0.0):
    """
    Generate a CSV checklist of schemes to switch from Regular to Direct plans.
    Output: outputs/MFCentral_Action_Checklist.csv
    
    Args:
        regular_funds: List of dicts with fund details (scheme, value, etc.)
        annual_bleed_inr: Annual commission bleed value
    """
    ROOT = Path(__file__).resolve().parent
    OUT = ROOT.parent / "outputs"
    OUT.mkdir(exist_ok=True)
    csv_file = OUT / "MFCentral_Action_Checklist.csv"
    
    rows = []
    
    if regular_funds:
        for fund in regular_funds:
            scheme_name = fund.get("scheme", fund.get("fund_name", ""))
            current_value = fund.get("current_value_inr", fund.get("value", 0))
            
            if "direct" not in scheme_name.lower():
                annual_savings = current_value * 1.5 / 100  # 1.5% commission
                
                # Generate direct variant name
                direct_scheme = scheme_name.replace("Regular", "Direct").replace("REGULAR", "Direct")
                if "Direct" not in direct_scheme:
                    if " - " in direct_scheme:
                        parts = direct_scheme.split(" - ")
                        direct_scheme = f"{parts[0]} - Direct Plan" + (f" - {' - '.join(parts[1:])}" if len(parts) > 1 else "")
                
                rows.append({
                    "Current Scheme Name": scheme_name,
                    "Current Value (INR)": f"{current_value:,.2f}",
                    "Recommended Action": "SWITCH to Direct",
                    "Annual Commission Saved (INR)": f"{annual_savings:,.2f}",
                    "Target Direct Scheme": direct_scheme
                })
    
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "Current Scheme Name", "Current Value (INR)", "Recommended Action",
        "Annual Commission Saved (INR)", "Target Direct Scheme"
    ])
    
    df.to_csv(csv_file, index=False)
    print(f"[generate_checklist] Generated {len(rows)} switch recommendations to {csv_file}")
    return csv_file


if __name__ == "__main__":
    generate_mfcentral_checklist()