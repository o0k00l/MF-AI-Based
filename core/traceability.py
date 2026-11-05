from __future__ import annotations
import rfc8785
import uuid
import hashlib
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, date
from decimal import Decimal
import math
from pathlib import Path
from typing import Dict, List, Any, Optional, Literal
from enum import Enum

class DecisionType(str, Enum):
    FUND_SELECTION = "FUND_SELECTION"
    PORTFOLIO_REBALANCING = "PORTFOLIO_REBALANCING"
    TAX_HARVESTING = "TAX_HARVESTING"
    REDEMPTION_PLANNING = "REDEMPTION_PLANNING"
    SIP_ALLOCATION = "SIP_ALLOCATION"
    LUMPSUM_DEPLOYMENT = "LUMPSUM_DEPLOYMENT"
    THEMATIC_TAPER = "THEMATIC_TAPER"
    MANDATE_HOLD = "MANDATE_HOLD"
    SWITCH_RECOMMENDATION = "SWITCH_RECOMMENDATION"
    CONSOLIDATION = "CONSOLIDATION"

class EvidenceType(str, Enum):
    GATE_EVALUATION = "GATE_EVALUATION"
    SCORE_BREAKDOWN = "SCORE_BREAKDOWN"
    COMPARATIVE_ANALYSIS = "COMPARATIVE_ANALYSIS"
    TAX_CALCULATION = "TAX_CALCULATION"
    LOOKTHROUGH_ANALYSIS = "LOOKTHROUGH_ANALYSIS"
    BENCHMARK_COMPARISON = "BENCHMARK_COMPARISON"
    MANDATE_CHECK = "MANDATE_CHECK"
    FOLIO_VERIFICATION = "FOLIO_VERIFICATION"
    POLICY_RULE = "POLICY_RULE"
    MARKET_DATA = "MARKET_DATA"

from datetime import timezone

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

@dataclass
class Evidence:
    evidence_id: str
    evidence_type: "EvidenceType"
    source: str
    description: str
    data: Dict[str, Any]
    timestamp: datetime
    confidence: Optional[float] = None
    verification_status: str = "UNVERIFIED"

    def __post_init__(self):
        if not isinstance(self.timestamp, datetime):
            raise ValueError("Evidence timestamp must be an explicit datetime object representing source observation time")
        if self.timestamp.tzinfo != timezone.utc:
            raise ValueError("Evidence timestamp must have explicit UTC timezone (timezone.utc required; implicit conversion prohibited)")
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
                raise ValueError("Evidence confidence must be numeric")
            if not 0.0 <= float(self.confidence) <= 1.0:
                raise ValueError("Evidence confidence must be bounded in [0.0, 1.0]")

    def to_dict(self) -> Dict[str, Any]:
        ts_utc = self.timestamp.astimezone(timezone.utc).isoformat()
        return _canonical_json_value({
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type.value,
            "source": self.source,
            "description": self.description,
            "data": self.data,
            "timestamp": ts_utc,
            "confidence": self.confidence,
            "verification_status": self.verification_status,
        })

@dataclass
class Decision:
    decision_id: str
    decision_type: "DecisionType"
    timestamp: datetime
    recommendation: str
    rationale: str
    policy_version: str
    code_version: str
    policy_digest: str
    evidence: List["Evidence"] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    mandate_state: str = "HOLD_PENDING_TRI_VALIDATION"
    is_actionable: bool = False
    hash: str = ""

    def __post_init__(self):
        if not isinstance(self.timestamp, datetime):
            raise ValueError("Decision timestamp must be a datetime object")
        if self.timestamp.tzinfo != timezone.utc:
            raise ValueError("Decision timestamp must have explicit UTC timezone (timezone.utc required; implicit conversion prohibited)")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("Explicit running policy_version is required; hardcoded defaults prohibited")
        if not isinstance(self.code_version, str) or not self.code_version.strip():
            raise ValueError("Explicit running code_version is required; hardcoded defaults prohibited")
        if not isinstance(self.policy_digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", self.policy_digest):
            raise ValueError("Decision requires an explicit 64-character SHA-256 policy_digest")

    def _hash_payload(self) -> Dict[str, Any]:
        """Return every decision field covered by the integrity digest."""
        ts_utc = self.timestamp.astimezone(timezone.utc).isoformat()
        payload = {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value,
            "timestamp": ts_utc,
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "evidence": [ev.to_dict() for ev in self.evidence],
            "inputs": self.inputs,
            "outputs": self.outputs,
            "policy_version": self.policy_version,
            "code_version": self.code_version,
            "mandate_state": self.mandate_state,
            "is_actionable": self.is_actionable,
            "policy_digest": self.policy_digest,
            "hash_version": "RFC8785-JCS-SHA256-v1",
        }
        return payload

    def compute_hash(self) -> str:
        """Return SHA-256 over RFC 8785/JCS canonical UTF-8 bytes.

        Exact Decimal audit values are normalized to JSON strings before JCS
        serialization so monetary precision is not silently rounded to an
        IEEE-754 binary float. Other JSON numbers must satisfy the I-JSON
        number domain enforced by the RFC 8785 implementation.
        """
        canonical_value = _canonical_json_value(self._hash_payload())
        encoded = rfc8785.dumps(canonical_value)
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        payload = _canonical_json_value(self._hash_payload())
        payload["hash"] = self.compute_hash()
        return payload


def _canonical_json_value(value: Any) -> Any:
    """Normalize supported audit values and reject ambiguous JSON values."""
    if isinstance(value, Enum):
        return _canonical_json_value(value.value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal values are not valid audit data")
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite float values are not valid audit data")
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Audit JSON object keys must be strings")
        return {key: _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return _canonical_json_value(value.model_dump(mode="json"))
    if hasattr(value, "__dataclass_fields__"):
        return _canonical_json_value(asdict(value))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Unsupported audit value type: {type(value).__name__}")
