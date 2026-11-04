"""Live, opt-in smoke test for all configured AI providers.

Only synthetic prompts are sent. Provider output and raw SDK diagnostics are
never printed; failures are reduced to safe, coarse categories.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPOSITORY_ROOT not in sys.path:
    sys.path.insert(0, REPOSITORY_ROOT)

from core import ai_engine


PROVIDERS = (
    ("Requesty", "REQUESTY_API_KEY", ai_engine._call_requesty),
    ("OpenRouter", "OPENROUTER_API_KEY", ai_engine._call_openrouter),
    ("Gemini", "GEMINI_API_KEY", ai_engine._call_gemini),
)

PROMPT = "Reply with exactly the word READY. This is a provider connectivity test."


def safe_failure_category(diagnostics: str, exc: Exception) -> str:
    """Map private SDK diagnostics to a non-sensitive operational category."""
    combined = f"{type(exc).__name__} {diagnostics}".lower()

    if re.search(r"\b(401|unauthorized|invalid api.?key|api key not valid)\b", combined):
        return "authentication rejected (401/invalid key)"
    if re.search(r"\b(403|forbidden|permission denied|access denied)\b", combined):
        return "permission/access rejected (403)"
    if re.search(r"\b(402|429|quota|rate.?limit|resource_exhausted|billing)", combined):
        return "quota, rate limit, or billing restriction"
    if re.search(r"\b(404|model.*(not found|unavailable)|not supported for.*generate)", combined):
        return "model unavailable or unsupported"
    if re.search(r"\b(400|bad request|invalid argument|unsupported parameter)", combined):
        return "request/model-parameter rejected (400)"
    if re.search(r"\b(timeout|timed out|connection|dns|network|ssl|tls)", combined):
        return "network or timeout failure"
    if "provider unavailable" in combined:
        return "all configured model attempts failed; SDK detail not classifiable"
    return "provider call failed; SDK detail not classifiable"


def main() -> int:
    missing = [name for _, name, _ in PROVIDERS if not os.getenv(name, "").strip()]
    if missing:
        print("Missing required GitHub Actions secrets: " + ", ".join(missing))
        return 2

    failed = []
    for label, _, call in PROVIDERS:
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                response = call(PROMPT, system_prompt="Return only the requested token.")
            if not isinstance(response, str) or not response.strip():
                raise RuntimeError("empty response")
            print(f"{label}: PASS")
        except Exception as exc:
            print(f"{label}: FAIL — {safe_failure_category(captured.getvalue(), exc)}")
            failed.append(label)

    if failed:
        print("Failed providers: " + ", ".join(failed))
        return 1
    print("All three AI providers returned a non-empty response.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
