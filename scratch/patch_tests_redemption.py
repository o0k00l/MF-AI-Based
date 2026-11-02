from pathlib import Path

test_file = Path("test_p0_fiduciary_invariants.py")
content = test_file.read_text(encoding="utf-8")

new_test = '''
def test_p0_5_fiduciary_personal_redemption_engine():
    """Verifies the Deterministic Fiduciary Personal Cash Redemption Engine across all ticket sizes."""
    from advisor import get_default_paths
    from core.math_engine import aggregate_fiduciary_facts
    from core.redemption_engine import compute_personal_redemption_plan
    from core.models import RedemptionPriorityTier

    cas, metrics, config, aliases, _ = get_default_paths()
    facts = aggregate_fiduciary_facts(cas, metrics, config, aliases)
    tx_path = cas.parent.parent / "transactions.json"
    if not tx_path.exists():
        tx_path = cas.parent / "transactions.json"

    # 1. Test Small-Ticket (<= 1L) -> Single-fund MFCentral friction minimization
    plan_small = compute_personal_redemption_plan(
        requested_amount=100000.0,
        holdings=facts.holdings,
        transactions_path=tx_path,
        is_net_cash=False
    )
    assert plan_small.ticket_category == "SMALL_TICKET"
    assert plan_small.funds_liquidated_count == 1, "Small-ticket must use single fund to minimize operational friction"
    assert plan_small.total_exit_load_inr == 0.0, "0% Exit load guarantee must be respected"
    assert plan_small.total_gross_redeemed_inr == 100000.0
    assert plan_small.tranches[0].priority_tier == RedemptionPriorityTier.BUBBLE_DERISKING
    assert plan_small.total_annual_commission_saved_inr > 0, "Must terminate broker commission bleed"

    # 2. Test Medium-Ticket (1L to 5L) -> Complete folio cleanups
    plan_med = compute_personal_redemption_plan(
        requested_amount=300000.0,
        holdings=facts.holdings,
        transactions_path=tx_path,
        is_net_cash=False
    )
    assert plan_med.ticket_category == "MEDIUM_TICKET"
    assert plan_med.full_folio_exits_count >= 1, "Medium ticket must prioritize 100% full folio closures"
    assert plan_med.total_gross_redeemed_inr == 300000.0
    assert plan_med.total_tax_sheltered_under_112a_inr == 125000.0, "Must maximize Sec 112A 1.25L annual exemption"
    assert plan_med.total_exit_load_inr == 0.0

    # 3. Test Large-Ticket (> 5L) -> Macro structural derisking & Sec 70 Loss Harvesting
    plan_large = compute_personal_redemption_plan(
        requested_amount=1000000.0,
        holdings=facts.holdings,
        transactions_path=tx_path,
        is_net_cash=False
    )
    assert plan_large.ticket_category == "LARGE_TICKET"
    assert plan_large.full_folio_exits_count >= 4, "Large ticket must sweep all bubble funds"
    # Ensure all bubble funds are wiped out before regular
    assert any("Loss Harvesting" in t.fiduciary_reason for t in plan_large.tranches), "Must harvest Sec 70 capital loss"
    assert plan_large.total_annual_commission_saved_inr >= 10000.0, "Must save substantial recurring broker fee"
    # Core Direct anchors must be protected
    for t in plan_large.tranches:
        assert "direct" not in t.scheme_name.lower() or "baf" not in t.scheme_name.lower(), "Core anchors must not be touched"

    # 4. Test Net Cash Target Mode
    plan_net = compute_personal_redemption_plan(
        requested_amount=200000.0,
        holdings=facts.holdings,
        transactions_path=tx_path,
        is_net_cash=True
    )
    assert plan_net.is_net_cash_target is True
    assert plan_net.total_net_cash_inr >= 200000.0, "Net cash received must satisfy requested amount"
    assert plan_net.total_exit_load_inr == 0.0

    print("[PASS] P0.5 Fiduciary Personal Redemption Engine Verified (Small, Med, Large, Net)")
'''

if "def test_p0_5_fiduciary_personal_redemption_engine" not in content:
    content = content.replace("if __name__ == \"__main__\":", new_test + "\nif __name__ == \"__main__\":")
    content = content.replace(
        "test_p0_4_candidate_universe_and_no_action_branch()",
        "test_p0_4_candidate_universe_and_no_action_branch()\n    test_p0_5_fiduciary_personal_redemption_engine()"
    )
    test_file.write_text(content, encoding="utf-8")
    print("test_p0_fiduciary_invariants.py updated with test_p0_5!")
else:
    print("test_p0_5 already present.")

