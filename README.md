# neura-control-mission

Autonomous agent swarm for the NeuraLake Agent Marketplace challenge: one agent receives a
business goal and — with no human choosing who does what — autonomously **Discovers,
Evaluates, Hires, Delegates and Verifies** other agents over the A2A protocol, while workers
can negotiate with an independent seller agent. Speak or type a goal in the web console and
watch every inter-agent message live.

## What's inside

| Folder | What it is |
|---|---|
| `neura_marketplace/` | Backend: JARVIS (consultant), MARCELO (orchestrator), A2A worker gateway (agent cards + JSON-RPC `message/send` + SSE progress), sandboxed tool runner, FreshMart seller agent (SQLite catalog, real negotiation), Agora voice bridge with RTC token minting |
| `autonomous-agent-swarm/` | The Mission Control web UI (voice + live agent network + timeline + negotiation transcripts). **Shipped inside this repo for delivery; move it out before running (step 2 below).** |
| `TESTING.md` / `DEMO.md` | Full runbook: scenarios, monitoring, troubleshooting |

## Quickstart

```bash
# 1. clone this single repository
git clone https://github.com/JorleyOliveira/neura-control-mission.git
cd neura-control-mission

# 2. IMPORTANT: move the UI folder OUT, so it sits BESIDE this repo
#    (docker-compose builds the frontend from ../autonomous-agent-swarm)
mv autonomous-agent-swarm ../

# 3. configure the only required secret
cp .env.example .env    # then edit .env and set NEURALAKE_API_KEY

# 4. boot all six services
docker compose up --build -d

# 5. open the console
#    http://localhost:8080   (UI; it auto-connects to the API on :8000)
```

Resulting layout:

```
~/some-dir/
├── neura-control-mission/       # backend (run docker compose here)
└── autonomous-agent-swarm/      # frontend (moved out in step 2)
```

## Prove it works

- Type or speak a goal in the console → JARVIS clarifies → MARCELO plans and hires
  marketplace agents on its own → live timeline shows every message between agents
  (click any `DELEGATE`/`WORKER_RESULT` row for the exact text sent/received).
- Negotiation goals open a transcript tab with the explicit buyer↔seller offers.
- `curl -s localhost:8020/negotiations | python3 -m json.tool` — raw negotiation log.
- Full test suite: `docker compose exec marcelo python -m pytest tests/ -q` (32 tests).

See `TESTING.md` for scenarios (product launch, the $1000 negotiation, voice setup) and
`DEMO.md` for the stakeholder demo script.

## Notes

- The bundled agent catalog is `data/sample-agents` (11 agents). For the full 300-agent
  dataset, clone [agency-agents](https://github.com/msitarzewski/agency-agents) into
  `data/agency-agents`.
- Voice (Agora) is optional: set the five `AGORA_*` values in `.env` and see `TESTING.md`.
