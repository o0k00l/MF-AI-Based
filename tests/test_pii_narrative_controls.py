import pytest
from core.ai_engine import NARRATIVE_CACHE_FILE, _get_narrative_cache, _save_narrative_cache
from core.prompt_advisor import _call_llm_with_retry


def test_narrative_cache_is_disabled_and_no_file_is_written():
    assert NARRATIVE_CACHE_FILE is None
    assert _get_narrative_cache() == {}
    # Saving to cache does nothing and writes nothing to disk
    _save_narrative_cache({"key": "sensitive response"})
    assert _get_narrative_cache() == {}


def test_ai_call_fails_without_explicit_external_consent():
    from core.ai_engine import ProviderError

    with pytest.raises(ProviderError, match="External AI processing is blocked"):
        _call_llm_with_retry("test prompt", external_processing_consent=False)
