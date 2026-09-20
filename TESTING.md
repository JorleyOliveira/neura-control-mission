# How to Clone and Test

An autonomous agent swarm: JARVIS (consultant) delegates to MARCELO (orchestrator), which
discovers, hires, and verifies marketplace agents over the A2A protocol (Agent Cards +
JSON-RPC 2.0 `message/send`), while workers can negotiate with an independent seller agent
(SQLite supermarket catalog) through the sandboxed `a2a.call` tool. Five Docker services,
live inter-agent monitoring, optional Agora voice.

## 1. Prerequisites

- Docker Desktop (with the daemon running; ~4GB free on the Docker VM disk)
- A NeuraLake API key (inference provider) — the only required secret
- Ports 8000-8002, 8010, 8020 free on localhost

```bash
git clone https://github.com/JorleyOliveira/autonomous-agent-swarm.git
cd autonomous-agent-swarm
cp .env.example .env
# edit .env and set NEURALAKE_API_KEY=<your key>   (voice/Agora vars are optional)
```

## 2. Boot the stack (all five services)

```bash
docker compose up --build -d
# If 8000-8002 are occupied on your machine, use the dev-ports override instead:
# docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d
# (then JARVIS is on 18000 and you add --jarvis http://127.0.0.1:18000 below)
```

Wait for health (all five must answer):

```bash
for p in 8000 8001 8002 8010 8020; do curl -s localhost:$p/health; echo; done
```

## 3. Run the test suite

```bash
docker compose exec marcelo python -m pytest tests/ -q     # expect: 32 passed
```

## 4. Test scenario A — product launch (RecipeSnap)

Terminal 1 (submits the goal, prints the run id, streams the transcript live):

```bash
docker compose exec -T marcelo python scripts/demo.py \
  --jarvis http://jarvis:8000 \
  --orchestration-db /app/state/neura.db --gateway-db /app/state/neura-worker.db \
  --workspace-root /workspace \
  --answer "Freemium: free daily recipes, subscription for personalization. Proceed."
```

Terminal 2 (paste the run id from terminal 1):

```bash
./scripts/monitor.sh <run_id>
```

What you should see: JARVIS accepts and delegates → MARCELO plans a 3-4 task DAG → for each
task DISCOVER → EVALUATE → HIRE (different marketplace agents each run) → DELEGATE over
JSON-RPC → live WORKER_PROGRESS (model + every tool call: web.search, web.fetch,
filesystem.write, shell.exec) → independent verifier PASS → FINAL_RESULT called back to JARVIS.
Deliverables land in `tmp-docker-workspace/<run_id>/<task_id>/` (landing.html, research note,
launch messaging). Expect 2-5 minutes, `RUN STATUS: completed`.

## 5. Test scenario B — the $1000 negotiation

Same as above with `--goal-minimal` (purist: zero hints, the orchestrator decides everything):

```bash
docker compose exec -T marcelo python scripts/demo.py --goal-minimal \
  --jarvis http://jarvis:8000 \
  --orchestration-db /app/state/neura.db --gateway-db /app/state/neura-worker.db \
  --workspace-root /workspace \
  --answer "No fixed list; compose a balanced basket from the seller's catalog. Proceed."
```

Explicit proof of buyer↔seller messages:

```bash
curl -s localhost:8020/negotiations | python -m json.tool
# or per run: curl -s localhost:8000/api/runs/<run_id>/negotiations
```

Each negotiation is pinned to `<run_id>:<task_id>`; seller replies carry
`reply / action (chat|counter|accept|reject) / offer{items, subtotal_cents, discount_percent,
total_cents}`. A completed reference run closed a real 3-round deal at $923.12 under budget.

## 6. Test scenario C — voice (optional, needs Agora)

1. In the Agora console, your Conversational AI agent must be RUNNING with its LLM endpoint
   pointing at `http://<this-machine>:8000/v1/chat/completions`.
2. Set the five `AGORA_*` values in `.env` (certificate stays server-side), then
   `docker compose up -d --force-recreate jarvis`.
3. `curl -s localhost:8000/api/voice/config` → `"configured": true, "token_enabled": true`.
4. `curl -s "localhost:8000/api/voice/rtc-token"` → returns a `007...` RTC token for the UI.
5. Full voice loop: speak → JARVIS consults (question or acceptance is spoken back) → swarm
   runs → the final result is spoken into the channel automatically.

## 7. The web UI (voice + live swarm view)

The API for a hosted UI (Lovable/React) is specified in `UI_API_SPEC.md`, and
`LOVABLE_PROMPT.md` is a ready-to-paste build prompt. Quick checks without any UI:

```bash
curl -s localhost:8000/api/runs | python -m json.tool          # run history
curl -s -N localhost:8000/api/runs/<run_id>/events | head -40  # live SSE event stream
```

## Troubleshooting

- `NeuraLake HTTP 504` during planning: transient provider flakiness; the client auto-retries.
  Keep `MARCELO_MODEL=text` (the compose default) — the reasoning endpoint is less stable.
- Gateway/worker unhealthy right after boot: check `docker compose logs worker`; if the Docker
  VM disk is full (`docker system df`), prune build cache (`docker builder prune -f`).
- Never open `tmp-docker-state`/container SQLite files from the host while the stack runs —
  all monitoring goes through `scripts/monitor.sh` (reads inside the container).
- The full `data/agency-agents` catalog is a git submodule pointer; clones fall back to the
  bundled `data/sample-agents` (11 agents) automatically — every flow above works with it.
