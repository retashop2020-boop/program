# Changelog

## 1.0.0rc2 — 2026-11-28

- Removed the unselected MIT license classifier; package metadata now agrees with the licensing note.
- Added independent reference-encoder assertions for canonical output, round trips, and public/private encoder consistency.
- Added an independent configuration oracle and exhaustive validation of 1,356 valid configurations.
- Added branch-aware coverage enforcement and a Python 3.10–3.14 GitHub Actions matrix with collection and test-execution guards.
- Updated release and validation documentation for this candidate.

## 1.0.0rc1 — 2026-11-26

- Initial review-candidate implementation of the two input modes.
- Added configurable internal-enter and end markers with Escape encoding.
- Added public strict decoder and module-specific exception types.
- Added lazy line-source support and incomplete-input detection.
- Added standalone README, acceptance tests, and independent-review brief.
