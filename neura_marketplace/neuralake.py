from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .config import settings
from .json_utils import extract_json


class NeuraLakeClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None) -> None:
        key = api_key if api_key is not None else settings.neuralake_api_key
        if not key:
            raise RuntimeError('NEURALAKE_API_KEY is not configured')
        self.api_key = key
        self.base_url = (base_url or settings.neuralake_base_url).rstrip('/')
        self.model = model or settings.neuralake_model

    async def chat(self, *, messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 4096, model=None) -> str:
        payload = {
            'model': model or self.model,
            'messages': messages,
            'temperature': temperature,
            'max_tokens': max_tokens,
            'stream': False,
        }
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        # NeuraLake's edge intermittently returns 504s on long prompts; retry transient failures.
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(f'{self.base_url}/chat/completions', headers=headers, json=payload)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            if response.status_code >= 500 and attempt < 2:
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            break
        if response.status_code >= 400:
            raise RuntimeError(f'NeuraLake HTTP {response.status_code}: {response.text[:1000]}')
        data = response.json()
        try:
            content = data['choices'][0]['message']['content']
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f'Unexpected NeuraLake response shape: {str(data)[:1000]}') from exc
        if not content:
            raise RuntimeError('NeuraLake returned an empty response')
        return str(content)

    async def complete(self, *, system: str, user: str, temperature: float = 0.2, max_tokens: int = 4096, model=None) -> str:
        return await self.chat(
            messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
        )

    async def json(self, *, system: str, user: str, temperature: float = 0.1, max_tokens: int = 4096, model=None) -> Any:
        text = await self.complete(system=system, user=user, temperature=temperature, max_tokens=max_tokens, model=model)
        return extract_json(text)
