# Neura Marketplace

Local hackathon implementation of an autonomous A2A marketplace:

`Human → JARVIS → MARCELO → Discover → Evaluate → Hire → Delegate → Verify → JARVIS`

JARVIS and MARCELO are separate FastAPI services. Every reasoning/worker invocation uses the NeuraLake OpenAI-compatible Chat Completions API with `model=auto` by default.

## Architecture

- **JARVIS (`:8000`)**: human-facing consultant. Clarifies only material ambiguity and emits a `GoalBrief`.
- **MARCELO (`:8001`)**: autonomous marketplace orchestrator. Creates a task DAG and performs `Discover → Evaluate → Hire → Delegate → Verify` for each task.
- **Marketplace**: Markdown agent catalog indexed into SQLite + FTS5. No human maps tasks to workers.
- **Worker invariant**: the selected agent Markdown is SHA-256 verified and passed unchanged as the worker's `system` message. MARCELO's bounded task brief is the `user` message.
- **Verifier**: independently discovered and hired from the same marketplace; MARCELO does not self-grade worker output.
- **A2A transport**: JARVIS submits jobs to MARCELO with HTTP `202 Accepted`; MARCELO calls JARVIS back with the final result/failure.
- **Audit UI**: JARVIS streams persisted marketplace events over SSE.

## Requirements

- Python 3.11+
- Git (only required to clone the full Agency Agents dataset)
- A valid NeuraLake API key

## 1. Setup

```bash
cp .env.example .env
# edit .env and set NEURALAKE_API_KEY

make setup
```

The repository includes a small original sample catalog so it boots without downloading anything else.

## 2. Use the full Agency Agents marketplace

```bash
make bootstrap-agents
```

This clones:

```text
https://github.com/msitarzewski/agency-agents.git
```

into `data/agency-agents/`. The application automatically prefers that directory when it contains Markdown files; otherwise it uses `data/sample-agents/`.

You can use any other local Markdown dataset by setting:

```bash
AGENT_DATASET_DIR=/absolute/path/to/your/agents
```

## 3. Index and test

```bash
make index
make test
```

## 4. Run locally

```bash
make dev
```

Open:

```text
http://127.0.0.1:8000
```

Health checks:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8001/health
```

Suggested demo goal:

```text
Launch an AI code review SaaS for small engineering teams. I need market research, MVP/product direction, implementation guidance, and a concrete launch plan. Optimize for something we can validate quickly.
```

## Runtime sequence

1. Human sends goal to JARVIS.
2. JARVIS either asks one material clarification or creates a `GoalBrief`.
3. JARVIS asynchronously submits an A2A job to MARCELO.
4. MARCELO generates a small dependency-aware task DAG.
5. For every task MARCELO searches the agent catalog (`DISCOVER`).
6. MARCELO compares only discovered candidate metadata and selects one (`EVALUATE`).
7. MARCELO creates a persisted contract (`HIRE`).
8. MARCELO builds a bounded task brief and executes the exact selected agent file as the system prompt (`DELEGATE`).
9. MARCELO independently discovers and hires a verifier (`VERIFY_DISCOVER` / `VERIFY_HIRE`).
10. Failed work is rejected and MARCELO autonomously discovers/rehires another worker, up to `MAX_TASK_ATTEMPTS`.
11. Accepted task outputs are synthesized and returned to JARVIS by callback.

## Security

- Never commit `.env`.
- Never put API keys in prompts, events, source code, screenshots, or Git history.
- Rotate any key that has already been pasted into chat or another untrusted surface.
- Marketplace worker files are read only from the configured dataset directory and SHA-256 checked immediately before execution.

## Push to GitHub

Create an empty GitHub repository, then:

```bash
git init
git add .
git commit -m "feat: autonomous A2A agent marketplace"
git branch -M main
git remote add origin git@github.com:YOUR_USER/neura-marketplace.git
git push -u origin main
```

Or with GitHub CLI:

```bash
gh repo create neura-marketplace --private --source=. --remote=origin --push
```

## Useful configuration

```text
NEURALAKE_BASE_URL=https://api.neuralake.cloud/v1
NEURALAKE_MODEL=auto
MAX_TASK_ATTEMPTS=2
MARKETPLACE_CANDIDATE_LIMIT=5
```

## Why no Codex runtime

This version calls NeuraLake's documented Chat Completions API directly. The agent behavior, delegation, marketplace selection, retries, verification, and audit trail are implemented by this application rather than depending on a separate coding-agent runtime.


http://32.197.43.221:8080/