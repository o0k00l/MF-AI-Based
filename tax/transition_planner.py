"""
Tax-Aware Transition Planner.

Takes the execution manifest (SELL verdicts) and per-lot transaction history,
then stages SELLs across financial years to maximize the ₹1.25L LTCG exemption
per FY, per the fiduciary mandate (Substream 3d).

Outputs a phased transition plan: outputs/Transition_Plan.md
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from decimal import Decimal
import logging
logger = logging.getLogger(__name__)


@dataclass
class Lot:
    """A single purchase lot of a fund."""
    fund_id: str
    folio_name: str
    purchase_date: date
    units: float
    nav: float  # purchase NAV
    cost: float  # units * nav
    source: str  # "cas" or "manual"
    equity_pct: float | None = None  # Section 198 annual-average monthly-opening/closing percentage
    equity_pct_method: str | None = None
    equity_pct_fy_start: int | None = None
    equity_pct_source_url: str | None = None
    equity_pct_source_sha256: str | None = None
    equity_pct_source_reviewed: bool = False
    equity_pct_source_file: str | None = None
    equity_pct_evidence_root: str | None = None

    def holding_days(self, as_of: date) -> int:
        return (as_of - self.purchase_date).days
    
    def is_long_term(self, as_of: date, holding_months: int = 12) -> bool:
        """LTCG if holding period > 12 months (strict: > 12 months, not >=)."""
        # Per tax_rules principle: "MORE THAN 12 months from the date of acquisition.
        # Exactly 12 months is SHORT term. Test against the 12-month anniversary date,
        # not an integer month count."
        try:
            anniversary = date(self.purchase_date.year + 1, self.purchase_date.month, self.purchase_date.day)
        except ValueError:
            anniversary = date(self.purchase_date.year + 1, 2, 28)
        return as_of > anniversary

    def is_long_term_given(self, as_of_date, lt_holding_months: int = 12) -> bool:
        """Alias matching TaxLot.is_long_term_given() API.
        Returns True if holding period exceeds calendar anniversary date.
        Per tax rules: LTCG requires holding period > 12 months (strictly >, not >=)."""
        try:
            # Calculate the anniversary date (12 months from purchase)
            anniversary_year = self.purchase_date.year + lt_holding_months // 12
            anniversary_month = self.purchase_date.month + (lt_holding_months % 12)
            if anniversary_month > 12:
                anniversary_year += 1
                anniversary_month -= 12
            anniversary = date(anniversary_year, anniversary_month, self.purchase_date.day)
        except ValueError:
            # Handle Feb 29 on non-leap years
            anniversary = date(anniversary_year, 2, 28)
        return as_of_date > anniversary


@dataclass
class FundSellPlan:
    """Plan for selling one fund across FYs."""
    fund_id: str
    total_amount: float  # total SELL amount from manifest
    lots: list[Lot] = field(default_factory=list)
    fy_allocations: dict[int, list[tuple[Lot, float]]] = field(default_factory=lambda: defaultdict(list))
    
    def add_lot(self, lot: Lot):
        self.lots.append(lot)
    
    def total_units(self) -> float:
        return sum(l.units for l in self.lots)
    
    def total_cost(self) -> float:
        return sum(l.cost for l in self.lots)
def _parse_date(s: str | date) -> date:
    """Parse date from multiple formats."""
    if isinstance(s, date):
        return s
    s = str(s).strip()
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {s!r}")


def load_transactions(
    transactions_path: Path,
    equity_allocation_by_fund: dict[str, float] | None = None,
    evidence_root: Path | None = None,
) -> dict[str, list[Lot]]:
    """
    Load and parse transactions.json into per-fund lots, applying FIFO burn
    to account for historical redemptions. Optional equity allocation inputs
    must come from a separately verified scheme master/factsheet, keyed by the
    exact CAS scheme name; transaction rows may also carry equity_allocation_pct.

    Returns: fund_id -> list[Lot]  (only currently-held lots survive)
    """
    data = json.loads(transactions_path.read_text(encoding="utf-8"))
    # An evidence root is an explicit trust boundary. Do not infer it from
    # the transaction file's parent directory.
    evidence_root_path = (
        Path(evidence_root).expanduser().resolve(strict=True)
        if evidence_root is not None
        else None
    )

    # First pass: collect all transactions per fund (both purchases and redemptions)
    transactions_by_fund: dict[str, list[dict]] = defaultdict(list)

    for row_index, tx in enumerate(data.get("transactions", [])):
        if not isinstance(tx, dict):
            raise ValueError(f"Transaction row {row_index} is not an object")
        import math
        try:
            units = Decimal(str(tx.get("units", 0)))
            amount = float(tx.get("amount", 0))
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise ValueError(f"Malformed amount/units in transaction row {row_index}: {exc}") from exc
        if not units.is_finite() or not math.isfinite(amount):
            raise ValueError(f"Non-finite amount/units in transaction row {row_index}")
        scheme = str(tx.get("scheme", "") or "").strip()
        if not scheme:
            if units == 0 and amount == 0:
                continue
            raise ValueError(f"Non-zero transaction row {row_index} is missing scheme name")
        txn_type = str(tx.get("type", "") or "").strip().upper()
        allowed_types = {
            "PURCHASE", "SIP", "SWITCH_IN", "STP_IN", "DIVIDEND_REINVEST",
            "REDEMPTION", "SWITCH_OUT", "STP_OUT", "DIVIDEND",
        }
        if txn_type not in allowed_types:
            raise ValueError(f"Unsupported transaction type {txn_type!r} for scheme {scheme!r}")
        description = str(tx.get("description", tx.get("desc", "")) or "")
        if txn_type == "DIVIDEND" and any(
            marker in description.casefold() for marker in ("reinvest", "reinvestment", "drp")
        ):
            txn_type = "DIVIDEND_REINVEST"
        elif txn_type == "DIVIDEND":
            continue  # Cash payout does not create or remove units in the lot pool.
        if units == 0 and amount == 0:
            continue  # Skip zero-activity entries (address updates, nominee registrations, etc.)

        dt = _parse_date(tx.get("date", ""))
        allocation_record = tx.get("equity_allocation")
        if allocation_record is None:
            allocation_record = (equity_allocation_by_fund or {}).get(scheme)
        if isinstance(allocation_record, dict):
            equity_pct = allocation_record.get("equity_pct")
            equity_pct_method = allocation_record.get("method")
            equity_pct_fy_start = allocation_record.get("financial_year_start")
            equity_pct_source_url = allocation_record.get("source_url")
            equity_pct_source_sha256 = allocation_record.get("source_document_sha256")
            equity_pct_source_reviewed = allocation_record.get("independently_verified", False)
            equity_pct_source_file = allocation_record.get("source_file")
        else:
            equity_pct = tx.get("equity_allocation_pct", allocation_record)
            equity_pct_method = tx.get("equity_allocation_method")
            equity_pct_fy_start = tx.get("equity_allocation_fy_start")
            equity_pct_source_url = tx.get("equity_allocation_source_url")
            equity_pct_source_sha256 = tx.get("equity_allocation_source_sha256")
            equity_pct_source_reviewed = tx.get("equity_allocation_source_verified", False)
            equity_pct_source_file = tx.get("equity_allocation_source_file")
        transactions_by_fund[scheme].append({
            "date": dt,
            "units": Decimal(str(units)),
            "amount": float(amount),
            "nav": float(tx.get("nav", 0)) if tx.get("nav") else 0.0,
            "type": txn_type,
            "equity_pct": equity_pct,
            "equity_pct_method": equity_pct_method,
            "equity_pct_fy_start": equity_pct_fy_start,
            "equity_pct_source_url": equity_pct_source_url,
            "equity_pct_source_sha256": equity_pct_source_sha256,
            "equity_pct_source_reviewed": equity_pct_source_reviewed,
            "equity_pct_source_file": equity_pct_source_file,
            "description": tx.get("description", ""),
        })

    # GAP-200 FIX: canonicalise the sign convention and net out CAMS reversal
    # pairs BEFORE the FIFO pass. Live CAS data records a redemption as a
    # negative row, then its reversal as a POSITIVE row (same |amount|, same
    # |units|, description contains "reversal"), then the re-entry redemption
    # as a negative row again. Splitting purely by arithmetic sign turns the
    # reversal row into a phantom purchase lot at the redemption-time NAV,
    # contaminating cost basis, holding periods and taxable gains.
    #
    # Normalisation rule: a row whose description mentions a redemption /
    # switch-out / payout must carry NEGATIVE units and amount. Rows that
    # violate this are flipped (and flagged) so downstream consumers see one
    # consistent convention.
    for fund_id, txs in transactions_by_fund.items():
        for t in txs:
            desc = (t.get("description") or "").lower()
            is_redemption = any(
                kw in desc for kw in ("redemption", "switch out", "switch-out",
                                      "payout", "dividend payout")
            )
            if is_redemption and t["units"] > 0 and t["amount"] > 0:
                t["units"] = -t["units"]
                t["amount"] = -t["amount"]
                t["_reversal_normalised"] = True

    purchase_types = {"PURCHASE", "SIP", "SWITCH_IN", "STP_IN", "DIVIDEND_REINVEST"}
    redemption_types = {"REDEMPTION", "SWITCH_OUT", "STP_OUT"}
    for fund_id, txs in transactions_by_fund.items():
        for row in txs:
            if row["type"] in purchase_types:
                if row["units"] <= 0 or row["amount"] <= 0:
                    raise ValueError(f"Purchase row for {fund_id} has non-positive amount/units")
                if not math.isfinite(row["nav"]) or row["nav"] < 0:
                    raise ValueError(f"Purchase row for {fund_id} has invalid NAV")
                if row["nav"] == 0:
                    row["nav"] = row["amount"] / float(row["units"])
            elif row["type"] in redemption_types:
                if row["units"] >= 0 or row["amount"] >= 0:
                    raise ValueError(f"Redemption/switch-out row for {fund_id} has invalid sign convention")

    # Reversal netting: drop BOTH rows of a matched reversal pair. A pair is
    # identified by equal |amount| (within 1 paisa) and |units| (within 0.001)
    # on the same scheme, with one description containing "reversal".
    netted: dict[str, list[dict]] = {}
    for fund_id, txs in transactions_by_fund.items():
        kept: list[dict] = []
        consumed: set[int] = set()
        for i, a in enumerate(txs):
            if i in consumed:
                continue
            matched = False
            for j, b in enumerate(txs):
                if j <= i or j in consumed:
                    continue
                same_scheme = (a.get("scheme") or "") == (b.get("scheme") or "")
                same_date = a["date"] == b["date"]
                desc_b = (b.get("description") or "").lower()
                if not (same_scheme and same_date and "reversal" in desc_b):
                    continue
                if (abs(abs(a["amount"]) - abs(b["amount"])) <= 1.0
                        and abs(abs(a["units"]) - abs(b["units"])) <= 0.001):
                    consumed.add(i)
                    consumed.add(j)
                    matched = True
                    break
            if not matched:
                kept.append(a)
        netted[fund_id] = kept
    transactions_by_fund = netted

    # Second pass: apply FIFO burn per fund
    lots_by_fund: dict[str, list[Lot]] = defaultdict(list)

    for fund_id, txs in transactions_by_fund.items():
        # Sort chronologically (oldest first)
        txs.sort(key=lambda x: x["date"])

        # Separate purchases and redemptions
        # GAP-289 FIX: Require units field for all transactions. No silent fallback.
        # Production CAS data always includes units. Test data must provide units and nav.
        purchases = [t for t in txs if t["type"] in purchase_types]
        redemptions = [t for t in txs if t["type"] in redemption_types]

        if not purchases:
            continue  # No purchases to survive

        # Apply FIFO: match each redemption against earliest purchases
        remaining_purchases = []
        for p in purchases:
            # GAP-289 FIX: Units field is mandatory. Raise clear error if missing.
            if p["units"] <= 0:
                raise ValueError(
                    f"Transaction for {fund_id} on {p['date']} has invalid units={p['units']}. "
                    f"All purchase transactions must have units > 0. "
                    f"Ensure your CAS data includes units field, or provide nav to compute units."
                )
            units = p["units"]
            remaining_purchases.append({
                "date": p["date"],
                "units": units,
                "nav": p["nav"],
                "cost": p["amount"],
                "equity_pct": p.get("equity_pct"),
                "equity_pct_method": p.get("equity_pct_method"),
                "equity_pct_fy_start": p.get("equity_pct_fy_start"),
                "equity_pct_source_url": p.get("equity_pct_source_url"),
                "equity_pct_source_sha256": p.get("equity_pct_source_sha256"),
                "equity_pct_source_reviewed": p.get("equity_pct_source_reviewed", False),
                "equity_pct_source_file": p.get("equity_pct_source_file"),
            })

        for red in redemptions:
            redeem_units = abs(red["units"])
            if redeem_units <= 0:
                continue

            # Burn from oldest purchases first
            for p in remaining_purchases:
                if redeem_units <= 0:
                    break
                if p["units"] <= 0:
                    continue

                burn = min(redeem_units, p["units"])
                p["units"] -= burn
                # Pro-rata cost reduction
                if p["units"] + burn > 0:
                    p["cost"] = float(p["cost"]) * float(p["units"] / (p["units"] + burn))
                redeem_units -= burn

        # Build Lot objects from surviving units
        for p in remaining_purchases:
            if p["units"] > 0:
                lots_by_fund[fund_id].append(Lot(
                    fund_id=fund_id,
                    folio_name=fund_id,
                    purchase_date=p["date"],
                    units=float(p["units"]),
                    nav=p["nav"],
                    cost=p["cost"],
                    source="cas",
                    equity_pct=p.get("equity_pct"),
                    equity_pct_method=p.get("equity_pct_method"),
                    equity_pct_fy_start=p.get("equity_pct_fy_start"),
                    equity_pct_source_url=p.get("equity_pct_source_url"),
                    equity_pct_source_sha256=p.get("equity_pct_source_sha256"),
                    equity_pct_source_reviewed=p.get("equity_pct_source_reviewed", False),
                    equity_pct_source_file=p.get("equity_pct_source_file"),
                    equity_pct_evidence_root=str(evidence_root_path) if evidence_root_path is not None else None,
                ))

    return lots_by_fund



def load_manifest(manifest_path: Path) -> list[dict]:
    """Load execution_manifest.json and return SELL lines."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    sells = [line for line in data.get("lines", []) if line.get("action") == "SELL"]
    return sells


def load_tax_rules(tax_rules_path: Path) -> dict:
    """Load equity tax parameters from tax_rules_india.json.

    Converts the new nested schema to the flat format expected by
    plan_fy_tranches and generate_transition_plan_md.

    Enforces 180-day freshness rule per engine_requirements.
    """
    data = json.loads(tax_rules_path.read_text(encoding="utf-8"))

    # --- Freshness check (180-day rule) ---
    as_of_str = data.get("as_of")
    if as_of_str:
        try:
            as_of_date = datetime.strptime(as_of_str, "%Y-%m-%d").date()
            days_old = (date.today() - as_of_date).days
            if days_old > 180:
                raise ValueError(
                    f"Tax rules stale: as_of={as_of_str} ({days_old} days old). "
                    f"Engine requirement: refuse if > 180 days old. Update tax_rules.json."
                )
        except ValueError:
            # Re-raise if it's our freshness error, otherwise wrap parse error
            raise
        except Exception as e:
            raise ValueError(f"Failed to parse tax_rules as_of date: {as_of_str}") from e
    else:
        raise ValueError("Tax rules missing required 'as_of' date field. Cannot enforce freshness.")

    eq = data.get("classes", {}).get("equity_oriented", {})
    lt = eq.get("long_term", {})
    st = eq.get("short_term", {})

    # Extract exit load from exit_load_schedules
    exit_load_schedules = data.get("exit_load_schedules", {})
    equity_exit_load = exit_load_schedules.get("equity_oriented", {})
    exit_load_pct = equity_exit_load.get("rate_pct", 1.0)

    return {
        "ltcg_rate": lt.get("rate_pct", 12.5) / 100.0,
        "stcg_rate": st.get("rate_pct", 20.0) / 100.0,
        "ltcg_exemption": lt.get("exemption_limit_inr", 125000),
        "lt_holding_months": lt.get("holding_period_months_gt", 12),
        "exit_load_pct": exit_load_pct,
        "exit_load_schedules": data.get("exit_load_schedules", {}),
        "classes": data.get("classes", {}),
        "as_of": data.get("as_of"),
    }
def _load_fund_aliases() -> dict[str, list[str]]:
    alias_file = Path(__file__).resolve().parent.parent / ".agents" / "knowledge" / "global_fund_aliases.json"
    if alias_file.exists():
        try:
            data = json.loads(alias_file.read_text(encoding="utf-8"))
            return data.get("aliases", {})
        except Exception as e:
            logger.warning(r"Alias file load failed: {e}")
            return {}
    return {}


def _find_matching_folios_for_fund(
    fund_id: str,
    folio_to_fund_id: dict[str, str],
    available_lots_keys: set[str],
    aliases: dict[str, list[str]]
) -> list[str]:
    """Resolve folios only through exact IDs or exact normalized aliases."""
    import re

    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())

    direct = [folio for folio, mapped_id in folio_to_fund_id.items() if mapped_id == fund_id and folio in available_lots_keys]
    if direct:
        return sorted(set(direct))
    if fund_id in available_lots_keys:
        return [fund_id]

    alias_keys = {normalize(alias) for alias in aliases.get(fund_id, []) if normalize(alias)}
    matches = [folio for folio in available_lots_keys if normalize(folio) in alias_keys]
    if matches:
        return sorted(set(matches))
    return []

def match_lots_to_manifest(
    manifest_sells: list[dict],
    lots_by_folio: dict[str, list[Lot]],
    folio_to_fund_id: dict[str, str]
) -> dict[str, FundSellPlan]:
    """
    Match manifest SELL lines (by fund_id) to transaction lots (by folio name).
    
    manifest_sells have fund_id (e.g., "HDFC BAF")
    lots_by_folio keyed by folio name from transactions (e.g., "HDFC Balanced Advantage Fund...")
    folio_to_fund_id maps folio name -> fund_id
    
    Supports alias lookup, token-sort similarity, and rebranded scheme resolution
    (GAP-206) so rebranded/renamed holdings are never orphaned.
    """
    import math

    plans: dict[str, FundSellPlan] = {}
    aliases = _load_fund_aliases()
    available_lots_keys = set(lots_by_folio.keys())

    for sell in manifest_sells:
        fund_id = str(sell.get("fund_id", "") or "").strip()
        if not fund_id:
            raise ValueError("Manifest SELL row is missing fund_id")
        try:
            amount = float(sell.get("amount"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Manifest SELL amount is invalid for {fund_id}") from exc
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError(f"Manifest SELL amount must be finite and positive for {fund_id}")

        matching_folios = _find_matching_folios_for_fund(
            fund_id, folio_to_fund_id, available_lots_keys, aliases
        )
        if not matching_folios:
            raise ValueError(
                f"No exact folio/alias match for manifest SELL fund {fund_id!r}; refusing fuzzy matching or silent omission."
            )

        plan = FundSellPlan(fund_id=fund_id, total_amount=amount)
        seen_lots = set()
        for folio in matching_folios:
            for lot in lots_by_folio[folio]:
                identity = (folio, lot.purchase_date, lot.units, lot.cost)
                if identity in seen_lots:
                    continue
                seen_lots.add(identity)
                lot.fund_id = fund_id
                plan.add_lot(lot)

        if not plan.lots:
            raise ValueError(f"Exact folio match for {fund_id!r} contains no verified tax lots")
        plans[fund_id] = plan

    return plans


def estimate_current_value(plan: FundSellPlan, current_nav: float) -> float:
    """Estimate current value of all lots in the plan."""
    return plan.total_units() * current_nav

def classify_fund_for_tax(source_holding, tax_rules, sale_date=None):
    """
    Classify only from a provenance-backed Section 198 annual-average monthly
    opening/closing calculation for the financial year of the intended sale.
    Point-in-time scheme allocation percentages are not accepted. The
    reviewer-attested source fields are not cryptographic source authentication;
    this result remains provisional and requires independent adviser sign-off.
    """
    import math
    import re
    import hashlib

    equity_pct = getattr(source_holding, "equity_pct", None)
    if equity_pct is None or isinstance(equity_pct, bool):
        raise ValueError("equity_allocation_pct is required for tax classification")
    try:
        equity_pct = float(equity_pct)
    except (TypeError, ValueError) as exc:
        raise ValueError("equity_allocation_pct must be numeric") from exc
    if not math.isfinite(equity_pct) or not 0.0 <= equity_pct <= 100.0:
        raise ValueError("equity_allocation_pct must be finite and between 0 and 100")

    method = getattr(source_holding, "equity_pct_method", None)
    if method != "annual_average_monthly_opening_closing":
        raise ValueError("equity allocation must use the Section 198 annual-average monthly opening/closing method")
    if getattr(source_holding, "equity_pct_source_reviewed", False) is not True:
        raise ValueError("Section 198 equity-allocation source must be explicitly reviewed by an adviser")
    source_url = getattr(source_holding, "equity_pct_source_url", None)
    if not isinstance(source_url, str) or not source_url.startswith("https://"):
        raise ValueError("Section 198 equity-allocation source URL must be HTTPS")
    source_hash = getattr(source_holding, "equity_pct_source_sha256", None)
    if not isinstance(source_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", source_hash):
        raise ValueError("Section 198 equity-allocation source document SHA-256 is required")

    # Recompute the digest from the actual local source bytes. A SHA-shaped
    # string or URL alone is not evidence. The resolved path must remain
    # contained inside the explicitly supplied evidence root (including
    # protection against ../ traversal and symlink escape).
    source_file = getattr(source_holding, "equity_pct_source_file", None)
    evidence_root = getattr(source_holding, "equity_pct_evidence_root", None)
    if not isinstance(source_file, str) or not source_file.strip():
        raise ValueError("Section 198 source document file is required for byte-level digest verification")
    if not isinstance(evidence_root, str) or not evidence_root.strip():
        raise ValueError("Section 198 source evidence root is required for byte-level digest verification")
    try:
        root_path = Path(evidence_root).expanduser().resolve(strict=True)
        relative_source = Path(source_file)
        if relative_source.is_absolute():
            raise ValueError("source document path must be relative to the evidence root")
        source_path = (root_path / relative_source).resolve(strict=True)
        source_path.relative_to(root_path)
        if not source_path.is_file():
            raise ValueError("source document path is not a regular file")
        actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"Section 198 source document cannot be safely verified: {exc}") from exc
    if actual_hash.lower() != source_hash.lower():
        raise ValueError("Section 198 source document SHA-256 does not match local source bytes")

    fy_start = getattr(source_holding, "equity_pct_fy_start", None)
    if isinstance(fy_start, bool) or not isinstance(fy_start, int):
        raise ValueError("Section 198 equity-allocation financial_year_start is required")

    if sale_date is not None:
        expected_fy_start = sale_date.year if sale_date.month >= 4 else sale_date.year - 1
        if fy_start != expected_fy_start:
            raise ValueError(
                f"Section 198 equity-allocation evidence is for FY starting {fy_start}, "
                f"but sale date {sale_date} requires FY starting {expected_fy_start}"
            )

    equity_threshold = float(tax_rules.get("classification_test", {}).get("equity_oriented_threshold_pct", 65.0))
    if not math.isfinite(equity_threshold) or equity_threshold != 65.0:
        raise ValueError("Section 198 statutory equity-oriented threshold must be 65%")
    return "equity_oriented" if equity_pct >= equity_threshold else "non_equity_oriented"


def get_tax_rates_for_sale(fund_tax_class, sale_date, tax_rules):
    """
    Get applicable tax rates for a sale based on fund classification and sale date.
    Returns (stcg_rate, ltcg_rate, ltcg_exemption, cess_rate, exit_load_schedule, holding_period_months).
    """
    cutoff_date = date(2026, 4, 1)
    is_new_regime = sale_date >= cutoff_date
    classes = tax_rules.get("classes", {})
    
    if fund_tax_class == "equity_oriented":
        eq_class = classes.get("equity_oriented", {})
        lt = eq_class.get("long_term", {})
        st = eq_class.get("short_term", {})
        ltcg_rate = lt.get("rate_pct", 12.5) / 100.0
        stcg_rate = st.get("rate_pct", 20.0) / 100.0
        ltcg_exemption = lt.get("exemption_limit_inr", 125000)
        holding_months = lt.get("holding_period_months_gt", 12)
        exit_load_schedule = tax_rules.get("exit_load_schedules", {}).get("equity_oriented", {})
        cess_rate = tax_rules.get("cess", {}).get("health_education_cess_pct", 4.0) / 100.0
        return {
            "stcg_rate": stcg_rate,
            "ltcg_rate": ltcg_rate,
            "ltcg_exemption": ltcg_exemption,
            "cess_rate": cess_rate,
            "exit_load_schedule": exit_load_schedule,
            "holding_months": holding_months,
            "regime": "new" if is_new_regime else "old",
        }
    
    raise ValueError(
        f"Tax schedule for {fund_tax_class!r} is not implemented. "
        "Non-equity/debt tax treatment requires acquisition-date, instrument classification and investor-slab inputs."
    )


def plan_fy_tranches(
    plans: dict[str, FundSellPlan],
    tax_rules: dict,
    as_of: date,
    current_navs: dict[str, float],
    prior_ltcg_this_fy: float | None = None,
) -> dict[int, list[dict]]:
    """
    Plan SELL tranches across financial years to maximize LTCG exemption.
    
    Strategy:
    1. For each fund, classify lots as LT/ST as of `as_of` date
    2. Sort LT lots by gain (highest first) - shelter highest-rate gains first
    3. Fill each FY's ₹1.25L exemption with LT gains
    4. STCG lots don't get exemption - schedule them after LT gains are exhausted
    5. Continue across FYs until all SELL amounts are allocated
    
    Returns: fy_start_year -> list of {fund_id, lot, amount, gain_type, gain_amount, tax}

    Args:
        prior_ltcg_this_fy: Verified net LTCG already realized in the current FY
            from other sources. This value is mandatory; pass 0.0 only when
            independently verified that no prior eligible LTCG has been realized.
    """
    import math
    if prior_ltcg_this_fy is None:
        raise ValueError(
            "Verified prior_ltcg_this_fy is required. Do not assume the full annual exemption remains available."
        )
    try:
        raw_exemption = float(tax_rules["ltcg_exemption"])
        prior_ltcg = float(prior_ltcg_this_fy)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Tax exemption and prior realized LTCG must be numeric") from exc
    if not math.isfinite(raw_exemption) or raw_exemption < 0:
        raise ValueError("Configured LTCG exemption must be finite and non-negative")
    if isinstance(prior_ltcg_this_fy, bool) or not math.isfinite(prior_ltcg) or prior_ltcg < 0:
        raise ValueError("prior_ltcg_this_fy must be finite and non-negative")
    # Validate the configured allowance once; the per-fund tax schedule supplies
    # the operative class-specific allowance below.
    try:
        exit_load_pct = float(tax_rules.get("exit_load_pct", 1.0))
        holding_months = int(tax_rules.get("lt_holding_months", 12))
    except (TypeError, ValueError) as exc:
        raise ValueError("Exit-load rate and long-term holding period must be numeric") from exc
    if not math.isfinite(exit_load_pct) or not 0.0 <= exit_load_pct <= 100.0:
        raise ValueError("Exit-load percentage must be finite and between 0 and 100")
    if holding_months <= 0:
        raise ValueError("Long-term holding period must be a positive number of months")
    # Collect lots up to plan.total_amount per fund using strict FIFO
    all_lots = []
    
    for fund_id, plan in plans.items():
        # Validate the requested amount before looking up NAV or iterating lots.
        try:
            target_sell_amount = float(plan.total_amount) if plan.total_amount is not None else float("inf")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid sale amount for {fund_id}: {plan.total_amount!r}") from exc
        if (
            math.isnan(target_sell_amount)
            or target_sell_amount < 0
            or (plan.total_amount is not None and not math.isfinite(target_sell_amount))
        ):
            raise ValueError(f"Invalid sale amount for {fund_id}: {plan.total_amount!r}")
        if target_sell_amount == 0 or (target_sell_amount == float("inf") and not plan.lots):
            continue
        if not plan.lots:
            raise ValueError(f"No verified tax lots available for positive sale request: {fund_id}")

        raw_nav = current_navs.get(fund_id)
        try:
            current_nav = float(raw_nav)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Missing or invalid current NAV for {fund_id}: {raw_nav!r}") from exc
        if not math.isfinite(current_nav) or current_nav <= 0:
            raise ValueError(f"Current NAV for {fund_id} must be finite and positive")
        
        remaining_target = target_sell_amount
        
        # Sort lots strictly by FIFO (purchase_date)
        sorted_lots = sorted(plan.lots, key=lambda l: (l.purchase_date, l.folio_name))
        for lot in sorted_lots:
            if remaining_target <= 0.01:
                break
            if (
                isinstance(lot.units, bool) or isinstance(lot.cost, bool)
                or not math.isfinite(float(lot.units)) or not math.isfinite(float(lot.cost))
                or lot.units <= 0 or lot.cost < 0
            ):
                raise ValueError(f"Invalid lot units/cost for {fund_id}: units={lot.units}, cost={lot.cost}")
            lot_val = lot.units * current_nav
            units_to_sell = lot.units
            if lot_val > remaining_target:
                units_to_sell = remaining_target / current_nav
                lot_val = remaining_target
            remaining_target -= lot_val
            
            is_lt = lot.is_long_term_given(as_of, holding_months)
            cost_basis = (units_to_sell / lot.units) * lot.cost if lot.units > 0 else 0.0
            lot_gain = lot_val - cost_basis
            if not math.isfinite(lot_gain) or not math.isfinite(cost_basis):
                raise ValueError(f"Non-finite gain/cost basis for {fund_id}")
            fund_tax_class = classify_fund_for_tax(lot, tax_rules, as_of)
            if fund_tax_class != "equity_oriented":
                raise ValueError(
                    f"Tax planning for {fund_tax_class!r} holdings is not supported by this equity-only exemption planner."
                )
            
            all_lots.append({
                "fund_id": fund_id,
                "lot": lot,
                "type": "LT" if is_lt else "ST",
                "gain": lot_gain,
                "cost": cost_basis,
                "units": units_to_sell,
                "current_nav": current_nav,
                "fund_tax_class": fund_tax_class,
            })
        if target_sell_amount != float("inf") and remaining_target > 0.01:
            raise ValueError(
                f"Insufficient verified lot value for {fund_id}: requested {target_sell_amount:.2f}, "
                f"unallocated {remaining_target:.2f}"
            )
    # Separate loss lots vs gain lots
    loss_lots = [l for l in all_lots if l["gain"] <= 0]
    gain_lots = [l for l in all_lots if l["type"] == "LT" and l["gain"] > 0]
    st_lots = [l for l in all_lots if l["type"] == "ST" and l["gain"] > 0]

    # Allocate across FYs
    fy_plans: dict[int, list[dict]] = defaultdict(list)
    current_fy_start = as_of.year if as_of.month >= 4 else as_of.year - 1
    
    def calculate_exit_load(lot, units_sold, fy_start, current_nav, exit_load_pct, fund_id="", tax_rules=None):
        """Calculate category-aware exit load based on holding period and fund category.
        
        Uses exit_load_schedules from tax_rules for category-specific rates and thresholds.
        Falls back to heuristic classification if tax_rules not provided.
        """
        # For the current FY use the actual planning date; future FY tranches
        # use the first day of that FY as a conservative scheduled sale date.
        sale_date = as_of if fy_start == current_fy_start else date(fy_start, 4, 1)
        holding_days = (sale_date - lot.purchase_date).days
        
        # Use tax_rules exit_load_schedules if available
        if tax_rules and "exit_load_schedules" in tax_rules:
            schedules = tax_rules["exit_load_schedules"]
            f_lower = str(fund_id).lower()
            
            # Check each schedule for match
            for category, schedule in schedules.items():
                threshold_days = schedule.get("threshold_days", 0)
                rate_pct = schedule.get("rate_pct", 0.0)
                
                # Match categories by keyword
                if category == "equity_oriented":
                    # Default equity: 365 days, 1% exit load
                    if holding_days < threshold_days:
                        exit_load_rate = rate_pct
                    else:
                        exit_load_rate = 0.0
                    break
                elif category in ("debt_short_term", "debt", "money market", "banking & psu"):
                    if any(k in f_lower for k in ("short term", "debt", "money market", "banking & psu")):
                        if holding_days < threshold_days:
                            exit_load_rate = rate_pct
                        else:
                            exit_load_rate = 0.0
                        break
                elif category == "debt_liquid":
                    if any(k in f_lower for k in ("liquid", "overnight")):
                        if holding_days < threshold_days:
                            exit_load_rate = rate_pct
                        else:
                            exit_load_rate = 0.0
                        break
                elif category == "arbitrage":
                    if "arbitrage" in f_lower:
                        if holding_days < threshold_days:
                            exit_load_rate = rate_pct
                        else:
                            exit_load_rate = 0.0
                        break
            else:
                # No matching schedule found, use default equity
                exit_load_rate = exit_load_pct if holding_days < 365 else 0.0
        else:
            # Fallback to heuristic classification
            f_lower = str(fund_id).lower()
            if any(k in f_lower for k in ("liquid", "overnight")):
                exit_load_rate = 0.0070 if holding_days < 7 else 0.0
            elif any(k in f_lower for k in ("short term", "debt", "money market", "banking & psu", "arbitrage")):
                exit_load_rate = 0.25 if holding_days < 30 else 0.0
            else:
                exit_load_rate = exit_load_pct if holding_days < 365 else 0.0
        
        sale_value = units_sold * current_nav
        exit_load_amount = sale_value * exit_load_rate / 100.0
        net_amount = sale_value - exit_load_amount
        return exit_load_amount, net_amount, holding_days

    # 1. Harvest loss lots in Year 1 first for Section 70 offsetting
    for lot_info in loss_lots:
        exit_load_amount, net_amount, holding_days = calculate_exit_load(
            lot_info["lot"], lot_info["units"], current_fy_start, lot_info["current_nav"], exit_load_pct, lot_info.get("fund_id", ""), tax_rules
        )
        fy_plans[current_fy_start].append({
            "fund_id": lot_info["fund_id"],
            "lot": lot_info["lot"],
            "amount_sold": lot_info["units"],
            "units_sold": lot_info["units"],
            "gain_type": lot_info["type"],
            "gain_amount": lot_info["gain"],
            "sheltered": 0.0,
            "taxable": lot_info["gain"],
            "tax_estimate": 0.0,
            "fy_start": current_fy_start,
            "exit_load": exit_load_amount,
            "net_amount": net_amount,
        })

    # 2. Fiduciary Invariant 3: Universal Tax Exemption Shield (₹1.25L Annual Siphon)
    # Stagger mature gain lots up to exemption (₹1.25L) per financial year.
    # Defer immature lots (<365 days) to Day 366 (Phase 2), eliminating 1% exit load
    # and converting 20% STCG into 0% tax LTCG under Section 112A.
    from datetime import timedelta

    # Process all gain lots (both mature and deferred immature lots)
    # Sort mature lots first, followed by maturing lots in order of maturity date
    scheduled_gain_lots = []
    for l in gain_lots:
        scheduled_gain_lots.append({
            **l,
            "available_date": as_of,
            "deferred": False
        })

    # Immature lots with gains are deferred to Day 366
    for l in st_lots:
        maturation_date = l["lot"].purchase_date + timedelta(days=366)
        scheduled_gain_lots.append({
            **l,
            "available_date": maturation_date,
            "deferred": True,
            "type": "LT"  # Converted to LTCG at Day 366
        })

    # Sort lots by (target_fy_start, deferred_first, available_date, descending gain)
    # This ensures deferred lots get priority within their target FY
    def _sort_key(lot_info):
        avail_date = lot_info["available_date"]
        target_fy = avail_date.year if avail_date.month >= 4 else avail_date.year - 1
        deferred_first = 0 if lot_info.get("deferred", False) else 1
        return (target_fy, deferred_first, lot_info["available_date"], -lot_info["gain"])
    
    scheduled_gain_lots.sort(key=_sort_key)

    # Reserve exemption capacity for deferred lots in their target FY
    # This prevents mature lots from consuming exemption needed by deferred lots
    deferred_reserved = defaultdict(float)
    for lot_info in scheduled_gain_lots:
        if lot_info.get("deferred", False):
            avail_date = lot_info["available_date"]
            target_fy = avail_date.year if avail_date.month >= 4 else avail_date.year - 1
            deferred_reserved[target_fy] += lot_info["gain"]

    # Track exemption capacity used per FY (for mature lots)
    fy_sheltered_ltcg = defaultdict(float)
    # Track reserved capacity used by deferred lots
    fy_reserved_used = defaultdict(float)

    for lot_info in scheduled_gain_lots:
        gain = lot_info["gain"]
        lot_units = lot_info["units"]
        current_nav = lot_info["current_nav"]
        lot_gain_per_unit = gain / lot_units if lot_units > 0 else 0.0
        avail_date = lot_info["available_date"]
        target_fy_start = avail_date.year if avail_date.month >= 4 else avail_date.year - 1
        fy_ptr = max(current_fy_start, target_fy_start)
        
        # Get tax rates for this specific fund and sale date
        sale_date = date(fy_ptr, 4, 1)  # Approximate sale date as start of FY
        fund_tax_class = classify_fund_for_tax(lot_info["lot"], tax_rules, sale_date)
        if fund_tax_class != "equity_oriented":
            raise ValueError(
                f"Tax planning for {fund_tax_class!r} holdings is not supported by this equity-only exemption planner. "
                "Use a tax-class-specific computation with acquisition-date and investor-slab inputs."
            )
        tax_rates = get_tax_rates_for_sale(fund_tax_class, sale_date, tax_rules)
        try:
            ltcg_rate = float(tax_rates["ltcg_rate"])
            stcg_rate = float(tax_rates["stcg_rate"])
            exemption = float(tax_rates["ltcg_exemption"])
            cess_rate = float(tax_rates["cess_rate"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Incomplete tax rate schedule for {fund_tax_class}: {exc}") from exc
        if (
            not all(math.isfinite(v) for v in (ltcg_rate, stcg_rate, exemption, cess_rate))
            or not 0.0 <= ltcg_rate <= 1.0
            or not 0.0 <= stcg_rate <= 1.0
            or exemption < 0
            or not 0.0 <= cess_rate <= 1.0
        ):
            raise ValueError(f"Invalid tax rate schedule for {fund_tax_class}")
        if fy_ptr == current_fy_start:
            exemption = max(0.0, exemption - prior_ltcg)
        
        while lot_units > 0.0001:
            is_deferred = lot_info.get("deferred", False)
            avail_date = lot_info["available_date"]
            target_fy = avail_date.year if avail_date.month >= 4 else avail_date.year - 1
            
            if is_deferred:
                # Deferred lots use their reserved capacity
                reserved = deferred_reserved.get(target_fy, 0)
                used_reserved = fy_reserved_used.get(fy_ptr, 0)
                rem_in_fy = max(0.0, reserved - used_reserved)
            else:
                # Mature lots use non-reserved capacity
                reserved = deferred_reserved.get(fy_ptr, 0)
                available = exemption - reserved
                used = fy_sheltered_ltcg[fy_ptr]
                rem_in_fy = max(0.0, available - used)
            
            if rem_in_fy <= 1.0:
                fy_ptr += 1
                continue

            units_to_sell = lot_units
            if lot_gain_per_unit > 0:
                units_to_sell = min(lot_units, rem_in_fy / lot_gain_per_unit)
            
            if (lot_units - units_to_sell) < 0.001:
                units_to_sell = lot_units
            
            sold_gain = units_to_sell * lot_gain_per_unit
            
            # At fy_ptr (or Day 366), holding period >= 366 days -> exit load = 0.0%
            exit_load_amount = 0.0
            sale_value = units_to_sell * current_nav
            net_amount = sale_value
            
            sheltered = min(sold_gain, rem_in_fy)
            taxable = max(0.0, sold_gain - sheltered)
            tax_est = taxable * ltcg_rate * (1 + cess_rate)
            
            fy_plans[fy_ptr].append({
                "fund_id": lot_info["fund_id"],
                "lot": lot_info["lot"],
                "amount_sold": units_to_sell,
                "units_sold": units_to_sell,
                "gain_type": "LT",
                "gain_amount": sold_gain,
                "sheltered": sheltered,
                "taxable": taxable,
                "tax_estimate": tax_est,
                "fy_start": fy_ptr,
                "exit_load": exit_load_amount,
                "net_amount": net_amount,
                "held_to_day_366": lot_info["deferred"]
            })
            
            if is_deferred:
                fy_reserved_used[fy_ptr] += sheltered
            else:
                fy_sheltered_ltcg[fy_ptr] += sheltered
            lot_units -= units_to_sell

    first_fy = as_of.year if as_of.month >= 4 else as_of.year - 1
    
    # GAP-164 & GAP-215: Apply Section 70 Intra-Head Netting to first_fy tranches
    if first_fy in fy_plans:
        f_items = fy_plans[first_fy]
        stcl = sum(abs(it["gain_amount"]) for it in f_items if it["gain_type"] == "ST" and it["gain_amount"] < 0)
        stcg = sum(it["gain_amount"] for it in f_items if it["gain_type"] == "ST" and it["gain_amount"] > 0)
        
        # Stage 1: STCL absorbs STCG (Sec 70(1))
        stcl_used_stcg = min(stcl, stcg)
        net_stcg = stcg - stcl_used_stcg
        
        if stcg > 0:
            scale_ratio = net_stcg / stcg
            for it in f_items:
                if it["gain_type"] == "ST" and it["gain_amount"] > 0:
                    it["taxable"] = it["gain_amount"] * scale_ratio
                    it["sheltered"] = it["gain_amount"] - it["taxable"]
                    it["tax_estimate"] = it["taxable"] * stcg_rate
    
    return fy_plans


def generate_transition_plan_md(
    fy_plans: dict[int, list[dict]],
    tax_rules: dict,
    total_sell_amount: float,
    client_name: str,
    as_of: date,
) -> str:
    """Generate the Transition Plan Markdown."""
    lines = []
    lines.append(f"# Tax-Aware Transition Plan")
    lines.append(f"**Client:** {client_name}  |  **Planning Date:** {as_of.strftime('%d %B %Y')}")
    lines.append(f"**Total SELL Amount:** ₹{total_sell_amount:,.0f}")
    lines.append("")
    lines.append("> This plan stages mandatory SELL verdicts across financial years to maximize the")
    lines.append(f"> ₹{tax_rules['ltcg_exemption']:,} LTCG exemption per FY, per the fiduciary mandate.")
    lines.append("> Verify all figures with your tax advisor before acting.")
    lines.append("")
    lines.append("---")
    
    total_tax = 0.0
    total_sheltered = 0.0
    total_exit_load = 0.0
    total_net_amount = 0.0
    
    for fy_start in sorted(fy_plans.keys()):
        fy_end = fy_start + 1
        fy_label = f"FY {fy_start}-{str(fy_end)[2:]}"
        items = fy_plans[fy_start]
        
        lines.append(f"## {fy_label}")
        lines.append("")
        
        fy_tax = 0.0
        fy_sheltered = 0.0
        fy_gains = 0.0
        fy_exit_load = 0.0
        fy_net_amount = 0.0
        
        lines.append("| Fund | Holding Period | Gain Type | Est. Gain | Sheltered | Taxable | Est. Tax | Exit Load | Net Amount |")
        lines.append("|------|---------------|-----------|-----------|-----------|---------|----------|-----------|------------|")
        
        for item in items:
            lot = item["lot"]
            gain = item["gain_amount"]
            sheltered = item["sheltered"]
            taxable = item["taxable"]
            tax = item["tax_estimate"]
            gain_type = item["gain_type"]
            exit_load = item.get("exit_load", 0.0)
            net_amount = item.get("net_amount", 0.0)
            
            holding_str = f"Since {lot.purchase_date.strftime('%b %Y')}"
            if gain_type == "LT":
                holding_str += f" ({lot.holding_days(as_of)} days)"
            
            lines.append(f"| {item['fund_id']} | {holding_str} | {gain_type} | ₹{gain:,.0f} | ₹{sheltered:,.0f} | ₹{taxable:,.0f} | ₹{tax:,.0f} | ₹{exit_load:,.0f} | ₹{net_amount:,.0f} |")
            
            fy_tax += tax
            fy_sheltered += sheltered
            fy_gains += gain
            fy_exit_load += exit_load
            fy_net_amount += net_amount
        
        total_tax += fy_tax
        total_sheltered += fy_sheltered
        total_exit_load += fy_exit_load
        total_net_amount += fy_net_amount
        
        lines.append(f"\n**FY Summary:** Total Gains: ₹{fy_gains:,.0f} | Sheltered: ₹{fy_sheltered:,.0f} | Taxable: ₹{fy_gains - fy_sheltered:,.0f} | Est. Tax: ₹{fy_tax:,.0f} | Exit Load: ₹{fy_exit_load:,.0f} | Net Amount: ₹{fy_net_amount:,.0f}")
        lines.append("")
    
    lines.append("---")
    lines.append(f"**Overall Summary:**")
    lines.append(f"- Total Estimated Gains: ₹{sum(item['gain_amount'] for items in fy_plans.values() for item in items):,.0f}")
    lines.append(f"- Total Sheltered (LTCG Exemption & Loss Offsets): ₹{total_sheltered:,.0f}")
    lines.append(f"- Total Estimated Tax: ₹{total_tax:,.0f}")
    lines.append(f"- Total Exit Load: ₹{total_exit_load:,.0f}")
    lines.append(f"- Total Net Amount: ₹{total_net_amount:,.0f}")
    lines.append(f"- Completion: FY {max(fy_plans.keys())}-{str(max(fy_plans.keys())+1)[2:]}")
    lines.append("")

    # Section: Tax-Loss Harvesting & Substitute Pairing (GAP-179, GAP-159)
    loss_items = [it for items in fy_plans.values() for it in items if it.get("gain_amount", 0) < 0]
    if loss_items:
        lines.append("---")
        lines.append("## Tax-Loss Harvesting & Equivalent Substitute Pairing (Rule 14 & GAP-179)")
        lines.append("")
        lines.append("> To prevent wash-sale violations while preserving target asset class exposure,")
        lines.append("> capital losses are harvested in Year 1 and paired with equivalent broad-market engines.")
        lines.append("")
        lines.append("| Liquidated Fund (Loss Position) | Harvested Loss (₹) | Holding Period | Loss Category | Recommended Substitute Category |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for it in loss_items:
            f_name = it["fund_id"]
            h_loss = abs(it["gain_amount"])
            h_days = it["lot"].holding_days(as_of)
            g_cat = it["gain_type"] + "CL"
            lines.append(f"| {f_name} | ₹{h_loss:,.0f} | {h_days} days | {g_cat} | Broad Market Diversified Equity / Index Equivalent |")
        lines.append("")

    # Section: STP vs Lump Sum Friction Disclosure (RULE-L2, GAP-124)
    if total_sell_amount > 0:
        stp_comp = generate_stp_vs_lump_sum_comparison(
            parked_amount=total_sell_amount,
            slab_rate_pct=30.0,
            liquid_yield_pct=7.0,
            stp_months=12,
            equity_return_pct=12.0,
            equity_volatility_pct=18.0
        )
        opt_a = stp_comp["option_a_stp"]
        opt_b = stp_comp["option_b_lump_sum"]
        lines.append("---")
        lines.append("## STP Tax Friction & Deployment Analysis (Fiduciary Rule L2 & GAP-124)")
        lines.append("")
        pref = stp_comp.get("preference") or stp_comp.get("preferred") or stp_comp.get("recommendation", {}).get("preferred", "STP (Option A)")
        rat = stp_comp.get("rationale") or stp_comp.get("recommendation", {}).get("rationale", "")
        lines.append(f"> **Fiduciary Assessment:** Preference: **{pref}**")
        lines.append(f"> {rat}")
        lines.append("")
        lines.append("| Strategy Option | Deployment Horizon | Tax Friction (₹) | Opportunity Drag (₹) | Net Cost / Risk Profile |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        lines.append(f"| **Option A: STP via Liquid Fund** | 12 Months | ₹{opt_a['tax_friction_inr']:,.0f} | ₹{opt_a['opportunity_cost_inr']:,.0f} | Total Drag: ₹{opt_a['total_cost_inr']:,.0f} (Rupee Cost Averaging) |")
        lines.append(f"| **Option B: Direct Lump Sum** | Immediate | ₹0 | ₹0 | Zero Drag (Market Timing Volatility: {opt_b['market_timing_risk_pct']:.1f}% VaR) |")
        lines.append("")

    lines.append("---")
    lines.append("> **Disclaimer:** This is an algorithmic projection based on transaction data and current NAVs.")
    lines.append("> Actual tax liability depends on exact sale dates, NAVs at sale, and applicable tax laws.")
    lines.append("> Consult your tax advisor for filing.")
    
    return "\n".join(lines)

def write_transition_plan(
    client_dir: Path,
    fy_plans: dict[int, list[dict]],
    tax_rules: dict,
    total_sell_amount: float,
    client_name: str,
    as_of: date,
) -> Path:
    """Generate and write the transition plan to outputs/Transition_Plan.md."""
    output_path = client_dir / "outputs" / "Transition_Plan.md"
    content = generate_transition_plan_md(fy_plans, tax_rules, total_sell_amount, client_name, as_of)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# STP vs Lump Sum Comparison (GAP-CFA-03, RULE-L2)
# ---------------------------------------------------------------------------

def generate_stp_vs_lump_sum_comparison(
    parked_amount: float,
    slab_rate_pct: float,
    liquid_yield_pct: float = 7.0,
    stp_months: int = 12,
    equity_return_pct: float = 12.0,
    equity_volatility_pct: float = 18.0
) -> Dict[str, any]:
    """
    Generate STP vs Lump Sum comparison table (GAP-CFA-03, RULE-L2).
    
    RULE-L2: Must present "Option A: STP (tax friction = ₹X) vs Option B: 
    Direct lump-sum reinvestment (market timing risk = Y%)" and let client choose.
    
    Args:
        parked_amount: Amount parked in liquid fund for STP
        slab_rate_pct: Marginal tax slab rate (e.g., 30)
        liquid_yield_pct: Liquid fund annual yield (default 7%)
        stp_months: STP duration in months (default 12)
        equity_return_pct: Expected equity annual return (default 12%)
        equity_volatility_pct: Equity annual volatility (default 18%)
        
    Returns:
        Dict with comparison table and recommendation
    """
    from engine.portfolio_math import compute_stp_tax_friction
    
    # Option A: STP (GAP-099 FIX: Pass named parameters to prevent liquid_yield_pct being passed as slab_rate_pct)
    stp_result = compute_stp_tax_friction(
        parked_amount=parked_amount,
        instalments=stp_months,
        slab_rate_pct=slab_rate_pct,
        liquid_fund_rate_pct=liquid_yield_pct,
    )
    stp_tax_friction = stp_result['total_friction']
    monthly_gain = stp_result.get('monthly_gain', 0)
    
    # Opportunity cost of holding cash in liquid funds vs deploying in equity (GAP-141 FIX):
    # Over N instalments, average parked balance is P * (N + 1) / (2 * N)
    avg_parked_balance = parked_amount * (stp_months + 1) / (2.0 * max(1, stp_months))
    opportunity_cost_pct = max(0.0, equity_return_pct - liquid_yield_pct)
    opportunity_cost_inr = avg_parked_balance * (opportunity_cost_pct / 100.0) * (stp_months / 12.0)
    option_a_total_cost = stp_tax_friction + opportunity_cost_inr
    
    # Option B: Direct Lump Sum Reinvestment
    # Market timing risk: Volatility exposure over horizon (95% 1-year VaR)
    # This is a risk exposure metric, not a guaranteed cash drag fee.
    var_95 = min(equity_volatility_pct * 1.65, 30.0)
    timing_risk_pct = var_95
    expected_shortfall_inr = parked_amount * (timing_risk_pct / 100.0)
    option_b_total_cost = 0.0  # Zero tax friction and zero cash-drag opportunity cost
    
    # Fiduciary comparison
    if option_a_total_cost > expected_shortfall_inr * 0.5 and stp_months > 6:
        preference = "Lump Sum (Option B)"
        rationale = (
            f"Lump Sum avoids ₹{stp_tax_friction:,.0f} STP tax friction and "
            f"₹{opportunity_cost_inr:,.0f} cash drag. Ideal for long-term equity horizons."
        )
    else:
        preference = "STP (Option A)"
        rationale = (
            f"STP provides rupee cost averaging mitigating short-term market timing risk ({timing_risk_pct:.1f}% VaR), "
            f"at an estimated tax friction of ₹{stp_tax_friction:,.0f}."
        )
    
    return {
        "option_a_stp": {
            "description": f"STP over {stp_months} months from liquid fund",
            "tax_friction_inr": round(stp_tax_friction, 2),
            "monthly_gain_inr": round(monthly_gain, 2),
            "opportunity_cost_inr": round(opportunity_cost_inr, 2),
            "total_cost_inr": round(option_a_total_cost, 2),
            "breakdown": {
                "stp_tax_friction": round(stp_tax_friction, 2),
                "monthly_gain": round(monthly_gain, 2),
                "opportunity_cost_inr": round(opportunity_cost_inr, 2),
            }
        },
        "option_b_lump_sum": {
            "description": "Immediate lump-sum reinvestment in target equity funds",
            "market_timing_risk_pct": round(timing_risk_pct, 2),
            "potential_drawdown_exposure_inr": round(expected_shortfall_inr, 2),
            "total_cost_inr": round(option_b_total_cost, 2),
            "breakdown": {
                "timing_risk_pct": round(timing_risk_pct, 2),
                "tax_friction_inr": 0.0,
                "opportunity_cost_inr": 0.0,
            }
        },
        "recommendation": {
            "preferred": preference,
            "rationale": rationale,
        },
        "preference": preference,
        "preferred": preference,
        "rationale": rationale,
        "rule_l2_compliance": True,
        "as_of": datetime.now().date().isoformat()
    }


# ---------------------------------------------------------------------------
# Bogleheads Payback Circuit Breaker (GAP-115 / TRAP-05 / RULE-13)
# ---------------------------------------------------------------------------

def bogleheads_payback_years(
    unrealized_gain: float,
    current_value: float,
    delta_ter_pct: float,
    is_long_term: bool = True,
    ltcg_rate: float = 0.125,
    stcg_rate: float = 0.20,
    ltcg_exemption_remaining: float = 0.0,
    exit_load_pct: float = 0.0,
    switch_amount: float | None = None,
) -> float:
    """
    Calculate the Bogleheads Payback Horizon (Rule 13 / TRAP-05 / GAP-115):
    How many years of lower Direct Plan expense ratio it takes to recover
    the upfront switching costs (capital gains tax + exit load) triggered
    by liquidating a Regular plan and switching to Direct.

    REVIEW-P0-2 FIX: Now includes exit load in upfront costs and uses
    switch_amount (eligible investment value) for annual savings calculation
    per the review specification.

    Formula (per review):
        Taxable Gain = max(0, unrealized_gain - ltcg_exemption_remaining) if is_long_term else max(0, unrealized_gain)
        Upfront Tax = Taxable Gain * (ltcg_rate if is_long_term else stcg_rate) * 1.04 (with cess)
        Exit Load Cost = switch_amount * (exit_load_pct / 100.0)
        Total Upfront Cost = Upfront Tax + Exit Load Cost
        Annual TER Savings = switch_amount * (delta_ter_pct / 100.0)
        Payback Years = Total Upfront Cost / Annual TER Savings

    Args:
        unrealized_gain: Total unrealized gain on the holding
        current_value: Current market value of the holding
        delta_ter_pct: TER difference (Regular TER - Direct TER) in percentage points
        is_long_term: Whether holding qualifies for LTCG treatment
        ltcg_rate: LTCG tax rate (default 12.5%)
        stcg_rate: STCG tax rate (default 20%)
        ltcg_exemption_remaining: Remaining ₹1.25L LTCG exemption for the FY
        exit_load_pct: Exit load percentage (e.g., 1.0 for 1%)
        switch_amount: Amount actually being switched to Direct (defaults to current_value)
    """
    if current_value <= 0 or delta_ter_pct <= 0:
        return float("inf")
    
    # Use switch_amount for savings calculation (amount actually being moved to Direct)
    # Defaults to current_value for backward compatibility
    if switch_amount is None:
        switch_amount = current_value
    if switch_amount <= 0:
        return float("inf")

    # REVIEW-P0-2: For partial switches, taxable gain is proportional to switch_amount
    if switch_amount < current_value:
        proportional_gain = unrealized_gain * (switch_amount / current_value)
    else:
        proportional_gain = unrealized_gain

    # Calculate taxable gain
    taxable_gain = max(0.0, proportional_gain - ltcg_exemption_remaining) if is_long_term else max(0.0, proportional_gain)
    rate = ltcg_rate if is_long_term else stcg_rate
    upfront_tax = taxable_gain * rate * 1.04  # 4% health & education cess

    # REVIEW-P0-2: Add exit load cost to upfront switching costs
    exit_load_cost = switch_amount * (exit_load_pct / 100.0) if exit_load_pct > 0 else 0.0
    total_upfront_cost = upfront_tax + exit_load_cost

    if total_upfront_cost <= 0:
        return 0.0  # Immediate payback (gain sheltered, at a loss, or no exit load)

    # Annual TER savings based on amount actually switched
    annual_savings = switch_amount * (delta_ter_pct / 100.0)
    if annual_savings <= 0:
        return float("inf")
        
    return total_upfront_cost / annual_savings


def bogleheads_circuit_breaker(
    unrealized_gain: float,
    current_value: float,
    delta_ter_pct: float,
    client_horizon_years: int,
    is_long_term: bool = True,
    ltcg_rate: float = 0.125,
    stcg_rate: float = 0.20,
    ltcg_exemption_remaining: float = 0.0,
    exit_load_pct: float = 0.0,
    switch_amount: float | None = None,
) -> dict:
    """
    Evaluate if liquidating a Regular plan violates the Bogleheads rule.
    If payback_years > client_horizon_years, liquidating destroys client wealth.

    REVIEW-P0-2 FIX: Now passes exit_load_pct and switch_amount to payback calculation.
    """
    payback = bogleheads_payback_years(
        unrealized_gain=unrealized_gain,
        current_value=current_value,
        delta_ter_pct=delta_ter_pct,
        is_long_term=is_long_term,
        ltcg_rate=ltcg_rate,
        stcg_rate=stcg_rate,
        ltcg_exemption_remaining=ltcg_exemption_remaining,
        exit_load_pct=exit_load_pct,
        switch_amount=switch_amount,
    )
    should_liquidate = payback <= client_horizon_years
    return {
        "payback_years": round(payback, 2) if payback != float("inf") else 999.0,
        "client_horizon_years": client_horizon_years,
        "should_liquidate": should_liquidate,
        "rationale": (
            f"Payback in {payback:.1f} yrs is within {client_horizon_years} yr horizon."
            if should_liquidate else
            f"CIRCUIT BREAKER TRIGGERED: Payback ({payback:.1f} yrs) exceeds client horizon ({client_horizon_years} yrs). Upfront tax exceeds lifetime TER savings."
        )
    }


# Canonical alias for Bogleheads switch evaluation (GAP-115)
evaluate_bogleheads_switch_hurdle = bogleheads_circuit_breaker

# REVIEW-P0-2: Switch vs Stop SIP comparison
def compare_switch_vs_stop_sip(
    current_value: float,
    unrealized_gain: float,
    exit_load_pct: float,
    ter_regular_pct: float,
    ter_direct_pct: float,
    is_long_term: bool = True,
    ltcg_rate: float = 0.125,
    stcg_rate: float = 0.20,
    ltcg_exemption_remaining: float = 0.0,
    monthly_sip_amount: float = 0.0,
    remaining_sip_months: int = 0,
    client_horizon_years: int = 10,
    expected_return_pct: float = 12.0,
) -> dict:
    """REVIEW-P0-2: Compare SWITCH_NOW vs STOP_SIP_REDIRECT for Regular→Direct."""
    delta_ter = ter_regular_pct - ter_direct_pct
    if delta_ter <= 0 or current_value <= 0:
        return {"recommendation": "NO_BENEFIT", "rationale": "No TER advantage", "switch_now": None, "stop_sip": None}
    
    # Strategy A: SWITCH NOW
    switch_payback = bogleheads_payback_years(
        unrealized_gain=unrealized_gain, current_value=current_value, delta_ter_pct=delta_ter,
        is_long_term=is_long_term, ltcg_rate=ltcg_rate, stcg_rate=stcg_rate,
        ltcg_exemption_remaining=ltcg_exemption_remaining, exit_load_pct=exit_load_pct, switch_amount=current_value
    )
    taxable_gain = max(0.0, unrealized_gain - ltcg_exemption_remaining) if is_long_term else max(0.0, unrealized_gain)
    rate = ltcg_rate if is_long_term else stcg_rate
    upfront_tax = taxable_gain * rate * 1.04
    exit_load_cost = current_value * (exit_load_pct / 100.0)
    total_upfront = upfront_tax + exit_load_cost
    annual_savings_switch = current_value * (delta_ter / 100.0)
    net_benefit_switch = (annual_savings_switch * client_horizon_years) - total_upfront
    
    # Strategy B: STOP SIP, redirect new SIP to Direct
    if monthly_sip_amount <= 0 or remaining_sip_months <= 0:
        stop_sip_annual = 0.0
        stop_sip_total = 0.0
    else:
        monthly_savings = monthly_sip_amount * (delta_ter / 100.0)
        months = min(remaining_sip_months, client_horizon_years * 12)
        r_m = expected_return_pct / 100.0 / 12.0
        fv = ((1 + r_m) ** months - 1) / r_m if r_m > 0 else months
        stop_sip_total = monthly_savings * fv
        stop_sip_annual = monthly_savings * 12
    
    lost_annual = current_value * (delta_ter / 100.0)
    lost_total = lost_annual * client_horizon_years
    net_benefit_stop = stop_sip_total - lost_total
    
    switch_viable = switch_payback != float("inf") and switch_payback <= client_horizon_years
    stop_viable = net_benefit_stop > 0
    
    if switch_viable and (not stop_viable or net_benefit_switch > net_benefit_stop):
        rec = "SWITCH_NOW"
        rat = f"Switch pays back in {switch_payback:.1f} yrs. Net: ₹{net_benefit_switch:,.0f} vs Stop: ₹{net_benefit_stop:,.0f}"
    elif stop_viable:
        rec = "STOP_SIP_REDIRECT"
        rat = f"Switch payback {switch_payback:.1f} yrs exceeds horizon or Stop better. Stop net: ₹{net_benefit_stop:,.0f}"
    else:
        rec = "DO_NOTHING"
        rat = f"Neither viable. Switch payback: {switch_payback:.1f} yrs, Stop net: ₹{net_benefit_stop:,.0f}"
    
    return {
        "recommendation": rec, "rationale": rat,
        "switch_now": {"payback_years": round(switch_payback,2) if switch_payback!=float("inf") else None,
                       "upfront_tax": round(upfront_tax,2), "exit_load_cost": round(exit_load_cost,2),
                       "total_upfront_cost": round(total_upfront,2), "annual_savings": round(annual_savings_switch,2),
                       "net_benefit_horizon": round(net_benefit_switch,2), "viable": switch_viable},
        "stop_sip": {"annual_savings_new_sip": round(stop_sip_annual,2), "total_savings_new_sip": round(stop_sip_total,2),
                     "lost_savings_existing": round(lost_total,2), "net_benefit_horizon": round(net_benefit_stop,2),
                     "viable": stop_viable},
        "client_horizon_years": client_horizon_years
    }


def compute_carried_market_risk(
    deferred_capital: float,
    annual_volatility_pct: float = 16.5,
    months_deferred: float = 8.0,
    tax_saved: float = 0.0,
) -> dict[str, Any]:
    """
    Empirical Carried Market Risk computation per RULE-T5.
    
    Quantifies the market risk incurred by delaying an exit into the next FY:
    - Time horizon in years: T = months_deferred / 12.0
    - Annualized volatility: sigma = annual_volatility_pct / 100.0
    - Carried Risk (1-sigma expected volatility): Deferred Capital * sigma * sqrt(T)
    - Downside VaR (95% confidence, Z=1.645): Deferred Capital * 1.645 * sigma * sqrt(T)
    - Downside VaR (99% confidence, Z=2.326): Deferred Capital * 2.326 * sigma * sqrt(T)
    """
    import math

    if deferred_capital <= 0:
        return {
            "deferred_capital": 0.0,
            "annual_volatility_pct": annual_volatility_pct,
            "months_deferred": months_deferred,
            "time_years": 0.0,
            "carried_risk_1sigma": 0.0,
            "downside_var_95": 0.0,
            "downside_var_99": 0.0,
            "tax_saved": tax_saved,
            "risk_exceeds_tax_savings": False,
            "recommendation": "No deferred capital; zero carried market risk.",
        }

    t_years = max(0.0, months_deferred / 12.0)
    sigma = annual_volatility_pct / 100.0
    sqrt_t = math.sqrt(t_years)

    carried_risk_1sigma = deferred_capital * sigma * sqrt_t
    downside_var_95 = deferred_capital * 1.644853 * sigma * sqrt_t
    downside_var_99 = deferred_capital * 2.326348 * sigma * sqrt_t
    risk_exceeds_tax_savings = downside_var_95 > tax_saved if tax_saved > 0 else True

    rec = (
        f"95% Downside VaR (₹{downside_var_95:,.0f}) exceeds tax saved (₹{tax_saved:,.0f}). Immediate single-shot exit is prudently recommended over staging."
        if (tax_saved > 0 and risk_exceeds_tax_savings)
        else f"Tax savings of ₹{tax_saved:,.0f} compensate for 95% Downside VaR of ₹{downside_var_95:,.0f} over {months_deferred:.1f} months deferral."
    )

    return {
        "deferred_capital": round(deferred_capital, 2),
        "annual_volatility_pct": round(annual_volatility_pct, 2),
        "months_deferred": round(months_deferred, 1),
        "time_years": round(t_years, 3),
        "carried_risk_1sigma": round(carried_risk_1sigma, 2),
        "downside_var_95": round(downside_var_95, 2),
        "downside_var_99": round(downside_var_99, 2),
        "tax_saved": round(tax_saved, 2),
        "risk_exceeds_tax_savings": risk_exceeds_tax_savings,
        "recommendation": rec,
    }


def compute_exit_load_amortization(
    lot: Lot,
    current_nav: float,
    as_of: date,
    exit_load_pct: float = 1.0,
    exit_load_days: int = 365,
) -> dict[str, Any]:
    """
    Computes exit load amortization schedule for a lot per GAP-146.
    Identifies if a lot is within 60 days of becoming exit-load free.
    """
    from datetime import timedelta
    holding_days = (as_of - lot.purchase_date).days
    sale_value = lot.units * current_nav
    free_date = lot.purchase_date + timedelta(days=exit_load_days)
    days_to_free = max(0, exit_load_days - holding_days)

    if holding_days < exit_load_days:
        exit_load_amount = sale_value * (exit_load_pct / 100.0)
        is_amortizing_soon = (0 < days_to_free <= 60)
    else:
        exit_load_amount = 0.0
        is_amortizing_soon = False

    return {
        "fund_id": lot.fund_id,
        "purchase_date": lot.purchase_date.isoformat(),
        "as_of_date": as_of.isoformat(),
        "holding_days": holding_days,
        "exit_load_days_threshold": exit_load_days,
        "days_to_exit_load_free": days_to_free,
        "exit_load_free_date": free_date.isoformat(),
        "is_amortizing_soon": is_amortizing_soon,
        "current_valuation": round(sale_value, 2),
        "exit_load_amount": round(exit_load_amount, 2),
        "net_proceeds": round(sale_value - exit_load_amount, 2),
        "amortization_action": (
            f"DEFER EXIT {days_to_free} DAYS (Amortizes on {free_date.isoformat()} to save ₹{exit_load_amount:,.0f})"
            if is_amortizing_soon else
            ("EXIT LOAD ACTIVE" if exit_load_amount > 0 else "ZERO EXIT LOAD (Amortized)")
        )
    }

# ---------------------------------------------------------------------------
# P0 PRODUCTION SAFETY GATE — tax transition and switch-cost advice disabled.
#
# This legacy module contains provisional statutory rates, default exit-load
# assumptions, fund-name heuristics, future-date approximations, and hard-coded
# STP/lump-sum assumptions. These are not an approved Indian tax computation
# basis. Keep transaction parsing available for controlled data preparation,
# but block every public function that can turn those inputs into tax,
# redemption, transition, or switch recommendations until independent
# tax/legal approval and lot-/scheme-specific evidence are released.
# ---------------------------------------------------------------------------

class TaxAdviceDisabledError(RuntimeError):
    """Raised when an unapproved legacy tax-advice pathway is invoked."""


def _tax_advice_disabled(*args, **kwargs):
    raise TaxAdviceDisabledError(
        "Tax transition, redemption, exit-load, and switch-cost advice is "
        "disabled pending independently approved Indian tax rules, "
        "scheme/plan/lot-specific evidence, and production release approval. "
        "No estimate or action plan has been generated."
    )


# Preserve parsing and provenance preparation only. The following names are
# intentionally rebound after legacy definitions so all direct and internal
# callers fail closed, rather than silently receiving provisional outputs.
load_tax_rules = _tax_advice_disabled
classify_fund_for_tax = _tax_advice_disabled
get_tax_rates_for_sale = _tax_advice_disabled
plan_fy_tranches = _tax_advice_disabled
generate_transition_plan_md = _tax_advice_disabled
write_transition_plan = _tax_advice_disabled
generate_stp_vs_lump_sum_comparison = _tax_advice_disabled
bogleheads_payback_years = _tax_advice_disabled
bogleheads_circuit_breaker = _tax_advice_disabled
evaluate_bogleheads_switch_hurdle = _tax_advice_disabled
compare_switch_vs_stop_sip = _tax_advice_disabled
compute_exit_load_amortization = _tax_advice_disabled
