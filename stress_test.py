"""
stress_test.py — Deterministic Portfolio Stress Testing & Market Shock Simulator.
Simulates market drawdowns across Current Portfolio vs Target Fiduciary Portfolio.
Zero external dependencies; accepts holdings/config as parameters (no circular imports).
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

# Ensure workspace root is importable
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Predefined Historical & Macro Shocks
SCENARIOS = {
    "mild_correction": {
        "name": "15% Market Correction (Normal Business Cycle Dip)",
        "description": "Standard 15% equity correction with higher mid/small-cap volatility.",
        "shocks": {
            "large_cap": -0.10,
            "mid_small_cap": -0.18,
            "thematic": -0.22,
            "hybrid": -0.06,
            "debt": +0.015,
        }
    },
    "covid_2020_crash": {
        "name": "2020 Covid Shock (Rapid Severe Liquidity Shock)",
        "description": "Fast 30%+ broad-market plunge with flight to safety into sovereign debt.",
        "shocks": {
            "large_cap": -0.25,
            "mid_small_cap": -0.38,
            "thematic": -0.45,
            "hybrid": -0.14,
            "debt": +0.030,
        }
    },
    "thematic_unwind": {
        "name": "Thematic Sector Rotation (Defence & Energy Unwind)",
        "description": "Overvalued thematic momentum bets retrace while broad market remains flat.",
        "shocks": {
            "large_cap": +0.02,
            "mid_small_cap": -0.05,
            "thematic": -0.30,
            "hybrid": +0.01,
            "debt": +0.020,
        }
    },
    "gfc_2008_crisis": {
        "name": "2008 GFC Systemic Meltdown (Deep Extended Bear Market)",
        "description": "Prolonged liquidity & banking freeze with multi-year drawdown.",
        "shocks": {
            "large_cap": -0.45,
            "mid_small_cap": -0.60,
            "thematic": -0.65,
            "hybrid": -0.25,
            "debt": +0.050,
        }
    }
}

def classify_holding(scheme_name: str) -> str:
    """Classifies a mutual fund scheme into stress shock buckets."""
    s = scheme_name.lower()
    if any(k in s for k in ["defence", "energy", "special opportunities", "special opp"]):
        return "thematic"
    if any(k in s for k in ["balanced advantage", "baf", "prudence", "multi asset", "hybrid"]):
        return "hybrid"
    if any(k in s for k in ["debt", "liquid", "short term", "gilt", "overnight", "money market", "banking & psu"]):
        return "debt"
    if any(k in s for k in ["mid", "small", "emerging", "multi cap", "multicap"]):
        return "mid_small_cap"
    return "large_cap"

def run_stress_tests(
    custom_holdings: Optional[List[Dict[str, Any]]] = None,
    target_saa: Optional[Dict[str, float]] = None,
    client_cfg: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Evaluates Current Portfolio vs Target Fiduciary Portfolio under each stress scenario.
    Dynamically maps target asset allocation based on client's selected SEBI tolerance profile.
    """
    # Default to empty holdings if not provided (for testing)
    holdings = custom_holdings if custom_holdings is not None else []
    total_val = sum(h["value"] for h in holdings) if holdings else 0.0

    # 1. Map Current Holdings to Asset Buckets
    bucket_values = {
        "large_cap": 0.0,
        "mid_small_cap": 0.0,
        "thematic": 0.0,
        "hybrid": 0.0,
        "debt": 0.0,
    }
    for h in holdings:
        bucket = classify_holding(h["scheme"])
        bucket_values[bucket] += h["value"]

    # 2. Define Target Fiduciary Portfolio Asset Buckets
    # If target_saa provided (e.g. {"large": 50.0, "mid_small": 35.0, "debt": 15.0}), use it;
    # otherwise default to client config target.
    if target_saa:
        tgt_large = float(target_saa.get("large", 50.0)) / 100.0
        tgt_msm = float(target_saa.get("mid_small", 35.0)) / 100.0
        tgt_debt = float(target_saa.get("debt", 15.0)) / 100.0
    else:
        cfg_target = (client_cfg or {}).get("target_allocation", {})
        tgt_large = float(cfg_target.get("large_cap_pct", 50.0)) / 100.0
        tgt_msm = float(cfg_target.get("mid_small_cap_pct", 35.0)) / 100.0
        tgt_debt = float(cfg_target.get("debt_global_pct", 15.0)) / 100.0

    target_bucket_values = {
        "large_cap": total_val * tgt_large,
        "mid_small_cap": total_val * tgt_msm,
        "thematic": 0.0,  # Thematics eliminated in core fiduciary model
        "hybrid": 0.0,
        "debt": total_val * tgt_debt,
    }

    results = {}
    for sc_key, sc in SCENARIOS.items():
        shocks = sc["shocks"]
        
        # Current Portfolio Impact
        curr_post_val = sum(bucket_values[b] * (1.0 + shocks[b]) for b in bucket_values)
        curr_loss = curr_post_val - total_val
        curr_loss_pct = (curr_loss / total_val) * 100.0

        # Target Fiduciary Portfolio Impact
        tgt_post_val = sum(target_bucket_values[b] * (1.0 + shocks[b]) for b in target_bucket_values)
        tgt_loss = tgt_post_val - total_val
        tgt_loss_pct = (tgt_loss / total_val) * 100.0

        # Capital Protected by Fiduciary Rebalancing
        capital_cushioned = tgt_post_val - curr_post_val
        cushion_pct = (capital_cushioned / total_val) * 100.0

        results[sc_key] = {
            "name": sc["name"],
            "description": sc["description"],
            "current_portfolio": {
                "initial_value": total_val,
                "post_shock_value": round(curr_post_val, 2),
                "drawdown_inr": round(curr_loss, 2),
                "drawdown_pct": round(curr_loss_pct, 2),
            },
            "target_portfolio": {
                "initial_value": total_val,
                "post_shock_value": round(tgt_post_val, 2),
                "drawdown_inr": round(tgt_loss, 2),
                "drawdown_pct": round(tgt_loss_pct, 2),
            },
            "fiduciary_cushion": {
                "capital_saved_inr": round(capital_cushioned, 2),
                "drawdown_reduction_pct": round(abs(curr_loss_pct) - abs(tgt_loss_pct), 2),
            }
        }

    return {
        "portfolio_total": total_val,
        "current_buckets": bucket_values,
        "target_buckets": target_bucket_values,
        "scenarios": results,
    }


class StressTestEngine:
    """Object-oriented fiduciary stress testing and macro shock engine."""

    def __init__(self, holdings: Optional[List[Dict[str, Any]]] = None, target_saa: Optional[Dict[str, float]] = None):
        self.holdings = holdings
        self.target_saa = target_saa

    def run(self) -> Dict[str, Any]:
        """Runs the 4 deterministic macro stress scenarios."""
        return run_stress_tests(custom_holdings=self.holdings, target_saa=self.target_saa)

    def print_report(self):
        """Prints the terminal report for client presentation."""
        print_cli_report()


def print_cli_report():
    # Import here to avoid circular import
    import advisor_lean as adv
    data = run_stress_tests(
        custom_holdings=adv.holdings,
        client_cfg=adv.cfg
    )
    tot = data["portfolio_total"]
    b = data["current_buckets"]
    client_name = adv.facts.get("client", "Valued Client")

    print("=" * 80)
    print("  PORTFOLIO STRESS TEST & DRAWDOWN SIMULATOR")
    print(f"  Client: {client_name} | Portfolio Base: INR {tot:,.2f}")
    print("=" * 80)
    print("Current Risk Distribution:")
    print(f"  • Large Cap Equity:    INR {b['large_cap']:>11,.0f} ({b['large_cap']/tot*100:4.1f}%)")
    print(f"  • Mid & Small Cap:     INR {b['mid_small_cap']:>11,.0f} ({b['mid_small_cap']/tot*100:4.1f}%)")
    print(f"  • Thematic Bets:       INR {b['thematic']:>11,.0f} ({b['thematic']/tot*100:4.1f}%) [Sectoral/Momentum]")
    print(f"  • Hybrid / BAF:        INR {b['hybrid']:>11,.0f} ({b['hybrid']/tot*100:4.1f}%)")
    print(f"  • Debt / Fixed Income: INR {b['debt']:>11,.0f} ({b['debt']/tot*100:4.1f}%)")
    print("-" * 80)

    print(f"{'Shock Scenario':<36} | {'Current Loss':<18} | {'Target Loss':<18} | {'Capital Saved':<12}")
    print("-" * 80)

    for sc_key, sc in data["scenarios"].items():
        name = sc["name"][:35]
        curr = f"INR {sc['current_portfolio']['drawdown_inr']:>10,.0f} ({sc['current_portfolio']['drawdown_pct']:+.1f}%)"
        tgt = f"INR {sc['target_portfolio']['drawdown_inr']:>10,.0f} ({sc['target_portfolio']['drawdown_pct']:+.1f}%)"
        saved = f"+INR {sc['fiduciary_cushion']['capital_saved_inr']:>7,.0f}"
        print(f"{name:<36} | {curr:<18} | {tgt:<18} | {saved:<12}")

    covid_cushion = data["scenarios"].get("covid_2020_crash", {}).get("fiduciary_cushion", {}).get("capital_saved_inr", 0.0)
    thematic_cushion = data["scenarios"].get("thematic_unwind", {}).get("fiduciary_cushion", {}).get("capital_saved_inr", 0.0)
    target_debt = data["target_buckets"].get("debt", 0.0)

    print("=" * 80)
    print("KEY TAKEAWAYS:")
    print(f"1. In a Covid-2020 liquidity crash, moving to the target fiduciary portfolio cushions ~INR {covid_cushion:,.0f} in capital.")
    print(f"2. In a Sectoral Unwind, eliminating high-beta thematics protects ~INR {thematic_cushion:,.0f} from sharp drawdown.")
    print(f"3. The target INR {target_debt:,.0f} debt floor provides dry powder to rebalance into equities at market bottoms.")
    print("=" * 80)

if __name__ == "__main__":
    print_cli_report()

