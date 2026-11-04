import json
import time
from unittest.mock import patch, MagicMock

import pytest

from core import ai_engine
from core.ai_engine import (
    ProviderError,
    _discover_openai_models,
    _read_model_cache,
    _write_model_cache,
    _call_openai_compatible,
)


def test_model_cache_persists_and_validates_zero_pricing_evidence(tmp_path, monkeypatch):
    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr(ai_engine, "MODEL_CACHE_FILE", cache_file)

    key = "test-api-key"
    models = ["model-free-1", "model-free-2"]
    pricing_evidence = {
        "model-free-1": {"input_price": 0.0, "output_price": 0.0, "verified_at": time.time()},
        "model-free-2": {"input_price": 0.0, "output_price": 0.0, "verified_at": time.time()},
    }

    _write_model_cache("Requesty", key, models, pricing_evidence=pricing_evidence, catalogue_digest="digest-123")
    cached = _read_model_cache("Requesty", key)
    assert cached == models

    # If any cached model has non-zero pricing in evidence, cache is invalidated
    tampered_evidence = {
        "model-free-1": {"input_price": 0.001, "output_price": 0.0, "verified_at": time.time()},
        "model-free-2": {"input_price": 0.0, "output_price": 0.0, "verified_at": time.time()},
    }
    _write_model_cache("Requesty", key, models, pricing_evidence=tampered_evidence)
    assert _read_model_cache("Requesty", key) is None


def test_model_cache_rejects_missing_or_malformed_pricing_evidence(tmp_path, monkeypatch):
    cache_file = tmp_path / "model_cache.json"
    monkeypatch.setattr(ai_engine, "MODEL_CACHE_FILE", cache_file)

    key = "test-api-key"
    models = ["model-free-1"]
    # Write old-format cache with no pricing_evidence
    _write_model_cache("Requesty", key, models)
    assert _read_model_cache("Requesty", key) is None


def test_call_blocks_when_model_is_repriced_during_generation(monkeypatch):
    # Discovery returns model-1 as free
    initial_catalogue = {
        "data": [
            {
                "id": "model-1",
                "input_price": 0.0,
                "output_price": 0.0,
                "architecture": {"modality": "text->text"},
            }
        ]
    }
    # Pre-call check simulates price increase to $0.05
    repriced_catalogue = {
        "data": [
            {
                "id": "model-1",
                "input_price": 0.05,
                "output_price": 0.05,
                "architecture": {"modality": "text->text"},
            }
        ]
    }

    monkeypatch.setenv("REQUESTY_API_KEY", "test-key")
    responses = [initial_catalogue, repriced_catalogue]

    def mock_http_json(url, key, provider):
        if responses:
            return responses.pop(0)
        return repriced_catalogue

    monkeypatch.setattr(ai_engine, "_http_json", mock_http_json)
    monkeypatch.setattr(ai_engine, "MODEL_CACHE_FILE", None)

    with pytest.raises(ProviderError, match="no longer verified as zero-priced|no usable discovered models"):
        _call_openai_compatible("Requesty", "https://api.requesty.ai/v1", "Test prompt")


def test_models_with_free_suffix_without_explicit_zero_price_are_excluded(monkeypatch):
    catalogue = {
        "data": [
            {
                "id": "some-model:free",
                "pricing": {"prompt": "0.01", "completion": "0.02"},
                "architecture": {"modality": "text->text"},
            },
            {
                "id": "real-free-model:free",
                "pricing": {"prompt": "0.0", "completion": "0.0"},
                "architecture": {"modality": "text->text"},
            },
        ]
    }

    monkeypatch.setattr(ai_engine, "_http_json", lambda url, key, prov: catalogue)
    monkeypatch.setattr(ai_engine, "MODEL_CACHE_FILE", None)

    discovered = _discover_openai_models("OpenRouter", "https://openrouter.ai/api/v1/models", "test-key")
    assert "real-free-model:free" in discovered
    assert "some-model:free" not in discovered
