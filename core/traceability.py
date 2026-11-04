from __future__ import annotations
import json
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

@dataclass
class Evidence:
    evidence_id: str
    evidence_type: "EvidenceType"
    source: str
    description: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "evidence_type": self.evidence_type.value,
            "source": self.source,
            "description": self.description,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "confidence": self.confidence
        }

@dataclass
class Decision:
    decision_id: str
    decision_type: "DecisionType"
    timestamp: datetime
    recommendation: str
    rationale: str
    evidence: List["Evidence"] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    policy_version: str = "2.5"
    code_version: str = "1.0"
    mandate_state: str = "HOLD_PENDING_TRI_VALIDATION"
    is_actionable: bool = False
    hash: str = ""

    def _hash_payload(self) -> Dict[str, Any]:
        """Return every decision field covered by the integrity digest."""
        return {
            "decision_id": self.decision_id,
            "decision_type": self.decision_type.value,
            "timestamp": self.timestamp.isoformat(),
            "recommendation": self.recommendation,
            "rationale": self.rationale,
            "evidence": [ev.to_dict() for ev in self.evidence],
            "inputs": self.inputs,
            "outputs": self.outputs,
            "policy_version": self.policy_version,
            "code_version": self.code_version,
            "mandate_state": self.mandate_state,
            "is_actionable": self.is_actionable,
        }

    def compute_hash(self) -> str:
        """Return a full SHA-256 digest over deterministic canonical JSON.

        This is a deterministic Python JSON canonicalization contract. It is
        deliberately not advertised as RFC 8785/JCS until a conforming
        implementation is adopted and cross-language test vectors are added.
        """
        encoded = json.dumps(
            _canonical_json_value(self._hash_payload()),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        payload = self._hash_payload()
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
