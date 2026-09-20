from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from .a2a import AgentCapabilities, AgentCard, AgentSearchRequest, JSONRPCRequest, JSONRPCResponse, text_from_message
from .capabilities import tools_for_agent
from .config import settings
from .db import Database
from .executor import AgentExecutor
from .marketplace import AgentMarketplace
from .models import AgentListing
from .neuralake import NeuraLakeClient


def create_worker_app(
    *,
    db: Database,
    marketplace: AgentMarketplace,
    executor: AgentExecutor,
    base_url: str | None = None,
    auth_token: str | None = None,
) -> FastAPI:
    """Build the A2A Worker Gateway around injected dependencies.

    The gateway owns worker execution: callers never see worker system prompts
    or drive worker inference; they only exchange Agent Cards and JSON-RPC.
    """
    app = FastAPI(title="A2A Worker Gateway", version="0.1.0")
    app.state.db = db
    app.state.marketplace = marketplace
    app.state.executor = executor
    app.state.base_url = (base_url or f'http://{settings.worker_gateway_host}:{settings.worker_gateway_port}').rstrip('/')
    app.state.auth_token = settings.worker_gateway_token if auth_token is None else auth_token
    app.state.sse_idle_ticks = 40
    # A2A protocol task registry for tasks/get; execution is synchronous, so
    # tasks reach a terminal state before the JSON-RPC response returns.
    app.state.tasks: dict[str, dict[str, Any]] = {}

    def card_for(listing: AgentListing) -> AgentCard:
        return AgentCard(
            agent_id=listing.id,
            name=listing.name,
            description=listing.description,
            division=listing.division,
            vibe=listing.vibe,
            tools=tools_for_agent(listing),
            endpoint=f'{app.state.base_url}/agents/{listing.id}/rpc',
            auth_required=bool(app.state.auth_token),
            capabilities=AgentCapabilities(streaming=True),
            skills=[{'id': listing.division, 'name': listing.division.title(), 'description': listing.description[:200]}],
        )

    async def require_auth(request: Request) -> None:
        token: str = app.state.auth_token
        if not token:
            return
        if request.headers.get('authorization') != f'Bearer {token}':
            raise HTTPException(status_code=401, detail='invalid or missing bearer token')

    async def resolve_agent(agent_id: str) -> AgentListing:
        clean_id = agent_id.removesuffix('.md')
        try:
            return await marketplace.get(clean_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Agent '{clean_id}' not found")

    @app.get('/health')
    async def health() -> dict[str, str]:
        return {'status': 'ok', 'service': 'worker-gateway'}

    @app.get('/agents/{agent_id:path}/.well-known/agent.json', response_model=AgentCard)
    async def get_agent_card(agent_id: str, request: Request) -> AgentCard:
        await require_auth(request)
        return card_for(await resolve_agent(agent_id))

    @app.post('/agents/search')
    async def search_agents(search: AgentSearchRequest, request: Request) -> dict[str, Any]:
        await require_auth(request)
        discovered = await marketplace.search(
            search.query,
            limit=max(search.limit * 4, 20),
            exclude=set(search.exclude),
        )
        required = set(search.required_tools)
        candidates = [c for c in discovered if required.issubset(set(tools_for_agent(c)))][:search.limit]
        return {'candidates': [{**c.model_dump(), 'tools': tools_for_agent(c)} for c in candidates]}

    @app.post('/agents/{agent_id:path}/rpc', response_model=JSONRPCResponse)
    async def agent_rpc(agent_id: str, rpc: JSONRPCRequest, request: Request) -> JSONRPCResponse:
        await require_auth(request)
        listing = await resolve_agent(agent_id)

        if rpc.method == 'tasks/get':
            task = app.state.tasks.get(str(rpc.params.get('id') or ''))
            if task is None:
                return JSONRPCResponse(error={'code': -32001, 'message': 'Task not found'}, id=rpc.id)
            return JSONRPCResponse(result={'task': task}, id=rpc.id)

        if rpc.method == 'tasks/cancel':
            task = app.state.tasks.get(str(rpc.params.get('id') or ''))
            if task is None:
                return JSONRPCResponse(error={'code': -32001, 'message': 'Task not found'}, id=rpc.id)
            return JSONRPCResponse(
                error={'code': -32002, 'message': 'Task is already in a terminal state (synchronous execution)'},
                id=rpc.id,
            )

        if rpc.method == 'message/send':
            prompt = text_from_message(rpc.params.get('message'))
            meta = dict(rpc.params.get('metadata') or {})
        elif rpc.method == 'execute_task':
            prompt = str(rpc.params.get('prompt') or '')
            meta = dict(rpc.params)
        else:
            return JSONRPCResponse(
                error={'code': -32601, 'message': f'Method {rpc.method} not found'},
                id=rpc.id,
            )

        if not prompt:
            return JSONRPCResponse(
                error={'code': -32602, 'message': 'params.message/prompt is required'},
                id=rpc.id,
            )

        run_id = str(meta.get('run_id') or f'a2a-{uuid4()}')
        task_id = str(meta.get('task_id') or 'a2a-task')
        model = str(meta.get('model') or settings.worker_text_model)
        temperature = float(meta.get('temperature', 0.2))
        required_tools = list(meta.get('required_tools') or [])

        row = await db.fetchone('SELECT COALESCE(MAX(seq), 0) AS max_seq FROM events')
        since_seq = int(row['max_seq']) if row else 0

        try:
            output = await executor.run(
                run_id=run_id,
                task_id=task_id,
                agent_id=listing.id,
                user_prompt=prompt,
                temperature=temperature,
                required_tools=required_tools,
                model=model,
            )
            state = 'completed'
        except Exception as exc:
            return JSONRPCResponse(
                error={'code': -32603, 'message': str(exc)[:1500]},
                id=rpc.id,
            )

        rows = await db.fetchall(
            'SELECT event_type, payload FROM events WHERE run_id=? AND seq>? ORDER BY seq',
            (run_id, since_seq),
        )
        worker_events = [
            {'event_type': row['event_type'], 'payload': json.loads(row['payload'])}
            for row in rows
        ]

        a2a_task_id = f'task-{uuid4().hex[:12]}'
        task_record = {
            'id': a2a_task_id,
            'state': state,
            'status': {'state': state},
            'artifacts': [{'parts': [{'kind': 'text', 'text': output}]}],
            'metadata': {
                'agent_id': listing.id,
                'run_id': run_id,
                'task_id': task_id,
                'model': model,
                'output': output,
                'events': worker_events,
            },
        }
        if len(app.state.tasks) > 512:
            app.state.tasks.clear()
        app.state.tasks[a2a_task_id] = task_record

        if rpc.method == 'message/send':
            return JSONRPCResponse(result={'task': task_record}, id=rpc.id)
        return JSONRPCResponse(
            result={'status': 'completed', 'agent_id': listing.id, 'output': output, 'events': worker_events},
            id=rpc.id,
        )

    @app.get('/runs/{run_id}/events')
    async def stream_run_events(run_id: str, request: Request, after: int = 0) -> StreamingResponse:
        """Live SSE feed of gateway-side worker events for a run (agent starts, tool calls, completion)."""
        await require_auth(request)

        async def generator():
            seq = after
            idle_ticks = 0
            while True:
                rows = await db.fetchall(
                    'SELECT seq, event_type, actor, payload FROM events WHERE run_id=? AND seq>? ORDER BY seq',
                    (run_id, seq),
                )
                for row in rows:
                    seq = row['seq']
                    data = json.dumps(
                        {'seq': row['seq'], 'event_type': row['event_type'], 'actor': row['actor'], 'payload': json.loads(row['payload'])},
                        ensure_ascii=False,
                    )
                    yield f'id: {seq}\nevent: gateway\ndata: {data}\n\n'
                if rows:
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    if idle_ticks >= app.state.sse_idle_ticks:
                        yield 'event: idle\ndata: {}\n\n'
                        break
                await asyncio.sleep(0.25)

        return StreamingResponse(generator(), media_type='text/event-stream')

    return app


db = Database(settings.worker_gateway_database_path)
marketplace = AgentMarketplace(db, settings.effective_agent_dataset_dir)
executor = AgentExecutor(marketplace, NeuraLakeClient(), db)

app = create_worker_app(db=db, marketplace=marketplace, executor=executor)


@app.on_event('startup')
async def startup() -> None:
    await db.init()
    indexed = await marketplace.index()
    if indexed == 0:
        raise RuntimeError('Marketplace contains no agents')


if __name__ == '__main__':
    import uvicorn

    uvicorn.run(app, host=settings.worker_gateway_host, port=settings.worker_gateway_port)
