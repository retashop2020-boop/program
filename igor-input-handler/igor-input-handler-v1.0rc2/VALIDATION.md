# Validation record — 1.0.0rc2

Validation performed in the isolated build environment and GitHub Actions:

- Local runtime: CPython 3.13.18.
- Local test runner: pytest; **85 tests passed**.
- Local branch-aware coverage: **96.86%** (90% minimum enforced).
- Independent configuration oracle: **1,356 valid** and **165 invalid** marker pairs checked; all matched the implementation's acceptance/rejection behavior.
- GitHub Actions compatibility matrix: **Python 3.10, 3.11, 3.12, 3.13, and 3.14 all passed** test collection and the complete test/coverage step. [Workflow run](https://github.com/retashop2020-boop/program/actions/runs/46085612767).
- Wheel build and separate-target installation smoke test: not yet performed.

The workflow first runs `python -m pytest --collect-only -q`, which fails if no tests are collected, then runs the full suite with branch-aware coverage enforcement.

These results establish broad compatibility evidence for the supported Python matrix, but do not guarantee the implementation is defect-free or ready for a stable release.
