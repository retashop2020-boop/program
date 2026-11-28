# Follow-up Work Plan — Igor Input Handler 1.0.0rc2

**Status:** Deferred work; not a release approval.  
**Baseline:** `1.0.0rc2` review candidate on `main`.  
**Rule:** Keep `v1.0.0rc1` immutable. Do not alter the rc2 production module merely to make the tests pass; every behavior change needs a reproducible defect, an agreed contract change, and regression tests.

This file records the work intentionally left for a later session so that Ilan design can continue without losing the remaining module tasks.

## 1. Current verified baseline

- The rc2 CI workflow passed on CPython 3.10, 3.11, 3.12, 3.13, and 3.14.
- The local run recorded 85 passing tests and 96.86% branch-aware coverage.
- The independent configuration oracle checked 1,356 accepted and 165 rejected marker-pair configurations.
- The production file `igor_input_handler.py` is byte-for-byte unchanged from rc1; rc2's main changes are stronger tests, package metadata, documentation, and CI.
- rc2 is still a review candidate. It is not tagged as a stable release.
- A wheel build and installation test from the built distribution have not yet been performed.
- No open-source license has been selected. Do not publish or redistribute this candidate as an openly licensed package until the project owner makes that decision.

These are validation results, not proof that the implementation is defect-free.

## 2. Remaining work — in recommended order

### P0 — Independent contract and implementation review

**Goal:** Find defects that the current tests and their reference oracle may share or fail to expose.

Review the exact rc2 source and documentation without modifying them first. Use `REVIEW_BRIEF.md` as the review specification.

Required review areas:

- Token grammar and parsing boundaries for arbitrary custom markers, including markers that share a first character or contain one another's ordinary characters.
- Escape runs, marker-like text, and literal Mode 2 end-marker lines.
- The complete logical-body domain for the round-trip invariant: `decode(encode(body)) == body`.
- Equivalence of Mode 1 and Mode 2 for equivalent logical messages.
- Exact lazy-iterator consumption, EOF handling, and propagation of unrelated iterator exceptions.
- Unicode behavior and the documented distinction between CR/LF and other Unicode line-separator characters.
- Python 3.10 language/runtime compatibility and agreement between README, exceptions, and implementation.

**Deliverable:** A written findings report. Every claimed defect must include its location, a reproducible counterexample, expected behavior, and severity (Critical/High/Medium/Low). Separate confirmed defects from preferences and speculative risks.

**Exit condition:** No unresolved Critical or High finding. Medium/Low findings must be fixed, explicitly accepted, or recorded as deferred with rationale.

### P1 — Build and install the distributable package

**Goal:** Verify the artifact users would actually install, not only the source checkout.

Tasks:

1. Build both wheel and source distribution from the rc2 package directory using an isolated build environment.
2. Inspect the artifacts: module inclusion, README metadata, version, Python requirement, dependencies, and license metadata.
3. Create a fresh virtual environment outside the repository/source directory.
4. Install the wheel into that environment.
5. Import the installed module while the current directory is outside the source tree; verify the imported module path belongs to the installed environment.
6. Run a small public-API smoke test for both input modes, decoding, custom configuration, and an invalid configuration.
7. If practical, install the source distribution in a second clean environment and repeat the import/smoke test.
8. Record exact commands, tool versions, artifact names, and outcomes in `VALIDATION.md`.

**Exit condition:** Wheel and sdist build successfully; clean-target installation and public API smoke tests pass; no accidental source-tree import masks a packaging defect.

### P2 — Close test gaps only where review justifies them

Potential additions to consider after the independent review:

- Property-based or generated tests over a broader range of custom marker shapes and message contents.
- More direct tests for marker contents that overlap ordinary text in complex ways.
- Explicit regression tests for every confirmed review finding.
- A check that the built wheel contains exactly the intended public module and does not accidentally include tests or development-only files.
- Mutation testing as an optional diagnostic, not as a substitute for reviewing the contract.

Do not add tests merely to inflate coverage. The existing 90% branch-coverage threshold is a guardrail, not the quality objective.

### P3 — Release decision

Before a stable release:

- Resolve the independent review report.
- Complete the distribution build/install checks.
- Confirm README, changelog, package metadata, and validation record agree.
- Make an explicit license decision and add the corresponding license file/metadata only after that decision.
- Decide whether the public API and behavioral contract are stable enough for 1.0.
- Only then create a stable release tag and release notes.

Until these conditions are met, keep rc2 labelled as a review candidate and do not create a stable tag.

## 3. Ilan integration — separate workstream

The module is intended to be a small, interface-independent input component. Integration into Ilan must not turn it into a terminal UI, Telegram receiver, model client, or message-processing subsystem.

### Integration principles

- Keep `igor_input_handler.py` independent and free of terminal I/O, Telegram, prompt-toolkit, model calls, network access, and Ilan-specific imports.
- Let Ilan's input adapter own the user interaction and translate the adapter's collected input into the module's public API.
- Keep input collection separate from the later message-processing path. The adapter should return the one canonical encoded string expected by the agreed Ilan message contract.
- Do not duplicate marker parsing or Escape handling inside Ilan if the module already owns that behavior.
- Do not modify the legacy Telegram receiver or unrelated bridge components as part of this integration.
- Pin or vendor a reviewed version deliberately; do not silently track a moving source file or assume rc2 is already a stable dependency.

### Decisions to make when Ilan design resumes

1. Identify the exact input-adapter boundary and the current message hand-off contract in Ilan.
2. Decide whether the adapter should call `from_text()` after a UI has collected a complete message, or `from_lines()` when it can provide a lazy line source ending at the exact configured terminator.
3. Define which layer owns the end-of-message interaction. Avoid having both the UI and Input Handler independently consume or strip the same terminator.
4. Map Ilan's current Enter / send behavior to the module's two modes without changing user-visible behavior unintentionally.
5. Define how EOF, Ctrl-C, incomplete input, and module exceptions are translated into Ilan's existing cancellation/error/reporting behavior.
6. Decide where marker configuration lives and how it is supplied; do not scatter marker literals across the adapter and core.
7. Add adapter-level tests using a fake input source. Verify canonical output, blank lines, literal marker text, termination, cancellation, and that no extra line is consumed.
8. Run the existing Ilan tests and a manual end-to-end terminal check before enabling the new adapter by default.

**Integration exit condition:** The adapter uses only the public module API; Ilan's message-processing core remains independent of terminal mechanics; existing behavior and cancellation semantics are covered by tests.

## 4. Explicitly out of scope for this follow-up

Unless a later design decision expands scope, do not add these to Igor Input Handler:

- Terminal rendering, key bindings, or prompt-toolkit UI.
- Telegram, GUI, web, or asynchronous transport adapters.
- Model communication, prompt construction, response parsing, or conversation history.
- File storage, logging, network access, or background services.
- Ilan lifecycle, relay, or bridge management.

These belong to the application or adapter layer, not this standalone module.

## 5. Suggested session order

1. Independent review against `REVIEW_BRIEF.md`.
2. Triage and resolve confirmed findings.
3. Build wheel/sdist and test clean installations.
4. Update `VALIDATION.md` with evidence.
5. Make the explicit release/license decision.
6. Resume Ilan input-adapter design and integrate the reviewed module behind that boundary.

**Do not restart the module design from zero.** Reuse the rc2 baseline and this checklist; reopen a design decision only when review evidence or Ilan's actual integration contract requires it.
