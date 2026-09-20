# UI API Specification — JARVIS Agent Console

Base URL: `http://localhost:18000` (dev ports; canonical Docker ports are 8000/8001/8002/8010/8020).
All endpoints are CORS-open for externally hosted UIs (Lovable). No auth required.

## 1. Conversation

### POST /api/chat
Send the user's goal or clarification answer (text or transcribed voice).

```json
// request
{ "message": "launch RecipeSnap...", "session_id": "optional-keep-context" }
// response — JARVIS needs more info:
{ "session_id": "uuid", "status": "needs_input", "message": "What is the revenue model?", "run_id": null }
// response — goal accepted and delegated to MARCELO:
{ "session_id": "uuid", "status": "accepted", "message": "Delegated to MARCELO. Run <uuid> accepted.", "run_id": "<uuid>" }
```

### GET /api/sessions/{session_id}/messages
Chat history: `[{"role": "user"|"assistant", "content": "...", "created_at": "..."}]`

## 2. Runs

### GET /api/runs
Last 20 runs: `[{"run_id", "session_id", "objective", "status", "created_at", "updated_at"}]`
`status`: `accepted` → `running` → `completed` | `failed`.

### GET /api/runs/{run_id}
Full run row incl. `final_result` (the synthesized answer delivered by MARCELO).

## 3. Live agent activity (SSE)

### GET /api/runs/{run_id}/events?after={lastSeq}
Server-Sent Events stream; reconnect with `after=<last received seq>`.

- `event: marketplace` — `data: {"seq": n, "event_type": "...", "actor": "...", "payload": {...}, "created_at": "..."}`
- `: keep-alive` comments every 0.5s idle
- `event: done` — `data: {"status": "completed"|"failed"}` (terminal; fires once)

### Event types and payloads (all observed live)

| event_type | actor | payload keys | meaning |
|---|---|---|---|
| GOAL_DELEGATED | JARVIS | goal | goal accepted by orchestrator |
| GOAL_RECEIVED | MARCELO | objective | orchestrator started |
| PLAN_CREATED | MARCELO | tasks[] | execution DAG planned |
| DISCOVER | MARCELO | task_id, query, candidates[] | capability search over the mesh |
| EVALUATE | MARCELO | task_id, selected_agent_id, confidence | LLM picked a worker |
| HIRE | MARCELO | task_id, agent_id, agent_name | contract created |
| DELEGATE | MARCELO | task_id, agent_name, attempt | JSON-RPC message/send to the worker |
| WORKER_PROGRESS | worker name | task_id, worker_event_type, tool?, arguments?, model?, used_tools? | live mirror of worker execution (see below) |
| WORKER_RESULT | worker name | task_id, model, used_tools, status | worker run returned over JSON-RPC |
| WORK_SUBMITTED | MARCELO | task_id | output accepted for verification |
| VERIFY_DISCOVER / VERIFY_HIRE | MARCELO | verifier_agent_name? | independent verifier hired |
| VERIFY_PASS / VERIFY_FAIL | verifier | task_id, score / failed_criteria | verdict |
| REJECT_AND_REHIRE | MARCELO | rejected_agent_id, next_attempt | verification loop |
| FINAL_RESULT | MARCELO | result | answer sent to JARVIS via callback |
| RUN_FAILED | MARCELO | error | terminal failure |
| VOICE_SPEAK_FAILED | JARVIS | — | voice channel unavailable (result still persisted) |

`WORKER_PROGRESS.worker_event_type`: `AGENT_STARTED` (has `model`, `required_tools`),
`TOOL_REQUESTED` / `TOOL_COMPLETED` / `TOOL_FAILED` (has `tool`, `arguments`),
`AGENT_ACTION_INVALID` (recovery), `AGENT_FINAL_BLOCKED` (enforcement), `AGENT_COMPLETED` (has `used_tools`).

## 4. Negotiation transcript (seller agent)

### GET /api/runs/{run_id}/negotiations
Explicit buyer↔seller message log for this run (poll every ~3s while running):

```json
{ "run_id": "...", "negotiations": [ { "id": "<run_id>:<task_id>", "rounds": 3,
  "messages": [ {"round": 1, "role": "buyer",  "content": "text...", "created_at": "..."},
                {"round": 1, "role": "seller", "content": "{\"reply\":..., \"action\":\"counter\", \"offer\":{...}}", "created_at": "..."} ] } ] }
```
Seller `content` is a JSON string: `reply`, `action` (chat|counter|accept|reject), `offer {items[{name,qty,unit_price_cents}], subtotal_cents, discount_percent, total_cents}`.

## 5. Voice (Agora Conversational AI)

### GET /api/voice/config
`{"configured": bool, "app_id": "...", "agent_id": "...", "channel": "neura-demo", "token_enabled": bool}`
No secrets exposed; the Agora customer credentials and app certificate stay server-side.

### GET /api/voice/rtc-token?channel=neura-demo&uid=0
Mints a 1-hour RTC publisher token (JoinChannel + PublishAudioStream) using the server-side
app certificate: `{"token": "007...", "app_id": "...", "channel": "...", "uid": 0, "expires_in": 3600}`.
Use when `token_enabled` is true; join with app-id only otherwise. Refresh on expiry.

Voice flow (already wired server-side):
1. UI joins the Agora RTC channel (`app_id` + `channel` + `token` when `token_enabled`) with
   the Agora Web SDK; the Conversational AI agent (must be RUNNING in the Agora project)
   joins the same channel.
2. User speaks → Agora STT → JARVIS `POST /v1/chat/completions` (OpenAI-compatible;
   stable session per conversation) → reply streamed back → Agora TTS speaks it.
3. When MARCELO finishes, JARVIS pushes the final answer into the channel via the
   Agora `speak` API (512-byte chunks) — the user HEARS the result unprompted.

If `/api/voice/config.configured` is false, hide the voice UI; text chat remains fully functional.
Keep a typed-input fallback always available.

## 6. Health

`GET /health` → `{"status": "ok", "agent": "JARVIS"}` — use for the connection indicator.
