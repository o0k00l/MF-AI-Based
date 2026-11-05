from datetime import datetime, timezone
import hashlib
import json

import pytest

from services.engine_fund_data import (
    AcquiredFeed,
    EngineRuntimeConfig,
    FundDataAcquisitionError,
    acquire_amfi_nav_feed,
    build_public_fund_artifacts,
    load_engine_manifest,
    parse_amfi_nav_feed,
    refresh_engine_fund_data,
)


SAMPLE = (
    "Scheme Code|ISIN Div Payout/ISIN Growth|ISIN Div Reinvestment|Scheme Name|Net Asset Value|Date\n"
    "100001|INF000000001|INF000000002|Example Equity Fund - Direct Plan - Growth|123.45|04-Nov-2026\n"
).encode()


class FakeResponse:
    content = SAMPLE

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, response=None):
        self.response = response or FakeResponse()
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_runtime_config_uses_engine_owned_directory_and_environment():
    config = EngineRuntimeConfig.from_environment({"MF_ENGINE_DATA_DIR": "~/mf-data"})
    assert config.data_dir.name == "mf-data"
    assert config.request_timeout_seconds > 0


def test_runtime_config_rejects_invalid_timeout():
    with pytest.raises(ValueError):
        EngineRuntimeConfig.from_environment({"MF_ENGINE_HTTP_TIMEOUT_SECONDS": "nan"})


def test_acquisition_preserves_source_digest_and_requires_https_allowlist():
    now = datetime(2026, 11, 5, tzinfo=timezone.utc)
    feed = acquire_amfi_nav_feed(session=FakeSession(), now=now)
    assert feed.sha256 == hashlib.sha256(SAMPLE).hexdigest()
    assert feed.retrieved_at == now.isoformat()
    with pytest.raises(FundDataAcquisitionError):
        acquire_amfi_nav_feed(session=FakeSession(), url="https://example.com/feed", now=now)


def test_parser_rejects_duplicate_scheme_codes_and_invalid_nav():
    duplicate = SAMPLE + b"100001|INF000000001||Duplicate|2.0|04-Nov-2026\n"
    with pytest.raises(FundDataAcquisitionError, match="Duplicate"):
        parse_amfi_nav_feed(duplicate)
    invalid = SAMPLE.replace(b"|123.45|", b"|nan|")
    with pytest.raises(FundDataAcquisitionError, match="finite and positive"):
        parse_amfi_nav_feed(invalid)


def test_generated_artifacts_are_unverified_and_do_not_claim_unavailable_metrics():
    feed = AcquiredFeed(
        url="https://www.amfiindia.com/spages/NAVAll.txt",
        retrieved_at="2026-11-05T00:00:00+00:00",
        sha256=hashlib.sha256(SAMPLE).hexdigest(),
        content=SAMPLE,
    )
    artifacts = build_public_fund_artifacts(feed)
    assert artifacts["fund_metrics"]["metrics_scope"] == ["NAV"]
    assert artifacts["fund_metrics"]["status"] == "ACQUIRED_UNVERIFIED"
    assert artifacts["scheme_master"]["records"]["100001"]["identity_status"].startswith("UNRESOLVED")
    assert artifacts["fund_aliases"]["aliases"]["Example Equity Fund - Direct Plan - Growth"] == ["100001"]


def test_refresh_writes_engine_owned_snapshot_and_manifest_last(tmp_path):
    paths = refresh_engine_fund_data(
        EngineRuntimeConfig(data_dir=tmp_path),
        session=FakeSession(),
        now=datetime(2026, 11, 5, tzinfo=timezone.utc),
    )
    assert set(paths) == {"scheme_master", "fund_metrics", "fund_aliases", "manifest"}
    manifest = json.loads(paths["manifest"].read_text())
    assert manifest["promotion_eligible"] is False
    assert manifest["status"] == "ACQUIRED_UNVERIFIED"
    assert all(path.is_file() for path in paths.values())


def test_missing_manifest_is_not_a_client_setup_error(tmp_path):
    manifest = load_engine_manifest(tmp_path)
    assert manifest["status"] == "NOT_ACQUIRED"
    assert manifest["promotion_eligible"] is False
