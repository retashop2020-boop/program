# Ilan Relay Phase 2 — HTTP server component

This package contains a revised HTTP Relay server component and isolated HTTP
unit tests. It is **not production-integrated** and must not be launched as the
production Relay yet.

## Files

- `core/relay_server.py` — fixed-upstream HTTP server, session heartbeat and
  authenticated shutdown endpoints.
- `tests/test_relay_server.py` — HTTP tests using a fake session manager and a
  local fake Ollama endpoint. These tests do not replace the real
  `relay_session.py` unit tests.

## Copy into the WSL project

Copy the two Python files into the matching directories under:

`~/ilan-lab/ilan-bootstrap`

Do not overwrite `core/relay_session.py`, `main.py`, AgentLoop, Bridge files,
firewall settings, or Ollama settings.

## Test

```bash
python -m pytest -v tests/test_relay_session.py tests/test_relay_server.py
```

The HTTP tests bind only to loopback and use a local fake upstream. They do not
verify the Windows WSL interface bind, real Windows Ollama connectivity,
production lease timings, Relay process ownership/recovery, secure credential
persistence, firewall behavior, or `main.py` lifecycle integration.

The server's `close()` method is intended to be called by the future lifecycle
owner after the serve thread has started. Production startup and ownership
supervision are a later phase.
