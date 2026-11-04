from pathlib import Path

import pytest

from core import settings


def test_save_enabled_free_keys_without_returning_secret_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.delenv("REQUESTY_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    status = settings.save_ai_keys({
        "REQUESTY_API_KEY": "requesty-secret",
        "OPENROUTER_API_KEY": "openrouter-secret",
    }, env_file=env_file)

    assert all(status.values())
    contents = env_file.read_text()
    assert "requesty-secret" in contents
    assert "openrouter-secret" in contents
    assert "requesty-secret" not in repr(status)


def test_blank_value_preserves_existing_key_and_clear_removes_key(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.delenv("REQUESTY_API_KEY", raising=False)
    settings.save_ai_keys({"REQUESTY_API_KEY": "keep-me"}, env_file=env_file)

    settings.save_ai_keys({"REQUESTY_API_KEY": "   "}, env_file=env_file)
    assert "keep-me" in env_file.read_text()

    result = settings.save_ai_keys(
        {}, clear=("REQUESTY_API_KEY",), env_file=env_file
    )
    assert result["Requesty.ai"] is False
    assert "keep-me" not in env_file.read_text()


def test_rejects_unknown_keys_and_multiline_values(tmp_path):
    env_file = tmp_path / ".env"
    with pytest.raises(ValueError):
        settings.save_ai_keys({"UNKNOWN_API_KEY": "secret"}, env_file=env_file)
    with pytest.raises(ValueError):
        settings.save_ai_keys(
            {"UNSUPPORTED_PROVIDER_API_KEY": "first-line\nsecond-line"}, env_file=env_file
        )


def test_status_never_exposes_key_values(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-secret")
    result = settings.ai_key_status_from_environment()
    assert result["Requesty.ai"] is True
    assert "private-secret" not in repr(result)
