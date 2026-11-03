# Security, Client-Data Purge and Production Branch Controls

This repository has previously contained client-specific portfolio configuration, transaction ledgers, fund metrics and aliases. Those files have been removed from the current working tree and the private-data paths are ignored. **This does not remove the historical Git objects from prior commits or from existing clones.**

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

Remove the former client-data directory from every commit reachable from the mirrored refs:

```bash
git filter-repo --path data/lalit_portfolio/ --invert-paths
```

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
5. Require the GitHub Actions status check for the CI workflow's `test` job. Confirm the exact displayed check name in the latest successful workflow run before selecting it.
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
