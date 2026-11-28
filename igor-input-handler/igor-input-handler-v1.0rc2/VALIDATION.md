# Validation record — 1.0.0rc2

Validation performed in the isolated build environment:

- Python runtime: CPython 3.13.18.
- Test runner: pytest; **85 tests passed**.
- Branch-aware coverage: **96.86%** (90% minimum enforced).
- Independent configuration oracle: **1,356 valid** and **165 invalid** marker pairs checked; all matched the implementation's acceptance/rejection behavior.
- Python 3.10–3.14 compatibility: automated GitHub Actions matrix added; remote CI results are pending.
- Package build and wheel smoke test: pending execution.

The workflow first runs `python -m pytest --collect-only -q`, which fails if no tests are collected, then runs the full suite with branch-aware coverage enforcement.

Python 3.10 has not yet been executed locally in this validation environment. These results do not guarantee the implementation is defect-free or ready for a stable release.
