from datetime import datetime, timezone
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
