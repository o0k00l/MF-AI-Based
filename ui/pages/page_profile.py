"""
ui/pages/page_profile.py — SEBI Risk Profiling & Asset Allocation Questionnaire.
Maps client responses to official regulatory risk tiers (Level 1 Low to Level 6 Very High).
"""
from __future__ import annotations

import streamlit as st
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import advisor_lean as adv


def render_profile_page() -> None:
    st.header("📋 SEBI Regulatory Risk Profiler & SAA Engine")
    st.caption("Determine your regulatory risk capacity vs. tolerance under SEBI Investment Adviser Regulations.")

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
        status_label = "REBALANCE REQUIRED" if saa_res.get("rebalance_required") else "WITHIN TOLERANCE"
        st.metric("Drift Status", status_label)

    if drift["debt"] < -5.0:
        st.warning(f"⚠️ **Debt Deficit Alert:** Your portfolio is underweight debt by {abs(drift['debt']):.1f}%. Fresh SIP and lumpsum flows should be prioritized to bridge this gap.")


if __name__ == "__main__":
    render_profile_page()

