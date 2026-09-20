# Agent Nexus

Build "NEURA Mission Control" — a single-page voice agent console where a user speaks a business

goal to JARVIS (a consultant AI agent), hears the answer spoken back, and watches — live, with

full detail — as an autonomous marketplace of AI agents discovers, hires, delegates to, verifies,

and negotiates with other agents to solve the goal without any human choosing who does what.




STYLE (exact): dark mission-control console. Near-black background (#0B0F1A), glass panels with

subtle borders, neon accent colors per agent role (JARVIS cyan, MARCELO violet, workers emerald,

verifier amber, seller pink). Monospace for event payloads. Smooth 200ms transitions. This is a

demo stage for hackathon judges: every state change must feel alive.




HARD CONSTRAINTS (read first):

- Frontend only. React + TypeScript. You MUST NOT create any backend, database, authentication,

  account system, payments, routing pages, or any feature not listed in this prompt.

- ALL data comes from one REST/SSE API. Add a "API URL" input in the header, default

`http://localhost:18000`, persisted in localStorage. Show a green/red connection dot polling

`{API}/health` every 5s. When disconnected, show the panels in an empty "waiting for agents" state.

- Exactly one page with the layout below. No dark-mode toggle (it IS dark), no settings page.




LAYOUT (3 columns, full viewport, no page scroll; columns scroll internally):

1. LEFT SIDEBAR (~260px): "Runs" list. On load, GET `{API}/api/runs` → items showing objective

   (truncated 60 chars), status pill (accepted=gray, running=blue pulse, completed=green,

   failed=red), relative time. Clicking a run selects it and hydrates the center+right panels.

2. CENTER (~420px): the JARVIS conversation.

- Chat bubbles: user right, JARVIS left. Hydrate from

     GET `{API}/api/sessions/{sessionId}/messages`.

- VOICE ORB pinned at the bottom center: a glowing circle with a mic icon.

     On load, GET `{API}/api/voice/config`. If `configured` is true, clicking the orb joins the

     Agora channel using agora-rtc-sdk-ng (`AgoraRTC.createClient({mode:"rtc"})`,

`join(app_id, channel, null)` with the values from that endpoint, publish local mic audio;

     orb glows "listening" while joined; click again to leave). Spoken words are handled entirely

     by the backend voice agent — the orb only joins/leaves the channel.

     If `configured` is false, the orb shows a tooltip "voice offline — type below" and a text

     input is always available next to it as the fallback.

- Sending: POST `{API}/api/chat` `{message, session_id}`. If `status==="needs_input"`, render

     JARVIS's question as a bubble (voice users hear it spoken by the backend) and keep the

     session_id for the next message. If `status==="accepted"`, store `session_id` + `run_id`,

     add a system bubble "Delegated to MARCELO — Run started", and auto-select that run.

3. RIGHT (flex-1): the live agent network, stacked:

   a. NETWORK MAP (top ~45%): nodes on an SVG canvas — center-top JARVIS, below it MARCELO,

      right edge "SELLER" (FreshMart). Hired workers appear as nodes around MARCELO as events

      arrive (from HIRE payload `agent_name`); a verifier node per task (amber). Animate edges

      (dash flow) whenever a message passes between two nodes (see event mapping). Node states:

      idle (dim), working (pulsing accent), done (solid), failed (red).

   b. ACTIVITY TIMELINE (bottom ~55%): reverse-chronological feed of SSE events, newest on top,

      each row: time, colored actor chip, event badge, one-line summary, expandable (click)

      pretty-printed JSON payload. Hydrate history when selecting an older run by fetching

      events once with `after=0`.




EVENT WIRING — subscribe with EventSource to `{API}/api/runs/{run_id}/events?after={lastSeq}`

(reconnect on error with the last seq; `event: done` means finished — stop, then refresh

GET `{API}/api/runs/{run_id}` and if `final_result` exists render it as a highlighted gold

"FINAL ANSWER" card at the top of the chat column).

Map every `event: marketplace` data JSON `{seq, event_type, actor, payload}`:

- GOAL_DELEGATED / GOAL_RECEIVED: timeline rows; pulse JARVIS→MARCELO edge.

- PLAN_CREATED: timeline row "Planned N tasks"; briefly list task titles from payload.tasks.

- DISCOVER: edge MARCELO→network flash; row "Searched mesh: {payload.query} → N candidates".

- EVALUATE: row "Selected {payload.selected_agent_id} (confidence {payload.confidence})".

- HIRE: add worker node (emerald) with payload.agent_name; row with contract.

- DELEGATE: MARCELO→worker edge flows; worker node → working state.

- WORKER_PROGRESS: the heart of the demo — append rows like:

  · worker_event_type AGENT_STARTED → "▶ {actor} started · model {payload.model}"

  · TOOL_REQUESTED/COMPLETED/FAILED → "🔧 {payload.tool} {first arg hint from payload.arguments

    (query/url/command/path)}" (FAILED rows in red; COMPLETED rows get a ✓)

  · AGENT_ACTION_INVALID → red row "invalid action — recovering"

  · AGENT_FINAL_BLOCKED → amber row "blocked from finishing until required tool really runs"

  · AGENT_COMPLETED → "{actor} finished · used {payload.used_tools.join(', ')}"

  Also animate worker↔SELLER edge when payload.tool === "a2a.call", and worker node pulse.

- WORKER_RESULT: row "result from {actor} · model {payload.model}"; worker node → done.

- VERIFY_HIRE / VERIFY_PASS / VERIFY_FAIL: amber verifier node appears; PASS → green badge row

  "verified · score {payload.score}"; FAIL → red row with failed_criteria; REJECT_AND_REHIRE →

  row "rejected, rehiring (attempt N)".

- FINAL_RESULT: gold flash across the map; JARVIS node glow (the backend also SPEAKS this

  answer in the voice channel automatically).

- RUN_FAILED: red banner row with payload.error.

NEGOTIATION DRAWER: when the selected run gets its first WORKER_PROGRESS with tool "a2a.call",

show a "Negotiation" tab over the timeline. Poll GET `{API}/api/runs/{run_id}/negotiations`

every 3s while the run is active. Render each negotiation as a chat thread: buyer bubbles

(right, emerald) with content text; seller bubbles (left, pink) parsing the JSON string content

into: reply text, an action chip (chat/counter/accept/reject), and an offer card listing

items (name ×qty @ $unit_price_cents/100) with subtotal/discount/total. action "accept" gets a

gold "DEAL CLOSED" stamp.




BEHAVIOR RULES:

- MUST tolerate empty API (loading skeletons, no crashes), SSE drops (auto-reconnect), and

  payloads with missing keys (render what exists).

- MUST never invent or simulate agent events: every rendered line comes from the API.

- Keep the last 200 timeline rows rendered (virtualize or trim older).




DONE WHEN: with the API reachable, I can type or speak a goal; JARVIS's question or acceptance

appears in chat; the network map builds itself as agents are hired; tool calls stream live in

the timeline; a negotiation thread appears with explicit buyer/seller offers when the goal

involves the seller; and on completion a gold final-answer card renders and (with voice on) the

answer is spoken aloud — all without a single page reload.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/2db92926-db04-43fd-9efe-56f78ad117f9).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
