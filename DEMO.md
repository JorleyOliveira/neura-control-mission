# A2A Demo Runbook (all-Docker)

Prove to stakeholders that independent agents communicate over the A2A protocol:
no human chooses agents, prompts, or tools; every message is recorded by the
receiving service; and a real buyer↔seller negotiation happens between agents.

## Architecture (5 independent Docker services)

```
Human ──HTTP──> JARVIS (:8000, consultant)
                 │  A2A job: POST /a2a/jobs (+ result callback /a2a/messages)
                 ▼
               MARCELO (:8001, orchestrator)
                 │  Discover:  POST /agents/search               ┐
                 │  Delegate:  JSON-RPC message/send (A2A spec)  ├─ A2A Worker Gateway (:8010)
                 │  Progress:  SSE  /runs/{id}/events            ┘
                 ▼                                                 │ a2a.call + tools over HTTP
               marketplace agents (exact .md prompts)              ▼
               + independent verifier                          Tool Runner (:8002, sandbox)
                                                                    │ allowlisted a2a.call
                                                                    ▼
                                                          FreshMart Seller Agent (:8020)
                                                          (SQLite supermarket catalog +
                                                           LLM negotiation, spec card at
                                                           /.well-known/agent.json)
```

## Boot (everything in Docker)

```bash
docker compose up --build -d          # canonical ports 8000/8001/8002/8010/8020

# If 8000-8002 are occupied (e.g. an SSH tunnel), use the dev port override:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d   # 18000/18001/18002/18010/18020
```

## The negotiation scenario ($1000 budget)

Run the demo from inside the marcelo container (container-side DB access only —
never open the containers' SQLite files from the host, WAL over the mount
boundary corrupts them):

```bash
docker compose exec -T marcelo python scripts/demo.py \
  --jarvis http://jarvis:8000 \
  --orchestration-db /app/state/neura.db \
  --gateway-db /app/state/neura-worker.db \
  --workspace-root /workspace \
  --goal "Goal: negotiate directly with the FreshMart seller agent to acquire a two-week
grocery package for a family of four under a strict budget of \$1000. CRITICAL: FreshMart is
NOT a public website; it exists ONLY as an A2A agent at http://seller:8020/rpc. Communicate
ONLY via the a2a.call tool (url http://seller:8020/rpc, method message/send). Ask for its
catalog and a complete basket proposal, exchange at least 3 explicit rounds, close with
action=accept under \$1000, then write negotiation_report.md with the final basket, prices,
total, discount, and round-by-round summary. Constraints: required tools a2a.call and
filesystem.write; the plan must contain exactly 1 task." \
  --answer "No fixed list; the buyer composes a balanced basket from the seller's catalog
within the \$1000 budget. Proceed now."
```

## Monitoring (the stakeholder view)

```bash
scripts/monitor.sh                 # latest run: seller negotiation log + live transcript
scripts/monitor.sh <run_id>        # specific run
curl -s localhost:8020/negotiations | python -m json.tool        # every explicit buyer/seller message
curl -s localhost:8010/agents/finance:finance-investment-researcher/.well-known/agent.json   # agent card
docker logs -f neura_marketplace_worker                          # wire-level RPC traffic
```

Worker deliverables land in `tmp-docker-workspace/<run_id>/<task_id>/`.

## The purist autonomy variant

The scripted goal above pins verification policy (required tools) and plan size for demo
determinism. The purist variant removes every hint — the orchestrator alone decides tools,
plan shape, and execution:

```bash
docker compose exec -T marcelo python scripts/demo.py --goal-minimal \
  --jarvis http://jarvis:8000 \
  --orchestration-db /app/state/neura.db --gateway-db /app/state/neura-worker.db \
  --workspace-root /workspace
```

Show both: the scripted run for reliability, the minimal run to prove no human chose
tools, plan shape, or agents.

## Two-terminal live observation

Terminal 1 drives the demo (submits the goal and prints the run id in its header):

```bash
docker compose exec -T marcelo python scripts/demo.py --goal-minimal \
  --jarvis http://jarvis:8000 \
  --orchestration-db /app/state/neura.db --gateway-db /app/state/neura-worker.db \
  --workspace-root /workspace
```

Terminal 2 observes everything as it happens (copy the run id from terminal 1):

```bash
./scripts/monitor.sh <run_id>      # seller negotiation log + live merged transcript
```

Optional terminal 3 — the wire itself:

```bash
docker logs -f neura_marketplace_worker     # every JSON-RPC call hitting the worker gateway
```

Or open http://127.0.0.1:8000 in a browser: chat there and the event stream shows
WORKER_PROGRESS lines live.

## What to point at

1. `demo.py` live transcript — JARVIS→MARCELO job, DISCOVER/EVALUATE/HIRE over the mesh,
   `message/send` delegations, live `WORKER_PROGRESS` (model + tool calls),
   `a2a.call` round-trips to the seller, VERIFY_PASS, callback to JARVIS.
2. Seller `/negotiations` — the explicit buyer↔seller message log with offers, counters,
   and the accepted deal (pinned negotiation id = `<run_id>:<task_id>`).
3. Anti-fabrication: the verifier is instructed to cross-check the seller's
   `negotiation/history` record; failed RPCs never count as tool use.
4. Resilience moments: `AGENT_FINAL_BLOCKED` enforcement, `AGENT_ACTION_INVALID`
   recovery, NeuraLake 504 auto-retry.

## Demo tips

- Keep `MARCELO_MODEL=text` (compose default) — the reasoning endpoint intermittently 504s.
- The negotiation worker gets 32 steps (compose default); keep the goal to 1 task.
- Reference completed run with full evidence: `adffceef-0ec1-4a6b-9a27-58de4411497d`
  (3-round pinned negotiation, $923.12 accepted, verify PASS, report on disk).
