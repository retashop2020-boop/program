# Independent Review Brief — Igor Input Handler 1.0.0rc2

Please conduct an independent technical review of this implementation and its documented contract, including the new independent reference encoder and exhaustive configuration oracle. Do not assume the design is correct merely because its tests pass. Do not modify files during the review.

## Review objectives

1. Find correctness defects in the encoder/decoder grammar, especially around token boundaries, shared marker prefixes, overlapping marker contents, Escape runs, and arbitrary custom markers.
2. Check that `decode(encode(body)) == body` holds for the entire documented logical-body domain.
3. Check that Mode 1 and Mode 2 produce identical canonical output for equivalent logical messages.
4. Examine the Mode 2 quoting rule for a literal end-marker line, including 1, 2, 3, and long Escape runs.
5. Check exact lazy-iterator behavior: no over-read after the end marker, correct EOF handling, and propagation of unrelated source exceptions.
6. Check configuration validation and Python 3.10 compatibility.
7. Look for mismatches between implementation, README, exception behavior, and the proposed 1.0 contract.
8. Identify unnecessary API complexity, portability concerns, Unicode edge cases, and documentation gaps.

## Important implementation facts to verify independently

- `I` and `E` are non-empty, distinct, and prefix-free. They may share their first character.
- `X` is one Python character, is not CR/LF, and does not occur in either marker.
- All first characters of control markers are escaped in ordinary encoded text.
- `X` is doubled in ordinary encoded text.
- An unescaped `I` token means one logical LF; one unescaped final `E` terminates the encoded message.
- Mode 1 normalizes CRLF/LF/CR; a final normalized LF is a submission event, not part of the body.
- Mode 2 lines contain no CR/LF, and only an exact `E` line terminates collection.
- For a literal Mode 2 line of the form `X^n + E`, one leading `X` is removed.

## Required review output

Please report:

- Findings ranked as Critical / High / Medium / Low.
- For each finding, the exact code or contract location, a concrete counterexample, expected behavior, and a proposed correction.
- Any properties you believe are not proven by the current test suite.
- Whether you recommend acceptance, acceptance after fixes, or redesign.

Please distinguish confirmed defects from stylistic preferences and speculative risks. Do not claim a defect without a reproducible example or a clearly explained violated invariant.
