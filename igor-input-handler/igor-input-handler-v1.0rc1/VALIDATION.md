# Validation record — 1.0.0rc1

Validation performed in the build environment for this review candidate:

- Python runtime: CPython 3.13.5.
- Test runner: pytest; **83 tests passed**.
- `compileall` completed successfully for the module and tests.
- A wheel was built successfully with the locally installed setuptools using `--no-build-isolation`.
- The wheel was installed into a separate target directory and passed an import/round-trip smoke test.
- An additional deterministic randomized check exercised **28,760** round trips across generated valid marker configurations; all passed.

Limitations:

- Python 3.10 itself was not available in this environment, so the declared Python 3.10 minimum has not been executed directly here. The implementation uses language and standard-library features available in Python 3.10, but a reviewer should run the suite on Python 3.10 before stable publication.
- The first isolated wheel-build attempt could not download build dependencies because network access was unavailable. The successful build used the already-installed local setuptools and `--no-build-isolation`.
- Independent review by Claude or another language model has not yet been performed.
- No public license has been selected; see `LICENSING_NOTE.md`.

These results establish local checks, not a guarantee that the implementation is defect-free or ready for a stable public release.
