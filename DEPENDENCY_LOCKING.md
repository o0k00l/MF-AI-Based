# Reproducible Python dependency lock

**Status:** \`requirements.lock\` is present and has passed a hash-enforced install, \`pip check\` and \`pip-audit\` on CPython 3.11 / Ubuntu CI (run against commit \`abb36d0\`).

## Files and roles

- \`requirements.txt\`: human-maintained direct dependency constraints. It is not a reproducible installation manifest.
- \`requirements.lock\`: resolved direct and transitive dependency graph with package hashes. CI and release workflows install this file with \`--require-hashes\`.

## Verify the lock from a clean environment

\`\`\`bash
python -m venv .venv-lock-check
# Activate the environment, then:
python -m pip install --upgrade pip
python -m pip install --require-hashes -r requirements.lock
python -m pip check
python -m pip install pip-audit
pip-audit -r requirements.lock
\`\`\`

The repository's Security workflow performs these checks automatically. A lock install must not be replaced by \`pip install -r requirements.txt\` for release builds.

## Regenerate after changing dependencies

Use a clean CPython 3.11 environment on the supported Ubuntu CI platform:

\`\`\`bash
python -m pip install --upgrade pip
python -m pip install "pip-tools==7.4.1"
pip-compile --resolver=backtracking --generate-hashes \\
  --output-file=requirements.lock requirements.txt
\`\`\`

Commit the input constraints and lock together. Do not hand-edit package versions or hashes. Review the resolved dependency graph, run the full test suite and dependency audit, and verify \`pip check\` before merging.

## Security notes

- \`python-jose\` is intentionally not declared; do not reintroduce it without a maintained implementation and explicit algorithm/key restrictions.
- \`xhtml2pdf\` has been removed; PDF output uses ReportLab flowables.
- The lock is a platform-specific resolution for CPython 3.11 on Ubuntu. Other deployment platforms require their own lock and validation.
- A clean dependency audit does not replace an independent SBOM review, static analysis, secret scanning or production security review.

## Refresh cadence

Review Dependabot updates weekly. Regenerate the lock through \`pip-compile\`, rerun the complete suite and security audit, then merge through a protected PR after independent approval.
