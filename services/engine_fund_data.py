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

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable
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
            headers={"User-Agent": "MF-Engine/1.0 (public-data acquisition)"},
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
    """Parse AMFI NAVAll pipe-delimited rows without guessing missing fields."""
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
        if not line or line.startswith("Scheme Code") or "|" not in line:
            continue
        fields = [part.strip() for part in line.split("|")]
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
            nav = float(nav_raw)
        except ValueError as exc:
            raise FundDataAcquisitionError(f"Invalid NAV value at line {line_number}") from exc
        if not (nav > 0 and nav < float("inf")):
            raise FundDataAcquisitionError(f"NAV must be finite and positive at line {line_number}")

        isins = {
            value for value in (isin_growth, isin_reinvestment)
            if value and re.fullmatch(r"INF[A-Z0-9]{9,}", value)
        }
        rows.append({
            "amfi_scheme_code": scheme_code,
            "isin_values": sorted(isins),
            "scheme_name_raw": scheme_name,
            "nav": format(nav, ".10g"),
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
    )
    artifacts = build_public_fund_artifacts(feed)
    # Each artifact embeds the same source digest; the manifest is written last
    # and acts as the snapshot commit marker for readers.
    output_paths = {
        "scheme_master": config.data_dir / "scheme_master.json",
        "fund_metrics": config.data_dir / "fund_metrics.json",
        "fund_aliases": config.data_dir / "fund_aliases.json",
    }
    for name, path in output_paths.items():
        _atomic_write_json(path, artifacts[name])

    manifest = {
        "schema": _DATASET_SCHEMA,
        "dataset_id": feed.sha256,
        "status": "ACQUIRED_UNVERIFIED",
        "retrieved_at": feed.retrieved_at,
        "source_url": feed.url,
        "source_sha256": feed.sha256,
        "artifacts": {name: path.name for name, path in output_paths.items()},
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
    return manifest
