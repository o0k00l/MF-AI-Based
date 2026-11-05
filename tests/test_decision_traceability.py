from datetime import datetime, timezone
import pytest
from core.traceability import Decision, DecisionType, Evidence, EvidenceType


def test_evidence_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        Evidence(
            evidence_id="ev-1",
            evidence_type=EvidenceType.GATE_EVALUATION,
            source="test",
            description="test",
            data={},
            timestamp=datetime(2026, 11, 5, 10, 0),  # Naive
        )


def test_decision_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        Decision(
            decision_id="dec-1",
            decision_type=DecisionType.SIP_ALLOCATION,
            timestamp=datetime(2026, 11, 5, 10, 0),  # Naive
            recommendation="HOLD",
            rationale="test",
            policy_version="1.0",
            code_version="1.0",
        )


def test_decision_rejects_missing_policy_version():
    with pytest.raises(ValueError, match="policy_version"):
        Decision(
            decision_id="dec-1",
            decision_type=DecisionType.SIP_ALLOCATION,
            timestamp=datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc),
            recommendation="HOLD",
            rationale="test",
            policy_version="",  # Empty
            code_version="1.0",
        )


def test_decision_rejects_missing_code_version():
    with pytest.raises(ValueError, match="code_version"):
        Decision(
            decision_id="dec-1",
            decision_type=DecisionType.SIP_ALLOCATION,
            timestamp=datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc),
            recommendation="HOLD",
            rationale="test",
            policy_version="1.0",
            code_version="",  # Empty
        )


def test_evidence_validates_confidence_range():
    with pytest.raises(ValueError, match="bounded"):
        Evidence(
            evidence_id="ev-1",
            evidence_type=EvidenceType.GATE_EVALUATION,
            source="test",
            description="test",
            data={},
            timestamp=datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc),
            confidence=1.5,  # Out of bounds
        )


def test_decision_serializes_utc_and_computes_reproducible_jcs_hash():
    dt = datetime(2026, 11, 5, 10, 30, tzinfo=timezone.utc)
    ev = Evidence(
        evidence_id="ev-100",
        evidence_type=EvidenceType.POLICY_RULE,
        source="fund_screening.json",
        description="Gate evaluation passed",
        data={"gate": "AMC_CONCENTRATION", "passed": True},
        timestamp=dt,
        confidence=0.95,
        verification_status="VERIFIED",
    )
    dec = Decision(
        decision_id="dec-100",
        decision_type=DecisionType.SIP_ALLOCATION,
        timestamp=dt,
        recommendation="PROCEED",
        rationale="All screening gates passed",
        policy_version="2026.10",
        code_version="2.0.0",
        evidence=[ev],
        inputs={"budget_inr": 15000},
        outputs={"allocated_inr": 15000},
        policy_digest="a" * 64,
        mandate_state="ACTIVE",
        is_actionable=True,
    )

    d_dict = dec.to_dict()
    assert "+00:00" in d_dict["timestamp"] or d_dict["timestamp"].endswith("Z")
    assert len(d_dict["hash"]) == 64
    assert d_dict["hash_version"] == "RFC8785-JCS-SHA256-v1"
    assert d_dict["policy_version"] == "2026.10"
    assert d_dict["code_version"] == "2.0.0"
    assert d_dict["policy_digest"] == "a" * 64
