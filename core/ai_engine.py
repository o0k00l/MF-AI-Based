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
CACHE_TTL_SECONDS = 3600


def _external_model_cache_file() -> Path | None:
    """Optional model catalogue cache; never write inside the Git checkout."""
    configured = os.getenv("MF_AI_CACHE_DIR", "").strip()
    if not configured:
        return None
    root = Path(configured).expanduser().resolve()
    try:
        root.relative_to(PROJECT_ROOT)
    except ValueError:
        pass
    else:
        return None
    try:
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve(strict=True)
        root.relative_to(PROJECT_ROOT)
    except (OSError, ValueError):
        return None
    return root / "free_models_cache.json"


MODEL_CACHE_FILE = _external_model_cache_file()
# Investor-specific narrative caching is disabled; no plaintext report cache.
NARRATIVE_CACHE_FILE = None

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
    if MODEL_CACHE_FILE is None:
        return None
    try:
        data = json.loads(MODEL_CACHE_FILE.read_text(encoding="utf-8"))
        entry = data.get(provider, {})
        if (entry.get("key_fingerprint") == _key_fingerprint(key)
                and time.time() - float(entry.get("timestamp", 0)) < CACHE_TTL_SECONDS):
            models = entry.get("models")
            pricing_evidence = entry.get("pricing_evidence")
            if (isinstance(models, list) and models
                    and isinstance(pricing_evidence, dict)
                    and all(isinstance(x, str) and x in pricing_evidence for x in models)):
                for m in models:
                    ev = pricing_evidence[m]
                    if not isinstance(ev, dict):
                        return None
                    if provider == "Requesty":
                        if not (_is_zero_price(ev.get("input_price")) and _is_zero_price(ev.get("output_price"))):
                            return None
                    else:
                        if not (_is_zero_price(ev.get("prompt")) and _is_zero_price(ev.get("completion"))):
                            return None
                return models
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def _write_model_cache(
    provider: str,
    key: str,
    models: list[str],
    pricing_evidence: dict[str, Any] | None = None,
    catalogue_digest: str | None = None,
) -> None:
    if MODEL_CACHE_FILE is None:
        return
    try:
        try:
            data = json.loads(MODEL_CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data[provider] = {
            "timestamp": time.time(),
            "key_fingerprint": _key_fingerprint(key),
            "models": models,
            "pricing_evidence": pricing_evidence or {},
            "catalogue_digest": catalogue_digest,
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
    # Boolean false is not a valid price declaration; never coerce it to 0.0.
    if isinstance(value, bool) or value is None:
        return False
    try:
        return float(value) == 0.0
    except (TypeError, ValueError, OverflowError):
        return False


def _discover_openai_models(
    provider: str, url: str, key: str, *, force_refresh: bool = False
) -> list[str]:
    # A forced refresh must bypass the cache even when cache-file deletion or
    # replacement is unavailable (read-only filesystem, transient I/O error).
    cached = None if force_refresh else _read_model_cache(provider, key)
    if cached:
        return cached
    payload = _http_json(url, key, provider)
    discovered: list[str] = []
    pricing_evidence: dict[str, Any] = {}
    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        if provider == "Requesty":
            # Requesty exposes per-token prices in its model catalogue. Unknown
            # pricing is not treated as free.
            in_p = item.get("input_price")
            out_p = item.get("output_price")
            if not (_is_zero_price(in_p) and _is_zero_price(out_p)):
                continue
            pricing_evidence[model_id] = {
                "input_price": float(in_p),
                "output_price": float(out_p),
                "verified_at": time.time(),
            }
        else:
            pricing = item.get("pricing") or {}
            if not isinstance(pricing, dict):
                continue
            # A `:free` suffix is a catalogue label, not sufficient
            # billing evidence. Require explicit zero prompt AND completion
            # prices for every model, including models carrying that suffix.
            prompt_p = pricing.get("prompt")
            comp_p = pricing.get("completion")
            is_zero_price = (
                _is_zero_price(prompt_p)
                and _is_zero_price(comp_p)
            )
            if not is_zero_price:
                continue
            pricing_evidence[model_id] = {
                "prompt": float(prompt_p),
                "completion": float(comp_p),
                "verified_at": time.time(),
            }
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
    cat_digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    _write_model_cache(provider, key, discovered, pricing_evidence=pricing_evidence, catalogue_digest=cat_digest)
    return discovered


def discover_requesty_free_models(api_key: str = "", force_refresh: bool = False) -> list[str]:
    """Return only free model IDs actually returned by the authenticated catalogue."""
    key = api_key or os.getenv("REQUESTY_API_KEY", "")
    if not key:
        raise ProviderError("Requesty", "REQUESTY_API_KEY is not configured.")
    return _discover_openai_models(
        "Requesty", REQUESTY_MODELS_URL, key, force_refresh=force_refresh
    )


def discover_openrouter_free_models(api_key: str = "", force_refresh: bool = False) -> list[str]:
    """Return only free model IDs actually returned by the authenticated catalogue."""
    key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise ProviderError("OpenRouter", "OPENROUTER_API_KEY is not configured.")
    return _discover_openai_models(
        "OpenRouter", OPENROUTER_MODELS_URL, key, force_refresh=force_refresh
    )


def _cache_key(
    prompt: str,
    data_snapshot: str = "",
    system_instruction: str = "",
    policy_version: str = "v1",
) -> str:
    payload = f"{policy_version}||{system_instruction}||{prompt}||{data_snapshot}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _get_narrative_cache() -> dict[str, Any]:
    """Legacy compatibility: investor-specific narrative cache is disabled."""
    return {}


def _save_narrative_cache(cache: dict[str, Any]) -> None:
    """Legacy compatibility: investor-specific narrative cache is disabled."""
    return


def _is_rate_limit(err_str: str) -> bool:
    upper = err_str.upper()
    return any(term in upper for term in ("429", "402", "RATE LIMIT", "QUOTA", "RESOURCE_EXHAUSTED"))


def _should_try_next_model(error: ProviderError) -> bool:
    """Retry another model only when failure is plausibly model-specific/transient.

    Authentication, permission, quota and malformed-request failures are
    provider/account/request scoped; trying more models would waste quota and
    obscure the original failure.
    """
    status = error.status_code
    if status in (404, 408, 409):
        return True
    if isinstance(status, int) and status >= 500:
        return True
    message = str(error).lower()
    return any(token in message for token in (
        "apiconnectionerror", "api connection", "timeout", "timed out",
        "connectionerror", "network",
    ))


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


def _get_provider_key(env_name: str) -> str:
    key = os.getenv(env_name, "").strip()
    if key:
        return key
    try:
        import streamlit as st
        if hasattr(st, "secrets") and env_name in st.secrets:
            return str(st.secrets[env_name]).strip()
    except Exception:
        pass
    return ""


def _call_openai_compatible(provider: str, base_url: str, prompt: str,
                            system_prompt: str = "") -> str:
    env_name = "REQUESTY_API_KEY" if provider == "Requesty" else "OPENROUTER_API_KEY"
    key = _get_provider_key(env_name)
    if not key:
        raise ProviderError(provider, f"{env_name} is not configured.")
    models = (discover_requesty_free_models(key) if provider == "Requesty"
              else discover_openrouter_free_models(key))
    from openai import OpenAI
    timeout_sec = int(os.getenv("AI_TIMEOUT_SECONDS", "10"))
    client = OpenAI(base_url=base_url, api_key=key, max_retries=0, timeout=timeout_sec,
                    default_headers={"HTTP-Referer": "https://fiduciary.engine",
                                     "X-Title": "Fiduciary Portfolio Engine"})
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    last_error: ProviderError | None = None
    lock = _requesty_mutex if provider == "Requesty" else _NullLock()
    with lock:
        currently_free = None
        for model in models[:2]:
            try:
                # Re-fetch the live catalogue immediately before generation.
                # Cached IDs alone cannot prove that a model is still free.
                if currently_free is None:
                    currently_free = (
                        discover_requesty_free_models(key, force_refresh=True)
                        if provider == "Requesty"
                        else discover_openrouter_free_models(key, force_refresh=True)
                    )
                if model not in currently_free:
                    last_error = ProviderError(
                        provider,
                        f"{provider} model is no longer verified as zero-priced; generation blocked.",
                        model=model,
                    )
                    continue
                # Intentionally send only the portable required fields. Do not
                # assume temperature, seed, max_tokens, or other optional knobs.
                response = client.chat.completions.create(model=model, messages=messages)
                result = (response.choices[0].message.content or "").strip()
                if result:
                    return result
                last_error = ProviderError(provider, f"{provider} returned an empty response.", model=model)
            except Exception as exc:
                failure = _openai_exception(provider, exc, model)
                last_error = failure
                if not _should_try_next_model(failure):
                    raise failure from None
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


def _exception_http_status(exc: Exception) -> int | None:
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    return None


def _safe_exception_code(exc: Exception) -> str | None:
    """Return a bounded symbolic provider code, never the raw error message."""
    for attribute in ("status", "reason", "code"):
        value = getattr(exc, attribute, None)
        if value is None or isinstance(value, int):
            continue
        candidate = str(value).strip()
        if candidate and len(candidate) <= 80 and all(
            char.isalnum() or char in "_-." for char in candidate
        ):
            return candidate
    return None


def _call_gemini(prompt: str, system_prompt: str = "") -> str:
    """Gemini is prohibited by the binding free-only policy."""
    raise ProviderError(
        "Gemini",
        "Gemini is disabled by FREE_ONLY policy: zero-cost API pricing cannot be verified.",
    )


def call_llm(
    prompt: str,
    data_snapshot: str = "",
    system_instruction: str = "",
    use_cache: bool = False,
    append_guardrail: bool = False,
    external_processing_consent: bool = False,
) -> str:
    """Generate qualitative narrative only after explicit per-request consent.

    The legacy use_cache parameter is retained for compatibility but ignored:
    investor-specific narratives are never persisted in a shared plaintext cache.
    """
    if external_processing_consent is not True:
        raise ProviderError(
            "Privacy",
            "External AI processing is blocked: explicit investor consent is required for this request.",
        )
    full_prompt = prompt
    if append_guardrail:
        full_prompt = f"{prompt}\n\n{GUARDRAIL}\n\n{OUTPUT_FORMAT_GUARD}"
    # Deliberately never read/write investor-specific narrative cache.
    _ = _cache_key(full_prompt, data_snapshot, system_instruction=system_instruction)

    # FREE_ONLY: only adapters with explicit zero-cost catalogue evidence are eligible.
    providers = (
        ("OpenRouter", _call_openrouter),
        ("Requesty", _call_requesty),
    )
    errors = []
    for name, function in providers:
        try:
            result = function(full_prompt, system_prompt=system_instruction)
            if result:
                return result
        except Exception as exc:
            errors.append(f"{name}: {type(exc).__name__}")
    raise ProviderError(
        "FreeProviders",
        "All eligible free narrative providers are unavailable: " + "; ".join(errors),
    )
