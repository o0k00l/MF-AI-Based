# Reproducible Python dependency lock

**Current status: not complete.** `requirements.txt` is a human-maintained input file with open version ranges. Current security floors include Requests 2.33.0, python-dotenv 1.2.2, xhtml2pdf 0.2.20, pytest 9.0.3 and Pillow 13.0.0. It is not a reproducible environment and must not be used as the production installation manifest.

## Generate the lock on the supported build platform

The repository CI currently targets CPython 3.11 on Ubuntu Linux. Generate and review the lock on a clean CPython 3.11 environment for that target:

```bash
python -m pip install --upgrade pip
python -m pip install "pip-tools==7.4.1"
pip-compile --resolver=backtracking --generate-hashes \
  --output-file=requirements.lock requirements.txt
```

Commit both the input constraints and the generated lock together. Do not hand-edit transitive package versions or hashes. Review the resolved package list and every hash change in the PR. The lock must include the complete transitive dependency graph, package hashes and environment markers.

Verify installation from scratch:

```bash
python -m venv .venv-lock-check
# Activate .venv-lock-check, then:
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.lock
python -m pip check
python -m pytest test_p0_fiduciary_invariants.py -v --tb=short
python -m pytest tests/test_p0_correctness_regressions.py -v --tb=short
python validate_final_logics.py
```

The project does not currently declare a JWT library. The previous `python-jose[cryptography]` requirement was removed: the latest upstream 3.5.0 release is affected by a critical algorithm-confusion advisory, and no patched release is listed. Its default package dependency also brought in the `ecdsa` package, for which the upstream project states no planned fix for the Minerva timing issue. Do not re-add either library by transitive constraint. When an authenticated API is actually implemented, select a maintained JOSE/JWT implementation and restrict accepted algorithms and key types explicitly.

The production release workflow installs only from `requirements.lock` and fails closed while it is absent. Do not create a placeholder lock or claim reproducibility from `pip freeze` generated in an unclean developer environment.

## Platform policy

If the application is deployed on a platform other than Ubuntu Linux / CPython 3.11, define and test a separate lock for that target. Do not assume a Linux lock establishes Windows or macOS reproducibility. Record the Python implementation/version, OS image, architecture, package index, pip-tools version and lock-generation date in the PR/release notes.

## Refresh cadence

Use the weekly Dependabot PRs as review signals, not automatic release approval. Regenerate the lock through pip-tools, run the complete suite, review dependency audit results, and merge only through a protected PR after independent approval.
