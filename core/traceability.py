from __future__ import annotations
import json
import uuid
import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime, date
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

    def compute_hash(self) -> str:
        content = f"{self.decision_id}{self.decision_type.value}{self.recommendation}{self.rationale}"
        for ev in self.evidence:
            content += f"{ev.evidence_id}{ev.evidence_type.value}{ev.source}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
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
            "hash": self.hash or self.compute_hash()
        }

    def compute_hash(self) -> str:
        content = f"{self.decision_id}{self.decision_type.value}{self.recommendation}{self.rationale}"
        for ev in self.evidence:
            content += f"{ev.evidence_id}{ev.evidence_type.value}{ev.source}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
