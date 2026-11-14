# Security, Client-Data Purge and Production Branch Controls

This repository has previously contained client-specific portfolio configuration, transaction ledgers, fund metrics and aliases. A history review confirmed that the initial commit `b28f008b` also included a `.env` file containing third-party provider API credentials. Client configuration and transaction files were later removed in commits including `e7ebf41e` and `8689873d`. Those removals cleaned later trees; they did not erase the historical Git objects or existing clones.

**Treat every credential ever present in the committed `.env` as compromised and rotate it with its provider.** Do not restore or reproduce the old values. As of 2026-11-14, GitHub reports this repository as public (`private=false`). This violates the required privacy boundary: the owner must make it private immediately. Making it private does not revoke exposed credentials or purge historical objects.

The repository must remain private until the history-remediation steps below are completed.

## 1. Freeze and preserve

1. Temporarily stop pushes and merges to the repository.
2. Confirm the current `main` working tree contains no private client data.
3. Make a restricted, encrypted backup of any client files that must be retained for lawful records. Do not put that backup in this repository.
4. Identify all branches, tags, pull-request refs, release assets, Actions artifacts, logs, cached reports and forks that may contain the former data.
5. Treat all previously committed client information as disclosed to anyone who had read access to the repository during the exposure period.

## 2. Rewrite Git history locally

This is a destructive repository-wide operation. It should be run by the repository owner from a secure workstation, after preserving any required compliance backup.

Install `git-filter-repo` and create a mirror clone:

```bash
git clone --mirror https://github.com/o0k00l/MF-AI-Based.git MF-AI-Based-purge.git
cd MF-AI-Based-purge.git
```

Remove every confirmed sensitive path from every commit reachable from the mirrored refs. The initial commit contained the provider-key file, client CAS/CGS statements, transaction/configuration/metrics/alias files, and generated investor reports:

```bash
git filter-repo \
  --path .env \
  --path data/lalit_portfolio/ \
  --path outputs/ \
  --invert-paths
```

Before pushing the rewritten history, inspect the full initial-commit path list and all path-specific history for any additional client-data or credential files. Add every confirmed path to the same filter operation; do not assume the three paths above are exhaustive.

`git-filter-repo` may remove the `origin` remote as a safety measure. Re-add it and force-update the branches and tags only after inspecting the rewritten history:

```bash
git remote add origin https://github.com/o0k00l/MF-AI-Based.git
git push --force origin --all
git push --force origin --tags
```

Do not restore the former client-specific directory or any of its JSON, statement, transaction or report files. External-data setup instructions are maintained in the root README.

### Verify the purge

- Search every reachable branch and tag for the former data paths and unique client identifiers.
- Inspect the rewritten commit graph and confirm that no old commits containing client data remain reachable.
- Check GitHub pull-request refs, cached file URLs, Actions artifacts, logs, releases and forks. A branch rewrite does not automatically delete every separately retained artifact or clone.
- For cached GitHub views or objects not removable through the repository's refs, contact GitHub Support and request sensitive-data cache removal.
- Require all collaborators to delete old clones and re-clone the rewritten repository. Do not merge old branches or push old tags back.
- Rotate any credentials or tokens that were ever committed. Do not assume that making the repository private retroactively removes access.

A force-push changes repository history and disrupts existing clones. Do not run it during ordinary development.

## 3. Protect `main`

At the time of this document, `main` was not protected and had no required status checks. Enable controls in GitHub's repository settings:

1. Open **Settings → Rules → Rulesets** (or **Settings → Branches → Branch protection rules**, depending on the GitHub UI).
2. Create a branch ruleset targeting the exact branch name `main`.
3. Require a pull request before merging, with at least one approval from a reviewer who did not author the change.
4. Dismiss stale approvals when new commits are pushed.
5. Require the current CI checks shown by GitHub for the exact `main` commit. The latest verified CI run exposes six jobs: `Dependencies / lock matches declared constraints`, `P0 / fiduciary-invariants`, `P0 / correctness-regressions`, `Tests / full repository suite`, `Policy / static validation`, and `Benchmark / fixture integrity (not alpha approval)`. Select the exact check names displayed by GitHub; do not configure a stale `test` job name. Also require `Security / pip-audit` if the repository's ruleset supports checks from the Security workflow.
6. Require conversation resolution.
7. Block force pushes and branch deletion.
8. Do not allow bypass for ordinary maintainers or the implementation author. Document any emergency administrator bypass and require an audit record.
9. Require the production release checklist to be approved independently of the implementation author.

A PR-based workflow is intended for future maintenance; it does not change the historical fact that earlier repairs were committed directly to `main`.

## 4. Current code and data-handling rules

- Client data belongs outside the repository in a local directory supplied through `MF_CLIENT_DATA_DIR`.
- Commit only schemas, empty templates and synthetic test fixtures.
- Never commit CAS statements, folio identifiers, transaction histories, identity data, bank balances, tax-lot details or client reports.
- A filename being ignored is not proof that it is absent from a commit. Review `git status --ignored`, `git ls-files` and the actual staged diff before committing.
- Never use real-client values in unit tests, examples, screenshots, logs or benchmark fixtures.

## 5. Production-release conditions

The application remains a non-executable decision-support prototype until the release report records the exact release SHA, complete passing CI results, tax/legal review, authenticated benchmark data and calendar, private-data purge verification, protected-branch status and independent reviewer sign-off.


## 6. External AI and third-party lookup approval

External processing is **default-deny**. Two independent conditions are required before an AI-provider request is made:

1. The request path must receive explicit per-request investor consent (`external_processing_consent=True`). A deployment default, environment variable, or general terms acceptance is not a substitute for that investor's consent.
2. The deployment must set `MF_EXTERNAL_PROCESSING_POLICY_APPROVED=true` only after an authorized reviewer has approved the exact provider(s), applicable terms and data-use configuration. The code treats every missing, malformed or false value as denial.

The environment variable is an operator attestation gate, not proof that a review occurred. Keep the review record outside this repository and identify: provider and endpoint; terms/privacy-policy version and review date; prompt retention and deletion period; model-training/data-use opt-out status; subprocessors and processing region; security and access controls; incident notification; and contractual/DPA coverage. Re-review after a provider, endpoint, terms, retention policy or model changes. Do not enable the gate while any required item is unknown.

The gate applies to LLM narrative/classification requests and third-party online scheme lookups. Online scheme classification transmits only the canonical scheme name required to resolve that scheme (plan/option suffixes are stripped); it must not include a client's name, account/folio, balances, transaction history, goals or a holdings list. Narrative paths must continue to redact client/holding identifiers and numeric portfolio facts before the provider adapter. Provider failures and logs must not include prompts, credentials, raw response bodies or investor data.

Narrative-response caching remains disabled. The former repository-root `cache/narrative_cache.json` is removed on AI-engine startup; if it cannot be removed, external provider calls fail closed. This unlink operation does not guarantee forensic erasure from backups, snapshots or storage media, which require separate retention/purge handling. Do not re-enable caching through `use_cache`; the compatibility argument is ignored. The external model-catalogue cache contains provider catalogue metadata only and must remain outside the repository. Third-party scheme look-through query results are retained in process memory only; persistent disk caching is disabled because the queried scheme set can reveal an investor's holdings. A legacy `online_fund_lookthrough.json` in the configured engine-data directory is purged on startup.

The boolean consent argument is an enforcement input, not an auditable consent ledger. Production UI/API integration must source it from a recorded, purpose-specific investor consent event and retain the consent version, timestamp, scope, withdrawal and evidence in the approved client-data store. Do not infer consent from login, upload, service use or a global setting.

Before issue #44 can be closed, independently verify the production consent capture/withdrawal flow, provider review record, encrypted storage and access controls, retention/deletion behavior, and absence of investor payloads in application logs, telemetry, temporary files, CI artifacts and reports. These deployment facts cannot be established by repository unit tests alone.


## 7. Narrative/provider call-site inventory

The following inventory covers every active narrative/classification call path found in the repository source. The values listed are the fields assembled locally before the privacy boundary; only the minimized form described in the final column may leave the process.

| Call site | Locally assembled context | External payload after minimization / gate |
|---|---|---|
| `core/prompt_advisor.py:generate_health_audit_report` | Portfolio/invested value, unrealized gain, holding and Regular-plan counts, Regular-plan value/fee drag, current/target SAA and drift, overlap/risk/eligibility summaries, thematic/stability-buffer facts | Client, scheme, folio/account and other known holding identifiers are redacted; currency and all numeric facts are redacted. Generic qualitative report instructions remain. |
| `core/prompt_advisor.py:generate_switch_and_consolidation_plan` | Reported portfolio value, holding count, Regular-plan expense-difference estimates, unrealized gain and switch/eligibility context | Same identifier and numeric redaction; no exact scheme/folio or balances leave the process. |
| `core/prompt_advisor.py:generate_fresh_money_deployment_plan` | Investor age/horizon, risk tier, target SAA and monthly SIP budget/plan context | Age, horizon, allocations, budgets and other numeric facts are redacted; known investor and destination-scheme identifiers are redacted. |
| `core/prompt_advisor.py:answer_interactive_query` | Current question plus locally assembled fee, holding, SAA, cash-plan and deterministic SIP/lumpsum summaries | Arbitrary user-entered question is withheld entirely from third-party AI; only generic qualitative instructions and anonymized context are sent. Prior chat history is not appended. |
| `services/ai_fund_classifier.py:classify_fund_with_llm` and `batch_classify_funds_with_llm` | One requested scheme name, or a bounded batch of scheme names, plus the fixed SEBI classification schema | Only the requested public scheme name(s) and schema are sent. No investor name, folio/account, balances, transaction history, goals or portfolio list. Both gates are enforced and narrative caching is disabled. |
| `services/ai_fund_classifier.py:generate_fiduciary_ai_narrative` | Aggregate `total_value`, `eq_pct`, `debt_pct`, `regular_value`, `regular_pct`, `annual_bleed`, `compounded_10y_drag`, `unique_strategies_count`, `dual_count`, and fund records | Shared privacy helper removes known client/fund/folio/account/goal identifiers and all numeric facts; `use_cache=False`. |
| `services/ai_fund_classifier.py:answer_fiduciary_query` | User-entered question and the same aggregate portfolio metrics/fund records | User-entered question is withheld entirely from third-party AI; only anonymized generic context is sent. Known identifiers and numeric facts are removed; `use_cache=False`. |
| `services/ai_fund_classifier.py:lookup_fund_segment_allocation_online` | Canonical mutual-fund scheme name | Only that scheme name is sent to the third-party search/factsheet lookup. Per-request consent and deployment provider/privacy approval are both required. Returned third-party facts remain explicitly unverified. |
| `services/cgs_parser.py:evaluate_tax_harvesting_strategy` | Realized LTCG/STCG, Section 112A limit/headroom, unrealized equity gain, harvestable amount, potential tax saving and Regular-plan switch capacity | Identifier and numeric redaction runs before `call_llm`; no tax-lot/folio/client identifiers or amounts are transmitted. |
| `services/goal_planner.py:evaluate_goal_scenarios_with_ai` | Active-goal count, required SIP, monthly budget/deficit, inflation-shock SIP and accelerated-target SIP | Goal names/descriptions and numeric facts are redacted before `call_llm`. |
| `services/risk_profiler.py:predict_risk_tier_from_portfolio` | Portfolio value/count, equity/debt, mid/small-cap and thematic exposure, predicted tier | Known scheme/holding identifiers and every numeric fact are redacted before `call_llm`. |
| `core/ai_engine.py:call_llm` and provider adapters | Already-minimized prompt plus fixed, non-investor system instructions | Enforces per-request consent and deployment approval again at the provider network adapter. No narrative cache read/write; only OpenRouter/Requesty free-model adapters are eligible. |

Legacy `ui/app.py` calls that request live narrative without passing consent therefore remain on local fallback behavior; they do not silently opt in. Production use must wire the consent boolean to a recorded, purpose-specific consent event as described above.
