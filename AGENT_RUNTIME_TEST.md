# Agent Runtime Patch — test sequence

This ZIP is an overlay patch. Extract it into the existing `neura-marketplace` repository root. It intentionally does not contain `data/agency-agents`; your existing 280-agent dataset remains in place.

## 1. Backup and overlay

```bash
cd neura-marketplace
git status
git add -A && git commit -m 'checkpoint before agent runtime' || true
unzip -o ../neura-marketplace-agent-runtime-patch.zip -d .
```

Keep your existing `.env`. It must contain a rotated `NEURALAKE_API_KEY`.

## 2. Rebuild from clean containers

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
docker compose ps
```

Expected services: `jarvis`, `marcelo`, `runner`, all healthy.

```bash
curl -fsS http://127.0.0.1:8000/health | jq
curl -fsS http://127.0.0.1:8001/health | jq
curl -fsS http://127.0.0.1:8002/health | jq
```

## 3. Re-index the real marketplace

```bash
docker compose exec marcelo python scripts/index_agents.py
```

Expected: `Indexed 280 agents from /app/data/agency-agents`.

## 4. Direct tool runner smoke

```bash
bash scripts/smoke_runner.sh
```

This proves, without an LLM:
- skill loading/invocation
- filesystem write/read
- real subprocess execution
- live web search
- live web fetch

## 5. Actual agent runtime smoke

```bash
docker compose exec marcelo python scripts/test_runtime.py
```

The Research Synthesist is forced to autonomously perform:

`skill.invoke -> web.search -> web.fetch -> filesystem.write -> final`

Copy the emitted `RUN_ID`.

## 6. Inspect audit trail

```bash
RUN_ID='paste-runtime-smoke-id-here'

docker compose exec -T marcelo env RUN_ID="$RUN_ID" python - <<'PY'
import json, os, sqlite3

db = sqlite3.connect(os.environ['DATABASE_PATH'])
db.row_factory = sqlite3.Row

print('\nEVENTS')
for r in db.execute('SELECT seq,event_type,actor,payload FROM events WHERE run_id=? ORDER BY seq', (os.environ['RUN_ID'],)):
    print(r['seq'], r['event_type'], r['actor'], json.loads(r['payload']))

print('\nTOOL CALLS')
for r in db.execute('SELECT agent_id,tool,status,arguments,output FROM tool_calls WHERE run_id=? ORDER BY started_at', (os.environ['RUN_ID'],)):
    print('\n', r['agent_id'], r['tool'], r['status'])
    print('args=', r['arguments'])
    print('out =', (r['output'] or '')[:1200])
PY
```

Expected events include `TOOL_REQUESTED` and `TOOL_COMPLETED` for the required tools.

## 7. Inspect durable workspace artifact

```bash
docker compose exec runner find /workspace -maxdepth 4 -type f -print
```

```bash
docker compose exec runner sh -lc 'find /workspace -name research.md -print -exec cat {} \;'
```

## 8. Run automated tests inside the image

```bash
docker compose exec marcelo python -m pytest -q
```

## 9. Full JARVIS -> MARCELO test

Use the UI at `http://127.0.0.1:8000`, or:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Launch a developer SaaS for 10-100 engineer teams. Research current competitors using the live web, create positioning, create a small implementation artifact and execute a real test, then create a go-to-market plan. Every specialist result must be independently verified. Autonomously choose all marketplace agents."}' | jq
```

If JARVIS asks one material clarification, send the answer with the returned `session_id`. Only start streaming once `status=accepted` and a non-null `run_id` exists.
