"""
core/ai_engine.py
Resilient 3-Tier AI Engine & Dynamic Model Discovery.
Ported from reference implementation in 'C:\\Users\\l9999\\Documents\\VSworks\\Mutual Funds':
  1. Provider 1 (PRIMARY): Requesty.ai (Tier 0 zero-cost models, mutex serialized)
  2. Provider 2 (FALLBACK): OpenRouter (Universal free router with headers)
  3. Provider 3 (LAST RESORT): Google Gemini (google.genai SDK)
  4. Dynamic Free Model Discovery with 24-Hour Disk Cache
  5. Anti-Hallucination & Output Format Guardrails
  6. Disk-Based Narrative Response Cache (sha256 keyed)
"""
from __future__ import annotations

import os
import re
import json
import time
import hashlib
import threading
import urllib.request
from pathlib import Path
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Concurrency mutex: Requesty enforces in-flight limit of 1
_requesty_mutex = threading.Lock()

# Directory configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
MODEL_CACHE_FILE = CACHE_DIR / "free_models_cache.json"
NARRATIVE_CACHE_FILE = CACHE_DIR / "narrative_cache.json"

CACHE_TTL_SECONDS = 86400  # 24 hours for model discovery
NARRATIVE_TTL_SECONDS = 90 * 86400  # 90 days for narrative cache

# Verified static fallbacks in priority order
VERIFIED_REQUESTY_FALLBACKS: List[str] = [
    "nvidia/nemotron-3-ultra-550b-a55b",
    "novita/ling-3.1-flash",
]

VERIFIED_OPENROUTER_FALLBACKS: List[str] = [
    "nvidia/nemotron-3.5-lightning:free",
    "minimax/minimax-m3.1-flash:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemini-2.5-flash",
]

VERIFIED_GEMINI_FALLBACKS: List[str] = [
    "gemini-flash-lite-latest",
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]

GUARDRAIL = (
    "Use ONLY the data provided above. If any data point is missing or unclear, "
    "write 'Data not available' instead of guessing. Do not invent any numbers. "
    "Frame every statement as 'The engine indicates...' not 'You should...'."
)

OUTPUT_FORMAT_GUARD = (
    "OUTPUT FORMAT: Respond with ONLY the final text of the requested section. "
    "Do not restate these instructions, do not show your reasoning or analysis "
    "process, do not repeat the payload, and do not add any preamble."
)


# ---------------------------------------------------------------------------
# Dynamic Model Discovery (Requesty & OpenRouter)
# ---------------------------------------------------------------------------

def _read_model_cache(provider: str) -> Optional[List[str]]:
    try:
        if not MODEL_CACHE_FILE.exists():
            return None
        data = json.loads(MODEL_CACHE_FILE.read_text(encoding="utf-8"))
        entry = data.get(provider)
        if isinstance(entry, dict):
            ts = entry.get("timestamp", 0)
            models = entry.get("models", [])
            if time.time() - ts < CACHE_TTL_SECONDS and models:
                return models
    except Exception:
        pass
    return None


def _write_model_cache(provider: str, models: List[str]) -> None:
    try:
        data = {}
        if MODEL_CACHE_FILE.exists():
            try:
                data = json.loads(MODEL_CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data[provider] = {"timestamp": time.time(), "models": models}
        MODEL_CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def discover_requesty_free_models(api_key: str = "", force_refresh: bool = False) -> List[str]:
    """Dynamically discover Tier 0 zero-cost models from Requesty.ai."""
    if not force_refresh:
        cached = _read_model_cache("requesty")
        if cached:
            return cached

    key = api_key or os.getenv("REQUESTY_API_KEY", "")
    if not key:
        return list(VERIFIED_REQUESTY_FALLBACKS)

    discovered: List[str] = []
    try:
        req = urllib.request.Request(
            "https://router.requesty.ai/v1/models",
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "https://fiduciary.engine",
                "X-Title": "Fiduciary Portfolio Engine",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("data", []):
                mid = m.get("id", "")
                inp = m.get("input_price")
                out = m.get("output_price")
                if inp == 0 and out == 0:
                    low = mid.lower()
                    if any(x in low for x in ("safety", "moderation", "guard", "tiny", "content")):
                        continue
                    discovered.append(mid)

        primary = "nvidia/nemotron-3-ultra-550b-a55b"
        if primary in discovered:
            discovered.remove(primary)
        discovered.insert(0, primary)

        if discovered:
            _write_model_cache("requesty", discovered)
            return discovered
    except Exception:
        pass

    return list(VERIFIED_REQUESTY_FALLBACKS)


def discover_openrouter_free_models(api_key: str = "", force_refresh: bool = False) -> List[str]:
    """Dynamically discover active free chat models on OpenRouter."""
    if not force_refresh:
        cached = _read_model_cache("openrouter")
        if cached:
            return cached

    key = api_key or os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        return list(VERIFIED_OPENROUTER_FALLBACKS)

    discovered: List[str] = []
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": "https://fiduciary.engine",
                "X-Title": "Fiduciary Portfolio Engine",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("data", []):
                mid = m.get("id", "")
                pricing = m.get("pricing", {})
                is_free_slug = mid.endswith(":free")
                is_zero = (
                    str(pricing.get("prompt", "")).strip() == "0"
                    and str(pricing.get("completion", "")).strip() == "0"
                )
                if is_free_slug or is_zero:
                    low = mid.lower()
                    if any(x in low for x in ("safety", "moderation", "guard", "tiny", "content", "embed", "whisper", "tts", "flux", "diffusion", "vl", "vision", "preview", "audio")):
                        continue
                    discovered.append(mid)

        # Prioritize lightning and minimax for ultra-fast, high-accuracy completion
        primary_or = "nvidia/nemotron-3.5-lightning:free"
        if primary_or in discovered:
            discovered.remove(primary_or)
        discovered.insert(0, primary_or)

        secondary_or = "minimax/minimax-m3.1-flash:free"
        if secondary_or in discovered:
            discovered.remove(secondary_or)
            discovered.insert(1, secondary_or)

        if discovered:
            _write_model_cache("openrouter", discovered)
            return discovered
    except Exception:
        pass

    return list(VERIFIED_OPENROUTER_FALLBACKS)


# ---------------------------------------------------------------------------
# Disk-Based Narrative Cache
# ---------------------------------------------------------------------------

def _cache_key(prompt: str, data_snapshot: str = "") -> str:
    return hashlib.sha256((prompt + "||" + data_snapshot).encode("utf-8")).hexdigest()


def _get_narrative_cache() -> Dict[str, Any]:
    try:
        if NARRATIVE_CACHE_FILE.exists():
            return json.loads(NARRATIVE_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_narrative_cache(cache: Dict[str, Any]) -> None:
    try:
        NARRATIVE_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Provider Call Implementations
# ---------------------------------------------------------------------------

def _is_rate_limit(err_str: str) -> bool:
    err_upper = err_str.upper()
    return "429" in err_upper or "402" in err_upper or "RATE LIMIT" in err_upper or "QUOTA" in err_upper or "RESOURCE_EXHAUSTED" in err_upper


def _call_requesty(prompt: str, system_prompt: str = "") -> str:
    """Provider 1: Requesty.ai (Free Tier 0 zero-cost models)."""
    key = os.getenv("REQUESTY_API_KEY", "")
    if not key:
        raise RuntimeError("REQUESTY_API_KEY not set")

    from openai import OpenAI
    client = OpenAI(
        base_url="https://router.requesty.ai/v1",
        api_key=key,
        max_retries=0,
        default_headers={"HTTP-Referer": "https://fiduciary.engine", "X-Title": "Fiduciary Portfolio Engine"}
    )
    models = discover_requesty_free_models(api_key=key)
    
    with _requesty_mutex:
        for model in models[:2]:
            try:
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})

                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.0,
                    seed=42,
                    max_tokens=4000,
                    timeout=60
                )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    print(f"  ✅ [Requesty.ai] Success via model: {model}", flush=True)
                    return text
            except Exception as e:
                err = str(e)
                print(f"  [Requesty/{model}] Error: {err[:70]}", flush=True)
                if _is_rate_limit(err):
                    print("  [..] Requesty rate/credit limited. Breaking to fallback provider...", flush=True)
                    break
                continue

    raise RuntimeError("Requesty provider unavailable.")


def _call_openrouter(prompt: str, system_prompt: str = "") -> str:
    """Provider 2: OpenRouter (Universal free router with headers)."""
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")

    from openai import OpenAI
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=key,
        max_retries=0,
        default_headers={"HTTP-Referer": "https://fiduciary.engine", "X-Title": "Fiduciary Portfolio Engine"}
    )
    models = discover_openrouter_free_models(api_key=key)

    for model in models[:3]:
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.0,
                seed=42,
                max_tokens=4000,
                timeout=60
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                print(f"  ✅ [OpenRouter] Success via model: {model}", flush=True)
                return text
        except Exception as e:
            err = str(e)
            print(f"  [OpenRouter/{model}] Error: {err[:70]}", flush=True)
            if _is_rate_limit(err):
                print("  [..] OpenRouter rate/credit limited. Breaking to fallback provider...", flush=True)
                break
            continue

    raise RuntimeError("OpenRouter provider unavailable.")


def _call_gemini(prompt: str, system_prompt: str = "") -> str:
    """Provider 3: Google Gemini (google.genai SDK)."""
    key = os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    from google import genai
    client = genai.Client(api_key=key)
    
    cfg = {"temperature": 0.0, "seed": 42, "max_output_tokens": 8192}
    if system_prompt:
        cfg["system_instruction"] = system_prompt

    for model in VERIFIED_GEMINI_FALLBACKS:
        try:
            resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
            text = (resp.text or "").strip()
            if text:
                print(f"  ✅ [Gemini] Success via model: {model}", flush=True)
                return text
        except Exception as e:
            err = str(e)
            print(f"  [Gemini/{model}] Error: {err[:70]}", flush=True)
            if _is_rate_limit(err):
                print("  [..] Gemini quota/rate limited. Trying next model...", flush=True)
            continue

    raise RuntimeError("Gemini provider unavailable.")


# ---------------------------------------------------------------------------
# Master Fiduciary LLM Dispatcher
# ---------------------------------------------------------------------------

def call_llm(
    prompt: str,
    data_snapshot: str = "",
    system_instruction: str = "",
    use_cache: bool = True,
    append_guardrail: bool = False
) -> str:
    """
    Master 3-Tier AI Caller:
      1. Cache lookup (sha256 of prompt + data snapshot)
      2. Requesty.ai (Tier 0 zero-cost, mutex locked)
      3. OpenRouter (Free models with required headers)
      4. Google Gemini (google.genai fallback)
    """
    full_prompt = prompt
    if append_guardrail:
        full_prompt = f"{prompt}\n\n{GUARDRAIL}\n\n{OUTPUT_FORMAT_GUARD}"

    ckey = _cache_key(full_prompt, data_snapshot)

    # 1. Cache Check
    if use_cache:
        cache = _get_narrative_cache()
        entry = cache.get(ckey)
        if entry and isinstance(entry, dict) and entry.get("text"):
            ts = entry.get("timestamp", 0)
            if time.time() - ts < NARRATIVE_TTL_SECONDS:
                print(f"  ⚡ [Cache Hit] Returning cached narrative ({entry.get('provider', 'cached')})", flush=True)
                return entry["text"]

    # 2. Provider Cascade (Gemini primary for full 8k token depth, OpenRouter/Requesty fallback)
    providers = [
        ("Gemini", _call_gemini),
        ("OpenRouter", _call_openrouter),
        ("Requesty.ai", _call_requesty),
    ]

    last_error = None
    for name, fn in providers:
        try:
            print(f"  [..] Calling {name}...", flush=True)
            result = fn(full_prompt, system_prompt=system_instruction)
            if result:
                # Update Cache
                if use_cache:
                    cache = _get_narrative_cache()
                    cache[ckey] = {
                        "text": result,
                        "provider": name,
                        "timestamp": time.time()
                    }
                    _save_narrative_cache(cache)
                return result
        except Exception as e:
            last_error = e
            print(f"  [!!] {name} failed: {str(e)[:70]}", flush=True)
            continue

    raise RuntimeError(f"All 3 AI providers failed! Last error: {last_error}")
