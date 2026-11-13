from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import pytest

from core.models import AssetAllocationTarget, RiskTier
from core.math_engine import (
    calculate_universal_tier_split,
    select_autonomous_blueprint_funds,
    compute_deterministic_sip_blueprint,
)
from services import sip_recommendation as service


def test_calculate_universal_tier_split_with_custom_saa():
    target = AssetAllocationTarget(
        equity_pct=Decimal("65.0"),
        debt_pct=Decimal("35.0"),
        cash_pct=Decimal("0.0"),
    )
    eq, debt = calculate_universal_tier_split(0, custom_saa_target=target)
    assert eq == 65.0
    assert debt == 35.0


def test_calculate_universal_tier_split_rejects_invalid_custom_saa():
    with pytest.raises(ValueError, match="AssetAllocationTarget instance"):
        calculate_universal_tier_split(0, custom_saa_target={"equity_pct": 60})

    with pytest.raises(ValueError, match="tier_num must be an integer from 1 through 6"):
        calculate_universal_tier_split(7, custom_saa_target=None)


def test_select_autonomous_blueprint_funds_custom_requires_target():
    with pytest.raises(ValueError, match="Custom risk profile requires an explicitly approved custom SAA"):
        select_autonomous_blueprint_funds(client_risk_tier=RiskTier.CUSTOM, custom_saa_target=None)

    with pytest.raises(ValueError, match="Custom risk profile requires an explicitly approved custom SAA"):
        select_autonomous_blueprint_funds(client_risk_tier="Custom", custom_saa_target=None)


def test_select_autonomous_blueprint_funds_custom_with_target():
    target = AssetAllocationTarget(
        equity_pct=Decimal("75.0"),
        debt_pct=Decimal("25.0"),
        cash_pct=Decimal("0.0"),
        large_cap_pct=Decimal("30.0"),
        mid_cap_pct=Decimal("20.0"),
        small_cap_pct=Decimal("15.0"),
        flexi_cap_pct=Decimal("10.0"),
        risk_ceiling=4,
    )
    # Call with minimal candidate universe
    slots = select_autonomous_blueprint_funds(
        client_risk_tier=RiskTier.CUSTOM,
        custom_saa_target=target,
        candidate_universe=[],
    )
    assert isinstance(slots, dict)
    assert "Slot 1: Core Flexi-Cap Compounder" in slots
    assert "High-Grade Debt Anchor" in slots


def test_compute_deterministic_sip_blueprint_custom_requires_target():
    with pytest.raises(ValueError, match="Custom risk profile requires an explicitly approved custom SAA target"):
        compute_deterministic_sip_blueprint(
            monthly_budget=10000,
            risk_tier="Custom",
            client_aum=1000000,
            client_aum_verified=True,
            custom_saa_target=None,
        )


def test_compute_deterministic_sip_blueprint_custom_executes_correctly():
    target = AssetAllocationTarget(
        equity_pct=Decimal("80.0"),
        debt_pct=Decimal("20.0"),
        cash_pct=Decimal("0.0"),
        large_cap_pct=Decimal("30.0"),
        mid_cap_pct=Decimal("25.0"),
        small_cap_pct=Decimal("15.0"),
        flexi_cap_pct=Decimal("10.0"),
        risk_ceiling=4,
    )
    plan = compute_deterministic_sip_blueprint(
        monthly_budget=10000,
        risk_tier="Custom",
        client_aum=2000000,
        client_aum_verified=True,
        custom_saa_target=target,
        candidate_universe=[],
    )
    assert plan.equity_sip_pct == 80.0
    assert plan.debt_sip_pct == 20.0
    assert plan.total_monthly_budget_inr == Decimal("10000.00")
    roles = {item.category_role for item in plan.items}
    assert any("Debt" in role for role in roles)
    assert "Core Flexi-Cap Compounder" in roles
    assert "Mid-Cap Alpha Engine" in roles
    assert "Small-Cap Growth Engine" in roles
    assert "Large-Cap Bluechip Anchor" in roles


def test_recommend_sip_custom_saa_e2e_with_approved_context(tmp_path, monkeypatch):
    import openpyxl

    cas = tmp_path / "cas.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Portfolio Details"
    today_str = date.today().strftime("%d-%b-%Y")
    as_of = date.today().isoformat()
    sheet.append(["To Date", today_str])
    sheet.append(["Scheme Name", "Folio No.", "Invested Value", "Current Value", "Units"])
    sheet.append(["Custom Fund Direct Growth", "FOLIO-1", 100000.0, 100000.0, 1000.0])
    workbook.save(cas)

    target = AssetAllocationTarget(
        equity_pct=Decimal("60.0"),
        debt_pct=Decimal("40.0"),
        cash_pct=Decimal("0.0"),
        large_cap_pct=Decimal("25.0"),
        mid_cap_pct=Decimal("15.0"),
        small_cap_pct=Decimal("10.0"),
        flexi_cap_pct=Decimal("10.0"),
        risk_ceiling=4,
    )

    candidates = [
        {
            "fund_id": f"CAND-{i}",
            "scheme_id": f"SCHEME-{i}",
            "category": "Large Cap",
            "direct_plan_evidence": {
                "scheme_id": f"SCHEME-{i}",
                "reviewed_at": as_of,
                "source_document_sha256": "a" * 64,
            },
        }
        for i in range(1, 31)
    ]

    context = {
        "current_core_fund_count": 0,
        "evidence_attested_by_provider": True,
        "investor_owner_ref": "INVESTOR-REF-TEST",
        "sip_mandate_evidence": {
            "coverage_status": "COMPLETE",
            "source_ref": "sha256:" + "a" * 64,
            "mandates": [],
        },
        "as_of_date": as_of,
        "cas_valuation_date": as_of,
        "perimeter_complete": True,
        "assets": [
            {
                "asset_id": "ASSET-1",
                "asset_class": "cas_mutual_fund",
                "saa_bucket": "large_cap",
                "value_inr": "100000.00",
                "source_ref": "sha256:1234567890abcdef",
                "owner_scope": "primary_investor",
                "as_of_date": as_of,
            }
        ],
        "excluded_assets": [],
        "unmatched_items": [],
        "sign_off": {
            "attested_by": "ADV-001 (Senior Advisor)",
            "attestation_timestamp_utc": "2026-11-11T00:00:00Z",
            "attestation_statement": "Perimeter verified and reconciled for custom SAA mandate.",
            "signature_ref": "sig:ed25519:advisor_signature",
        },
        "ips": {
            "approved": True,
            "source_ref": "DOC-IPS-CUSTOM-001",
            "effective_date": as_of,
            "target_weights_pct": {
                "large_cap": 25.0,
                "mid_cap": 15.0,
                "small_cap": 10.0,
                "flexi_multi_cap": 10.0,
                "debt_liquid": 40.0,
            },
            "tolerance_band_pct": 3.0,
        },
        "candidate_policy": {
            "max_evidence_age_days": 45,
            "mandatory_gates": ["direct_plan"],
            "candidate_sleeves": {f"CAND-{i}": "large_cap" for i in range(1, 31)},
            "rounding_increment_inr": "500",
        },
        "candidate_gate_results": {
            f"CAND-{i}": {"direct_plan": "PASS"} for i in range(1, 31)
        },
        "operational_evidence_by_candidate_id": {
            f"CAND-{i}": {
                "scheme_identity": {
                    "scheme_id": f"SCHEME-{i}", "isin": f"INF000000{i:03d}",
                    "plan": "Direct", "option": "Growth", "amc": "Example AMC",
                    "category": "Large Cap", "benchmark": "Nifty 100 TRI",
                },
                "evidence_ref": "sha256:ops", "evidence_as_of_date": as_of,
                "scheme_status": "ACTIVE", "minimum_monthly_sip_inr": "500",
                "exit_load_evidence_ref": "sha256:exit",
                "lockin_evidence_ref": "sha256:lock",
                "subscription_status_evidence_ref": "sha256:subscription",
            } for i in range(1, 31)
        },
        "goal_policy": {
            "max_evidence_age_days": 45,
            "minimum_horizon_days_by_asset_class": {"equity": 3650},
        },
        "goals": [{
            "goal_id": "custom-goal",
            "mandate_approved": True,
            "source_ref": "sha256:goal",
            "evidence_as_of_date": as_of,
            "target_amount_inr": "1000000",
            "liabilities_inr": "0",
            "target_date": f"{date.today().year + 11}-{date.today().month:02d}-{date.today().day:02d}",
            "asset_class": "equity",
            "approved_risk_profile": "Custom",
        }],
        "liquidity": {
            "verified_cash_inr": 50000.0,
            "approved_reserve_target_inr": 20000.0,
            "near_term_obligations_inr": 0.0,
            "monthly_net_income_inr": 150000.0,
            "essential_monthly_expenses_inr": 50000.0,
            "monthly_debt_service_inr": 0.0,
            "evidence_refs": {
                "cash": "BANK-001",
                "reserve": "BANK-001",
                "obligations": "BANK-001",
                "income": "BANK-001",
                "expenses": "BANK-001",
                "debt_service": "BANK-001",
                "as_of_dates": {
                    key: as_of for key in (
                        "cash", "reserve", "obligations", "income", "expenses", "debt_service"
                    )
                },
            },
            "max_evidence_age_days": 45,
        },
        "stress_scenarios": [{
            "scenario_id": "income-shock", "income_reduction_pct": "10",
            "expense_increase_pct": "5",
        }],
        "concentration_policy": {
            "max_issuer_pct_of_portfolio": 25.0,
            "effective_date": as_of,
            "source_ref": "DOC-CONC-001",
        },
        "freshness": {
            "recommendation_as_of_date": as_of,
            "max_age_days": 90,
            "events": [],
        },
    }

    from mandate_test_utils import make_signed_mandate_schedule, install_mandate_trust_registry
    mandate_evidence, mandate_trust_registry = make_signed_mandate_schedule(
        as_of, context["investor_owner_ref"]
    )
    context["sip_mandate_evidence"] = mandate_evidence
    install_mandate_trust_registry(monkeypatch, mandate_trust_registry)

    def fake_load_holdings(*args, **kwargs):
        return [
            SimpleNamespace(
                scheme="Custom Fund Direct Growth",
                fund_id="FUND-1",
                scheme_id="SCHEME-1",
                plan_option_status="VERIFIED",
                option_type="GROWTH",
                is_direct=True,
                lookthrough_status="VERIFIED",
                metrics_status="VERIFIED",
                constituent_weights={"ISSUER A": 100.0},
                equity_pct=100.0,
                constituent_weights_coverage_pct=100.0,
                current_value_inr=100000.0,
            )
        ]

    monkeypatch.setattr(service, "load_holdings_from_cas_excel", fake_load_holdings)

    result = service.recommend_sip(
        cas_path=cas,
        metrics_path=None,
        aliases_path=None,
        monthly_budget_inr=10000,
        risk_profile="Custom",
        custom_saa_target=target,
        scheme_master={"status": "VERIFIED"},
        scheme_master_source_bytes=b"master bytes",
        portfolio_disclosures_by_scheme_id={"SCHEME-1": {"scheme_id": "SCHEME-1"}},
        portfolio_disclosure_source_bytes_by_scheme_id={"SCHEME-1": b"disclosure bytes"},
        disclosure_as_of_date=date.today(),
        candidate_universe=candidates,
        portfolio_context=context,
    )

    assert result["status"] == "HOLD"  # TRI release gate keeps status HOLD
    assert "total_portfolio_context" in result["portfolio_assessment"]
    ctx = result["portfolio_assessment"]["total_portfolio_context"]
    assert "portfolio_reconciliation" in ctx, f"Context failed with: {ctx}"
    reconciliation = ctx["portfolio_reconciliation"]
    assert reconciliation["status"] == "RECONCILED"
    assert reconciliation["is_approved_for_sip_routing"] is True


def test_custom_saa_resolves_exact_investable_sleeves_from_approved_target():
    target = AssetAllocationTarget(
        equity_pct=60.0, debt_pct=40.0, cash_pct=0.0,
        large_cap_pct=25.0, mid_cap_pct=15.0,
        small_cap_pct=10.0, flexi_cap_pct=10.0,
        risk_ceiling=4,
    )
    policy = {
        "custom_saa_policy": {
            "default_equity_distribution_pct": {
                "large_cap_pct": 40.0,
                "flexi_multi_cap_pct": 20.0,
                "mid_cap_pct": 25.0,
                "small_cap_pct": 15.0,
            }
        }
    }
    resolved = service._custom_saa_sleeve_targets(target, policy)
    assert resolved == {
        "large_cap": 25.0,
        "mid_cap": 15.0,
        "small_cap": 10.0,
        "flexi_multi_cap": 10.0,
        "debt_liquid": 40.0,
    }
    assert sum(resolved.values()) == pytest.approx(100.0)


def test_custom_saa_does_not_silently_discard_cash_target():
    target = AssetAllocationTarget(
        equity_pct=60.0, debt_pct=30.0, cash_pct=10.0,
        risk_ceiling=4,
    )
    policy = {
        "custom_saa_policy": {
            "default_equity_distribution_pct": {
                "large_cap_pct": 40.0,
                "flexi_multi_cap_pct": 20.0,
                "mid_cap_pct": 25.0,
                "small_cap_pct": 15.0,
            }
        }
    }
    with pytest.raises(service.PortfolioInputError, match="does not model a separate cash sleeve"):
        service._custom_saa_sleeve_targets(target, policy)


def test_custom_saa_policy_default_distribution_must_reconcile():
    target = AssetAllocationTarget(
        equity_pct=60.0, debt_pct=40.0, cash_pct=0.0,
        risk_ceiling=4,
    )
    policy = {
        "custom_saa_policy": {
            "default_equity_distribution_pct": {
                "large_cap_pct": 40.0,
                "flexi_multi_cap_pct": 20.0,
                "mid_cap_pct": 25.0,
                "small_cap_pct": 10.0,
            }
        }
    }
    with pytest.raises(service.PortfolioInputError, match="must reconcile to 100%"):
        service._custom_saa_sleeve_targets(target, policy)


def test_custom_saa_requires_matching_independent_risk_ceiling():
    target = AssetAllocationTarget(
        equity_pct=60.0, debt_pct=40.0, cash_pct=0.0,
        risk_ceiling=4,
    )
    assert service._resolve_custom_saa_risk_ceiling(target, {"risk_ceiling": 4}) == 4
    assert service._resolve_custom_saa_risk_ceiling(target, {}) == 4
    with pytest.raises(service.PortfolioInputError, match="conflicts"):
        service._resolve_custom_saa_risk_ceiling(target, {"risk_ceiling": 3})
    with pytest.raises(service.PortfolioInputError, match="integer risk ceiling"):
        service._resolve_custom_saa_risk_ceiling(
            target.model_copy(update={"risk_ceiling": None}),
            {"risk_ceiling": 4.0},
        )
