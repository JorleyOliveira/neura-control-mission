from __future__ import annotations

import asyncio
import html
import ipaddress
import os
import shlex
import socket
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from uuid import uuid4

from .config import settings


app = FastAPI(title='NEURA TOOL RUNNER', version='0.2.0')

ALLOWED_BINARIES = {
    'python', 'python3', 'pytest', 'git', 'ls', 'cat', 'sed', 'grep', 'find',
    'mkdir', 'touch', 'cp', 'mv', 'rm', 'pwd', 'head', 'tail', 'wc', 'echo',
}
MAX_OUTPUT = 24000
MAX_FETCH_TEXT = 30000
USER_AGENT = 'Mozilla/5.0 (compatible; NeuraMarketplaceHackathon/1.0)'

from .skill_catalog import SkillCatalog

skill_catalog = SkillCatalog(settings.skills_dir)

class ToolRequest(BaseModel):
    run_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=128)
    agent_id: str = Field(min_length=1, max_length=300)
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class SearchHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._href: str | None = None
        self._capture = False
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != 'a':
            return
        values = dict(attrs)
        classes = values.get('class') or ''
        if 'result__a' in classes or 'result-link' in classes:
            self._capture = True
            self._href = values.get('href')
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != 'a' or not self._capture:
            return
        title = ' '.join(''.join(self._text).split())
        url = self._normalize_url(self._href or '')
        if title and url and url.startswith(('http://', 'https://')):
            self.results.append({'title': title, 'url': url, 'snippet': ''})
        self._capture = False
        self._href = None
        self._text = []

    @staticmethod
    def _normalize_url(raw: str) -> str:
        raw = html.unescape(raw)
        if raw.startswith('//'):
            raw = 'https:' + raw
        parsed = urlparse(raw)
        if 'duckduckgo.com' in (parsed.hostname or ''):
            target = parse_qs(parsed.query).get('uddg')
            if target:
                return unquote(target[0])
        return raw


class PageTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {'script', 'style', 'noscript', 'svg'}:
            self._skip_depth += 1
        elif tag == 'title':
            self._in_title = True
        elif tag in {'p', 'br', 'div', 'section', 'article', 'li', 'h1', 'h2', 'h3', 'h4', 'tr'}:
            self.parts.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag in {'script', 'style', 'noscript', 'svg'} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == 'title':
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.parts.append(data)

    @property
    def title(self) -> str:
        return ' '.join(''.join(self.title_parts).split())

    @property
    def text(self) -> str:
        lines = []
        for line in ''.join(self.parts).splitlines():
            clean = ' '.join(line.split())
            if clean:
                lines.append(clean)
        return '\n'.join(lines)


def _safe_segment(value: str) -> str:
    return ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in value)[:128]


def _task_dir(request: ToolRequest) -> Path:
    root = settings.workspace_root.resolve()
    path = (root / _safe_segment(request.run_id) / _safe_segment(request.task_id)).resolve()
    if root != path and root not in path.parents:
        raise HTTPException(400, 'Workspace escape rejected')
    path.mkdir(parents=True, exist_ok=True)
    return path


def _resolve_user_path(task_dir: Path, raw_path: str) -> Path:
    if not raw_path:
        raise HTTPException(400, 'path is required')
    candidate = (task_dir / raw_path).resolve()
    if task_dir != candidate and task_dir not in candidate.parents:
        raise HTTPException(400, 'Path traversal rejected')
    return candidate


def _validate_external_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise HTTPException(400, 'Only absolute http/https URLs are allowed')
    host = parsed.hostname.lower()
    if host in {'localhost', 'host.docker.internal'} or host.endswith('.local'):
        raise HTTPException(400, 'Local/private hosts are blocked')
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(400, 'Private IP targets are blocked')
    except ValueError:
        pass
    return raw_url


async def _assert_dns_public(url: str) -> None:
    host = urlparse(url).hostname
    if not host:
        raise HTTPException(400, 'Missing hostname')

    def resolve() -> list[str]:
        return list({item[4][0] for item in socket.getaddrinfo(host, None)})

    try:
        ips = await asyncio.to_thread(resolve)
    except socket.gaierror as exc:
        raise HTTPException(400, f'DNS resolution failed: {exc}') from exc
    for raw_ip in ips:
        ip = ipaddress.ip_address(raw_ip)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(400, 'DNS resolved to a private address')


async def _safe_get(url: str) -> httpx.Response:
    current = _validate_external_url(url)
    headers = {'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.5'}
    async with httpx.AsyncClient(timeout=settings.tool_timeout_seconds, follow_redirects=False, headers=headers) as client:
        for _ in range(5):
            await _assert_dns_public(current)
            response = await client.get(current)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get('location')
                if not location:
                    return response
                current = str(response.url.join(location))
                current = _validate_external_url(current)
                continue
            return response
    raise HTTPException(400, 'Too many redirects')


async def web_search(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get('query', '')).strip()
    if not query:
        raise HTTPException(400, 'query is required')
    max_results = max(1, min(int(args.get('max_results', 8)), 10))
    url = f'https://html.duckduckgo.com/html/?q={quote_plus(query)}'
    response = await _safe_get(url)
    response.raise_for_status()
    parser = SearchHTMLParser()
    parser.feed(response.text)
    results = parser.results[:max_results]
    provider = 'duckduckgo-html'
    if not results:
        fallback = await _safe_get(f'https://lite.duckduckgo.com/lite/?q={quote_plus(query)}')
        fallback.raise_for_status()
        parser = SearchHTMLParser()
        parser.feed(fallback.text)
        results = parser.results[:max_results]
        provider = 'duckduckgo-lite'
    if not results:
        raise HTTPException(502, 'Search provider returned no parseable results')
    return {'query': query, 'provider': provider, 'results': results}


async def web_fetch(args: dict[str, Any]) -> dict[str, Any]:
    url = _validate_external_url(str(args.get('url', '')).strip())
    response = await _safe_get(url)
    response.raise_for_status()
    content_type = response.headers.get('content-type', '')
    if not any(kind in content_type for kind in ('text', 'json', 'xml', 'html')):
        raise HTTPException(400, f'Unsupported content-type: {content_type}')
    parser = PageTextParser()
    parser.feed(response.text)
    text = parser.text
    return {
        'url': str(response.url),
        'status_code': response.status_code,
        'title': parser.title,
        'text': text[:MAX_FETCH_TEXT],
        'truncated': len(text) > MAX_FETCH_TEXT,
    }


async def filesystem_list(task_dir: Path, args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_user_path(task_dir, str(args.get('path', '.')))
    if not path.exists():
        raise HTTPException(404, 'Path does not exist')
    if not path.is_dir():
        raise HTTPException(400, 'Path is not a directory')
    entries = []
    for item in sorted(path.iterdir(), key=lambda p: p.name)[:200]:
        entries.append({'name': item.name, 'type': 'dir' if item.is_dir() else 'file', 'size': item.stat().st_size if item.is_file() else None})
    return {'path': str(path.relative_to(task_dir)), 'entries': entries}


async def filesystem_read(task_dir: Path, args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_user_path(task_dir, str(args.get('path', '')))
    if not path.is_file():
        raise HTTPException(404, 'File does not exist')
    text = path.read_text(encoding='utf-8', errors='replace')
    return {'path': str(path.relative_to(task_dir)), 'content': text[:MAX_OUTPUT], 'truncated': len(text) > MAX_OUTPUT}


async def filesystem_write(task_dir: Path, args: dict[str, Any]) -> dict[str, Any]:
    path = _resolve_user_path(task_dir, str(args.get('path', '')))
    content = str(args.get('content', ''))
    if len(content) > 200_000:
        raise HTTPException(400, 'content too large')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return {'path': str(path.relative_to(task_dir)), 'bytes': len(content.encode('utf-8'))}


async def shell_exec(task_dir: Path, args: dict[str, Any]) -> dict[str, Any]:
    command = str(args.get('command', '')).strip()
    if not command:
        raise HTTPException(400, 'command is required')
    if len(command) > 4000:
        raise HTTPException(400, 'command too long')
    argv = shlex.split(command)
    if not argv:
        raise HTTPException(400, 'empty command')
    binary = Path(argv[0]).name
    if binary not in ALLOWED_BINARIES:
        raise HTTPException(400, f'Command not allowed: {binary}')
    env = {'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'), 'HOME': str(task_dir), 'PYTHONUNBUFFERED': '1'}
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=task_dir, env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=settings.tool_timeout_seconds)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise HTTPException(408, 'Command timed out')
    out = stdout.decode(errors='replace')
    err = stderr.decode(errors='replace')
    return {
        'command': command, 'exit_code': proc.returncode,
        'stdout': out[:MAX_OUTPUT], 'stderr': err[:MAX_OUTPUT],
        'truncated': len(out) > MAX_OUTPUT or len(err) > MAX_OUTPUT,
    }

async def skill_search(args):
    query = str(args.get("query", "")).strip()

    if not query:
        raise HTTPException(
            400,
            "query is required",
        )

    limit = max(
        1,
        min(
            int(args.get("limit", 8)),
            20,
        ),
    )

    skills = await asyncio.to_thread(
        skill_catalog.search,
        query,
        limit,
    )

    return {
        "query": query,
        "skills": [
            skill.as_dict()
            for skill in skills
        ],
    }


async def skill_list(args):
    offset = max(
        int(args.get("offset", 0)),
        0,
    )

    limit = max(
        1,
        min(
            int(args.get("limit", 50)),
            100,
        ),
    )

    skills = await asyncio.to_thread(
        skill_catalog.scan
    )

    page = skills[offset:offset + limit]

    return {
        "total": len(skills),
        "offset": offset,
        "skills": [
            skill.as_dict()
            for skill in page
        ],
        "next_offset": (
            offset + len(page)
            if offset + len(page) < len(skills)
            else None
        ),
    }


async def skill_list_files(args):
    skill_id = str(
        args.get("skill_id", "")
    ).strip()

    if not skill_id:
        raise HTTPException(
            400,
            "skill_id is required",
        )

    try:
        files = await asyncio.to_thread(
            skill_catalog.list_files,
            skill_id,
        )
    except KeyError:
        raise HTTPException(
            404,
            "Unknown skill",
        )

    return {
        "skill_id": skill_id,
        "files": files,
    }


async def skill_read(args):
    skill_id = str(
        args.get("skill_id", "")
    ).strip()

    path = str(
        args.get("path", "SKILL.md")
    ).strip()

    offset = int(
        args.get("offset", 0)
    )

    max_chars = int(
        args.get("max_chars", 20000)
    )

    if not skill_id:
        raise HTTPException(
            400,
            "skill_id is required",
        )

    try:
        return await asyncio.to_thread(
            skill_catalog.read,
            skill_id,
            path,
            offset=offset,
            max_chars=max_chars,
        )

    except KeyError:
        raise HTTPException(
            404,
            "Unknown skill",
        )

    except FileNotFoundError:
        raise HTTPException(
            404,
            "Skill file not found",
        )

    except ValueError as exc:
        raise HTTPException(
            400,
            str(exc),
        )


async def skill_invoke(args):
    skill_id = str(
        args.get("skill_id", "")
    ).strip()

    loaded = await skill_read(
        {
            "skill_id": skill_id,
            "path": "SKILL.md",
            "offset": 0,
            "max_chars": 20000,
        }
    )

    return {
        **loaded,
        "input": str(
            args.get("input", "")
        ),
        "instruction": (
            "Apply these skill instructions. "
            "If truncated, call skill.read using "
            "next_offset before completing the task. "
            "Load referenced files using skill.read "
            "only when the SKILL.md requires them."
        ),
    }

def _allowed_a2a_url(raw_url: str) -> str:
    parsed = urlparse(str(raw_url).strip())
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise HTTPException(400, 'a2a.call requires an absolute http(s) URL')
    allowlist = [
        item.strip().rstrip('/')
        for item in settings.a2a_outbound_allowlist.split(',')
        if item.strip()
    ]
    target = f'{parsed.scheme}://{parsed.netloc}{parsed.path}'.rstrip('/')
    for allowed in allowlist:
        if target == allowed or target.startswith(allowed + '/'):
            return str(raw_url).strip()
    raise HTTPException(
        400,
        f'a2a.call destination is not allowlisted: {target}. '
        f'Allowed destinations: {", ".join(allowlist)}',
    )


async def a2a_call(args: dict[str, Any], run_id: str = '', task_id: str = '') -> dict[str, Any]:
    """JSON-RPC 2.0 call from a worker agent to an allowlisted external A2A agent."""
    url = _allowed_a2a_url(str(args.get('url', '')))
    method = str(args.get('method', '')).strip()
    if not method:
        raise HTTPException(400, 'a2a.call requires a JSON-RPC method')
    params = dict(args.get('params') or {})
    # Pin the negotiation to the delegated task so every round continues the
    # same conversation even if the worker forgets the id it used before.
    if isinstance(params.get('metadata'), dict):
        params['metadata']['negotiation_id'] = f'{run_id}:{task_id}'
    else:
        params['metadata'] = {'negotiation_id': f'{run_id}:{task_id}'}
    payload = {'jsonrpc': '2.0', 'method': method, 'params': params, 'id': uuid4().hex}
    async with httpx.AsyncClient(timeout=settings.tool_timeout_seconds) as client:
        response = await client.post(url, json=payload)
    if response.status_code >= 400:
        raise HTTPException(400, f'a2a.call HTTP {response.status_code}: {response.text[:500]}')
    data = response.json()
    if data.get('error'):
        # A failed RPC must not count as a successful tool use.
        raise HTTPException(400, f"a2a.call RPC error: {data['error'].get('message')}")
    return {'url': url, 'method': method, 'result': data.get('result')}


@app.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok', 'service': 'runner'}


@app.post('/tools/execute')
async def execute_tool(request: ToolRequest) -> dict[str, Any]:
    task_dir = _task_dir(request)
    try:
        if request.tool == 'web.search':
            result = await web_search(request.arguments)
        elif request.tool == 'web.fetch':
            result = await web_fetch(request.arguments)
        elif request.tool == 'filesystem.list':
            result = await filesystem_list(task_dir, request.arguments)
        elif request.tool == 'filesystem.read':
            result = await filesystem_read(task_dir, request.arguments)
        elif request.tool == 'filesystem.write':
            result = await filesystem_write(task_dir, request.arguments)
        elif request.tool == 'shell.exec':
            result = await shell_exec(task_dir, request.arguments)
        elif request.tool == "skill.search":
            result = await skill_search(
                request.arguments
            )

        elif request.tool == "skill.list":
            result = await skill_list(
                request.arguments
            )

        elif request.tool == "skill.list_files":
            result = await skill_list_files(
                request.arguments
            )

        elif request.tool == "skill.read":
            result = await skill_read(
                request.arguments
            )

        elif request.tool == "skill.invoke":
            result = await skill_invoke(
                request.arguments
            )
        elif request.tool == 'a2a.call':
            result = await a2a_call(
                request.arguments,
                run_id=request.run_id,
                task_id=request.task_id,
            )
        else:
            raise HTTPException(400, f'Unknown tool: {request.tool}')
        return {'ok': True, 'tool': request.tool, 'result': result}
    except HTTPException:
        raise
    except Exception as exc:
        return {'ok': False, 'tool': request.tool, 'error': f'{type(exc).__name__}: {exc}'}
