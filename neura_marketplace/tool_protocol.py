from __future__ import annotations
import json
from typing import Any

from .config import settings
from .json_utils import extract_json


KNOWN_TOOLS = {
    'web.search',
    'web.fetch',
    'filesystem.list',
    'filesystem.read',
    'filesystem.write',
    'shell.exec',
    'skill.list',
    'skill.read',
    'skill.invoke',
    "skill.search",
    "skill.list_files",
    'a2a.call',
}


def render_tool_contract(allowed_tools: list[str], required_tools: list[str] | None = None) -> str:
    allowed = '\n'.join(f'- {tool}' for tool in allowed_tools) or '- none'
    required = '\n'.join(f'- {tool}' for tool in (required_tools or [])) or '- none'
    return f'''## Agent Runtime Tools
You can interact with the real execution environment through the tools below.

Allowed tools:
{allowed}

Tools explicitly required by this task when applicable:
{required}

Return exactly ONE JSON object per turn.

To call a tool:
{{
  "type": "tool_call",
  "tool": "web.search",
  "arguments": {{"query": "..."}}
}}

To finish:
{{
  "type": "final",
  "content": "your completed deliverable"
}}

Tool argument schemas:
- web.search: {{"query": "search terms", "max_results": 8}}
- web.fetch: {{"url": "https://..."}}
- filesystem.list: {{"path": "."}}
- filesystem.read: {{"path": "relative/file"}}
- filesystem.write: {{"path": "relative/file", "content": "..."}}
- shell.exec: {{"command": "pytest -q"}}
- skill.search:
  {{"query":"test driven development","limit":8}}

- skill.list:
  {{"offset":0,"limit":50}}

- skill.list_files:
  {{"skill_id":"anthropics--skills/pdf"}}

- skill.read:
  {{
    "skill_id":"anthropics--skills/pdf",
    "path":"SKILL.md",
    "offset":0,
    "max_chars":20000
  }}

- skill.invoke:
  {{
    "skill_id":"prompt-master",
    "input":"prepare the delegation prompt"
  }}

- a2a.call (talk to another A2A agent over JSON-RPC 2.0; destinations are allowlisted):
  {{"url":"http://seller:8020/rpc","method":"message/send","params":{{"message":{{"role":"user","parts":[{{"kind":"text","text":"your negotiation message"}}]}},"metadata":{{"negotiation_id":"stable-id"}}}}}}

Rules:
- Never claim a tool was used unless the runtime returned a TOOL_RESULT for it.
- a2a.call only works against these destinations (do not search the web for the agent, do not invent URLs): {settings.a2a_outbound_allowlist}
- Use web.search/web.fetch for current external facts instead of relying on memory.
- When web.search is required, do not invent a URL for web.fetch. Fetch a URL returned by a successful web.search result unless the task explicitly supplied the URL.
- Use filesystem.write for durable deliverables when useful.
- Use shell.exec for actual code/test execution when implementation or verification requires it.
- Use skill.invoke when a reusable skill can improve execution; the returned instructions become part of your working context.
- Paths are relative to your isolated task workspace.
- Do not wrap the JSON in Markdown fences.

IMPORTANT:
- For a tool action, the canonical `type` is exactly "tool_call".
- Never use "tool", "tool_calls", or omit "type".
- Return exactly one JSON object and no surrounding prose.
'''


def parse_action(text: str) -> dict[str, Any]:
    data = extract_json(text)

    if not isinstance(data, dict):
        raise ValueError("Agent action must be a JSON object")

    action_type = data.get("type")

    # Normalize common model variations.
    if action_type in {"tool", "tool_call", "tool_calls"}:
        action_type = "tool_call"

    # Some models omit `type` when the intent is obvious.
    if action_type is None and isinstance(data.get("tool"), str):
        action_type = "tool_call"

    if action_type == "final":
        content = data.get("content")

        if isinstance(content, (dict, list)):
            content = json.dumps(
                content,
                ensure_ascii=False,
                indent=2,
            )

        if not isinstance(content, str) or not content.strip():
            raise ValueError("final action requires non-empty content")

        return {
            "type": "final",
            "content": content,
        }
        
    if action_type == "tool_call":
        tool = data.get("tool")
        arguments = data.get("arguments", {})

        if not isinstance(tool, str) or not tool:
            raise ValueError("tool_call requires non-empty tool")

        if tool not in KNOWN_TOOLS:
            raise ValueError(f"Unknown tool: {tool}")

        if not isinstance(arguments, dict):
            raise ValueError(
                "tool_call arguments must be an object"
            )

        validate_tool_arguments(
            tool,
            arguments,
        )

        return {
            "type": "tool_call",
            "tool": tool,
            "arguments": arguments,
        }

    raise ValueError(f"Unknown action type: {action_type!r}")

def validate_tool_arguments(
    tool: str,
    arguments: dict[str, Any],
) -> None:
    required: dict[str, tuple[str, ...]] = {
        "web.search": ("query",),
        "web.fetch": ("url",),
        "filesystem.list": ("path",),
        "filesystem.read": ("path",),
        "filesystem.write": ("path", "content"),
        "shell.exec": ("command",),
        "skill.search": ("query",),
        "skill.list_files": ("skill_id",),
        "skill.read": ("skill_id", "path"),
        "skill.invoke": ("skill_id", "input"),
        "a2a.call": ("url", "method"),
    }

    missing = [
        key
        for key in required.get(tool, ())
        if key not in arguments
        or arguments[key] is None
        or arguments[key] == ""
    ]

    if missing:
        raise ValueError(
            f"{tool} missing required arguments: {missing}"
        )    