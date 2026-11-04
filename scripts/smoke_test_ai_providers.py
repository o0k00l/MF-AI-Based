"""Live, opt-in smoke test for all configured AI providers.

This test sends only a synthetic, non-client prompt. Provider output and
captured SDK logs are deliberately suppressed to keep workflow logs secret-safe.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys

from core import ai_engine


PROVIDERS = (
    ("Requesty", "REQUESTY_API_KEY", ai_engine._call_requesty),
    ("OpenRouter", "OPENROUTER_API_KEY", ai_engine._call_openrouter),
    ("Gemini", "GEMINI_API_KEY", ai_engine._call_gemini),
)

PROMPT = "Reply with exactly the word READY. This is a provider connectivity test."


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
            # Do not print exception messages: provider SDKs can echo request data.
            print(f"{label}: FAIL ({type(exc).__name__})")
            failed.append(label)

    if failed:
        print("One or more configured AI providers failed connectivity validation.")
        return 1
    print("All three AI providers returned a non-empty response.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
