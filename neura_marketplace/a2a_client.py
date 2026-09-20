from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx

from .a2a import AgentCard, JSONRPCRequest, JSONRPCResponse
from .config import settings
from .models import AgentListing


class A2AMeshClient:
    """HTTP client MARCELO uses to discover and hire workers on the A2A mesh.

    Workers are opaque: MARCELO exchanges Agent Cards and JSON-RPC payloads
    only, never worker system prompts or inference calls.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or settings.worker_gateway_base_url).rstrip('/')
        self.token = settings.worker_gateway_token if token is None else token
        self.timeout = settings.a2a_request_timeout if timeout is None else timeout
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        return headers

    def _client(self, timeout: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(timeout if timeout is not None else self.timeout, connect=10.0),
            transport=self.transport,
        )

    async def get_agent_card(self, agent_id: str) -> AgentCard:
        async with self._client(timeout=10.0) as client:
            response = await client.get(
                f'{self.base_url}/agents/{agent_id}/.well-known/agent.json',
                headers=self._headers(),
            )
        response.raise_for_status()
        return AgentCard.model_validate(response.json())

    async def search(
        self,
        *,
        query: str,
        limit: int,
        exclude: set[str],
        required_tools: list[str] | None = None,
    ) -> list[AgentListing]:
        payload = {
            'query': query,
            'limit': limit,
            'exclude': sorted(exclude),
            'required_tools': sorted(required_tools or []),
        }
        async with self._client(timeout=30.0) as client:
            response = await client.post(f'{self.base_url}/agents/search', json=payload, headers=self._headers())
        response.raise_for_status()
        candidates = response.json().get('candidates', [])
        return [
            AgentListing.model_validate({key: value for key, value in item.items() if key != 'tools'})
            for item in candidates
        ]

    async def send_message(
        self,
        *,
        agent_id: str,
        text: str,
        required_tools: list[str],
        model: str,
        run_id: str,
        task_id: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """A2A protocol `message/send`: returns a normalized view of the resulting Task."""
        request = JSONRPCRequest(
            method='message/send',
            params={
                'message': {'role': 'user', 'parts': [{'kind': 'text', 'text': text}]},
                'metadata': {
                    'required_tools': required_tools,
                    'model': model,
                    'temperature': temperature,
                    'run_id': run_id,
                    'task_id': task_id,
                },
            },
            id=uuid4().hex,
        )
        async with self._client() as client:
            response = await client.post(
                f'{self.base_url}/agents/{agent_id}/rpc',
                json=request.model_dump(mode='json'),
                headers=self._headers(),
            )
        response.raise_for_status()
        rpc_response = JSONRPCResponse.model_validate(response.json())
        if rpc_response.error:
            raise RuntimeError(f'A2A RPC error from {agent_id}: {rpc_response.error.get("message")}')

        task = dict((rpc_response.result or {}).get('task') or {})
        metadata = dict(task.get('metadata') or {})
        artifacts = task.get('artifacts') or []
        artifact_text = '\n'.join(
            str(part.get('text', ''))
            for artifact in artifacts
            for part in (artifact.get('parts') or [])
            if isinstance(part, dict)
        ).strip()
        return {
            'a2a_task_id': task.get('id'),
            'state': task.get('state'),
            'output': artifact_text or str(metadata.get('output', '')),
            'events': metadata.get('events', []),
        }

    async def execute_task(
        self,
        *,
        agent_id: str,
        prompt: str,
        required_tools: list[str],
        model: str,
        run_id: str,
        task_id: str,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        request = JSONRPCRequest(
            method='execute_task',
            params={
                'prompt': prompt,
                'required_tools': required_tools,
                'model': model,
                'temperature': temperature,
                'run_id': run_id,
                'task_id': task_id,
            },
            id=uuid4().hex,
        )
        async with self._client() as client:
            response = await client.post(
                f'{self.base_url}/agents/{agent_id}/rpc',
                json=request.model_dump(mode='json'),
                headers=self._headers(),
            )
        response.raise_for_status()
        rpc_response = JSONRPCResponse.model_validate(response.json())
        if rpc_response.error:
            raise RuntimeError(f'A2A RPC error from {agent_id}: {rpc_response.error.get("message")}')
        return dict(rpc_response.result or {})

    async def watch_run(self, run_id: str, on_event) -> None:
        """Stream gateway-side run events over SSE, invoking ``on_event(event_dict)`` for each.

        The feed replays all events for the run from the beginning, so a watcher
        that connects late still observes the full worker execution history.
        """
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10.0), transport=self.transport) as client:
            async with client.stream(
                'GET',
                f'{self.base_url}/runs/{run_id}/events',
                headers=self._headers(),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith('data: '):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict) and event.get('event_type'):
                        await on_event(event)
