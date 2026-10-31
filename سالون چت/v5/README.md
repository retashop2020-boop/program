# Saloon V5 — Foundation

V5 is a separate architectural line. V4.1 remains unchanged.

## Stage 1 scope

This foundation implements the round boundary and the data contracts needed to
protect model independence. It deliberately does not yet include the web UI,
OpenRouter transport, disk persistence, context retrieval, or production
logging.

## Core invariants

1. Every enabled slot receives the same immutable snapshot of the shared
   conversation context and the current user message.
2. A slot receives only its own slot memory.
3. No member's current-round response is added to another member's request.
4. Public responses are committed to shared context only after all enabled
   members have finished.
5. Slot memory is versioned: a new update adds a version and does not erase
   earlier versions.
6. A member failure is isolated; other members still run. A failed member does
   not publish a public response or a memory update.

## Layout

- `saloon_v5/models.py`: immutable data contracts.
- `saloon_v5/orchestrator.py`: isolated parallel round execution.
- `tests/test_round_isolation.py`: tests for the key architecture invariants.

## Run tests (Python 3.10+)

From this directory:

```powershell
python -m unittest discover -s tests -v
```

This is an initial foundation, not a complete application. Persistence,
retrieval policy, structured model-output parsing, API transport, UI, and
member lifecycle logging are later stages.
