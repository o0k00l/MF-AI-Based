"""Engine-owned public mutual-fund data acquisition and artifact generation.

The first adapter consumes AMFI's publicly published NAVAll text feed. It builds
internal scheme-identity/NAV snapshots without requiring investors to author
fund_metrics.json or fund_aliases.json.

Important: acquisition is not approval. All generated records remain
ACQUIRED_UNVERIFIED and must not satisfy recommendation/release evidence gates.
The feed does not provide full risk, portfolio, expense, benchmark or holdings
metrics; this module deliberately does not invent them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import requests


AMFI_NAV_FEED_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
_ALLOWED_AMFI_HOSTS = frozenset({"www.amfiindia.com", "amfiindia.com"})
_DATASET_SCHEMA = "mf_engine.public_fund_data.v1"


class FundDataAcquisitionError(RuntimeError):
    """Raised when an upstream feed cannot be safely acquired or parsed."""


@dataclass(frozen=True)
class EngineRuntimeConfig:
    """Operational engine settings; investor mandate facts do not belong here."""

    data_dir: Path
    request_timeout_seconds: float = 20.0
    user_agent: str = "MF-Engine/1.0 (public-data acquisition)"

    @classmethod
    def from_environment(cls, environ: dict[str, str] | None = None) -> "EngineRuntimeConfig":
        env = os.environ if environ is None else environ
        configured = env.get("MF_ENGINE_DATA_DIR")
        data_dir = (
            Path(configured).expanduser().resolve()
            if configured
            else (Path.home() / ".local" / "share" / "mf-engine" / "datasets").resolve()
        )
        timeout_raw = env.get("MF_ENGINE_HTTP_TIMEOUT_SECONDS", "20")
        try:
            timeout = float(timeout_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("MF_ENGINE_HTTP_TIMEOUT_SECONDS must be numeric") from exc
        if not 0 < timeout < float("inf"):
            raise ValueError("MF_ENGINE_HTTP_TIMEOUT_SECONDS must be finite and positive")
        return cls(data_dir=data_dir, request_timeout_seconds=timeout)


@dataclass(frozen=True)
class AcquiredFeed:
    url: str
    retrieved_at: str
    sha256: str
    content: bytes


def _validate_source_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_AMFI_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise FundDataAcquisitionError("AMFI source URL is outside the approved HTTPS host allowlist")


def acquire_amfi_nav_feed(
    *,
    session: Any | None = None,
    url: str = AMFI_NAV_FEED_URL,
    timeout_seconds: float = 20.0,
    now: datetime | None = None,
    user_agent: str = "MF-Engine/1.0 (public-data acquisition)",
) -> AcquiredFeed:
    """Download AMFI's NAV feed and preserve the exact source bytes and digest."""
    _validate_source_url(url)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)):
        raise ValueError("timeout_seconds must be a positive finite number")
    if not 0 < float(timeout_seconds) < float("inf"):
        raise ValueError("timeout_seconds must be a positive finite number")

    client = session if session is not None else requests
    try:
        response = client.get(
            url,
            timeout=float(timeout_seconds),
            headers={"User-Agent": user_agent},
        )
        response.raise_for_status()
        content = response.content
    except requests.RequestException as exc:
        raise FundDataAcquisitionError(f"AMFI NAV feed acquisition failed: {exc}") from exc

    if not isinstance(content, bytes) or not content.strip():
        raise FundDataAcquisitionError("AMFI NAV feed returned an empty or invalid body")
    # Reject HTML/proxy error pages before interpreting them as a data feed.
    prefix = content.lstrip()[:256].lower()
    if b"<html" in prefix or b"<!doctype" in prefix:
        raise FundDataAcquisitionError("AMFI NAV feed returned HTML instead of the expected text feed")

    retrieved = now or datetime.now(timezone.utc)
    if retrieved.tzinfo is None or retrieved.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return AcquiredFeed(
        url=url,
        retrieved_at=retrieved.astimezone(timezone.utc).isoformat(),
        sha256=hashlib.sha256(content).hexdigest(),
        content=content,
    )


def parse_amfi_nav_feed(content: bytes) -> list[dict[str, Any]]:
    """Parse AMFI NAVAll feed - supports both legacy pipe-delimited and current semicolon-delimited formats."""
    if not isinstance(content, bytes) or not content.strip():
        raise FundDataAcquisitionError("AMFI NAV feed is empty")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FundDataAcquisitionError("AMFI NAV feed is not valid UTF-8") from exc

    rows: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("Scheme Code"):
            continue
        
        # Detect delimiter: semicolon (current AMFI format) or pipe (legacy)
        if ";" in line and not line.startswith("|"):
            # Current AMFI format uses semicolon delimiter
            fields = [part.strip() for part in line.split(";")]
        elif "|" in line:
            # Legacy AMFI format uses pipe delimiter
            fields = [part.strip() for part in line.split("|")]
        else:
            continue
        
        if len(fields) < 6:
            # AMFI also publishes category/AMC headings; ignore non-record lines,
            # but reject malformed rows that begin with a numeric scheme code.
            if fields and fields[0].isdigit():
                raise FundDataAcquisitionError(f"Malformed AMFI record at line {line_number}")
            continue

        scheme_code, isin_growth, isin_reinvestment, scheme_name, nav_raw, nav_date_raw = fields[:6]
        if not scheme_code.isdigit():
            continue
        if scheme_code in seen_codes:
            raise FundDataAcquisitionError(f"Duplicate AMFI scheme code at line {line_number}")
        seen_codes.add(scheme_code)
        if not scheme_name:
            raise FundDataAcquisitionError(f"Missing scheme name at line {line_number}")
        try:
            nav_date = datetime.strptime(nav_date_raw, "%d-%b-%Y").date()
        except ValueError as exc:
            raise FundDataAcquisitionError(f"Invalid NAV date at line {line_number}") from exc
        try:
            nav = Decimal(nav_raw)
        except (InvalidOperation, ValueError) as exc:
            raise FundDataAcquisitionError(f"Invalid NAV value at line {line_number}") from exc
        if not nav.is_finite() or nav < 0:
            raise FundDataAcquisitionError(f"NAV must be finite and positive at line {line_number}")
        if nav == 0:
            # Skip closed/wind-up funds with zero NAV (they are no longer active)
            continue

        isins = {
            value for value in (isin_growth, isin_reinvestment)
            if value and re.fullmatch(r"INF[A-Z0-9]{9,}", value)
        }
        rows.append({
            "amfi_scheme_code": scheme_code,
            "isin_values": sorted(isins),
            "scheme_name_raw": scheme_name,
            "nav": format(nav.normalize(), "f"),
            "nav_date": nav_date.isoformat(),
        })

    if not rows:
        raise FundDataAcquisitionError("AMFI feed contained no valid scheme records")
    return rows


def build_public_fund_artifacts(feed: AcquiredFeed) -> dict[str, dict[str, Any]]:
    """Build generated identity, NAV metric and alias artifacts from one feed snapshot."""
    rows = parse_amfi_nav_feed(feed.content)
    dataset_id = feed.sha256
    common = {
        "schema": _DATASET_SCHEMA,
        "dataset_id": dataset_id,
        "status": "ACQUIRED_UNVERIFIED",
        "source": {
            "publisher": "AMFI",
            "url": feed.url,
            "retrieved_at": feed.retrieved_at,
            "source_sha256": feed.sha256,
        },
    }

    scheme_records: dict[str, Any] = {}
    nav_metrics: dict[str, Any] = {}
    aliases: dict[str, list[str]] = {}
    for row in rows:
        code = row["amfi_scheme_code"]
        scheme_records[code] = {
            "amfi_scheme_code": code,
            "isin_values": row["isin_values"],
            "scheme_name_raw": row["scheme_name_raw"],
            "identity_status": "UNRESOLVED_REQUIRES_CROSS_SOURCE_VALIDATION",
        }
        nav_metrics[code] = {
            "amfi_scheme_code": code,
            "nav": row["nav"],
            "nav_date": row["nav_date"],
            "metric_status": "SOURCE_OBSERVED_NOT_REVIEWED",
        }
        aliases.setdefault(row["scheme_name_raw"], []).append(code)

    return {
        "scheme_master": {**common, "records": scheme_records},
        "fund_metrics": {
            **common,
            "metrics_scope": ["NAV"],
            "records": nav_metrics,
            "coverage_note": (
                "AMFI NAV feed does not establish expense ratios, AUM, riskometer, "
                "portfolio holdings, benchmark, manager tenure or suitability metrics."
            ),
        },
        "fund_aliases": {
            **common,
            "alias_semantics": "raw_source_name_to_amfi_scheme_code_candidates",
            "aliases": {key: sorted(value) for key, value in aliases.items()},
        },
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except OSError:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise



# SCHEME CLASSIFICATION AND CANDIDATE UNIVERSE GENERATION

_SCHEME_CATEGORY_PATTERNS = [
    ("index fund", "Index", {"is_passive": True, "sub_category": "Index"}),
    ("etf", "ETF", {"is_passive": True, "sub_category": "ETF"}),
    ("nifty 50", "Large Cap", {"is_passive": False, "sub_category": "Large Cap"}),
    ("sensex", "Large Cap", {"is_passive": False, "sub_category": "Large Cap"}),
    ("large cap", "Large Cap", {"is_passive": False, "sub_category": "Large Cap"}),
    ("largecap", "Large Cap", {"is_passive": False, "sub_category": "Large Cap"}),
    ("fifty", "Large Cap", {"is_passive": False, "sub_category": "Large Cap"}),
    ("flexi cap", "Flexi Cap", {"is_passive": False, "sub_category": "Flexi Cap"}),
    ("flexicap", "Flexi Cap", {"is_passive": False, "sub_category": "Flexi Cap"}),
    ("multi cap", "Multi Cap", {"is_passive": False, "sub_category": "Multi Cap"}),
    ("multicap", "Multi Cap", {"is_passive": False, "sub_category": "Multi Cap"}),
    ("focused", "Focused", {"is_passive": False, "sub_category": "Focused"}),
    ("value fund", "Value", {"is_passive": False, "sub_category": "Value"}),
    ("contra", "Contra", {"is_passive": False, "sub_category": "Contra"}),
    ("mid cap", "Mid Cap", {"is_passive": False, "sub_category": "Mid Cap"}),
    ("midcap", "Mid Cap", {"is_passive": False, "sub_category": "Mid Cap"}),
    ("small cap", "Small Cap", {"is_passive": False, "sub_category": "Small Cap"}),
    ("smallcap", "Small Cap", {"is_passive": False, "sub_category": "Small Cap"}),
    ("elss", "ELSS", {"is_passive": False, "sub_category": "ELSS", "lock_in_years": 3}),
    ("tax saver", "ELSS", {"is_passive": False, "sub_category": "ELSS", "lock_in_years": 3}),
    ("taxsaver", "ELSS", {"is_passive": False, "sub_category": "ELSS", "lock_in_years": 3}),
    ("balanced advantage", "Hybrid: Dynamic Asset Allocation", {"is_passive": False, "sub_category": "BAF"}),
    ("baf", "Hybrid: Dynamic Asset Allocation", {"is_passive": False, "sub_category": "BAF"}),
    ("aggressive hybrid", "Hybrid: Aggressive", {"is_passive": False, "sub_category": "Aggressive Hybrid"}),
    ("conservative hybrid", "Hybrid: Conservative", {"is_passive": False, "sub_category": "Conservative Hybrid"}),
    ("equity hybrid", "Hybrid: Aggressive", {"is_passive": False, "sub_category": "Aggressive Hybrid"}),
    ("arbitrage", "Arbitrage", {"is_passive": False, "sub_category": "Arbitrage"}),
    ("multi asset", "Multi Asset Allocation", {"is_passive": False, "sub_category": "Multi Asset"}),
    ("liquid fund", "Liquid", {"is_passive": False, "sub_category": "Liquid", "risk_tier": 1}),
    ("liquid", "Liquid", {"is_passive": False, "sub_category": "Liquid", "risk_tier": 1}),
    ("overnight", "Overnight", {"is_passive": False, "sub_category": "Overnight", "risk_tier": 1}),
    ("money market", "Money Market", {"is_passive": False, "sub_category": "Money Market", "risk_tier": 1}),
    ("banking and psu", "Banking and PSU", {"is_passive": False, "sub_category": "Banking and PSU"}),
    ("gilt", "Gilt", {"is_passive": False, "sub_category": "Gilt"}),
    ("floater", "Floater", {"is_passive": False, "sub_category": "Floater"}),
    ("gold", "Gold", {"is_passive": False, "sub_category": "Gold", "gold": True}),
    ("international fund", "International", {"is_passive": False, "sub_category": "International", "international": True}),
    ("global fund", "International", {"is_passive": False, "sub_category": "International", "international": True}),
    ("us equity", "International", {"is_passive": False, "sub_category": "International", "international": True}),
    ("nasdaq", "International", {"is_passive": False, "sub_category": "International", "international": True}),
    ("sectoral", "Sectoral", {"is_passive": False, "sub_category": "Sectoral", "thematic": True}),
    ("sector", "Sectoral", {"is_passive": False, "sub_category": "Sectoral", "thematic": True}),
    ("thematic", "Thematic", {"is_passive": False, "sub_category": "Thematic", "thematic": True}),
    ("infrastructure", "Thematic", {"is_passive": False, "sub_category": "Thematic", "thematic": True}),
    ("dividend yield", "Dividend Yield", {"is_passive": False, "sub_category": "Dividend Yield"}),
]


def _classify_scheme_from_name(scheme_name: str) -> dict[str, Any]:
    """Classify Indian mutual fund scheme from its name using keyword patterns."""
    if not scheme_name:
        return {"sebi_category": "UNCLASSIFIED", "sub_category": "UNCLASSIFIED",
                "is_passive": False, "classification_status": "UNCLASSIFIED_NO_NAME"}
    name_lower = scheme_name.lower()
    name_lower = re.sub(r"\b(direct|regular|plan|growth|idcw|dividend|payout|reinvestment|option)\b", "", name_lower)
    name_lower = re.sub(r"[^a-z0-9\s]", " ", name_lower)
    name_lower = " ".join(name_lower.split())
    for pattern, category, extra in _SCHEME_CATEGORY_PATTERNS:
        if pattern in name_lower:
            return {"sebi_category": category, "sub_category": category,
                    "is_passive": extra.get("is_passive", False),
                    "classification_status": "PROVISIONAL_NAME_BASED",
                    "requires_validation": True, **{k: v for k, v in extra.items() if k not in ("sub_category", "is_passive")}}
    return {"sebi_category": "Equity Diversified", "sub_category": "Equity Diversified",
            "is_passive": False, "classification_status": "PROVISIONAL_DEFAULT_EQUITY",
            "requires_validation": True}



def _infer_asset_class_from_category(sebi_category: str) -> str:
    """Infer broad asset class from SEBI category."""
    equity = {'Large Cap', 'Mid Cap', 'Small Cap', 'Flexi Cap', 'Multi Cap', 'Focused', 'Value', 'Contra', 'ELSS', 'Equity Diversified', 'Sectoral', 'Thematic', 'Dividend Yield', 'International'}
    hybrid = {'Hybrid: Dynamic Asset Allocation', 'Hybrid: Aggressive', 'Hybrid: Conservative', 'Arbitrage', 'Multi Asset Allocation'}
    debt = {'Liquid', 'Overnight', 'Money Market', 'Ultra Short Duration', 'Low Duration', 'Short Duration', 'Medium Duration', 'Corporate Bond', 'Banking and PSU', 'Gilt', 'Floater', 'Credit Risk', 'Dynamic Bond', 'Medium to Long Duration'}
    if sebi_category in equity: return 'Equity'
    if sebi_category in hybrid: return 'Hybrid'
    if sebi_category in debt: return 'Debt'
    if 'Gold' in sebi_category: return 'Commodity'
    return 'Unknown'


def build_candidate_universe(feed: "AcquiredFeed", *, min_aum_crore: float = 0.0,
    categories_filter: list[str] | None = None) -> dict[str, Any]:
    """Build category-wise candidate universe from AMFI NAV feed."""
    rows = parse_amfi_nav_feed(feed.content)
    classified, all_schemes = {}, []
    for row in rows:
        code, name = row["amfi_scheme_code"], row["scheme_name_raw"]
        cls = _classify_scheme_from_name(name)
        if categories_filter and cls["sebi_category"] not in categories_filter:
            continue
        candidate = {"amfi_scheme_code": code, "scheme_name": name,
                     "isin_values": row["isin_values"], "nav": row["nav"], "nav_date": row["nav_date"],
                     "sebi_category": cls["sebi_category"], "sub_category": cls.get("sub_category", cls["sebi_category"]),
                     "is_passive": cls.get("is_passive", False), "classification_status": cls["classification_status"],
                     "requires_validation": cls.get("requires_validation", True)}
        for k in ("lock_in_years", "risk_tier", "gold", "international"):
            if k in cls: candidate[k] = cls[k]
        all_schemes.append(candidate)
        classified.setdefault(cls["sebi_category"], []).append(candidate)
    for cat in classified: classified[cat].sort(key=lambda x: x["scheme_name"])
    all_schemes.sort(key=lambda x: x["scheme_name"])
    return {"metadata": {"schema": "mf_engine.candidate_universe.v1", "dataset_id": feed.sha256,
                "status": "ACQUIRED_UNVERIFIED", "total_schemes": len(all_schemes)},
            "category_wise": {c: {"count": len(s), "schemes": s} for c, s in classified.items()},
            "all_schemes": all_schemes}

def refresh_engine_fund_data(
    config: EngineRuntimeConfig,
    *,
    session: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Path]:
    """Acquire, validate and atomically publish an unverified engine-owned snapshot."""
    feed = acquire_amfi_nav_feed(
        session=session,
        timeout_seconds=config.request_timeout_seconds,
        now=now,
        user_agent=config.user_agent,
    )
    artifacts = build_public_fund_artifacts(feed)
    # Each artifact embeds the same source digest; the manifest is written last
    # and acts as the snapshot commit marker for readers.
    snapshot_dir = config.data_dir / "snapshots" / feed.sha256
    output_paths = {
        "scheme_master": snapshot_dir / "scheme_master.json",
        "fund_metrics": snapshot_dir / "fund_metrics.json",
        "fund_aliases": snapshot_dir / "fund_aliases.json",
    }
    for name, path in output_paths.items():
        _atomic_write_json(path, artifacts[name])

    source_dir = snapshot_dir / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    source_path = source_dir / "amfi-nav.txt"
    if not source_path.exists():
        temp_source = source_dir / ".amfi-nav.txt.tmp"
        temp_source.write_bytes(feed.content)
        os.replace(temp_source, source_path)

    manifest = {
        "schema": _DATASET_SCHEMA,
        "dataset_id": feed.sha256,
        "status": "ACQUIRED_UNVERIFIED",
        "retrieved_at": feed.retrieved_at,
        "source_url": feed.url,
        "source_sha256": feed.sha256,
        "source_file": str(source_path.relative_to(config.data_dir)),
        "artifacts": {
            name: str(path.relative_to(config.data_dir))
            for name, path in output_paths.items()
        },
        "promotion_eligible": False,
        "promotion_blockers": [
            "AMFI NAV feed alone is not a complete scheme-master or fund-metrics evidence bundle",
            "Independent source reconciliation and reviewer approval are required",
        ],
    }
    manifest_path = config.data_dir / "manifest.json"
    _atomic_write_json(manifest_path, manifest)
    return {**output_paths, "manifest": manifest_path}


def load_engine_manifest(data_dir: Path) -> dict[str, Any]:
    """Load a valid manifest; absence is a typed not-ready state, never a client prompt."""
    path = Path(data_dir) / "manifest.json"
    if not path.is_file():
        return {
            "schema": _DATASET_SCHEMA,
            "status": "NOT_ACQUIRED",
            "promotion_eligible": False,
            "promotion_blockers": ["Engine-managed public fund data has not yet been acquired"],
        }
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FundDataAcquisitionError("Engine fund-data manifest is unreadable or invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != _DATASET_SCHEMA:
        raise FundDataAcquisitionError("Engine fund-data manifest schema is unsupported")
    if manifest.get("status") == "ACQUIRED_UNVERIFIED":
        dataset_id = manifest.get("dataset_id")
        artifacts = manifest.get("artifacts")
        if not isinstance(dataset_id, str) or not isinstance(artifacts, dict):
            raise FundDataAcquisitionError("Engine fund-data manifest is incomplete")
        for name in ("scheme_master", "fund_metrics", "fund_aliases"):
            relative = artifacts.get(name)
            if not isinstance(relative, str) or Path(relative).is_absolute():
                raise FundDataAcquisitionError(f"Invalid artifact path for {name}")
            artifact_path = (Path(data_dir) / relative).resolve()
            try:
                artifact_path.relative_to(Path(data_dir).resolve())
                artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise FundDataAcquisitionError(f"Engine fund-data artifact {name} is missing or invalid") from exc
            if not isinstance(artifact, dict) or artifact.get("dataset_id") != dataset_id:
                raise FundDataAcquisitionError(f"Engine fund-data snapshot is inconsistent for {name}")
        source_relative = manifest.get("source_file")
        if not isinstance(source_relative, str) or Path(source_relative).is_absolute():
            raise FundDataAcquisitionError("Engine fund-data source path is invalid")
        source_path = (Path(data_dir) / source_relative).resolve()
        try:
            source_path.relative_to(Path(data_dir).resolve())
            source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise FundDataAcquisitionError("Original AMFI source bytes are missing or outside the data store") from exc
        if source_digest != dataset_id:
            raise FundDataAcquisitionError("Original AMFI source digest does not match the dataset manifest")
    return manifest
