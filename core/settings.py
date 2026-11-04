"""Local AI-provider secret configuration.

Secrets are written only to the ignored project .env file. They are never
returned to callers, logged, or included in status output.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv, set_key, unset_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"

AI_PROVIDER_KEYS = {
    "Requesty.ai": "REQUESTY_API_KEY",
    "OpenRouter": "OPENROUTER_API_KEY",
}


def load_ai_settings(env_file: Path | None = None) -> None:
    """Load local .env without overriding deployment-provided environment."""
    load_dotenv(dotenv_path=env_file or DEFAULT_ENV_FILE, override=False)


def ai_key_status() -> dict[str, bool]:
    """Return configured/not-configured flags only; never return secret values."""
    load_ai_settings()
    return {provider: bool(os.getenv(env_name, "").strip())
            for provider, env_name in AI_PROVIDER_KEYS.items()}


def save_ai_keys(
    values: Mapping[str, str],
    *,
    clear: tuple[str, ...] = (),
    env_file: Path | None = None,
) -> dict[str, bool]:
    """Persist supplied keys to the ignored local .env and update this process.

    Blank inputs are ignored, so a user can update one provider without
    overwriting the other two. Explicit clear names remove selected keys.
    """
    target = Path(env_file or DEFAULT_ENV_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch(mode=0o600, exist_ok=True)

    allowed = set(AI_PROVIDER_KEYS.values())
    unknown = set(values) - allowed
    if unknown or set(clear) - allowed:
        raise ValueError("Unsupported AI provider setting.")
    if set(values) & set(clear):
        raise ValueError("A key cannot be updated and cleared in the same operation.")

    for name, raw_value in values.items():
        if not isinstance(raw_value, str):
            raise TypeError("API keys must be text.")
        value = raw_value.strip()
        if not value:
            continue
        if "\n" in value or "\r" in value:
            raise ValueError("API keys must be a single line.")
        set_key(str(target), name, value, quote_mode="always")
        os.environ[name] = value

    for name in clear:
        unset_key(str(target), name)
        os.environ.pop(name, None)

    try:
        target.chmod(0o600)
    except OSError:
        # Windows does not support POSIX permission semantics.
        pass

    return ai_key_status_from_environment()


def ai_key_status_from_environment() -> dict[str, bool]:
    """Return key-presence flags without reading or exposing key contents."""
    return {provider: bool(os.getenv(env_name, "").strip())
            for provider, env_name in AI_PROVIDER_KEYS.items()}
