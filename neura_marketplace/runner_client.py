from __future__ import annotations

from typing import Any

import httpx

from .config import settings


class ToolRunnerClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.runner_base_url).rstrip('/')

    async def execute(
        self,
        *,
        run_id: str,
        task_id: str,
        agent_id: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        payload = {
            'run_id': run_id,
            'task_id': task_id,
            'agent_id': agent_id,
            'tool': tool,
            'arguments': arguments,
        }
        async with httpx.AsyncClient(timeout=settings.tool_timeout_seconds + 10.0) as client:
            response = await client.post(f'{self.base_url}/tools/execute', json=payload)
        if response.status_code >= 400:
            raise RuntimeError(f'Tool runner HTTP {response.status_code}: {response.text[:1200]}')
        data = response.json()
        if not data.get('ok'):
            raise RuntimeError(f"Tool {tool} failed: {data.get('error', 'unknown error')}")
        return data
