# Production Release Gate — Decision-Support Engine

**Status: NOT APPROVED FOR PRODUCTION**  
**Allowed operating mode: read-only analysis and synthetic testing.**  
**Execution authority: none.**

A release is assessed against one exact commit SHA. Evidence from older commits, a partial run, an individual passing test or an editable metadata field does not satisfy a release gate.

## Gate 0 — Scope and authority

- [ ] Product scope, supported asset classes, exclusions and intended users documented.
- [ ] Investor mandate independently captured and reviewed for the specific client case.
- [ ] Application and generated outputs explicitly state that they are non-executable.
- [ ] No broker, registrar or payment execution integration is enabled.
- [ ] A separate, tested execution authorization control exists outside this decision-support engine if a future product intends to execute trades.

**Current status:** The codebase contains mandate guards, but no production authorization is granted.

## Gate 1 — Input integrity and client isolation

- [x] Advisor entry points require `MF_CLIENT_DATA_DIR`, reject repository-local client paths, and write generated reports beside the external client data.
- [ ] CAS statements, transactions, scheme master records and factsheets have source, retrieval date, statement period, digest and reviewer metadata.
- [ ] Duplicate folios, duplicate ISINs, unexplained transactions, missing scheme mappings and CAS reconciliation breaks fail closed.
- [ ] Stale or incomplete data produces a structured unavailable / NO ACTION state.
- [ ] No investor-identifying data appears in source code, tests, documentation, logs, screenshots or artifacts.
- [ ] All historical Git objects containing previously committed client data have been purged by a repository owner.
- [ ] Old clones, forks, Actions artifacts, caches, releases and PR refs have been reviewed; collaborator clones have been replaced.
- [ ] Any committed credential has been rotated.

**Current status:** The current tree contains no client-specific data directory or portfolio records. Both advisor entry points now require an explicit external data directory, and generated outputs stay outside the repository. Historical Git objects, old clones, forks and retained artifacts have not been purged or independently reviewed. See `SECURITY_DATA_HANDLING.md`.

## Gate 2 — Candidate universe and recommendation integrity

- [ ] Candidate universe is complete for the intended market/category universe and has a dated source refresh.
- [ ] Scheme name, plan type, ISIN, category, AMC, benchmark and scheme structure are resolved from authoritative scheme-level records.
- [ ] Direct-plan status has a reviewer-attested local source document with an actual file digest; source publisher authenticity remains separately reviewed.
- [ ] Every candidate passes every applicable eligibility gate. No exception bypasses AUM, riskometer, data integrity, concentration, manager, mandate or plan gates.
- [ ] Candidate ranking is computed only after eligibility.
- [ ] Weights derive from one authoritative policy file and reconcile exactly.
- [ ] If any slot with a positive target has no qualifying candidate, its budget remains explicitly unallocated and no other slot receives it.
- [ ] Thematic satellites remain zero unless separately authorized by the IPS and carved out of the equity budget.
- [ ] Fund names and folios are never inferred from labels, IDs or fuzzy matching.

**Current status:** Selection and Direct-plan controls are being hardened. Full scheme-master source evidence and independent candidate-universe reconciliation remain release prerequisites.

## Gate 3 — Allocation and cash deployment

- [ ] Strategic asset allocation, new-SIP routing, current holdings, stability buffer and optional satellites are treated as separate quantities.
- [ ] Tier 6 100% equity new-SIP routing requires an explicit IPS override.
- [ ] Emergency reserve and available bank cash are independently verified from source evidence.
- [ ] SIP and lumpsum proposals reconcile: allocated + unallocated = requested budget.
- [ ] Lumpsum staging, parking instruments, exit loads, tax consequences and STP duration are validated from actual scheme documents and client constraints.
- [ ] No fixed 20/80 deployment, universal staging horizon, assumed yield or fabricated tax saving appears in an actionable output.
- [ ] Missing candidate, cash or staging evidence leaves the entire relevant amount unallocated.

**Current status:** Lumpsum logic is intentionally fail-closed; a validated tranche-construction implementation is not yet release-eligible.

## Gate 4 — Tax and legal review

- [ ] Applicable statute and version are selected by the actual transfer date.
- [ ] Acquisition dates, instrument type, fund-of-funds structure and annual observation period are verified for each tax lot.
- [ ] Section 198 monthly opening/closing observations and the correct direct-fund / qualifying FoF limb are evidenced.
- [ ] Section 50AA and Section 76 composition observations and date boundaries are evidenced under the applicable provision.
- [ ] Market-linked debentures are classified as instruments, not mutual-fund units.
- [ ] Tax planner supports every asset class it accepts; unsupported debt/non-equity cases are rejected.
- [ ] Loss netting, surcharge, cess, exemption utilization, holding period, exit load and tax-lot allocation are independently reconciled.
- [ ] Current Indian tax counsel / qualified reviewer signs off the interpretation for the release.
- [ ] Evidence hashes are recomputed from local source bytes. Reviewer attestation is not represented as publisher authentication.

**Current status:** Tax classifiers and tests are provisional. Statutory legal interpretation and scheme-level evidence have not received independent release sign-off.

## Gate 5 — Benchmark and performance claims

- [ ] Official historical daily TRI source files are obtained for each benchmark.
- [ ] Original source files, exact index identifiers, retrieval dates, URLs and SHA-256 digests are preserved.
- [ ] An independently sourced NSE trading-session calendar spans every investor cash flow through the terminal valuation date.
- [ ] Every daily market session is covered by actual observations; no interpolation or extrapolation is used.
- [ ] Non-trading-day flow convention, switches, STPs, dividends, reversals and terminal value are independently reconciled.
- [ ] Portfolio XIRR and matched benchmark XIRR are independently recomputed by a second implementation.
- [ ] Benchmark relative performance and fund rankings are blocked when evidence is incomplete.

**Current status:** **BLOCKED.** Checked-in TRI files are provisional fixtures; one frequency is explicitly monthly/interpolated; no authenticated historical daily source file or separate verified NSE calendar is committed. See `docs/TRI_CALENDAR_DATA_CONTRACT.md` and `data/policy/TRI_FIXTURE_PROVENANCE.md`.

## Gate 6 — Software quality and reproducibility

- [x] Complete P0 invariant suite passes on code SHA `609bd8a`.
- [x] Complete correctness regression suite passes on code SHA `0f1e1b9`.
- [ ] Property-based and boundary tests cover money, dates, XIRR, tax lots, coverage, duplicates and invalid inputs.
- [x] Universal policy checks pass against central policy files, without duplicated hardcoded thresholds.
- [x] The two current test skips are the documented private-CAS integration checks; they are isolated and skipped when client files are absent.
- [x] Clean-checkout privacy and engine initialization tests pass.
- [x] Runtime and development dependencies are hash-locked, and CI verifies `pip install --require-hashes`, `pip check` and `pip-audit`.
- [ ] Supported Python version and runtime platform are pinned and verified.
- [x] Dependency vulnerability review: `pip-audit` reports no known vulnerabilities in the hash-locked dependency tree.
- [ ] Static analysis, formatting, type checking and secret scanning pass.
- [x] CycloneDX dependency SBOM is generated and retained as a GitHub Actions artifact (digest recorded above).
- [ ] Production release artifact digest and independent reviewer sign-off are retained.

**Current status:** Full CI passed on SHA `0f1e1b9` (123 passed, 2 private-CAS integration skips). The same SHA passed hash-locked installation, `pip check` and `pip-audit`. Independent SBOM review, static analysis, formatting/type checking and secret-scan evidence remain outstanding.

## Gate 7 — GitHub release controls

- [ ] `main` protected by a repository ruleset.
- [ ] All changes require a PR and at least one approval from an independent reviewer.
- [ ] Required status check is configured for the CI test job.
- [ ] Stale approvals are dismissed after subsequent commits.
- [ ] Conversation resolution is required.
- [ ] Force pushes and branch deletion are prohibited for ordinary maintainers.
- [ ] Branch/ruleset bypass is disabled or tightly controlled and audited.
- [ ] The release owner is not the sole code author and approver.
- [ ] The exact approved SHA, test run, report, review sign-off and artifact digest are recorded.

**Current status:** `main` was last observed as unprotected. The GitHub connection available to this workflow can inspect branch protection but cannot change repository administration settings. Follow `SECURITY_DATA_HANDLING.md` in GitHub Settings.

## Release decision

The release owner must mark every applicable gate complete and attach evidence against one SHA before production approval. Until then:

- no investment order or transaction may be generated;
- no matched TRI alpha or fund ranking may be presented as verified;
- tax outputs must remain provisional and subject to review;
- missing inputs must produce NO ACTION / HOLD;
- all unallocated budget must remain explicitly unallocated.

**Default decision: NOT APPROVED FOR PRODUCTION.**
