with open("test_p0_fiduciary_invariants.py", "r", encoding="utf-8") as f:
    text = f.read()

new_test = '''

def test_p0_6_multi_horizon_selection_and_peer_evaluation():
    """
    Verifies that the autonomous fund selection engine incorporates multi-horizon metrics
    (1-year return, 6-month trend, 3-year CAGR, Sharpe, TER) and dynamically selects the
    top-performing candidate while rejecting underperforming peers with high expense ratios.
    Specifically tests Healthcare / Pharma peer selection:
    Mirae Asset Healthcare Direct (Winner) vs Nippon India Pharma Direct (Rejected).
    """
    from core.math_engine import compute_multi_horizon_fiduciary_score, select_autonomous_blueprint_funds
    from core.eligibility import load_candidate_universe

    metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
    candidates = load_candidate_universe(metrics_path)

    pharma_cands = {c["fund_id"]: c for c in candidates if "health" in c["fund_name"].lower() or "pharma" in c["fund_name"].lower()}
    assert "Mirae Healthcare Direct" in pharma_cands, "Mirae Healthcare must be in candidate universe"
    assert "Nippon Pharma Direct" in pharma_cands, "Nippon Pharma must be in candidate universe"

    mirae = pharma_cands["Mirae Healthcare Direct"]
    nippon = pharma_cands["Nippon Pharma Direct"]

    score_mirae = compute_multi_horizon_fiduciary_score(mirae)
    score_nippon = compute_multi_horizon_fiduciary_score(nippon)

    # Mirae must decisively beat Nippon on multi-horizon quantitative metrics
    assert score_mirae > score_nippon * 3, f"Mirae ({score_mirae}) must crush Nippon ({score_nippon}) by >3x"
    assert mirae["return_1y"] > nippon["return_1y"] + 10.0, "Mirae 1Y return must exceed Nippon by >10%"
    assert mirae["ter_direct_pct"] < nippon["ter_direct_pct"], "Mirae Direct TER (0.62%) must be lower than Nippon (1.00%)"

    # Verify blueprint selection dynamically routes to the highest multi-horizon scorer
    slots = select_autonomous_blueprint_funds(holdings=[], client_risk_tier=6)
    slot4 = slots["Slot 4: Tactical Thematic Satellite"]
    assert "Mirae Asset Healthcare" in slot4["scheme"], f"Expected Mirae Healthcare, got {slot4['scheme']}"
    assert slot4["gate_passed"] is True
    print("[PASS] P0.6 Multi-Horizon Selection & Peer Evaluation Verified")
'''

main_trigger = 'if __name__ == "__main__":'
idx = text.find(main_trigger)
if idx != -1:
    text = text[:idx] + new_test + "\n" + text[idx:]
    text = text.replace("test_p0_5_fiduciary_personal_redemption_engine()", "test_p0_5_fiduciary_personal_redemption_engine()\n    test_p0_6_multi_horizon_selection_and_peer_evaluation()")
    with open("test_p0_fiduciary_invariants.py", "w", encoding="utf-8") as f:
        f.write(text)
    print("Patched test_p0_fiduciary_invariants.py successfully!")
else:
    print("Could not find main trigger")

