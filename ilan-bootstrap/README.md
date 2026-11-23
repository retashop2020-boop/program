# Ilan Bootstrap

Ilan Bootstrap is a local Python agent workspace. It connects an agent loop to one of three model providers (Ollama, OpenRouter, or Gemini) and exposes a small set of workspace tools for listing and reading files, proposing patches, and running a registered test profile.

This snapshot includes the Relay session manager, HTTP server, and lifecycle components with unit and integration tests. The Relay lifecycle is integrated into `main.py`: it starts with the application, binds to the dynamically discovered WSL `eth0` IPv4 address, and stops during application shutdown. This integration does not by itself establish a production-ready Windows deployment.

## Requirements

- Python 3.10 or newer.
- `pytest` to run the project test suite.
- Docker Engine is needed only when using Ilan's Docker-backed test-execution tool. The default test image is `ilan-test:0.1`.
- A model provider and its corresponding local service or API credentials are needed to run interactive model conversations.

The application code uses Python's standard library; no third-party runtime Python packages are currently required. Development/test dependency is listed in `requirements-dev.txt`.

## Install and run tests

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

On Windows PowerShell, activate the environment with:

```powershell
.venv\Scripts\Activate.ps1
```

The test suite uses local fakes and loopback HTTP servers where applicable; it does not require live Ollama, OpenRouter, or Gemini credentials.

## Configure a model provider

Select the provider with `ILAN_MODEL_PROVIDER` (`ollama`, `openrouter`, or `gemini`). The default is `ollama`.

### Ollama

- `ILAN_OLLAMA_URL` — base URL; defaults to `http://localhost:11434`.
- `ILAN_OLLAMA_MODEL` — model name; defaults to `gpt-oss-20b-local:latest`.
- `ILAN_OLLAMA_TIMEOUT` — request timeout in seconds; defaults to `2000`.
- `ILAN_THINKING_MODE` — `auto`, `on`, or `off`; defaults to `auto`.

### OpenRouter

- `OPENROUTER_API_KEY` — required API key.
- `OPENROUTER_MODEL` — required model identifier.
- `OPENROUTER_SITE_URL` — optional HTTP Referer metadata.

### Gemini

- `GEMINI_API_KEY` — required API key.
- `GEMINI_MODEL` — optional model identifier; defaults to the value in `model/gemini.py`.

Set credentials through your shell environment or a secret manager. Do not commit API keys, tokens, or `.env` files.

## Workspace and tools

- `ILAN_WORKSPACE` sets the workspace directory. The default is `~/ilan-lab/ilan-workbench/workspace`.
- Registered tools include `list_files`, `read_file`, `apply_patch`, and `run_tests`.
- Patch application requires interactive approval. Administrative operations use an approval callback.
- The test execution tool uses Docker with the image `ilan-test:0.1`; `Dockerfile.test` defines that image. Build it from the repository root with:

```bash
docker build -f Dockerfile.test -t ilan-test:0.1 .
```

The configured Docker command currently uses `sudo -n docker` on Linux. Adjusting that policy is an environment/deployment decision, not an automatic setup step.

## Relay status and limitations

The Relay session manager, HTTP server, and lifecycle components are implemented. The application lifecycle in `main.py` starts and stops the Relay, and the bind address is obtained by discovering the WSL `eth0` IPv4 address.

The session manager generates and validates session, owner, and recovery credentials. A successful recovery reconnect rotates the owner and recovery tokens. The current session manager keeps this state in memory and does not provide filesystem persistence.

The following areas are not yet verified as complete:

- Windows-side Relay process ownership and launch supervision from WSL.
- Secure persistence and transfer of recovery credentials across application or WSL restarts.
- End-to-end communication through the Relay to the Windows Ollama service.
- Deployment-specific firewall behavior and network exposure restrictions.
- Full WSL shutdown/reboot recovery and multi-process stress testing.

Authentication for the `/api/chat` endpoint is proposed separately in PR #4 and is not included in this snapshot. Do not expose the Relay beyond its trusted interface or treat this snapshot as a production-ready deployment. No firewall rules are changed automatically by this project.
## Project layout

- `agent/` — agent loop.
- `core/` — authorization, workspace boundary, test execution, and Relay components.
- `model/` — Ollama, OpenRouter, and Gemini clients.
- `tools/` — tool registration and dispatch.
- `tests/` — unit and local integration tests.
- `Dockerfile.test` — isolated pytest execution image.

## Safety notes

Review workspace paths and proposed patches before approval. Keep credentials outside the repository. Do not expose the Relay listener beyond its intended trusted interface, and do not use this snapshot as a production Relay deployment without completing the remaining deployment and security work above.
