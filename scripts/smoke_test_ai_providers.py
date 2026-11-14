"""Live, opt-in smoke test for configured AI providers.

Only synthetic prompts are sent. Raw SDK messages, response bodies and secrets
are never printed. A provider failure is classified from structured metadata.
"""
from __future__ import annotations

import contextlib
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core import ai_engine

PROVIDERS = (
    ("Requesty", "REQUESTY_API_KEY", ai_engine._call_requesty),
    ("OpenRouter", "OPENROUTER_API_KEY", ai_engine._call_openrouter),
)
PROMPT = "Reply with exactly the word READY. This is a provider connectivity test."


def safe_failure_category(diagnostics: str, exc: Exception) -> str:
    """Classify without printing provider response bodies or credential material."""
    status = getattr(exc, "status_code", None)
    code = str(getattr(exc, "code", "") or "").lower()
    combined = f"{type(exc).__name__} {code} {diagnostics}".lower()
    if status == 401 or re.search(r"\b(401|unauthorized|invalid api.?key|api key not valid)\b", combined):
        return "authentication rejected (401/invalid key)"
    if status == 403 or re.search(r"\b(403|forbidden|permission denied|access denied)\b", combined):
        return "permission/access rejected (403)"
    if status in (402, 429) or re.search(r"\b(402|429|quota|rate.?limit|resource_exhausted|billing)\b", combined):
        return "quota, rate limit, or billing restriction"
    if status == 404 or re.search(r"\b(404|model.*(not found|unavailable)|not supported for.*generate)\b", combined):
        return "model unavailable or unsupported"
    if status == 400 or re.search(r"\b(400|bad request|invalid argument|unsupported parameter)\b", combined):
        return "request rejected (400); inspect provider code/model diagnostic"
    if re.search(r"\b(timeout|timed out|connection|dns|network|ssl|tls)\b", combined):
        return "network or timeout failure"
    return "provider call failed; diagnostic category unavailable"


def main() -> int:
    if not ai_engine.external_processing_policy_approved():
        print("Blocked: external AI is hard-disabled in this release. An environment flag or caller-supplied boolean cannot authorize processing. Implement and deploy the audited investor-consent ledger and independently approved provider integration before enabling any provider smoke test.")
        return 2
    missing = [name for _, name, _ in PROVIDERS if not os.getenv(name, "").strip()]
    if missing:
        print("Missing required GitHub Actions secrets: " + ", ".join(missing))
        return 2
    failed = []
    for label, _, call in PROVIDERS:
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
                # This opt-in diagnostic sends a synthetic token prompt only; no investor data is loaded.
                response = call(
                    PROMPT,
                    system_prompt="Return only the requested token.",
                    external_processing_consent=True,
                )
            if not isinstance(response, str) or not response.strip():
                raise RuntimeError("empty response")
            print(f"{label}: PASS")
        except Exception as exc:
            category = safe_failure_category(captured.getvalue(), exc)
            status = getattr(exc, "status_code", None)
            code = getattr(exc, "code", None)
            model = getattr(exc, "model", None)
            details = []
            if status is not None:
                details.append(f"HTTP {status}")
            if code:
                details.append(f"code={str(code)[:80]}")
            if model:
                details.append(f"model={str(model)[:100]}")
            suffix = " (" + "; ".join(details) + ")" if details else ""
            print(f"{label}: FAIL — {category}{suffix}")
            failed.append(label)
    if failed:
        print("Failed providers: " + ", ".join(failed))
        return 1
    print("All enabled free AI providers returned a non-empty response.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
