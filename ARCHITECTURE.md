# Architecture status

**Status: Historical architecture document retired — not normative.**  
**Release status: NOT APPROVED FOR PRODUCTION.**

The former v3.2 architecture narrative has been removed because it contained portfolio-specific figures, stale allocation and tax assumptions, and execution claims that do not describe the verified release state.

Use these sources for the current repository state:

- [README.md](README.md) — product scope, operating constraints and current high-level components.
- [PRODUCTION_RELEASE_CHECKLIST.md](PRODUCTION_RELEASE_CHECKLIST.md) — authoritative release gates and evidence requirements.
- [VERIFICATION_REPORT.md](VERIFICATION_REPORT.md) — commit-specific automated verification and remaining limitations.
- [SECURITY_DATA_HANDLING.md](SECURITY_DATA_HANDLING.md) — client-data handling and repository controls.
- `data/policy/` — machine-readable policy inputs used by the implementation.
- `core/` and `tax/` — current implementation modules.

This repository does not currently contain a complete, independently approved normative architecture specification. Do not infer production readiness, trade-execution authority, tax correctness, or benchmark validity from legacy documents or code comments. A versioned architecture specification and independent review remain release prerequisites.
