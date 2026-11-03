# Reproducible Python dependency lock

**Status:** `requirements.lock` is regenerated from `requirements.txt` and has passed a hash-enforced installation, `pip check`, `pip-audit`, and the full test suite on CPython 3.11 / Ubuntu in the dependency-cleanup workflow. CI now installs the lockfile for all Python test jobs and independently checks that it remains synchronized with its declared inputs.

## Files and roles

- `requirements.txt`: human-maintained direct dependency constraints. It is not a reproducible installation manifest.
- `requirements.lock`: resolved direct and transitive dependency graph with package hashes. All CI test jobs, security checks, and release gates install this file with `--require-hashes`.

## Verify the lock from a clean environment

```bash
python -m venv .venv-lock-check
# Activate the environment, then:
python -m pip install --require-hashes -r requirements.lock
python -m pip check
python -m pip install pip-audit
pip-audit -r requirements.lock
```

The Security workflow performs these checks automatically. Do not use `pip install -r requirements.txt` for CI tests or release builds; use the hash-locked file.

## Regenerate after changing dependencies

Use a clean CPython 3.11 environment on the supported Ubuntu CI platform. The repository's current lock-generation toolchain pins pip because `pip-tools==7.4.1` is incompatible with the newest pip release:

```bash
python -m pip install "pip==24.3.1" "pip-tools==7.4.1"
pip-compile --resolver=backtracking --generate-hashes \
  --output-file=requirements.lock requirements.txt
```

Commit the input constraints and lock together. Do not hand-edit package versions or hashes. The CI `Dependencies / lock matches declared constraints` job regenerates the lock from `requirements.txt` and uses `git diff --exit-code` to fail if the committed lock changes. After regeneration, review the resolved dependency graph and require the full test suite, `pip check`, and `pip-audit` to pass before release.

## Security notes

- `python-jose` is intentionally not declared; do not reintroduce it without a maintained implementation and explicit algorithm/key restrictions.
- `xhtml2pdf` has been removed; PDF output uses ReportLab flowables.
- The lock is a platform-specific resolution for CPython 3.11 on Ubuntu. Other deployment platforms require their own lock and validation.
- A clean dependency audit does not replace an independent SBOM review, static analysis, secret scanning or production security review.

## Refresh cadence

Review Dependabot updates weekly. Regenerate the lock through `pip-compile`, review the diff, and rerun the complete suite and dependency audit. Keep the lock synchronized with the direct dependency constraints on every dependency change.
