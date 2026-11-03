"""
ui/pages/page_profile.py — SEBI Risk Profiling & Asset Allocation Questionnaire.
Maps client responses to official regulatory risk tiers (Level 1 Low to Level 6 Very High).
Includes tolerance band customization and custom riskometer overrides.
"""
from __future__ import annotations

import streamlit as st
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import advisor_lean as adv

def _load_config(client_path: Path) -> dict:
    cfg_file = client_path / "config.json"
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_config(client_path: Path, cfg: dict) -> None:
    cfg_file = client_path / "config.json"
    cfg_file.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


def render_profile_page(client_path: Path | None = None) -> None:
    st.header("📋 SEBI Regulatory Risk Profiler & SAA Engine")
    st.caption("Determine your regulatory risk capacity vs. tolerance under SEBI Investment Adviser Regulations.")

    # Load existing config
    client_path = client_path or adv.get_default_client_dir()
    config = _load_config(client_path)

    sebi_tiers = {
        "5_high": {
            "title": "🟠 Level 5: High (Dark Orange) — 85% Equity / 15% Debt",
            "desc": "Aggressive wealth compounding over 7-10+ year horizon with disciplined downside floor.",
            "saa": {"large": 45.0, "mid_small": 40.0, "debt": 15.0}
        },
        "6_very_high": {
            "title": "🔴 Level 6: Very High (Red) — 95% Equity / 5% Debt",
            "desc": "Maximum equity beta. Willing to endure 30%+ market drawdowns for peak compounding.",
            "saa": {"large": 45.0, "mid_small": 50.0, "debt": 5.0}
        },
        "4_moderately_high": {
            "title": "🟠 Level 4: Moderately High (Caramel) — 70% Equity / 30% Debt",
            "desc": "Balanced growth with substantial fixed-income ballast.",
            "saa": {"large": 40.0, "mid_small": 30.0, "debt": 30.0}
        },
        "3_moderate": {
            "title": "🟡 Level 3: Moderate (Neon Yellow) — 50% Equity / 50% Debt",
            "desc": "Capital preservation with balanced equity participation.",
            "saa": {"large": 30.0, "mid_small": 20.0, "debt": 50.0}
        },
        "2_low_to_moderate": {
            "title": "🟡 Level 2: Low to Moderate (Chartreuse) — 25% Equity / 75% Debt",
            "desc": "Conservative income generation with minor equity hedge.",
            "saa": {"large": 15.0, "mid_small": 10.0, "debt": 75.0}
        },
        "1_low": {
            "title": "🟢 Level 1: Low (Irish Green) — 10% Equity / 90% Debt",
            "desc": "Pure capital preservation. Zero equity volatility tolerance.",
            "saa": {"large": 10.0, "mid_small": 0.0, "debt": 90.0}
        }
    }

    # ── Tolerance Band Customization ──
    st.subheader("⚖️ Tolerance Band & Riskometer Settings")
    
    tol_col1, tol_col2 = st.columns([1, 1])
    
    with tol_col1:
        # Load existing tolerance from config
        existing_tol = config.get("target_allocation", {}).get("tolerance_band_pct", 5.0)
        tolerance = st.number_input(
            "SAA Tolerance Band (±%)",
            min_value=0.0,
            max_value=25.0,
            value=float(existing_tol),
            step=0.5,
            help="How far equity/debt allocation can drift from target before rebalancing is triggered. Lower = stricter rebalancing.",
        )
    
    with tol_col2:
        # Custom riskometer override
        existing_tier = config.get("ips", {}).get("risk_tier", 6)
        custom_tier = st.selectbox(
            "Override Riskometer Tier (if needed):",
            options=["auto_detect", 1, 2, 3, 4, 5, 6],
            index=["auto_detect", 1, 2, 3, 4, 5, 6].index(existing_tier) if existing_tier in [1,2,3,4,5,6] else 0,
            format_func=lambda x: "Auto-detect from holdings" if x == "auto_detect" else f"Tier {x}: {['Low','Low-Moderate','Moderate','Moderately-High','High','Very-High'][x-1]}",
            help="Override the SEBI risk-o-meter tier. 'Auto-detect' uses holdings-level riskometer scores.",
        )
    
    st.divider()

    selected_tier = st.selectbox(
        "Select Regulatory Risk Tier:",
        options=list(sebi_tiers.keys()),
        format_func=lambda k: sebi_tiers[k]["title"],
        index=0
    )

    t_info = sebi_tiers[selected_tier]
    st.info(f"**Target Mandate:** {t_info['desc']}")

    st.subheader("🎯 Target Strategic Asset Allocation (SAA)")
    mcol1, mcol2, mcol3 = st.columns(3)
    with mcol1:
        st.metric("Large-Cap Core", f"{t_info['saa']['large']:.0f}%")
    with mcol2:
        st.metric("Mid & Small-Cap Alpha", f"{t_info['saa']['mid_small']:.0f}%")
    with mcol3:
        st.metric("Debt & Stability Cushion", f"{t_info['saa']['debt']:.0f}%")
    
    # Show effective tolerance
    eff_tol = tolerance
    st.caption(f"✅ Effective tolerance band: ±{eff_tol:.1f}% | Riskometer: {'Auto-detect' if custom_tier == 'auto_detect' else f'Tier {custom_tier} (manual override)'}")

    st.divider()

    st.subheader("📊 Your Current Portfolio vs. Target SAA Drift")
    saa_res = adv.compute_saa(profile_name=selected_tier)
    curr = saa_res["current"]
    drift = saa_res["drift"]

    dcol1, dcol2, dcol3 = st.columns(3)
    with dcol1:
        st.metric("Current Equity", f"{curr['equity_pct']:.1f}%", f"{drift['equity']:+.1f}% vs Target", delta_color="inverse")
    with dcol2:
        st.metric("Current Debt", f"{curr['debt_pct']:.1f}%", f"{drift['debt']:+.1f}% Deficit", delta_color="normal")
    with dcol3:
        # Use custom tolerance for drift status
        drift_abs = max(abs(drift['equity']), abs(drift['debt']))
        status_label = "REBALANCE REQUIRED" if drift_abs > eff_tol else "WITHIN TOLERANCE"
        st.metric("Drift Status", status_label, delta=f"±{eff_tol:.1f}% band")

    if drift["debt"] < -eff_tol:
        st.warning(f"⚠️ **Debt Deficit Alert:** Your portfolio is underweight debt by {abs(drift['debt']):.1f}%. Fresh SIP and lumpsum flows should be prioritized to bridge this gap.")

    # ── Save button ──
    st.divider()
    if st.button("💾 Save Tolerance & Riskometer Settings"):
        cfg = _load_config(client_path)
        if "target_allocation" not in cfg:
            cfg["target_allocation"] = {}
        cfg["target_allocation"]["tolerance_band_pct"] = float(tolerance)
        
        if "ips" not in cfg:
            cfg["ips"] = {}
        if custom_tier != "auto_detect":
            cfg["ips"]["risk_tier"] = int(custom_tier)
        else:
            cfg["ips"].pop("risk_tier", None)
        
        # Update selected tier in config
        cfg["ips"]["risk_tolerance"] = selected_tier.split("_")[0]
        
        _save_config(client_path, cfg)
        st.success(f"✅ Saved! Tolerance: ±{tolerance:.1f}% | Riskometer: {'Auto-detect' if custom_tier == 'auto_detect' else f'Tier {custom_tier}'}")


if __name__ == "__main__":
    render_profile_page()

