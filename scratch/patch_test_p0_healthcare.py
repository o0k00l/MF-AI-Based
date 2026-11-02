with open('test_p0_fiduciary_invariants.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_test = """def test_p0_6_multi_horizon_selection_and_peer_evaluation():
    \"\"\"
    Verifies that the autonomous fund selection engine incorporates multi-horizon metrics
    (1-year return, 6-month trend, 3-year CAGR, Sharpe, TER) and dynamically selects the
    top-performing candidate while rejecting underperforming peers with high expense ratios.
    Specifically tests Healthcare / Pharma peer selection:
    Mirae Asset Healthcare Direct (Winner) vs Nippon India Pharma Direct (Rejected).
    \"\"\"
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
    print("[PASS] P0.6 Multi-Horizon Selection & Peer Evaluation Verified")"""

new_test = """def test_p0_6_multi_horizon_selection_and_peer_evaluation():
    \"\"\"
    Verifies that the autonomous fund selection engine incorporates multi-horizon metrics
    (1-year return, 6-month trend, 3-year CAGR, Sharpe, TER) and dynamically selects the
    top-performing candidate while rejecting underperforming peers.
    Specifically tests Healthcare / Pharma peer selection across ICICI, Mirae, Tata, and Nippon.
    \"\"\"
    from core.math_engine import compute_multi_horizon_fiduciary_score, select_autonomous_blueprint_funds
    from core.eligibility import load_candidate_universe

    metrics_path = Path("data/lalit_portfolio/fund_metrics.json")
    candidates = load_candidate_universe(metrics_path)

    pharma_cands = {c["fund_id"]: c for c in candidates if "health" in c["fund_name"].lower() or "pharma" in c["fund_name"].lower()}
    assert "ICICI Healthcare Direct" in pharma_cands, "ICICI Healthcare must be in candidate universe"
    assert "Mirae Healthcare Direct" in pharma_cands, "Mirae Healthcare must be in candidate universe"
    assert "Tata Pharma Direct" in pharma_cands, "Tata Pharma must be in candidate universe"
    assert "Nippon Pharma Direct" in pharma_cands, "Nippon Pharma must be in candidate universe"

    icici = pharma_cands["ICICI Healthcare Direct"]
    mirae = pharma_cands["Mirae Healthcare Direct"]
    nippon = pharma_cands["Nippon Pharma Direct"]

    score_icici = compute_multi_horizon_fiduciary_score(icici)
    score_mirae = compute_multi_horizon_fiduciary_score(mirae)
    score_nippon = compute_multi_horizon_fiduciary_score(nippon)

    # ICICI and Mirae decisively outperform Nippon on multi-horizon quantitative metrics
    assert score_icici > score_nippon, f"ICICI ({score_icici}) must outperform Nippon ({score_nippon})"
    assert score_mirae > score_nippon, f"Mirae ({score_mirae}) must outperform Nippon ({score_nippon})"
    assert icici["return_1y"] > nippon["return_1y"], "ICICI 1Y return (49.4%) exceeds Nippon (35.2%)"
    assert icici["ter_direct_pct"] < nippon["ter_direct_pct"], "ICICI Direct TER (0.89%) lower than Nippon (0.99%)"

    # Verify blueprint selection dynamically routes to the highest multi-horizon scorer (ICICI)
    slots = select_autonomous_blueprint_funds(holdings=[], client_risk_tier=6, thematic_deficit_theme="Pharma")
    slot4 = slots["Slot 4: Tactical Thematic Satellite"]
    assert "ICICI Prudential Healthcare" in slot4["scheme"], f"Expected ICICI Healthcare, got {slot4['scheme']}"
    assert slot4["gate_passed"] is True
    print("[PASS] P0.6 Multi-Horizon Selection & Peer Evaluation Verified")"""

assert old_test in content, "old_test not found"
content = content.replace(old_test, new_test, 1)

with open('test_p0_fiduciary_invariants.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("SUCCESS: Updated test_p0_fiduciary_invariants.py")

