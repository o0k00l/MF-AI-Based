"""Provider adapters with live model discovery and fail-closed diagnostics.

Model IDs are never invented or injected when a provider catalogue is unavailable.
The module is for qualitative narrative assistance only; it does not participate in
SIP eligibility, evidence validation, allocation, or release-gate decisions.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

_requesty_mutex = threading.Lock()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MODEL_CACHE_FILE = CACHE_DIR / "free_models_cache.json"
NARRATIVE_CACHE_FILE = CACHE_DIR / "narrative_cache.json"
CACHE_TTL_SECONDS = 3600
NARRATIVE_TTL_SECONDS = 90 * 86400

REQUESTY_BASE_URL = "https://router.requesty.ai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
REQUESTY_MODELS_URL = REQUESTY_BASE_URL + "/models"
OPENROUTER_MODELS_URL = OPENROUTER_BASE_URL + "/models"

GUARDRAIL = (
    "Use ONLY the data provided above. If any data point is missing or unclear, "
    "write 'Data not available' instead of guessing. Do not invent any numbers. "
    "Frame every statement as 'The engine indicates...' not 'You should...'."
)
OUTPUT_FORMAT_GUARD = (
    "OUTPUT FORMAT: Respond with ONLY the final text of the requested section. "
    "Do not restate these instructions, show reasoning, repeat the payload, or add a preamble."
)


class ProviderError(RuntimeError):
    """Safe provider failure metadata; never stores raw response bodies or credentials."""

    def __init__(self, provider: str, message: str, *, status_code: int | None = None,
                 code: str | None = None, model: str | None = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.code = code
        self.model = model


def _key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _read_model_cache(provider: str, key: str) -> list[str] | None:
    try:
        data = json.loads(MODEL_CACHE_FILE.read_text(encoding="utf-8"))
        entry = data.get(provider, {})
        if (entry.get("key_fingerprint") == _key_fingerprint(key)
                and time.time() - float(entry.get("timestamp", 0)) < CACHE_TTL_SECONDS):
            models = entry.get("models")
            if isinstance(models, list) and models and all(isinstance(x, str) for x in models):
                return models
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def _write_model_cache(provider: str, key: str, models: list[str]) -> None:
    try:
        try:
            data = json.loads(MODEL_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data[provider] = {
            "timestamp": time.time(),
            "key_fingerprint": _key_fingerprint(key),
            "models": models,
        }
        temp_path = MODEL_CACHE_FILE.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_path.replace(MODEL_CACHE_FILE)
    except (OSError, TypeError, ValueError):
        # Cache failure must not prevent a live provider request.
        pass


def _http_json(url: str, key: str, provider: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "https://fiduciary.engine",
            "X-Title": "Fiduciary Portfolio Engine",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProviderError(
            provider, f"{provider} model discovery failed (HTTP {exc.code}).",
            status_code=exc.code,
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ProviderError(provider, f"{provider} model discovery network failure ({type(exc).__name__}).") from None
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError) as exc:
        raise ProviderError(provider, f"{provider} returned an invalid model catalogue ({type(exc).__name__}).") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ProviderError(provider, f"{provider} returned an unexpected model catalogue shape.")
    return payload


def _is_zero_price(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


def _discover_openai_models(provider: str, url: str, key: str) -> list[str]:
    cached = _read_model_cache(provider, key)
    if cached:
        return cached
    payload = _http_json(url, key, provider)
    discovered: list[str] = []
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        if provider == "Requesty":
            # Requesty exposes per-token prices in its model catalogue. Unknown
            # pricing is not treated as free.
            if not (_is_zero_price(item.get("input_price"))
                    and _is_zero_price(item.get("output_price"))):
                continue
        else:
            pricing = item.get("pricing") or {}
            if not isinstance(pricing, dict):
                continue
            is_free_slug = model_id.endswith(":free")
            is_zero_price = (
                _is_zero_price(pricing.get("prompt"))
                and _is_zero_price(pricing.get("completion"))
            )
            if not (is_free_slug or is_zero_price):
                continue
        # Only text-capable chat models are useful for this adapter.
        architecture = item.get("architecture") or {}
        modality = architecture.get("modality") if isinstance(architecture, dict) else None
        if modality and "text" not in str(modality).lower():
            continue
        if any(term in model_id.lower() for term in (
            "embedding", "embed", "whisper", "tts", "moderation", "image", "audio"
        )):
            continue
        discovered.append(model_id)
    discovered = list(dict.fromkeys(discovered))
    if not discovered:
        raise ProviderError(provider, f"{provider} returned no eligible free text-generation models.")
    _write_model_cache(provider, key, discovered)
    return discovered


def discover_requesty_free_models(api_key: str = "", force_refresh: bool = False) -> list[str]:
    """Return only free model IDs actually returned by the authenticated catalogue."""
    key = api_key or os.getenv("REQUESTY_API_KEY", "")
    if not key:
        raise ProviderError("Requesty", "REQUESTY_API_KEY is not configured.")
    if force_refresh:
        try:
            data = json.loads(MODEL_CACHE_FILE.read_text(encoding="utf-8"))
            data.pop("Requesty", None)
            MODEL_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError):
            pass
    return _discover_openai_models("Requesty", REQUESTY_MODELS_URL, key)


def discover_openrouter_free_models(api_key: str = "", force_refresh: bool = False) -> list[str]:
    """Return only free model IDs actually returned by the authenticated catalogue."""
    key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise ProviderError("OpenRouter", "OPENROUTER_API_KEY is not configured.")
    if force_refresh:
        try:
            data = json.loads(MODEL_CACHE_FILE.read_text(encoding="utf-8"))
            data.pop("OpenRouter", None)
            MODEL_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except (OSError, ValueError, TypeError):
            pass
    return _discover_openai_models("OpenRouter", OPENROUTER_MODELS_URL, key)


def _cache_key(prompt: str, data_snapshot: str = "") -> str:
    return hashlib.sha256((prompt + "||" + data_snapshot).encode("utf-8")).hexdigest()


def _get_narrative_cache() -> dict[str, Any]:
    try:
        value = json.loads(NARRATIVE_CACHE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_narrative_cache(cache: dict[str, Any]) -> None:
    try:
        temp_path = NARRATIVE_CACHE_FILE.with_suffix(".tmp")
        temp_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        temp_path.replace(NARRATIVE_CACHE_FILE)
    except (OSError, TypeError, ValueError):
        pass


def _is_rate_limit(err_str: str) -> bool:
    upper = err_str.upper()
    return any(term in upper for term in ("429", "402", "RATE LIMIT", "QUOTA", "RESOURCE_EXHAUSTED"))


def _openai_exception(provider: str, exc: Exception, model: str) -> ProviderError:
    status = getattr(exc, "status_code", None)
    code = getattr(exc, "code", None)
    if code is not None:
        code = str(code)[:80]
    return ProviderError(
        provider, f"{provider} request failed ({type(exc).__name__}).",
        status_code=status if isinstance(status, int) else None,
        code=code, model=model,
    )


def _call_openai_compatible(provider: str, base_url: str, prompt: str,
                            system_prompt: str = "") -> str:
    env_name = "REQUESTY_API_KEY" if provider == "Requesty" else "OPENROUTER_API_KEY"
    key = os.getenv(env_name, "")
    if not key:
        raise ProviderError(provider, f"{env_name} is not configured.")
    models = (discover_requesty_free_models(key) if provider == "Requesty"
              else discover_openrouter_free_models(key))
    from openai import OpenAI
    client = OpenAI(base_url=base_url, api_key=key, max_retries=0, timeout=60,
                    default_headers={"HTTP-Referer": "https://fiduciary.engine",
                                     "X-Title": "Fiduciary Portfolio Engine"})
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    last_error: ProviderError | None = None
    lock = _requesty_mutex if provider == "Requesty" else _NullLock()
    with lock:
        for model in models[:5]:
            try:
                # Intentionally send only the portable required fields. Do not
                # assume temperature, seed, max_tokens, or other optional knobs.
                response = client.chat.completions.create(model=model, messages=messages)
                result = (response.choices[0].message.content or "").strip()
                if result:
                    return result
                last_error = ProviderError(provider, f"{provider} returned an empty response.", model=model)
            except Exception as exc:
                failure = _openai_exception(provider, exc, model)
                if failure.status_code in (401, 403):
                    raise failure from None
                last_error = failure
                continue
    raise last_error or ProviderError(provider, f"{provider} had no usable discovered models.")


class _NullLock:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


def _call_requesty(prompt: str, system_prompt: str = "") -> str:
    return _call_openai_compatible("Requesty", REQUESTY_BASE_URL, prompt, system_prompt)


def _call_openrouter(prompt: str, system_prompt: str = "") -> str:
    return _call_openai_compatible("OpenRouter", OPENROUTER_BASE_URL, prompt, system_prompt)


def _call_gemini(prompt: str, system_prompt: str = "") -> str:
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise ProviderError("Gemini", "GEMINI_API_KEY is not configured.")
    from google import genai
    client = genai.Client(api_key=key)
    try:
        models = []
        for item in client.models.list():
            name = getattr(item, "name", None)
            actions = getattr(item, "supported_actions", None)
            if not isinstance(name, str) or not name:
                continue
            if actions and "generateContent" not in actions:
                continue
            model_id = name.removeprefix("models/")
            if model_id.startswith("gemini-") and "embedding" not in model_id.lower():
                models.append(model_id)
        models = list(dict.fromkeys(models))
    except Exception as exc:
        status = getattr(exc, "code", None)
        raise ProviderError("Gemini", f"Gemini model discovery failed ({type(exc).__name__}).",
                            status_code=status if isinstance(status, int) else None) from None
    if not models:
        raise ProviderError("Gemini", "Gemini returned no generateContent-capable models.")
    config = {"system_instruction": system_prompt} if system_prompt else None
    last_error: ProviderError | None = None
    for model in models[:5]:
        try:
            response = client.models.generate_content(
                model=model, contents=prompt, config=config
            )
            result = (response.text or "").strip()
            if result:
                return result
            last_error = ProviderError("Gemini", "Gemini returned an empty response.", model=model)
        except Exception as exc:
            status = getattr(exc, "code", None)
            last_error = ProviderError(
                "Gemini", f"Gemini generation failed ({type(exc).__name__}).",
                status_code=status if isinstance(status, int) else None,
                code=str(getattr(exc, "status", ""))[:80] or None,
                model=model,
            )
            if last_error.status_code in (401, 403):
                raise last_error from None
            continue
    raise last_error or ProviderError("Gemini", "Gemini had no usable discovered models.")


def call_llm(prompt: str, data_snapshot: str = "", system_instruction: str = "",
             use_cache: bool = True, append_guardrail: bool = False) -> str:
    """Generate a narrative only; deterministic SIP gates remain authoritative."""
    full_prompt = prompt
    if append_guardrail:
        full_prompt = f"{prompt}\n\n{GUARDRAIL}\n\n{OUTPUT_FORMAT_GUARD}"
    cache_key = _cache_key(full_prompt, data_snapshot)
    if use_cache:
        entry = _get_narrative_cache().get(cache_key)
        if isinstance(entry, dict) and entry.get("text"):
            if time.time() - float(entry.get("timestamp", 0)) < NARRATIVE_TTL_SECONDS:
                return str(entry["text"])

    providers = (
        ("Gemini", _call_gemini),
        ("OpenRouter", _call_openrouter),
        ("Requesty", _call_requesty),
    )
    errors = []
    for name, function in providers:
        try:
            result = function(full_prompt, system_prompt=system_instruction)
            if result:
                if use_cache:
                    cache = _get_narrative_cache()
                    cache[cache_key] = {"text": result, "provider": name, "timestamp": time.time()}
                    _save_narrative_cache(cache)
                return result
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}")
    raise RuntimeError("All configured AI providers failed: " + "; ".join(errors))
