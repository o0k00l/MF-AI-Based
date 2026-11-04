import pytest

from core import ai_engine


def test_external_ai_is_blocked_without_explicit_per_request_consent(monkeypatch):
    called = []
    monkeypatch.setattr(ai_engine, "_call_openrouter", lambda *a, **k: called.append("openrouter") or "unsafe")
    monkeypatch.setattr(ai_engine, "_call_requesty", lambda *a, **k: called.append("requesty") or "unsafe")
    monkeypatch.setenv("GEMINI_API_KEY", "configured-but-prohibited")

    with pytest.raises(ai_engine.ProviderError, match="explicit investor consent"):
        ai_engine.call_llm("client financial details", use_cache=True)

    assert called == []


def test_explicit_consent_allows_only_free_provider_and_never_persists_narrative(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_engine, "MODEL_CACHE_FILE", None)
    monkeypatch.setattr(ai_engine, "_call_openrouter", lambda *a, **k: "approved narrative")
    monkeypatch.setattr(ai_engine, "_call_requesty", lambda *a, **k: pytest.fail("fallback should not run"))
    monkeypatch.setattr(ai_engine, "NARRATIVE_CACHE_FILE", tmp_path / "narrative.json")

    result = ai_engine.call_llm(
        "minimized and consented portfolio facts",
        use_cache=True,
        external_processing_consent=True,
    )

    assert result == "approved narrative"
    assert not (tmp_path / "narrative.json").exists()


def test_model_catalogue_cache_is_disabled_without_external_cache_directory(monkeypatch):
    monkeypatch.delenv("MF_AI_CACHE_DIR", raising=False)
    assert ai_engine._external_model_cache_file() is None


def test_model_catalogue_cache_rejects_repository_local_directory(monkeypatch):
    monkeypatch.setenv("MF_AI_CACHE_DIR", str(ai_engine.PROJECT_ROOT / "cache"))
    assert ai_engine._external_model_cache_file() is None


def test_gemini_remains_disabled_even_when_a_key_is_present(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "configured-but-prohibited")
    with pytest.raises(ai_engine.ProviderError, match="disabled by FREE_ONLY"):
        ai_engine._call_gemini("prompt")
