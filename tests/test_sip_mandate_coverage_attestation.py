from __future__ import annotations

from datetime import date

import pytest

from services.sip_mandate_auth import MandateAuthenticationError, verify_mandate_schedule
from tests.mandate_test_utils import make_signed_mandate_schedule


AS_OF = date(2026, 11, 13)
OWNER = "investor-test-106"


def test_valid_signed_complete_empty_schedule_is_verified_zero() -> None:
    evidence, trust_registry = make_signed_mandate_schedule(AS_OF.isoformat(), OWNER)

    result = verify_mandate_schedule(
        evidence, owner_ref=OWNER, as_of=AS_OF, trust_registry=trust_registry,
    )

    assert result["status"] == "VERIFIED"
    assert evidence["signature_envelope"]["payload"]["schema_version"] == 2
    assert evidence["signature_envelope"]["payload"]["coverage_status"] == "COMPLETE"
    assert evidence["coverage_status"] == "COMPLETE"


def test_signed_partial_schedule_is_rejected_even_with_matching_outer_metadata() -> None:
    evidence, trust_registry = make_signed_mandate_schedule(
        AS_OF.isoformat(), OWNER, coverage_status="PARTIAL",
    )

    with pytest.raises(MandateAuthenticationError, match="completeness is not signer-attested"):
        verify_mandate_schedule(
            evidence, owner_ref=OWNER, as_of=AS_OF, trust_registry=trust_registry,
        )


def test_outer_complete_claim_cannot_override_signed_partial_coverage() -> None:
    evidence, trust_registry = make_signed_mandate_schedule(
        AS_OF.isoformat(), OWNER, coverage_status="PARTIAL",
    )
    evidence["coverage_status"] = "COMPLETE"

    with pytest.raises(MandateAuthenticationError, match="completeness is not signer-attested"):
        verify_mandate_schedule(
            evidence, owner_ref=OWNER, as_of=AS_OF, trust_registry=trust_registry,
        )


def test_outer_coverage_metadata_must_match_signed_payload() -> None:
    evidence, trust_registry = make_signed_mandate_schedule(AS_OF.isoformat(), OWNER)
    evidence["coverage_status"] = "PARTIAL"

    with pytest.raises(MandateAuthenticationError, match="coverage metadata is not signature-bound"):
        verify_mandate_schedule(
            evidence, owner_ref=OWNER, as_of=AS_OF, trust_registry=trust_registry,
        )


def test_schema_v1_unsigned_coverage_contract_is_rejected() -> None:
    evidence, trust_registry = make_signed_mandate_schedule(AS_OF.isoformat(), OWNER)
    payload = dict(evidence["signature_envelope"]["payload"])
    payload["schema_version"] = 1
    payload.pop("coverage_status")
    evidence["signature_envelope"]["payload"] = payload

    with pytest.raises(MandateAuthenticationError, match="signature payload schema is invalid"):
        verify_mandate_schedule(
            evidence, owner_ref=OWNER, as_of=AS_OF, trust_registry=trust_registry,
        )
