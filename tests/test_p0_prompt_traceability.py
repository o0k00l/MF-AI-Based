from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace

from core import prompt_advisor
from core.traceability import Decision, DecisionType, Evidence, EvidenceType


def _decision():
    return Decision(
        decision_id="decision-001",
        decision_type=DecisionType.SIP_ALLOCATION,
        timestamp=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc),
        recommendation="HOLD",
        rationale="Required evidence is unavailable.",
        evidence=[
            Evidence(
                evidence_id="evidence-001",
                evidence_type=EvidenceType.GATE_EVALUATION,
                source="synthetic-test",
                description="Missing candidate evidence",
                data={"gate": "candidate_universe", "passed": False},
                timestamp=datetime(2026, 11, 4, 11, 0, tzinfo=timezone.utc),
                confidence=0.0,
            )
        ],
        inputs={"budget_inr": 10000, "risk_tier": "very_high"},
        outputs={"allocated_inr": 0, "unallocated_inr": 10000},
        policy_version="test-policy-1",
        code_version="test-code-1",
        mandate_state="HOLD_PENDING_TRI_VALIDATION",
        is_actionable=False,
    )


def test_decision_hash_is_full_sha256_and_covers_all_decision_content():
    decision = _decision()
    original = decision.compute_hash()

    assert len(original) == 64
    assert decision.to_dict()["hash"] == original

    decision.inputs["budget_inr"] = 20000
    assert decision.compute_hash() != original
    changed_inputs = decision.compute_hash()

    decision.inputs["budget_inr"] = 10000
    decision.outputs["unallocated_inr"] = 9000
    assert decision.compute_hash() != changed_inputs
    changed_outputs = decision.compute_hash()

    decision.outputs["unallocated_inr"] = 10000
    decision.evidence[0].data["passed"] = True
    assert decision.compute_hash() != changed_outputs
    changed_evidence = decision.compute_hash()

    decision.evidence[0].data["passed"] = False
    decision.policy_version = "test-policy-2"
    assert decision.compute_hash() != changed_evidence


def test_decision_hash_is_independent_of_mapping_insertion_order():
    left = _decision()
    right = _decision()
    left.inputs = {"a": 1, "b": {"x": 2, "y": 3}}
    right.inputs = {"b": {"y": 3, "x": 2}, "a": 1}

    assert left.compute_hash() == right.compute_hash()


def test_decision_serialization_normalizes_decimal_audit_values():
    decision = _decision()
    decision.inputs["exact_amount"] = Decimal("123.4500")

    serialized = decision.to_dict()

    assert serialized["inputs"]["exact_amount"] == "123.4500"
    assert len(serialized["hash"]) == 64


def test_decision_hash_rejects_non_finite_numbers():
    decision = _decision()
    decision.outputs["invalid"] = float("nan")

    try:
        decision.compute_hash()
    except ValueError:
        pass
    else:
        raise AssertionError("Non-finite audit values must be rejected")


def test_cash_sip_prompt_fails_closed_without_deterministic_plans(monkeypatch):
    facts = SimpleNamespace(
        client_name="Synthetic Investor",
        client_age=40,
        horizon_years=5,
        risk_tier_name="Tier 6 (Very High)",
        saa_drift=SimpleNamespace(target_equity_pct=95, target_debt_pct=5),
        monthly_sip_budget_inr=10000.0,
        lumpsum_budget_inr=200000.0,
        deterministic_sip_plan=None,
        deterministic_lumpsum_plan=None,
        stability_buffer=None,
        mandate_state="HOLD_PENDING_TRI_VALIDATION",
        is_execution_authorized=False,
        is_actionable_order=False,
    )
    monkeypatch.setattr(prompt_advisor, "_build_dynamic_selection_dossier", lambda _: "Synthetic dossier")
    monkeypatch.setattr(prompt_advisor, "_call_llm_with_retry", lambda prompt: prompt)

    prompt = prompt_advisor.generate_cash_and_sip_plan(facts)

    assert "NO ACTION" in prompt
    assert "full requested lumpsum budget remains unallocated" in prompt
    assert "requested budget remains unallocated" in prompt
    assert "20/80" not in prompt
    assert "31.2%" not in prompt
    assert "Section 50AA" not in prompt
    assert "Equity Arbitrage Fund" not in prompt
    assert "6-month STP" not in prompt
    assert "95:5 SAA target" not in prompt
    assert "100% Equity SIP routing" not in prompt


def test_interactive_fresh_money_answer_does_not_invent_a_plan():
    facts = SimpleNamespace(
        deterministic_sip_plan=None,
        deterministic_lumpsum_plan=None,
        monthly_sip_budget_inr=10000.0,
        lumpsum_budget_inr=200000.0,
    )

    answer = prompt_advisor.answer_interactive_query(facts, "show fresh money deployment")

    assert "NO ACTION" in answer
    assert "INR 200,000.00 remains unallocated" in answer
    assert "INR 10,000.00/month remains unallocated" in answer
    assert "20/80" not in answer
    assert "Section 50AA" not in answer
    assert "Equity Arbitrage Fund" not in answer


def test_selection_dossier_does_not_invent_peer_metrics():
    facts = SimpleNamespace(
        deterministic_sip_plan=None,
        eligibility_results=[],
        thematic_exposures=[],
    )

    dossier = prompt_advisor._build_dynamic_selection_dossier(facts)

    assert "eligibility comparison unavailable" in dossier
    assert "Do not invent peer names" in dossier
    assert "360.1" not in dossier
    assert "0.69%" not in dossier
    assert "80+ diffused holdings" not in dossier
    assert "HDFC Flexi Cap" not in dossier


def test_switch_report_fails_closed_without_tax_or_cost_evidence(monkeypatch):
    facts = SimpleNamespace(
        client_name="Synthetic Investor",
        holdings=[],
        overlap_matrix=[],
        weighted_overlap=[],
        fee_bleed=SimpleNamespace(
            details=[],
            annual_bleed_inr=1000.0,
            ten_year_compounded_loss_inr=12000.0,
            regular_portfolio_value_inr=100000.0,
            regular_funds_count=0,
        ),
        switch_costs=[],
        tax_lots_summary=None,
        total_portfolio_value_inr=100000.0,
        holdings_count=0,
        total_unrealized_gain_inr=0.0,
        mandate_state="HOLD_PENDING_TRI_VALIDATION",
        is_execution_authorized=False,
        is_actionable_order=False,
        no_action=None,
    )
    monkeypatch.setattr(prompt_advisor, "_call_llm_with_retry", lambda prompt: prompt)

    prompt = prompt_advisor.generate_switch_and_consolidation_plan(facts)

    assert "NO ACTION" in prompt
    assert "tax-lot conclusions and tax-optimized switch schedules are NO ACTION" in prompt
    assert "NO ACTION: scheme-level exit-load and tax cost evidence is unavailable." in prompt
    assert "If tax-lot or scheme-level switch-cost evidence is missing, state NO ACTION" in prompt
    assert "20% STCG" not in prompt
    assert "12.5% LTCG" not in prompt
    assert "1.25L" not in prompt
    assert "365" not in prompt
    assert "70%" not in prompt
    assert "80x" not in prompt
    assert "1.94% Regular TER" not in prompt
    assert "Motilal Defence Index" not in prompt


def test_redemption_interactive_response_does_not_invent_tax_waterfall():
    facts = SimpleNamespace(stability_buffer=None, tax_lots_summary=None)

    answer = prompt_advisor.answer_interactive_query(facts, "how should I redeem")

    assert "NO ACTION" in answer
    assert "Tax-lot evidence unavailable" in answer
    assert "20% STCG" not in answer
    assert "1,25,000" not in answer
    assert "Day 366" not in answer
    assert "INR 0 tax" not in answer


def _unvalidated_lumpsum_plan():
    return SimpleNamespace(
        total_lumpsum_inr=200000.0,
        unallocated_amount_inr=0.0,
        cash_validation_passed=False,
        cash_validation_message="Synthetic cash validation failure",
        execution_status="PROPOSED",
        tranches=[
            SimpleNamespace(
                role="Large-cap",
                scheme_name="Synthetic Fake Fund",
                folio_target=None,
                amount_inr=200000.0,
                allocation_pct=100.0,
                timing="Immediate",
                source_vehicle="Bank",
                fiduciary_rationale="Synthetic only",
            )
        ],
    )


def test_unvalidated_lumpsum_tranches_are_not_exposed_in_report(monkeypatch):
    facts = SimpleNamespace(
        client_name="Synthetic Investor",
        client_age=40,
        horizon_years=5,
        risk_tier_name="Tier 6 (Very High)",
        saa_drift=SimpleNamespace(target_equity_pct=95, target_debt_pct=5),
        monthly_sip_budget_inr=10000.0,
        lumpsum_budget_inr=200000.0,
        deterministic_sip_plan=None,
        deterministic_lumpsum_plan=_unvalidated_lumpsum_plan(),
        stability_buffer=None,
        mandate_state="HOLD_PENDING_TRI_VALIDATION",
        is_execution_authorized=False,
        is_actionable_order=False,
    )
    monkeypatch.setattr(prompt_advisor, "_build_dynamic_selection_dossier", lambda _: "Synthetic dossier")
    monkeypatch.setattr(prompt_advisor, "_call_llm_with_retry", lambda prompt: prompt)

    prompt = prompt_advisor.generate_cash_and_sip_plan(facts)

    assert "NO ACTION" in prompt
    assert "cash validation has not passed" in prompt
    assert "Synthetic Fake Fund" not in prompt


def test_unvalidated_lumpsum_tranches_are_not_exposed_interactively():
    facts = SimpleNamespace(
        deterministic_sip_plan=None,
        deterministic_lumpsum_plan=_unvalidated_lumpsum_plan(),
        monthly_sip_budget_inr=10000.0,
        lumpsum_budget_inr=200000.0,
    )

    answer = prompt_advisor.answer_interactive_query(facts, "show lumpsum deployment")

    assert "NO ACTION" in answer
    assert "cash validation has not passed" in answer
    assert "Synthetic Fake Fund" not in answer


def test_lumpsum_reporting_rejects_non_reconciling_plan():
    plan = _unvalidated_lumpsum_plan()
    plan.cash_validation_passed = True
    plan.unallocated_amount_inr = 1000.0

    valid, reason = prompt_advisor._validate_lumpsum_plan_for_reporting(plan, 200000.0)

    assert valid is False
    assert "do not reconcile" in reason


def test_switch_cost_engine_reports_unavailable_instead_of_zero():
    from types import SimpleNamespace
    from core.math_engine import calculate_switch_cost_analysis

    result = calculate_switch_cost_analysis(
        source_fund="Synthetic Regular Fund",
        target_fund="Synthetic Direct Fund",
        source_holding=SimpleNamespace(),
        target_fund_ter=0.5,
    )

    assert result.is_available is False
    assert result.net_switch_cost_inr is None
    assert result.exit_load_inr is None
    assert result.capital_gains_tax_inr is None
    assert "not zero" in result.warning.lower()


def test_tax_rules_loader_rejects_provisional_policy():
    from pathlib import Path
    import pytest
    from core.math_engine import _load_tax_rules
    from core.models import InsufficientDataError

    policy_path = Path(__file__).resolve().parents[1] / "data" / "policy" / "tax_rules.json"

    with pytest.raises(InsufficientDataError, match="provisional or lack independent"):
        _load_tax_rules(policy_path)


def test_legacy_tax_transition_and_switch_advice_fail_closed():
    from datetime import date
    import pytest
    from tax import transition_planner as planner

    blocked_calls = [
        lambda: planner.load_tax_rules(None),
        lambda: planner.classify_fund_for_tax(None, None),
        lambda: planner.get_tax_rates_for_sale("equity_oriented", date(2026, 4, 1), {}),
        lambda: planner.plan_fy_tranches({}, {}, date(2026, 4, 1), {}),
        lambda: planner.generate_transition_plan_md({}, {}, 0, "Synthetic", date(2026, 4, 1)),
        lambda: planner.write_transition_plan(None, {}, {}, 0, "Synthetic", date(2026, 4, 1)),
        lambda: planner.generate_stp_vs_lump_sum_comparison(100000, 30),
        lambda: planner.bogleheads_payback_years(1000, 10000, 0.5),
        lambda: planner.bogleheads_circuit_breaker(1000, 10000, 0.5, 5),
        lambda: planner.compare_switch_vs_stop_sip(10000, 1000, 0, 1, 0.5),
        lambda: planner.compute_exit_load_amortization(10000, 1),
    ]

    for invoke in blocked_calls:
        with pytest.raises(planner.TaxAdviceDisabledError, match="disabled pending independently approved"):
            invoke()


def test_legacy_tax_advice_alias_is_also_disabled():
    import pytest
    from tax import transition_planner as planner

    with pytest.raises(planner.TaxAdviceDisabledError):
        planner.evaluate_bogleheads_switch_hurdle(1000, 10000, 0.5, 5)


def test_legacy_fifo_tax_summary_is_disabled():
    import pytest
    from core import math_engine

    with pytest.raises(math_engine.TaxClassificationDisabledError, match="generic 365-day and 1% exit-load assumptions"):
        math_engine.compute_fifo_tax_lots(Path("synthetic-transactions.json"))


def test_legacy_tax_classifier_cannot_be_bypassed_with_caller_supplied_rules():
    import pytest
    from types import SimpleNamespace
    from core import math_engine

    with pytest.raises(math_engine.TaxClassificationDisabledError):
        math_engine._classify_fund_for_tax(
            SimpleNamespace(equity_pct=99.0),
            {"classification_test": {"equity_oriented_threshold_pct": 65.0}},
        )


def test_unreviewed_statutory_tax_citations_are_withheld():
    import pytest
    from datetime import date
    from core import math_engine

    with pytest.raises(math_engine.TaxClassificationDisabledError):
        math_engine.get_statutory_tax_citation(date(2026, 11, 4))


def test_reporting_ignores_unverified_tax_lot_and_switch_cost_payloads(monkeypatch):
    from types import SimpleNamespace
    from core import prompt_advisor

    captured = {}
    monkeypatch.setattr(
        prompt_advisor,
        "_call_llm_with_retry",
        lambda prompt: captured.setdefault("prompt", prompt),
    )
    spoofed_tax = {"total_ltcg_tax_inr": 1, "classification": "APPROVED-SPOOF"}
    spoofed_cost = {
        "fund_name": "Synthetic Fund",
        "switch_cost_inr": 1,
        "switch_cost_pct": 0.01,
        "available": True,
        "warning": "none",
    }
    facts = SimpleNamespace(
        holdings=[],
        fee_bleed=SimpleNamespace(details=[], annual_bleed_inr=0, ten_year_compounded_loss_inr=0),
        overlap_matrix=[],
        weighted_overlap=[],
        switch_costs=[spoofed_cost],
        tax_lots_summary=spoofed_tax,
        total_portfolio_value_inr=100000,
        holdings_count=0,
        total_unrealized_gain_inr=0,
        mandate_state="HOLD_PENDING_TRI_VALIDATION",
        is_execution_authorized=False,
        is_actionable_order=False,
        no_action=None,
    )

    prompt_advisor.generate_switch_and_consolidation_plan(facts)
    prompt = captured["prompt"]

    assert "APPROVED-SPOOF" not in prompt
    assert "Synthetic Fund" not in prompt
    assert "switch_cost_inr" not in prompt
    assert "UNAVAILABLE — tax-lot conclusions" in prompt
    assert "switch-cost figures supplied to the report are unverified" in prompt


def test_legacy_taxlot_model_maturity_helper_is_disabled():
    import pytest
    from core.models import TaxLot

    lot = TaxLot(
        fund_id="synthetic",
        purchase_date="2025-11-04",
        units=1,
        nav=100,
        cost_basis=100,
        holding_days=365,
        is_long_term=False,
    )
    with pytest.raises(RuntimeError, match="Tax-lot maturity classification is disabled"):
        lot.is_long_term_given(datetime(2026, 11, 4).date())


def test_legacy_cli_stops_before_reading_client_data_or_generating_reports():
    import runpy
    import pytest

    legacy_cli = Path(__file__).resolve().parents[1] / "legacy" / "advisor_lean_cli.py"
    with pytest.raises(SystemExit, match="Legacy advisor CLI is disabled"):
        runpy.run_path(str(legacy_cli), run_name="__main__")


def test_legacy_advisor_wrapper_does_not_delegate_to_retired_cli():
    import pytest
    import advisor_lean

    with pytest.raises(SystemExit, match="legacy advisor CLI is retired and disabled"):
        advisor_lean.main()


def test_interactive_redemption_ignores_spoofed_tax_lot_summary():
    from types import SimpleNamespace
    from core import prompt_advisor

    facts = SimpleNamespace(
        stability_buffer=None,
        tax_lots_summary={
            "classification": "SPOOFED-APPROVED",
            "ltcg_tax_inr": 1,
            "exit_load": 0,
        },
    )
    response = prompt_advisor.answer_interactive_query(facts, "How should I redeem?")
    assert "SPOOFED-APPROVED" not in response
    assert "ltcg_tax_inr" not in response
    assert "Tax-lot evidence unavailable" in response


def test_health_audit_prompt_does_not_interpolate_caller_switch_costs():
    import inspect
    from core import prompt_advisor

    source = inspect.getsource(prompt_advisor.generate_health_audit_report)
    assert "Switch Cost Evidence: UNAVAILABLE" in source
    assert "Switch Cost Details: NO ACTION" in source
    assert "s['switch_cost_inr']" not in source
    assert "getattr(facts, 'switch_costs', [])[:5]" not in source


def test_portfolio_aggregation_does_not_call_disabled_tax_classifier():
    import inspect
    from core import math_engine

    source = inspect.getsource(math_engine.aggregate_fiduciary_facts)
    assert "compute_fifo_tax_lots(" not in source
    assert "tax_lots_summary = None" in source
    assert "reconcile_cas_holdings_with_transactions" in source


def test_legacy_fifo_lot_preparation_api_is_disabled_until_contract_is_complete():
    from pathlib import Path
    import pytest
    from core import math_engine

    with pytest.raises(math_engine.TaxClassificationDisabledError, match="output model and provenance/reconciliation contract are incomplete"):
        math_engine.build_fifo_tax_lots(Path("synthetic-transactions.json"), [])
