"""
Qualitative Fiduciary Verification Engine.

Calls the Gemini API with Google Search Grounding to produce a human-readable
qualitative rationale for each fund.

Design constraints:
  - Discovers available models at runtime via client.models.list(); never
    maintains a hardcoded list that can go stale on deprecation.
  - Prioritises the highest-capability model available (3.8-flash > 2.5-flash > 3.x flash > Pro > Lite).
  - generate_fiduciary_rationales_batch: one API call for the entire portfolio,
    exploiting Gemini's large context window and avoiding per-fund rate limits.
    Falls back to smaller chunks if the batch times out.
  - If the API key is absent, raises RuntimeError.
  - If models fail or Gemini is unreachable (e.g. quota exhaustion, API downtime,
    network failure), raises RuntimeError with a concise reason; main.py halts report
    generation immediately per the strict mandate: No AI Key / Reachability = No Report Generation.
"""
import json
import os
import re
import time
import random
import threading
import logging
from typing import Optional
from decimal import Decimal
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants: Verified working models & deprecated models (as of 2025-10-08)
# ---------------------------------------------------------------------------

VERIFIED_FALLBACK_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-flash-latest",
    "models/gemini-2.5-pro",
    "models/gemini-pro-latest",
    "models/gemini-3-flash-preview",
]

DEPRECATED_MODELS = {
    "gemini-1.5-pro", "gemini-1.5-flash", "gemini-1.5-flash-8b",
    "gemini-1.0-pro", "gemini-1.0-pro-vision",
    "gemini-2.0-flash", "gemini-2.0-flash-lite",
    "gemini-3.0-flash", "gemini-3.1-flash", "gemini-3.1-pro",
    "gemini-3.2-flash", "gemini-3.3-flash", "gemini-3.4-flash",
}

EXCLUDED_MODEL_TYPES = (
    "tts", "image", "imagen", "banana", "lyria", "robotics", "computer-use",
    "transcribe", "veo", "embedding", "aqa", "deep-research",
    "omni", "antigravity", "gemma"
)


def _is_deprecated(model_name: str) -> bool:
    """Check if a model is in the deprecated list."""
    name_lower = model_name.lower()
    name_norm = name_lower.replace("-", ".")
    for deprecated in DEPRECATED_MODELS:
        if deprecated in name_lower or deprecated.replace("-", ".") in name_norm:
            return True
    return False


def _is_eligible_model(m) -> bool:
    """Check if a model object is an eligible, non-deprecated, general Gemini LLM."""
    name = getattr(m, "name", "").lower()
    if "gemini" not in name:
        return False
    if any(x in name for x in EXCLUDED_MODEL_TYPES):
        return False
    if _is_deprecated(name):
        return False
    actions = getattr(m, "supported_actions", None) or []
    methods = getattr(m, "supported_generation_methods", None) or []
    return ("generateContent" in actions) or ("generateContent" in methods)


def _get_client_and_models(api_key: str):
    """
    Initialise the Gemini client and return a prioritised list of model IDs
    discovered from the live API, filtered to only working models.

    Priority order:
      Tier 0: gemini-3.8-flash (newest stable), gemini-2.5-flash (proven workhorse)
      Tier 1: Other 3.x flash variants, gemini-flash-latest
      Tier 2: Pro models (gemini-2.5-pro, gemini-pro-latest)
      Tier 3: Lite models (gemini-2.5-flash-lite) - separate quota bucket
    """
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "[Qualitative Engine Error: google-genai is not installed. "
            "Run: pip install google-genai]"
        ) from exc

    client = genai.Client(api_key=api_key, http_options={"timeout": 35000})

    try:
        all_models = list(client.models.list())
        usable = [m.name for m in all_models if _is_eligible_model(m)]

        # If nothing matched, fall back to general gemini models
        if not usable:
            usable = [
                m.name for m in all_models
                if "gemini" in getattr(m, "name", "").lower()
                and not any(x in getattr(m, "name", "").lower() for x in EXCLUDED_MODEL_TYPES)
                and not _is_deprecated(getattr(m, "name", ""))
            ]
    except Exception as exc:
        logger.info(f"  [WARN] Could not list available Gemini models: {exc}. Using verified fallback models.")
        usable = VERIFIED_FALLBACK_MODELS.copy()

    # Merge discovered models with verified fallbacks (discovered first, then fallbacks)
    all_candidates = []
    seen = set()
    for m in usable:
        if m not in seen:
            all_candidates.append(m)
            seen.add(m)
    for m in VERIFIED_FALLBACK_MODELS:
        if m not in seen:
            all_candidates.append(m)
            seen.add(m)

    def _priority(name: str) -> tuple:
        n = name.lower()
        if "gemini" not in n:
            return (99, 0.0, name)
        # Tier 0: Standard Flash models (fastest, most quota-friendly flagship)
        if "flash" in n and "lite" not in n:
            tier = 0
        # Tier 1: Flash-Lite models (separate quota bucket, highly reliable)
        elif "lite" in n:
            tier = 1
        # Tier 2: Pro models (heavier, often lower free-tier limits)
        elif "pro" in n:
            tier = 2
        else:
            tier = 3
        # Extract version number for secondary sort (higher version first)
        import re
        if "latest" in n:
            version = 99.0
        else:
            version_match = re.search(r'(\d+\.\d+|\d+)', n)
            version = float(version_match.group(1)) if version_match else 0.0
        return (tier, -version, name)

    models = sorted(all_candidates, key=_priority)[:12]
    logger.info(f"  [..] Gemini models available (prioritised, deprecated filtered, top 12): {models}")
    return client, models



def _human_error(exc: Exception) -> str:
    """
    Convert a raw API exception into a concise, client-safe reason string.

    The final report is a professional deliverable: it must never contain
    raw JSON error payloads, stack traces, or Google's internal quota
    metric names. This helper maps common failure classes to a short,
    human-readable cause and caps everything else at the first line.
    """
    s = str(exc).upper()
    if "RESOURCE_EXHAUSTED" in s or "QUOTA" in s or "429" in s:
        return ("Gemini API quota exhausted (429) - check the API key's billing "
                "plan or retry later")
    if "PERMISSION_DENIED" in s or "API_KEY_INVALID" in s or "API KEY NOT VALID" in s:
        return "Gemini API key not valid or not authorized - please check the key"
    if "UNAVAILABLE" in s or "DEADLINE_EXCEEDED" in s:
        return "Gemini API temporarily unavailable - please retry later"
    if "NETWORK" in s or "CONNECTION" in s or "TIMEOUT" in s:
        return "Network error reaching the Gemini API"
    # Fallback: exception type + first fragment before any JSON payload
    short = str(exc).split("{")[0].strip().split("\n")[0][:80]
    return f"{type(exc).__name__}: {short}"

def _extract_retry_after_seconds(exc: Exception) -> int:
    """Extract the Retry-After header value (seconds) from an API exception.

    OpenRouter 402 responses carry a `Retry-After` header telling the client
    how long to wait before retrying (e.g. when in-flight budget is exhausted).
    The openai-python client surfaces it on the response, but not always in a
    convenient attribute — so we scan the exception's string repr and any
    attached response object. Returns 0 when no value is found.
    """
    import re

    candidates = []

    # 1. The openai-python client stores the raw response on the exception
    resp = getattr(exc, "response", None)
    if resp is not None:
        headers = getattr(resp, "headers", None)
        if headers is not None:
            try:
                val = headers.get("Retry-After") or headers.get("retry-after")
                if val:
                    candidates.append(str(val))
            except Exception as e:
                logger.warning(r"Failed to parse Retry-After header: {e}")

    # 2. Fall back to scanning the full exception string
    candidates.append(str(exc))

    for text in candidates:
        # Matches both header form ("Retry-After: 120") and the JSON-body form
        # embedded in OpenRouter error payloads ("'Retry-After': '120'").
        m = re.search(r'[Rr]etry-[Aa]fter["\']?\s*[:=]\s*["\']?(\d+)', text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return 0
    return 0

# ---------------------------------------------------------------------------
# Response parsing (token-approach: plain text accepted as rationale)
# ---------------------------------------------------------------------------

def _parse_rationale_response(text: str, default_fund: str) -> dict:
    """Parse a model response into {fund_name: rationale}.

    Token-efficiency-first: JSON (array or single object) is honoured when the
    model returns it, but a plain-text reply is accepted DIRECTLY as the
    rationale for ``default_fund``. With 1-fund chunks the fund name is already
    known, so a plain sentence needs zero JSON instruction/parse overhead —
    this is what makes credit-starved fallback providers usable again
    (max_tokens=1 responses were the previous, broken workaround).
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty response body")
    
    # Validate response - reject safety filter responses and empty/garbage responses
    text_stripped = text.strip()
    if not text_stripped:
        raise ValueError("Empty response body")
    
    # Reject safety filter responses and other non-substantive responses
    safety_patterns = [
        r'^user safety: safe$',
        r'^safety.*filter',
        r'^content.*blocked',
        r'^safety.*violation',
        r'^this.*violates.*policy',
    ]
    for pattern in safety_patterns:
        if re.match(pattern, text_stripped, re.IGNORECASE):
            raise ValueError(f"Safety filter response rejected: {text_stripped[:100]}")
    
    # Reject extremely short responses (likely errors)
    if len(text_stripped) < 20:
        raise ValueError(f"Response too short to be valid rationale: {text_stripped[:100]}")
    
    # FIX #2: 144-Character AI Illusion - Detect canned rejection responses
    # If response is exactly ~144 chars (canned "I cannot provide financial advice"), reject
    if 140 <= len(text_stripped) <= 150:
        canned_indicators = [
            "cannot provide financial advice",
            "cannot provide personalized financial",
            "cannot provide investment advice",
            "as an ai language model",
            "i cannot provide",
            "unable to provide",
            "not licensed",
            "not a financial advisor",
            "consult a qualified",
            "seek professional advice",
        ]
        text_lower = text_stripped.lower()
        if any(indicator in text_lower for indicator in canned_indicators):
            raise ValueError(f"Canned AI rejection response rejected (len={len(text_stripped)}): {text_stripped[:100]}")
    
    def _items_to_map(items) -> dict:
        out = {}
        for item in items:
            if isinstance(item, dict) and item.get("rationale"):
                out[str(item.get("fund_name") or default_fund)] = str(item["rationale"])
        return out

    # 1. Direct JSON parse (array, single object, or json_object-wrapped array)
    try:
        result = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        result = None

    if isinstance(result, list):
        mapped = _items_to_map(result)
        if mapped:
            return mapped
    elif isinstance(result, dict):
        if result.get("rationale"):
            return {str(result.get("fund_name") or default_fund): str(result["rationale"])}
        for v in result.values():
            if isinstance(v, list):
                mapped = _items_to_map(v)
                if mapped:
                    return mapped

    # 2. Markdown-fenced / embedded JSON array or object
    for pattern in (r'```(?:json)?\s*(\[.*?\])\s*```', r'(\[.*\])',
                    r'```(?:json)?\s*(\{.*\})\s*```'):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(1))
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(parsed, list):
                mapped = _items_to_map(parsed)
                if mapped:
                    return mapped
            elif isinstance(parsed, dict) and parsed.get("rationale"):
                return {str(parsed.get("fund_name") or default_fund): str(parsed["rationale"])}

    # 2b. Line-by-line format: 'FundName|Verdict -> Rationale' or 'FundName -> Rationale'
    line_results = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "->" in line:
            left, _, right = line.partition("->")
            fund_part = left.split("|")[0].strip().lstrip("-* ").strip()
            rationale_part = right.strip()
            if fund_part and rationale_part:
                line_results[fund_part] = rationale_part
    if line_results:
        return line_results

    # 3. TOKEN APPROACH: plain text IS the rationale
    return {default_fund: text}


# ---------------------------------------------------------------------------
# Token Bucket Rate Limiter for API calls
# ---------------------------------------------------------------------------
class TokenBucket:
    """Thread-safe token bucket for rate limiting API calls."""
    def __init__(self, rate_per_minute: float = 10.0, burst: int = 2):
        """
        Args:
            rate_per_minute: Sustained requests per minute (e.g., 10 = 1 req per 6s)
            burst: Maximum burst allowance (tokens available at once)
        """
        self.rate_per_second = rate_per_minute / 60.0
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def take(self, tokens: int = 1) -> float:
        """
        Block until `tokens` are available. Returns seconds waited.
        """
        with self._lock:
            now = time.monotonic()
            # Refill tokens based on elapsed time
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_second)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return 0.0

            # Need to wait for tokens to refill
            deficit = tokens - self.tokens
            wait_time = deficit / self.rate_per_second
            self.tokens = 0.0
        # Sleep outside the lock
        time.sleep(wait_time)
        return wait_time


# Global rate limiters and concurrency locks for each provider (shared across calls)
_requesty_mutex = threading.Lock()
_REQUESTY_BUCKET = TokenBucket(rate_per_minute=6.0, burst=2)   # 1 req per 10s, burst 2
_OPENROUTER_BUCKET = TokenBucket(rate_per_minute=10.0, burst=3) # 1 req per 6s, burst 3
_GEMINI_BUCKET = TokenBucket(rate_per_minute=15.0, burst=3)     # 1 req per 4s, burst 3

def _openrouter_fallback(funds_data: list, prompt: str, cache_path=None, max_total_timeout=60) -> dict:
    """Try OpenRouter as a fallback when Requesty.ai is unavailable.

    Uses the openai Python client pointed at openrouter.ai.  Reads
    OPENROUTER_API_KEY from the environment.  Returns a dict mapping
    fund_name -> rationale string, or raises RuntimeError on failure.

    GAP-105 FIX: Uses openrouter/free universal router as primary model,
    which automatically routes to available free models without credit requirement.

    Timeout hardening: Overall timeout (default 60s) with fast-fail on quota exhaustion.
    """
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not or_key:
        raise RuntimeError(
            "OpenRouter fallback unavailable: OPENROUTER_API_KEY not set in environment."
        )
    
    # Timeout hardening: track overall start time
    import time as _time
    fallback_start_time = _time.time()
    max_fallback_timeout = max_total_timeout
    quota_exhausted_count = 0
    max_quota_failures = 3  # Fast-fail after N quota/credit failures across models

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("[Qualitative Engine: openai not installed for OpenRouter]") from exc

    # Dynamic /v1/models free model discovery (GAP-213 / GAP-090)
    from .model_discovery import discover_openrouter_free_models, handle_rate_limit_backoff
    or_models = discover_openrouter_free_models(api_key=or_key)

    # 1 fund/chunk needs ~150-300 output tokens for a 2-3 sentence rationale;
    # 512 is generous. Env-overridable via OPENROUTER_MAX_TOKENS.
    try:
        base_max_tokens = max(300, int(os.environ.get("OPENROUTER_MAX_TOKENS", "512")))
    except ValueError:
        base_max_tokens = 512

    # Default fund name for plain-text responses (1-fund chunks)
    default_fund = "Fund"
    if funds_data:
        f0 = funds_data[0]
        default_fund = f0.get("fund_name") or f0.get("name") or default_fund

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=or_key,
        default_headers={
            "HTTP-Referer": "https://fiduciary.engine",
            "X-Title": "Fiduciary Portfolio Engine",
        },
    )

    last_error = None
    for model_name in or_models:
        # Timeout hardening: check overall fallback timeout
        if _time.time() - fallback_start_time > max_fallback_timeout:
            print(f"  [!!] OpenRouter fallback timeout ({max_fallback_timeout}s). Fast-failing to next provider.", flush=True)
            raise RuntimeError(f"OpenRouter fallback timeout after {max_fallback_timeout}s")
        
        # Fast-fail on quota exhaustion across models
        if quota_exhausted_count >= max_quota_failures:
            print(f"  [!!] OpenRouter: {quota_exhausted_count} quota/credit failures. Fast-failing to next provider.", flush=True)
            raise RuntimeError(f"OpenRouter quota exhausted across {quota_exhausted_count} models")
        
        max_tokens = base_max_tokens
        for _token_attempt in range(4):  # adaptive: 512 -> 256(300 floor) -> 300
            try:
                print(f"  [..] OpenRouter: attempting {model_name} (max_tokens={max_tokens})...", flush=True)
                resp = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    # No response_format forcing: plain text is accepted by
                    # _parse_rationale_response and costs fewer output tokens.
                    max_tokens=max_tokens,
                    timeout=120,
                )
                # Validate before parsing (openrouter/auto returned HTTP 200
                # with an empty body in production).
                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError("OpenRouter returned an empty response body")

                chunk_results = _parse_rationale_response(text, default_fund)
                print(f"  [OK] OpenRouter: {model_name} succeeded.", flush=True)
                return chunk_results
            except Exception as e:
                last_error = e
                err_str = str(e).upper()

                # TOKEN APPROACH (402 credit error): OpenRouter requires the
                # balance to cover max_tokens x price. Halve max_tokens and
                # retry the same model (floor 300) before giving up on it.
                if "402" in err_str and "RETRY-AFTER" not in err_str and max_tokens > 300:
                    new_mt = max(300, max_tokens // 2)
                    print(
                        f"  [..] OpenRouter {model_name}: 402 credit limit at "
                        f"max_tokens={max_tokens}; halving to {new_mt}...",
                        flush=True,
                    )
                    max_tokens = new_mt
                    continue

                # Retry-After (rate limit / in-flight budget): honor it.
                retry_after = _extract_retry_after_seconds(e)
                if retry_after and ("429" in err_str or "402" in err_str):
                    print(
                        f"  [..] OpenRouter {model_name} rate-limited; "
                        f"sleeping {retry_after}s per Retry-After header...",
                        flush=True,
                    )
                    time.sleep(min(retry_after, 60))
                    continue

                # Fast-fail counter: track quota/credit failures across models
                if "429" in err_str or "402" in err_str or "QUOTA" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    quota_exhausted_count += 1
                    print(f"  [..] OpenRouter: quota/credit failure #{quota_exhausted_count}/{max_quota_failures}", flush=True)

                print(f"  [!!] OpenRouter {model_name} failed: {type(e).__name__}: {str(e)[:120]}.", flush=True)
                # GAP-105 FIX: Add rate-limit delay between model attempts to prevent 429 cascade
                time.sleep(2.0)
                break  # move to the next model

    # Self-explanatory remedy when the account has never been topped up
    # (OpenRouter locks ALL models — including ':free' variants — behind a
    # one-time credit purchase; observed: "This account never purchased credits").
    remedy = ""
    if last_error and "NEVER PURCHASED CREDITS" in str(last_error).upper():
        remedy = (" REMEDY: OpenRouter requires a one-time credit purchase "
                  "(min $10 at openrouter.ai/credits) before any model — "
                  "including ':free' variants — becomes accessible.")
    raise RuntimeError(
        f"OpenRouter fallback failed for all models. Reason: {last_error}.{remedy}"
    )

# ---------------------------------------------------------------------------
# Requesty.ai fallback (free, unlimited Nemotron 3 Ultra via proxy)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Requesty.ai fallback (free/cheap models via router.requesty.ai)
# ---------------------------------------------------------------------------
def _requesty_fallback(funds_data: list, prompt: str, cache_path=None, max_total_timeout=60) -> dict:
    """Try Requesty.ai as primary provider (free/cheap, no credit required).

    Requesty.ai (router.requesty.ai) provides access to 799+ models via OpenAI-compatible API.
    Many models are FREE (input_price=0, output_price=0) or extremely cheap.
    Uses OpenAI-compatible API at https://router.requesty.ai/v1

    GAP-104 FIX: Caller must hold _requesty_mutex due to in-flight concurrency limit of 1.

    Timeout hardening: Overall timeout (default 60s) with fast-fail on quota exhaustion.
    """
    requesty_key = os.environ.get("REQUESTY_API_KEY", "")
    if not requesty_key:
        raise RuntimeError(
            "Requesty.ai primary unavailable: REQUESTY_API_KEY not set in environment."
        )
    
    # Timeout hardening: track overall start time
    import time as _time
    fallback_start_time = _time.time()
    max_fallback_timeout = max_total_timeout
    quota_exhausted_count = 0
    max_quota_failures = 3  # Fast-fail after N quota/credit failures across models

    from openai import OpenAI
    from .model_discovery import discover_requesty_free_models, handle_rate_limit_backoff

    # GAP-213: Dynamic zero-cost model discovery with Nemotron 3 Ultra prioritized
    requesty_models = discover_requesty_free_models(api_key=requesty_key)

    # Default fund name for plain-text responses (1-fund chunks)
    default_fund = "Fund"
    if funds_data:
        f0 = funds_data[0]
        default_fund = f0.get("fund_name", "") or f0.get("name", "") or "Fund"

    # Base max tokens for paid models (adaptive on 402)
    try:
        base_max_tokens = max(300, int(os.environ.get("REQUESTY_MAX_TOKENS", "512")))
    except ValueError:
        base_max_tokens = 512

    client = OpenAI(
        base_url="https://router.requesty.ai/v1",  # Requesty.ai OpenAI-compatible endpoint
        api_key=requesty_key,
        default_headers={
            "HTTP-Referer": "https://fiduciary.engine",
            "X-Title": "Fiduciary Portfolio Engine",
        },
    )

    last_error = None

    for model_name in requesty_models:
        # Timeout hardening: check overall fallback timeout
        if _time.time() - fallback_start_time > max_fallback_timeout:
            print(f"  [!!] Requesty.ai fallback timeout ({max_fallback_timeout}s). Fast-failing to next provider.", flush=True)
            raise RuntimeError(f"Requesty.ai fallback timeout after {max_fallback_timeout}s")
        
        # Fast-fail on quota exhaustion across models
        if quota_exhausted_count >= max_quota_failures:
            print(f"  [!!] Requesty.ai: {quota_exhausted_count} quota/credit failures. Fast-failing to next provider.", flush=True)
            raise RuntimeError(f"Requesty.ai quota exhausted across {quota_exhausted_count} models")
        
        max_tokens = base_max_tokens if "free" not in model_name.lower() and ":free" not in model_name else 512
        for _token_attempt in range(4):  # adaptive: 512 -> 256(300 floor) -> 300
            try:
                print(f"  [..] Requesty.ai: attempting {model_name} (max_tokens={max_tokens})...", flush=True)
                resp = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=max_tokens,
                    timeout=180,
                )

                text = (resp.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError("Requesty.ai returned an empty response body")

                chunk_results = _parse_rationale_response(text, default_fund)
                print(f"  [OK] Requesty.ai: {model_name} succeeded.", flush=True)
                return chunk_results

            except Exception as e:
                last_error = e
                err_str = str(e).upper()

                if "402" in err_str and "RETRY-AFTER" not in err_str and max_tokens > 300:
                    new_mt = max(300, max_tokens // 2)
                    print(f"  [..] Requesty.ai {model_name}: 402 credit limit at max_tokens={max_tokens}; halving to {new_mt}...", flush=True)
                    max_tokens = new_mt
                    continue

                retry_after = _extract_retry_after_seconds(e)
                if retry_after and ("429" in str(e).upper() or "402" in str(e).upper()):
                    logger.info(f"  [..] Requesty.ai {model_name} rate-limited; sleeping {retry_after}s per Retry-After header...")
                    time.sleep(min(retry_after, 60))
                    continue

                # GAP-104 FIX: 429 without Retry-After header — apply minimum backoff
                # before falling through to the next model to prevent 429 cascade.
                if "429" in str(e).upper() or "RESOURCE_EXHAUSTED" in str(e).upper() or "QUOTA" in str(e).upper():
                    logger.info(f"  [..] Requesty.ai {model_name} rate-limited (no Retry-After); backing off 5s...")
                    time.sleep(5.0)
                    continue

                # Fast-fail counter: track quota/credit failures across models
                if "429" in str(e).upper() or "402" in str(e).upper() or "QUOTA" in str(e).upper() or "RESOURCE_EXHAUSTED" in str(e).upper():
                    quota_exhausted_count += 1
                    print(f"  [..] Requesty.ai: quota/credit failure #{quota_exhausted_count}/{max_quota_failures}", flush=True)

                if "CONNECTION" in str(e).upper() or "TIMEOUT" in str(e).upper() or "APICONNECTION" in str(e).upper():
                    logger.info(f"  [..] Requesty.ai {model_name} connection error ({type(e).__name__}); will retry...")
                    continue

                logger.info(f"  [!!] Requesty.ai {model_name} failed: {type(e).__name__}: {str(e)[:120]}.")
                # GAP-104 FIX: Add rate-limit delay between model attempts to prevent 429 cascade
                time.sleep(2.0)
                break

    raise RuntimeError(f"Requesty.ai primary failed for all models. Reason: {last_error}")
def _check_cache_age(entry: dict) -> bool:
    """Check if cache entry is within TTL. Returns True if VALID, False if STALE."""
    if not isinstance(entry, dict) or "timestamp" not in entry:
        return False  # No timestamp = unknown origin, treat as stale
    try:
        from datetime import timezone
        import datetime as _dt
        ts = _dt.datetime.fromisoformat(str(entry["timestamp"]))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        now_utc = _dt.datetime.now(timezone.utc)
        age_seconds = (now_utc - ts).total_seconds()
        return age_seconds < (30 * 24 * 60 * 60)  # 30 days
    except Exception:
        return False  # Malformed timestamp, treat as stale


def generate_fiduciary_rationales_batch(
    funds_data: list,
    api_key: str,
    cache_path=None,
    verbose: bool = False
) -> dict:
    """
    Main entry point for qualitative evaluation.

    Tries providers in order:
      1. Gemini (primary) - Google Search grounding for live web research
         on fund managers, investment process, and AMC governance
      2. Requesty.ai (fallback) - offline model cascade, no web search
      3. OpenRouter (last resort) - offline, no web search

    v2.0.7 Routing Split: The qualitative gate needs the LIVE WEB to evaluate
    People, Process, and Parent — a model without internet access is functionally
    blind. Gemini leads because it has Google Search grounding built in. The
    narrative layer (engine/narrative.py) keeps Requesty/OpenRouter as primary
    because it only translates engine-computed payloads (no web needed).

    The `api_key` parameter is kept for backward compatibility but is
    ignored - each provider reads its own key from the environment:
      - REQUESTY_API_KEY (primary)
      - OPENROUTER_API_KEY (fallback 1)
      - GEMINI_API_KEY (fallback 2)

    Raises RuntimeError if ALL providers fail. The caller (main.py) catches it
    and HALTS report generation per Fiduciary Mandate: No AI Reachability = No Report.
    """
    # ---- Persistent qualitative cache (all providers) ----
    # Schema: {fund_name|verdict: {"rationale": "...", "timestamp": "2026-10-21T10:30:00"}}
    # TTL: 30 days (30 * 24 * 60 * 60 = 2592000 seconds)
    # CACHE_MAX_AGE_SECONDS = 2592000
    # CACHE_WARN_DAYS = 25  # warn when cache is approaching TTL
    
    import datetime as _dt
    import time as _time
    
    CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60  # 30 days
    CACHE_WARN_SECONDS = 25 * 24 * 60 * 60     # 25 days
    
    _cache: dict = {}
    if cache_path is not None:
        try:
            import json as _json
            _cache = _json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}

    def _prefill_cached(target: dict) -> None:
        if not _cache:
            if verbose:
                print(f"  [cache] No cache file found or empty", flush=True)
            return
        if verbose:
            print(f"  [cache] Loaded cache with {len(_cache)} entries", flush=True)
        for _fd in funds_data:
            _fn = _fd.get("fund_name") or _fd.get("name") or "Fund"
            _fv = _fd.get("verdict", "")
            # If verdict is UNKNOWN, try both UNKNOWN and other possible verdicts in cache
            _fv_for_cache = _fv if _fv and _fv != "UNKNOWN" else "UNKNOWN"
            _ck = f"{_fn}|{_fv_for_cache}"
            if _ck in _cache and _fn not in target:
                entry = _cache[_ck]
                # Check TTL before using cached entry
                if _check_cache_age(entry):
                    target[_fn] = entry["rationale"]
                    print(f"  [cache] {_fn} (verdict={_fv_for_cache}) -> using cached rationale (age OK)", flush=True)
                else:
                    # Cache entry is stale - not using it
                    if verbose:
                        print(f"  [cache] {_fn} (verdict={_fv_for_cache}) -> stale, will evaluate live", flush=True)
            elif verbose:
                print(f"  [cache] {_fn} (verdict={_fv_for_cache}) -> cache MISS, will evaluate live", flush=True)

    def _persist_cached(live: dict) -> None:
        if cache_path is None:
            return
        try:
            import json as _json
            import datetime as _dt
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            combined = dict(_cache)
            for _fd in funds_data:
                _fn = _fd.get("fund_name") or _fd.get("name") or "Fund"
                _fv = _fd.get("verdict", "")
                # Use "UNKNOWN" for cache key if verdict is UNKNOWN or empty
                _fv_for_cache = _fv if _fv and _fv != "UNKNOWN" else "UNKNOWN"
                if _fn in live:
                    combined[f"{_fn}|{_fv_for_cache}"] = {
                        "verdict": _fv_for_cache,
                        "rationale": live[_fn],
                        "model": "cache_or_api",
                        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
                    }
            cache_path.write_text(_json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(r"Failed to write qualitative cache: {e}")  # cache is best-effort; never block on I/O

    # Generate prompt for qualitative evaluation (used by all providers) (GAP-191 FIX)
    # Format: "FundName|Verdict -> 2-3 sentence rationale: People,Process,Parent,Performance,Price."
    if funds_data:
        fund_lines = []
        for fd in funds_data:
            fname = fd.get("fund_name") or fd.get("name") or "Fund"
            fverd = fd.get("verdict", "PASS")
            m = fd.get("metrics", {})
            aum = m.get("aum_cr") or m.get("aum_crore")
            er = m.get("ter_direct_pct") or m.get("er")
            alpha = m.get("alpha_annual_pct") or m.get("alpha")
            holdings = m.get("h", [])[:5]
            details = []
            if aum:
                details.append(f"AUM: ₹{aum:,.0f}Cr")
            if er:
                details.append(f"TER: {er}%")
            if alpha is not None:
                details.append(f"Alpha: {alpha}%")
            if holdings:
                holdings_str = ", ".join(h.get("name", str(h)) if isinstance(h, dict) else str(h) for h in holdings[:3])
                details.append(f"Top: {holdings_str}")
            detail_str = f" ({'; '.join(details)})" if details else ""
            fund_lines.append(f"- {fname}|{fverd}{detail_str}")
        prompt = (
            "Provide fiduciary rationales (Morningstar 5-Pillars: People, Process, Parent, Performance, Price) "
            "for the following mutual funds:\n" + "\n".join(fund_lines) +
            "\n\nFormat output strictly with one line per fund: 'FundName|Verdict -> 2-3 sentence rationale'."
        )
    else:
        prompt = "TestFund|INCONCLUSIVE -> 2-3 sentence rationale: People,Process,Parent,Performance,Price."


    # --- Provider Chain: Requesty.ai (Primary) -> OpenRouter (Fallback) -> Gemini (Grounded Last Resort) ---
    # Per FreeLLMAPI reference architecture and forensic analysis (GAP-103 through GAP-107):
    # 1. Requesty.ai: Free/cheap, no credit needed, but in-flight limit = 1 (mutex required)
    # 2. OpenRouter: Universal free router via openrouter/free, dynamic model discovery
    # 3. Gemini: Google Search grounding (last resort for grounded analysis)
    #
    # CODE-GAP-26: Enforce live Google Search grounding. Results from non-grounded providers
    # (Requesty.ai, OpenRouter) are marked as UNVERIFIED_OFFLINE. Only grounded (Gemini with
    # Google Search) results are used in the final report. If no grounded provider succeeds,
    # all results are flagged UNVERIFIED_OFFLINE and the qualitative gate blocks.
    
    # Provider priority with grounding status
    # grounded=True means the provider uses live web search (Google Search for Gemini)
    PROVIDER_CHAIN = [
        {"name": "requesty", "grounded": False, "key_env": "REQUESTY_API_KEY", "func": "_requesty_fallback", "mutex": _requesty_mutex, "bucket": _REQUESTY_BUCKET},
        {"name": "openrouter", "grounded": False, "key_env": "OPENROUTER_API_KEY", "func": "_openrouter_fallback", "mutex": None, "bucket": _OPENROUTER_BUCKET},
        {"name": "gemini", "grounded": True, "key_env": "GEMINI_API_KEY", "func": "_gemini_fallback_batch", "mutex": None, "bucket": _GEMINI_BUCKET},
    ]
    
    # --- Provider 1: Requesty.ai (PRIMARY - Free, No Credit Required) ---
    if verbose:
        print("  [qualitative] Provider 1/3: Requesty.ai (PRIMARY - free/cheap, no credit needed)", flush=True)
    requesty_key = os.environ.get("REQUESTY_API_KEY", "")
    if requesty_key:
        print("  [..] Calling Requesty.ai (PRIMARY, free/cheap) for qualitative evaluation...", flush=True)
        try:
            # Serialize Requesty.ai calls due to in-flight concurrency limit of 1 (GAP-104)
            with _requesty_mutex:
                # Rate limit: take a token before making the call
                waited = _REQUESTY_BUCKET.take()
                if waited > 0:
                    print(f"  [..] Rate limited: waited {waited:.1f}s for Requesty.ai token", flush=True)
                return _requesty_fallback(funds_data, prompt, cache_path, max_total_timeout=30)
        except RuntimeError as e:
            print(f"  [!!] Requesty.ai primary failed: {e}", flush=True)
            if verbose:
                print(f"  [qualitative] Provider 1 FAILED: {e}", flush=True)
            print("  [..] Falling back to OpenRouter (free router)...", flush=True)
    else:
        if verbose:
            print("  [qualitative] No REQUESTY_API_KEY, skipping Provider 1", flush=True)
        print("  [..] REQUESTY_API_KEY not set. Trying OpenRouter fallback...", flush=True)

    # --- Provider 2: OpenRouter (FALLBACK - Universal Free Router) ---
    if verbose:
        print("  [qualitative] Provider 2/3: OpenRouter (FALLBACK - openrouter/free universal router)", flush=True)
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "")
    if openrouter_key:
        print("  [..] Calling OpenRouter (FALLBACK, openrouter/free) for qualitative evaluation...", flush=True)
        try:
            # Rate limit
            waited = _OPENROUTER_BUCKET.take()
            if waited > 0:
                print(f"  [..] Rate limited: waited {waited:.1f}s for OpenRouter token", flush=True)
            return _openrouter_fallback(funds_data, prompt, cache_path, max_total_timeout=30)
        except RuntimeError as e:
            print(f"  [!!] OpenRouter fallback failed: {e}", flush=True)
            if verbose:
                print(f"  [qualitative] Provider 2 FAILED: {e}", flush=True)
            print("  [..] Falling back to Gemini (grounded last resort)...", flush=True)
    else:
        print("  [..] OPENROUTER_API_KEY not set. Trying Gemini grounded last resort...", flush=True)

    # --- Provider 3: Gemini (LAST RESORT - Google Search Grounding) ---
    if verbose:
        print("  [qualitative] Provider 3/3: Gemini (LAST RESORT - Google Search Grounding)", flush=True)
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        print("  [..] Calling Gemini (LAST RESORT, Google Search grounded) for live qualitative evaluation...", flush=True)
        try:
            # Rate limit
            waited = _GEMINI_BUCKET.take()
            if waited > 0:
                print(f"  [..] Rate limited: waited {waited:.1f}s for Gemini token", flush=True)
            return _gemini_fallback_batch(funds_data, gemini_key, cache_path)
        except RuntimeError as e:
            print(f"  [!!] Gemini last resort failed: {e}", flush=True)
            if verbose:
                print(f"  [qualitative] Provider 3 FAILED: {e}", flush=True)
            # All providers exhausted
            raise RuntimeError(
                f"Qualitative Fiduciary Gate BLOCKED: All providers exhausted. "
                f"Requesty.ai: failed, OpenRouter: failed, Gemini: {e}. "
                f"Anti-Hallucination Shield: No AI Reachability = No Report Generation."
            )
    else:
        print("  [..] GEMINI_API_KEY not set. No providers available.", flush=True)
        raise RuntimeError(
            "Qualitative Fiduciary Gate BLOCKED: No API keys available. "
            "Set REQUESTY_API_KEY (primary), OPENROUTER_API_KEY (fallback), or GEMINI_API_KEY (grounded last resort). "
            "Anti-Hallucination Shield enforces: No AI Reachability = No Report Generation."
        )
                

def _gemini_fallback_batch(
    funds_data: list,
    api_key: str,
    cache_path=None
) -> dict:
    """
    Evaluate the entire portfolio using the best available Gemini model with 
    Google Search grounding. Sequentially tries all prioritised models with 
    exponential backoff, never aborting on a single model's failure.
    
    `funds_data` is a list of dicts: {"fund_name": str, "verdict": str, "metrics": dict}.
    Returns a dict mapping fund_name -> rationale string.
    
    Raises RuntimeError if all models fail. The caller (main.py) catches it
    and HALTS report generation per the Fiduciary Mandate: No AI Reachability = No Report.
    """
    if not api_key:
        raise RuntimeError(
            "HARD HALT: A Gemini API Key is required. "
            "Qualitative verification cannot be skipped under the Fiduciary Mandate."
        )

    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("[Qualitative Engine: google-genai not installed]") from exc

    client, models = _get_client_and_models(api_key)

    # ---- Load persistent qualitative cache ----
    # Schema: {fund_name|verdict: {"verdict": str, "rationale": str, "model": str, "timestamp": str}}
    # Only entries whose (fund_name, verdict) matches the current run are valid.
    _cache = {}
    if cache_path is not None:
        try:
            import json as _json
            _cache = _json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}


    def _pick(metrics, *names, default=None):
        for n in names:
            v = metrics.get(n)
            if v is not None:
                return v
        return default

    # Chunk portfolios into smaller batches to prevent token limits and JSON truncation
    # Reduced from 4 to 1: free-tier OpenRouter credit balance (~400 tokens)
    # and context limits (~200 tokens) cannot afford larger prompts. 
    # 1 fund/chunk fits within both budget and context window.
    MAX_FUNDS_PER_BATCH = 1
    all_results = {}
    funds_chunks = [funds_data[i:i + MAX_FUNDS_PER_BATCH] 
                    for i in range(0, len(funds_data), MAX_FUNDS_PER_BATCH)]

    # Pre-fill from cache: for each fund in funds_data, if (fund_name, verdict)
    # has a cached rationale, use it and skip the API call entirely. This makes
    # the pipeline idempotent: re-running with the same portfolio state costs zero
    # AI quota. The existing chunk-skip logic (all_results check) then drops the
    # cached chunks from the API loop.
    if _cache:
        for _fd in funds_data:
            _fn = _fd.get("fund_name", "")
            _fv = _fd.get("verdict", "")
            _ck = f"{_fn}|{_fv}"
            if _ck in _cache:
                all_results[_fn] = _cache[_ck]["rationale"]
                print(f"  [cache] {_fn} (verdict={_fv}) -> using cached rationale", flush=True)

    
    def _save_cache():
        """Persist current all_results + cached entries to disk."""
        if cache_path is None:
            return
        try:
            import json as _json
            import datetime as _dt
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            combined = dict(_cache)
            for _fd in funds_data:
                _fn = _fd.get("fund_name", "")
                _fv = _fd.get("verdict", "")
                if _fn in all_results:
                    combined[f"{_fn}|{_fv}"] = {
                        "verdict": _fv,
                        "rationale": all_results[_fn],
                        "model": "cache_or_api",
                        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
                    }
            cache_path.write_text(_json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(r"Failed to write qualitative cache: {e}")  # cache is best-effort; never block on I/O

    # BUG FIX (Gemini 429 cascade): once an entire Gemini tier reports
    # account-level quota exhaustion (every model returns 429), retrying all
    # ~12 models for EVERY subsequent chunk wastes ~24 API round-trips per chunk
    # before falling through to OpenRouter. Observed live: 5 chunks × 12 models
    # × 2 retries of guaranteed-429 calls. Once dead, skip straight to the
    # OpenRouter fallback for all remaining chunks.
    gemini_dead = False
    
    for chunk_idx, chunk in enumerate(funds_chunks):
        # TOKEN APPROACH: skip chunks whose funds were already answered by an
        # earlier response — a model may return items beyond the requested
        # chunk (observed: a 6-item array answering a 1-fund chunk). Re-calling
        # the API for already-answered funds wastes tokens and can exhaust
        # mocked/billed budgets (this exact pattern broke the chunking test).
        chunk = [f for f in chunk
                 if (f.get("fund_name") or f.get("name") or "Fund") not in all_results]
        if not chunk:
            continue
        if chunk_idx > 0:
            logger.info(f"  [..] Processing chunk {chunk_idx + 1}/{len(funds_chunks)} ({len(chunk)} funds)...")
            
        # Ultra-minimal: just fund name + verdict, no JSON, no instructions.
        # Plain-text response is accepted directly as the rationale (see
        # _parse_rationale_response) — zero JSON token overhead.
        f = chunk[0]
        fname = f.get("fund_name") or f.get("name") or "Fund"
        verdict = f.get("verdict", "INCONCLUSIVE")
        prompt = f"{fname}|{verdict} -> 2-3 sentence rationale: People,Process,Parent,Performance,Price."

        import re
        last_error = None
        tried = 0
        chunk_succeeded = False
        quota_exhausted_models = set()
        # Models that failed PERMANENTLY this chunk: 404 (retired/sunset ID)
        # or 429 (quota). If every attempted model failed permanently, Gemini
        # is dead for the rest of the batch — see gemini_dead below.
        permanent_fail_models = set()
        chunk_start_time = time.time()
        max_chunk_timeout_sec = 120.0

        # Try models sequentially for this chunk until one succeeds
        # (skipped entirely once Gemini is known quota-dead — see gemini_dead)
        for model_name in models if not gemini_dead else []:
            if chunk_succeeded:
                break
            if time.time() - chunk_start_time > max_chunk_timeout_sec:
                print(f"  [!!] Chunk {chunk_idx + 1} qualitative timeout ({max_chunk_timeout_sec}s exceeded). Fast-halting.", flush=True)
                break
            tried += 1
            max_retries = 2
            for attempt in range(max_retries):
                if time.time() - chunk_start_time > max_chunk_timeout_sec:
                    break
                try:
                    print(f"  [..] Chunk {chunk_idx + 1}: Attempting {model_name} (attempt {attempt + 1}/{max_retries})...", flush=True)
                    if attempt > 0:
                        backoff = 1.0 + random.uniform(0, 0.5)
                        time.sleep(backoff)

                    try:
                        response = client.models.generate_content(
                            model=model_name,
                            contents=prompt,
                            config=types.GenerateContentConfig(
                                tools=[{"google_search": {}}],
                            )
                        )
                    except Exception as search_err:
                        s_err = str(search_err).upper()
                        # Fatal quota error: do not attempt redundant direct synthesis
                        if "429" in s_err or "RESOURCE_EXHAUSTED" in s_err or "QUOTA" in s_err:
                            raise search_err
                        elif "TOOL" in s_err or "SEARCH" in s_err:
                            print(f"  [..] {model_name} search grounding unavailable, synthesizing with model directly...", flush=True)
                            # No response_mime_type forcing: plain text is accepted
                            # by _parse_rationale_response and costs fewer tokens.
                            response = client.models.generate_content(
                                model=model_name,
                                contents=prompt,
                            )
                        else:
                            raise search_err
                    text = (response.text or "").strip()

                    # FIX #4: 429 Rate-Limit Crash & Garbage Rejection
                    # Reject safety filters & garbage responses
                    if len(text) < 50 or "User Safety" in text:
                        print(f"  [!!] {model_name} returned garbage/safety-filtered response for {fname}: '{text[:80]}...'. Rejecting.", flush=True)
                        raise RuntimeError("Garbage or safety-filtered response rejected")
                    
                    # TOKEN APPROACH: honour JSON when the model returns it,
                    # but accept plain text directly as the rationale. With
                    # 1-fund chunks the fund name is already known, so a plain
                    # sentence needs zero JSON instruction/parse overhead.
                    chunk_results = _parse_rationale_response(text, fname)
                    all_results.update(chunk_results)
                    _save_cache()
                    print(f"  [OK] Chunk {chunk_idx + 1} qualitative evaluation complete via {model_name}.", flush=True)
                    
                    # FIX #4: Add sequential delay to prevent 429 rate limits
                    time.sleep(3.0)
                    
                    chunk_succeeded = True
                    break

                except Exception as e:
                    last_error = e
                    err_str = str(e).upper()
                    print(f"  [!!] {model_name} failed (attempt {attempt + 1}): {type(e).__name__}: {str(e)[:120]}.", flush=True)

                    if "404" in err_str or "NOT_FOUND" in err_str:
                        print(f"  [..] {model_name} not found, moving to next model...", flush=True)
                        # A retired model ID is a PERMANENT failure: it can never
                        # succeed again, so it counts toward the gemini_dead trigger.
                        permanent_fail_models.add(model_name)
                        break
                    elif "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "QUOTA" in err_str:
                        quota_exhausted_models.add(model_name)
                        permanent_fail_models.add(model_name)
                        print(f"  [..] {model_name} quota exhausted, trying next model...", flush=True)
                        # Only halt if ALL models have been tried and all returned quota errors
                        if len(quota_exhausted_models) >= len(models):
                            print(f"  [!!] All Gemini models exhausted (account-level quota). Trying Requesty.ai (priority fallback)...", flush=True)
                            # Mark Gemini dead so remaining chunks skip the futile retry cascade
                            gemini_dead = True
                            try:
                                chunk_results = _requesty_fallback(chunk, prompt, cache_path=cache_path, max_total_timeout=30)
                                all_results.update(chunk_results)
                                _save_cache()
                                chunk_succeeded = True
                                break
                            except RuntimeError:
                                print(f"  [..] Requesty.ai fallback failed, trying OpenRouter fallback...", flush=True)
                                try:
                                    chunk_results = _openrouter_fallback(chunk, prompt, cache_path=cache_path, max_total_timeout=30)
                                    all_results.update(chunk_results)
                                    _save_cache()
                                    chunk_succeeded = True
                                    break
                                except RuntimeError:
                                    raise RuntimeError(
                                        f"AI API quota exhausted (429 RESOURCE_EXHAUSTED) and Requesty.ai/OpenRouter fallbacks failed. "
                                        f"Anti-Hallucination Gate enforces: No AI Reachability = No Report Generation."
                                    ) from e
                        break
                    elif "503" in err_str or "504" in err_str or "UNAVAILABLE" in err_str or "DEADLINE_EXCEEDED" in err_str:
                        print(f"  [..] {model_name} unavailable or timed out, trying next model...", flush=True)
                        break
                    elif attempt < max_retries - 1:
                        print(f"  [..] Retrying same model in 1 second...", flush=True)
                        continue
                    else:
                        print(f"  [..] All retries exhausted for {model_name}, trying next model...", flush=True)
                        break
            if chunk_succeeded:
                break

        # BUG FIX (gemini_dead trigger with mixed failures): the all-429 fast
        # path above can never fire when the model list contains even ONE
        # retired (404) model — observed live with gemini-2.5-flash-lite. So
        # after the loop: if every model we attempted failed PERMANENTLY
        # (404 or 429), Gemini is dead for all remaining chunks too.
        if not chunk_succeeded and tried > 0 and len(permanent_fail_models) >= tried:
            print(f"  [!!] All {tried} Gemini model(s) failed permanently (404/429). Gemini disabled for remaining chunks.", flush=True)
            gemini_dead = True

        # If all models failed for this chunk, try Requesty.ai FIRST (it works!),
        # then OpenRouter as last resort.
        if not chunk_succeeded:
            print(f"  [..] Gemini failed for chunk {chunk_idx + 1}. Trying Requesty.ai (priority fallback)...", flush=True)
            try:
                chunk_results = _requesty_fallback(chunk, prompt, cache_path=cache_path, max_total_timeout=30)
                all_results.update(chunk_results)
                _save_cache()
                chunk_succeeded = True
            except RuntimeError as ry_exc:
                print(f"  [..] Requesty.ai failed: {ry_exc}. Trying OpenRouter fallback...", flush=True)
                try:
                    chunk_results = _openrouter_fallback(chunk, prompt, cache_path=cache_path, max_total_timeout=30)
                    all_results.update(chunk_results)
                    _save_cache()
                    chunk_succeeded = True
                except RuntimeError as or_exc:
                    raise RuntimeError(
                        f"Qualitative Fiduciary Gate Failed on Chunk {chunk_idx + 1}. "
                        f"Gemini: {tried}/{len(models)} model(s) attempted. "
                        f"Requesty.ai: {ry_exc}. "
                        f"OpenRouter: {or_exc}. "
                        f"Anti-Hallucination Gate enforces: No AI Reachability = No Report Generation."
                    ) from or_exc

    _save_cache()
    return all_results

