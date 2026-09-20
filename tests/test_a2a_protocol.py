from pathlib import Path

import asyncio
import json

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from neura_marketplace.a2a_client import A2AMeshClient
from neura_marketplace.db import Database
from neura_marketplace.executor import AgentExecutor
from neura_marketplace.marketplace import AgentMarketplace
from neura_marketplace.worker_app import create_worker_app


class ScriptedLLM:
    def __init__(self, responses):
        self.calls = []
        self.responses = list(responses)

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class ScriptedRunner:
    def __init__(self, results):
        self.calls = []
        self.results = list(results)

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return {'ok': True, 'tool': kwargs['tool'], 'result': self.results.pop(0)}


GATEWAY = 'http://gateway:8010'


async def build_gateway(tmp_path: Path, *, auth_token: str = ''):
    agents = tmp_path / 'agents'
    agents.mkdir()
    (agents / 'research').mkdir()
    (agents / 'engineering').mkdir()
    (
        agents / 'research' / 'analyst.md'
    ).write_text(
        '---\nname: Research Analyst\ndescription: market research analysis\n---\nRESEARCH SYSTEM\n',
        encoding='utf-8',
    )
    (
        agents / 'engineering' / 'coder.md'
    ).write_text(
        '---\nname: Code Engineer\ndescription: engineer developer writes code\n---\nCODE SYSTEM\n',
        encoding='utf-8',
    )
    db = Database(tmp_path / 'gateway.db')
    await db.init()
    marketplace = AgentMarketplace(db, agents)
    await marketplace.index()
    llm = ScriptedLLM(['{"type":"final","content":"mesh worker output"}'])
    runner = ScriptedRunner([])
    executor = AgentExecutor(marketplace, llm, db, runner=runner)  # type: ignore[arg-type]
    app = create_worker_app(
        db=db,
        marketplace=marketplace,
        executor=executor,
        base_url=GATEWAY,
        auth_token=auth_token,
    )
    return app, llm, runner


@pytest.mark.asyncio
async def test_agent_card_discovery(tmp_path: Path):
    app, _, _ = await build_gateway(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY) as client:
        response = await client.get('/agents/research:analyst/.well-known/agent.json')

    assert response.status_code == 200
    card = response.json()
    assert card['agent_id'] == 'research:analyst'
    assert card['name'] == 'Research Analyst'
    assert card['endpoint'] == f'{GATEWAY}/agents/research:analyst/rpc'
    assert 'web.search' in card['tools']
    assert 'skill.invoke' in card['tools']


@pytest.mark.asyncio
async def test_agent_card_unknown_agent_returns_404(tmp_path: Path):
    app, _, _ = await build_gateway(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY) as client:
        response = await client.get('/agents/unknown:agent/.well-known/agent.json')

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_search_filters_by_required_tools(tmp_path: Path):
    app, _, _ = await build_gateway(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY) as client:
        response = await client.post('/agents/search', json={
            'query': 'engineer developer code',
            'limit': 5,
            'required_tools': ['shell.exec'],
        })

    assert response.status_code == 200
    candidates = response.json()['candidates']
    assert [c['id'] for c in candidates] == ['engineering:coder']
    assert 'shell.exec' in candidates[0]['tools']


@pytest.mark.asyncio
async def test_rpc_execute_task_runs_worker_and_returns_events(tmp_path: Path):
    app, llm, _ = await build_gateway(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY) as client:
        response = await client.post('/agents/research:analyst/rpc', json={
            'jsonrpc': '2.0',
            'method': 'execute_task',
            'params': {
                'prompt': 'TASK',
                'model': 'code',
                'run_id': 'mesh-run',
                'task_id': 'mesh-task',
                'required_tools': [],
            },
            'id': 7,
        })

    assert response.status_code == 200
    body = response.json()
    assert body['jsonrpc'] == '2.0'
    assert body['id'] == 7
    assert body['error'] is None
    assert body['result']['status'] == 'completed'
    assert body['result']['output'] == 'mesh worker output'
    assert body['result']['agent_id'] == 'research:analyst'

    event_types = [item['event_type'] for item in body['result']['events']]
    assert 'AGENT_STARTED' in event_types
    assert 'AGENT_COMPLETED' in event_types
    started = next(item for item in body['result']['events'] if item['event_type'] == 'AGENT_STARTED')
    assert started['payload']['model'] == 'code'
    assert llm.calls[0]['messages'][0]['content'] == (
        '---\nname: Research Analyst\ndescription: market research analysis\n---\nRESEARCH SYSTEM\n'
    )


@pytest.mark.asyncio
async def test_rpc_unknown_method_returns_jsonrpc_error(tmp_path: Path):
    app, _, _ = await build_gateway(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY) as client:
        response = await client.post('/agents/research:analyst/rpc', json={
            'jsonrpc': '2.0',
            'method': 'reset_everything',
            'params': {},
            'id': 1,
        })

    assert response.status_code == 200
    body = response.json()
    assert body['error']['code'] == -32601


@pytest.mark.asyncio
async def test_message_send_returns_spec_task_object(tmp_path: Path):
    app, llm, _ = await build_gateway(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY) as client:
        response = await client.post('/agents/research:analyst/rpc', json={
            'jsonrpc': '2.0',
            'method': 'message/send',
            'params': {
                'message': {'role': 'user', 'parts': [{'kind': 'text', 'text': 'TASK'}]},
                'metadata': {'model': 'code', 'run_id': 'spec-run', 'task_id': 'spec-task'},
            },
            'id': 3,
        })

    assert response.status_code == 200
    body = response.json()
    assert body['id'] == 3
    assert body['error'] is None
    task = body['result']['task']
    assert task['state'] == 'completed'
    assert task['status']['state'] == 'completed'
    artifact_text = task['artifacts'][0]['parts'][0]['text']
    assert artifact_text == 'mesh worker output'
    assert task['metadata']['model'] == 'code'
    assert 'AGENT_STARTED' in [event['event_type'] for event in task['metadata']['events']]
    assert llm.calls[0]['messages'][1]['content'].startswith('TASK')

    # tasks/get returns the stored task; tasks/cancel reports the terminal state.
    task_id = task['id']
    async with AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY) as client:
        fetched = await client.post('/agents/research:analyst/rpc', json={
            'jsonrpc': '2.0', 'method': 'tasks/get', 'params': {'id': task_id}, 'id': 4,
        })
        cancel = await client.post('/agents/research:analyst/rpc', json={
            'jsonrpc': '2.0', 'method': 'tasks/cancel', 'params': {'id': task_id}, 'id': 5,
        })
        unknown = await client.post('/agents/research:analyst/rpc', json={
            'jsonrpc': '2.0', 'method': 'tasks/get', 'params': {'id': 'nope'}, 'id': 6,
        })

    assert fetched.json()['result']['task']['id'] == task_id
    assert cancel.json()['error']['code'] == -32002
    assert unknown.json()['error']['code'] == -32001


@pytest.mark.asyncio
async def test_agent_card_exposes_spec_fields(tmp_path: Path):
    app, _, _ = await build_gateway(tmp_path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY) as client:
        response = await client.get('/agents/research:analyst/.well-known/agent.json')
    card = response.json()
    assert card['protocol_version']
    assert card['capabilities']['streaming'] is True
    assert card['preferred_transport'] == 'JSONRPC'
    assert card['skills']


@pytest.mark.asyncio
async def test_gateway_requires_bearer_token_when_configured(tmp_path: Path):
    app, _, _ = await build_gateway(tmp_path, auth_token='secret-token')
    async with AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY) as client:
        denied = await client.get('/agents/research:analyst/.well-known/agent.json')
        allowed = await client.get(
            '/agents/research:analyst/.well-known/agent.json',
            headers={'Authorization': 'Bearer secret-token'},
        )

    assert denied.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json()['auth_required'] is True


@pytest.mark.asyncio
async def test_mesh_client_discovers_and_executes_over_http(tmp_path: Path):
    app, _, _ = await build_gateway(tmp_path)
    mesh = A2AMeshClient(base_url=GATEWAY, transport=ASGITransport(app=app))

    card = await mesh.get_agent_card('research:analyst')
    assert card.agent_id == 'research:analyst'
    assert card.endpoint == f'{GATEWAY}/agents/research:analyst/rpc'

    listings = await mesh.search(query='research', limit=5, exclude=set(), required_tools=['web.search'])
    assert [listing.id for listing in listings] == ['research:analyst']

    result = await mesh.execute_task(
        agent_id='research:analyst',
        prompt='TASK',
        required_tools=[],
        model='text',
        run_id='mesh-run',
        task_id='mesh-task',
    )
    assert result['output'] == 'mesh worker output'
    assert result['status'] == 'completed'


@pytest.mark.asyncio
async def test_gateway_streams_run_events_over_sse(tmp_path: Path):
    app, _, _ = await build_gateway(tmp_path)
    app.state.sse_idle_ticks = 1
    mesh = A2AMeshClient(base_url=GATEWAY, transport=ASGITransport(app=app))
    await mesh.execute_task(
        agent_id='research:analyst',
        prompt='TASK',
        required_tools=[],
        model='text',
        run_id='sse-run',
        task_id='sse-task',
    )

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url=GATEWAY, timeout=10.0) as client:
        async with client.stream('GET', '/runs/sse-run/events') as response:
            assert response.status_code == 200
            seen_types = []
            async for line in response.aiter_lines():
                if not line.startswith('data: '):
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get('event_type'):
                    seen_types.append(event['event_type'])

    assert 'AGENT_STARTED' in seen_types
    assert 'AGENT_COMPLETED' in seen_types


@pytest.mark.asyncio
async def test_marcelo_mirrors_worker_progress_from_mesh(tmp_path: Path):
    # ASGITransport buffers whole responses, which defeats live SSE; serve the
    # gateway on a real ephemeral uvicorn port so streaming behaves like production.
    import uvicorn

    from neura_marketplace.marcelo_core import MarceloOrchestrator
    from neura_marketplace.neuralake import NeuraLakeClient

    app, _, _ = await build_gateway(tmp_path)

    agents = tmp_path / 'orchestrator-agents'
    agents.mkdir()
    (agents / 'dummy.md').write_text('---\nname: Dummy\ndescription: placeholder\n---\nSYS\n', encoding='utf-8')
    db = Database(tmp_path / 'orchestrator.db')
    await db.init()
    marketplace = AgentMarketplace(db, agents)
    await marketplace.index()
    await db.create_run('mirror-run', 'session', 'test')

    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0, log_level='critical', lifespan='off'))
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    try:
        orchestrator = MarceloOrchestrator(db, marketplace, NeuraLakeClient())  # type: ignore[arg-type]
        orchestrator.mesh = A2AMeshClient(base_url=f'http://127.0.0.1:{port}')

        output = await orchestrator._run_agent(
            run_id='mirror-run',
            task_id='mirror-task',
            agent_id='research:analyst',
            agent_name='Research Analyst',
            user_prompt='TASK',
            model='text',
            required_tools=[],
        )
    finally:
        server.should_exit = True
        await server_task

    assert output == 'mesh worker output'
    rows = await db.fetchall("SELECT event_type, payload FROM events WHERE run_id='mirror-run' ORDER BY seq")
    by_type: dict[str, list[dict]] = {}
    for row in rows:
        by_type.setdefault(row['event_type'], []).append(json.loads(row['payload']))

    assert by_type['WORKER_RESULT'][0]['model'] == 'text'
    mirrored = {payload['worker_event_type'] for payload in by_type.get('WORKER_PROGRESS', [])}
    assert 'AGENT_STARTED' in mirrored
    assert 'AGENT_COMPLETED' in mirrored
