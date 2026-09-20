from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .config import settings
from .db import Database
from .jarvis_core import Jarvis
from .models import A2AJob, A2AMessage, ChatRequest, ChatResponse
from .neuralake import NeuraLakeClient


app = FastAPI(title="JARVIS", version="0.1.0")
# The demo UI is hosted externally (e.g. Lovable); allow cross-origin calls.
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])
db = Database(settings.database_path)
jarvis: Jarvis | None = None


def split_for_tts(text: str, limit: int = 500) -> list[str]:
    """Agora's speak API accepts at most 512 bytes per call."""
    chunks, current = [], []
    size = 0
    for word in text.split():
        word_size = len(word.encode("utf-8")) + 1
        if size + word_size <= limit:
            current.append(word)
            size += word_size
        else:
            if current:
                chunks.append(" ".join(current))
            current, size = [word], word_size
    if current:
        chunks.append(" ".join(current))
    return chunks


async def speak_in_agora(text: str) -> None:
    """Speak text into the running Agora Conversational AI voice channel."""
    if not all([settings.agora_app_id, settings.agora_agent_id, settings.agora_customer_id, settings.agora_customer_secret]):
        return
    url = (
        "https://api.agora.io/api/conversational-ai-agent/v2/projects/"
        f"{settings.agora_app_id}/agents/{settings.agora_agent_id}/speak"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        for index, chunk in enumerate(split_for_tts(text)):
            response = await client.post(
                url,
                auth=(settings.agora_customer_id, settings.agora_customer_secret),
                json={
                    "text": chunk,
                    "priority": "INTERRUPT" if index == 0 else "APPEND",
                    "interruptable": False,
                },
            )
            if response.status_code != 200:
                raise RuntimeError(f"Agora speak failed: {response.text[:300]}")


@app.on_event("startup")
async def startup() -> None:
    global jarvis
    await db.init()
    jarvis = Jarvis(NeuraLakeClient())


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "web" / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": "JARVIS"}


async def _handle_chat(message: str, session_id: str | None) -> ChatResponse:
    if jarvis is None:
        raise HTTPException(503, "JARVIS is not initialized")

    session_id = session_id or str(uuid4())
    history = await db.get_messages(session_id)
    await db.add_message(session_id, "user", message)

    decision = await jarvis.analyze(message, history)
    if not decision.ready or not decision.brief:
        question = decision.question or "What exact outcome should the agents deliver?"
        await db.add_message(session_id, "assistant", question)
        return ChatResponse(
            session_id=session_id,
            status="needs_input",
            message=question,
        )

    run_id = str(uuid4())
    await db.create_run(run_id, session_id, decision.brief.objective)
    await db.add_event(run_id, "GOAL_DELEGATED", "JARVIS", {"goal": decision.brief.model_dump()})

    job = A2AJob(
        run_id=run_id,
        callback_url=f"{settings.jarvis_base_url}/a2a/messages",
        goal=decision.brief,
    )
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{settings.marcelo_base_url}/a2a/jobs", json=job.model_dump(mode="json"))
        if response.status_code != 202:
            await db.set_run_status(run_id, "failed")
            raise HTTPException(502, f"MARCELO rejected the A2A job: {response.text}")

    msg = f"Delegated to MARCELO. Run {run_id} accepted."
    await db.add_message(session_id, "assistant", msg)
    return ChatResponse(
        session_id=session_id,
        status="accepted",
        message=msg,
        run_id=run_id,
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    return await _handle_chat(request.message, request.session_id)


@app.post("/v1/chat/completions")
async def openai_chat_completions(payload: dict):
    """OpenAI-compatible endpoint for the Agora Conversational AI voice agent.

    The user's spoken words arrive here transcribed; the reply is streamed back
    in OpenAI SSE shape so Agora speaks it in the voice channel.
    """
    messages = payload.get("messages", [])
    user_text = next(
        (message.get("content") for message in reversed(messages) if message.get("role") == "user"),
        None,
    )
    if not user_text:
        raise HTTPException(400, "Mensagem do usuário não encontrada")

    # Stable session per voice conversation so JARVIS keeps clarification context.
    first_message = str(messages[0].get("content", "") if messages else "")
    session_id = "voice-" + hashlib.sha1(first_message.encode("utf-8")).hexdigest()[:12]

    try:
        data = await _handle_chat(str(user_text), session_id)
        answer = data.message
    except HTTPException as exc:
        answer = f"JARVIS error: {exc.detail}"

    if payload.get("stream") is False:
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ]
        }

    def generate():
        chunk = {
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": answer},
                    "finish_reason": None,
                }
            ]
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        yield 'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/voice/config")
async def voice_config() -> dict:
    """Non-secret voice settings so the UI can join the Agora channel."""
    return {
        "configured": bool(settings.agora_app_id and settings.agora_agent_id),
        "app_id": settings.agora_app_id,
        "agent_id": settings.agora_agent_id,
        "channel": "neura-demo",
        "token_enabled": bool(settings.agora_app_id and settings.agora_app_certificate),
    }


@app.get("/api/voice/rtc-token")
async def voice_rtc_token(channel: str = "neura-demo", uid: int = 0) -> dict:
    """Mint a short-lived RTC token so a browser client can join the voice channel.

    Requires the app certificate, which never leaves the server.
    """
    if not (settings.agora_app_id and settings.agora_app_certificate):
        raise HTTPException(503, "RTC tokens are not configured (missing app certificate)")

    from .agora_token import AccessToken, ServiceRtc

    expire = 3600
    token = AccessToken(
        app_id=settings.agora_app_id,
        app_certificate=settings.agora_app_certificate,
        expire=expire,
    )
    service = ServiceRtc(channel_name=channel, uid=uid)
    service.add_privilege(ServiceRtc.kPrivilegeJoinChannel, expire)
    service.add_privilege(ServiceRtc.kPrivilegePublishAudioStream, expire)
    token.add_service(service)
    return {"token": token.build(), "app_id": settings.agora_app_id, "channel": channel, "uid": uid, "expires_in": expire}


@app.post("/a2a/messages", status_code=202)
async def a2a_message(message: A2AMessage) -> dict[str, bool]:
    run = await db.get_run(message.run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    session_id = run["session_id"]
    spoken: str | None = None
    if message.type == "result":
        result = str(message.payload.get("result", ""))
        await db.add_message(session_id, "assistant", result)
        await db.set_run_status(message.run_id, "completed", result)
        spoken = result
    elif message.type == "failure":
        failure_text = f"MARCELO failed: {message.payload.get('error', 'unknown error')}"
        await db.add_message(session_id, "assistant", failure_text)
        await db.set_run_status(message.run_id, "failed")
        spoken = failure_text

    if spoken:
        try:
            await speak_in_agora(spoken)
        except Exception:
            # Voice is best-effort; the persisted result and UI stream are the source of truth.
            await db.add_event(message.run_id, "VOICE_SPEAK_FAILED", "JARVIS", {})
    return {"accepted": True}


@app.get('/api/runs')
async def list_runs() -> list[dict]:
    rows = await db.fetchall(
        'SELECT run_id, session_id, objective, status, created_at, updated_at FROM runs ORDER BY rowid DESC LIMIT 20'
    )
    return [dict(row) for row in rows]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = await db.get_run(run_id)
    if not run:
        raise HTTPException(404, "Unknown run")
    return run


@app.get('/api/runs/{run_id}/negotiations')
async def run_negotiations(run_id: str) -> dict:
    """Proxy the seller agent's explicit negotiation log, filtered to this run."""
    negotiations: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f'{settings.seller_base_url}/negotiations')
        response.raise_for_status()
        negotiations = [
            item for item in response.json().get('negotiations', [])
            if str(item.get('id', '')).startswith(run_id)
        ]
    except Exception:
        pass
    return {'run_id': run_id, 'negotiations': negotiations}


@app.get('/api/sessions/{session_id}/messages')
async def session_messages(session_id: str) -> list[dict]:
    rows = await db.fetchall(
        'SELECT role, content, created_at FROM messages WHERE session_id=? ORDER BY seq',
        (session_id,),
    )
    return [dict(row) for row in rows]


@app.get("/api/runs/{run_id}/events", response_model=None)
async def stream_events(request: Request, run_id: str, after: int = 0, format: str = ""):
    if not await db.get_run(run_id):
        raise HTTPException(404, "Unknown run")

    # EventSource sends Accept: text/event-stream; plain fetch clients (e.g.
    # one-shot hydration of past runs) get the same data as JSON.
    wants_json = format == "json" or "text/event-stream" not in request.headers.get("accept", "")
    if wants_json:
        return await db.events_since(run_id, after)

    async def generator():
        seq = after
        idle_terminal_ticks = 0
        while True:
            events = await db.events_since(run_id, seq)
            for event in events:
                seq = event["seq"]
                payload = json.dumps(event, ensure_ascii=False)
                yield f"id: {seq}\nevent: marketplace\ndata: {payload}\n\n"

            run = await db.get_run(run_id)
            terminal = run and run["status"] in {"completed", "failed"}
            if terminal and not events:
                idle_terminal_ticks += 1
                if idle_terminal_ticks >= 2:
                    yield f"event: done\ndata: {json.dumps({'status': run['status']})}\n\n"
                    break
            else:
                idle_terminal_ticks = 0

            if not events:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(generator(), media_type="text/event-stream")
