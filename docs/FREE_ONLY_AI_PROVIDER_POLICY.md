# Free-only AI provider policy

## Binding rule

The application may call only providers whose authenticated model catalogue provides explicit evidence that both input and output generation cost are zero. Missing, ambiguous, stale, or non-zero pricing is ineligible. The policy is fail-closed.

## Currently eligible adapters

- Requesty: both input_price and output_price must be present and parse numerically to exactly zero in the authenticated model catalogue.
- OpenRouter: model must be explicitly marked with the :free model suffix or have both catalogue pricing.prompt and pricing.completion equal to zero. Unknown pricing is rejected.

## Disabled adapter

- Gemini: disabled from the runtime provider chain. Its model-list response used here does not expose authoritative per-model zero-cost pricing. A free-tier quota or account allowance is not sufficient proof that the configured project/API key cannot incur charges. Re-enable only after a verifiable no-billing control or authoritative zero-cost metadata is implemented and tested.

## Operational constraints

- No paid fallback, paid model IDs, or automatic upgrade path.
- Provider quota/rate-limit failures are surfaced; the engine does not route around them to paid services.
- Provider calls generate narrative text only. Deterministic fund eligibility, portfolio analysis, allocation, evidence validation, and release gates remain independent of AI provider availability.
- Live smoke tests use synthetic prompts and require only credentials for enabled providers. API keys belong in GitHub Actions repository secrets, never source code.
