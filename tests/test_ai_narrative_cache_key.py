"""
Unit tests for binding AI narrative cache keys to system instruction and policy context.
Addresses Issue #65: Bind narrative cache entries to the full system instruction and policy context.
"""
from __future__ import annotations

import pytest
from core.ai_engine import _cache_key


def test_cache_key_varies_with_system_instruction():
    prompt = "Explain portfolio drift"
    snapshot = "equity=70,debt=30"

    key1 = _cache_key(prompt, data_snapshot=snapshot, system_instruction="Fiduciary adviser persona v1")
    key2 = _cache_key(prompt, data_snapshot=snapshot, system_instruction="Fiduciary adviser persona v2")

    assert key1 != key2, "Different system instructions must produce different cache keys"


def test_cache_key_varies_with_policy_version():
    prompt = "Explain portfolio drift"
    snapshot = "equity=70,debt=30"
    instruction = "Fiduciary adviser persona"

    key_v1 = _cache_key(prompt, data_snapshot=snapshot, system_instruction=instruction, policy_version="v1")
    key_v2 = _cache_key(prompt, data_snapshot=snapshot, system_instruction=instruction, policy_version="v2")

    assert key_v1 != key_v2, "Different policy versions must invalidate older cache keys"


def test_cache_key_is_deterministic_and_sha256_hex():
    prompt = "Test prompt"
    key_a = _cache_key(prompt, data_snapshot="facts", system_instruction="system", policy_version="v1")
    key_b = _cache_key(prompt, data_snapshot="facts", system_instruction="system", policy_version="v1")

    assert key_a == key_b
    assert len(key_a) == 64
    assert int(key_a, 16) > 0

